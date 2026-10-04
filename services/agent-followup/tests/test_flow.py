"""Pilot integration tests exercise user workflows and dispatch safety."""

import asyncio
import base64
import hashlib
import json
import sqlite3
import time
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from followup.app import create_app
from followup.automation import dispatch, run_due
from followup.domain import is_opt_out
from followup.local import SQLiteDatabase
from followup.providers import ProviderConfig, ProviderError, SendResult
from followup.security import Settings, verify_webhook
from followup.voice_outcomes import issue_outcome_token

TOKENS = {"admin": "a" * 48, "agent": "b" * 48}


@pytest.fixture
def fixture():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    for path in sorted(Path("migrations").glob("*.sql")):
        connection.executescript(path.read_text())
    db = SQLiteDatabase(connection)
    private = Ed25519PrivateKey.generate()
    config = Settings(
        tenant_id="pilot",
        users=tuple(
            {
                "id": role,
                "name": role.title(),
                "role": role,
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            }
            for role, token in TOKENS.items()
        ),
        frontend_origins=("https://dashboard.test",),
        webhook_public_key=base64.b64encode(private.public_key().public_bytes_raw()).decode(),
        voice_outcome_secret="s" * 48,
    )

    async def verifier(key, signature, message):
        from cryptography.exceptions import InvalidSignature

        try:
            private.public_key().verify(signature, message)
            return True
        except InvalidSignature:
            return False

    api = TestClient(
        create_app(db, config, verifier), headers={"Authorization": "Bearer " + TOKENS["admin"]}
    )
    yield api, db, config, private, verifier
    connection.close()


def lead(api, **kwargs):
    response = api.post(
        "/api/leads",
        json={
            "name": "Ada Carrier",
            "phone": "+15551234567",
            "consent_sms": True,
            "consent_voice": True,
            "consent_note": "Signed opt in",
            **kwargs,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def enroll(api, item, steps=None):
    sequence = api.post(
        "/api/sequences",
        json={
            "name": "Pilot",
            "steps": steps
            or [
                {"channel": "sms", "message": "Hello {name}", "delay_minutes": 0},
                {"channel": "voice", "message": "Ask about viewing", "delay_minutes": 1},
            ],
        },
    ).json()["data"]
    response = api.post(
        "/api/leads/" + item["id"] + "/enroll", json={"sequence_id": sequence["id"]}
    )
    assert response.status_code == 200, response.text
    return sequence


def detail(api, item):
    return api.get("/api/leads/" + item["id"]).json()["data"]


def post_event(api, key, event):
    raw = json.dumps({"data": event}).encode()
    stamp = str(int(time.time()))
    signature = base64.b64encode(key.sign(stamp.encode() + b"|" + raw)).decode()
    return api.post(
        "/api/webhooks/telnyx",
        content=raw,
        headers={
            "telnyx-timestamp": stamp,
            "telnyx-signature-ed25519": signature,
            "content-type": "application/json",
        },
    )


def test_auth_assignment_cors_and_limits(fixture):
    api, db, _config, *_ = fixture
    assert api.get("/api/me", headers={"Authorization": ""}).status_code == 401
    assert api.get("/api/me", headers={"Origin": "https://evil.test"}).status_code == 403
    assert (
        api.options("/api/leads", headers={"Origin": "https://dashboard.test"}).headers[
            "access-control-allow-origin"
        ]
        == "https://dashboard.test"
    )
    item = lead(api)
    agent = {"Authorization": "Bearer " + TOKENS["agent"]}
    assert api.get("/api/leads/" + item["id"], headers=agent).status_code == 404
    assert api.get("/api/leads", headers=agent).json()["data"]["total"] == 0
    assert api.post("/api/automation/run", headers=agent).status_code == 403
    assert (
        api.post(
            "/api/leads",
            headers=agent,
            json={"name": "Other", "phone": "+15551234568", "agent_id": "admin"},
        ).status_code
        == 403
    )
    assert api.patch("/api/leads/" + item["id"], json={"agent_id": "agent"}).status_code == 200
    assert api.get("/api/leads/" + item["id"], headers=agent).status_code == 200
    assert (
        api.patch("/api/leads/" + item["id"], headers=agent, json={"agent_id": "admin"}).status_code
        == 403
    )
    assert api.post("/api/leads", content=b"x" * 262145).status_code == 413
    asyncio.run(db.run("UPDATE rate_limits SET count=60"))
    assert api.post("/api/automation/run").status_code == 429


def test_workflow_dispatch_pause_resume_manual_and_dashboard(fixture):
    api, _db, *_ = fixture
    item = lead(api)
    enroll(api, item)
    assert api.post("/api/automation/run").json()["data"]["sent"] == 1
    assert api.post("/api/automation/run").json()["data"]["sent"] == 0
    current = detail(api, item)
    assert current["jobs"][0]["status"] == "delivered"
    assert current["activities"][0]["text"] == "Hello Ada Carrier"
    assert api.get("/api/dashboard").json()["data"]["sent_today"] == 1
    assert api.post("/api/leads/" + item["id"] + "/pause").status_code == 200
    assert api.post("/api/leads/" + item["id"] + "/resume").status_code == 200
    assert (
        api.post("/api/leads/" + item["id"] + "/message", json={"text": "Manual message"}).json()[
            "data"
        ]["status"]
        == "sent"
    )
    assert detail(api, item)["lead"]["status"] == "paused"
    assert api.post("/api/leads/" + item["id"] + "/call").json()["data"]["status"] == "sent"
    assert api.post("/api/leads/" + item["id"] + "/complete").status_code == 200
    assert api.post("/api/leads/" + item["id"] + "/resume").status_code == 409
    assert api.get("/api/agents").json()["data"][0]["name"] == "Admin"
    assert api.get("/api/leads?search=Missing").json()["data"]["total"] == 0


def test_csv_consent_validation_and_settings(fixture):
    api, *_ = fixture
    assert api.post("/api/leads", json={"name": "A", "phone": "123"}).status_code == 422
    assert (
        api.post(
            "/api/leads", json={"name": "A", "phone": "+15551234567", "timezone": "BAD"}
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/api/leads", json={"name": "A", "phone": "+15551234567", "consent_sms": True}
        ).status_code
        == 422
    )
    result = api.post(
        "/api/leads/import",
        json={"csv": "name,phone\nAlice,+15551234567\nBad,123\nDuplicate,+15551234567"},
    ).json()["data"]
    assert result["created"] == 1 and len(result["errors"]) == 2
    item = api.get("/api/leads").json()["data"]["items"][0]
    assert item["consent_sms"] is False
    assert (
        api.post(
            "/api/leads/import", json={"csv": "name,phone\n" + ("Name,+15551234567\n" * 201)}
        ).status_code
        == 422
    )
    assert api.patch("/api/leads/" + item["id"], json={"timezone": "BAD"}).status_code == 422
    assert api.patch("/api/leads/" + item["id"], json={"consent_sms": True}).status_code == 422
    assert (
        api.patch(
            "/api/leads/" + item["id"], json={"consent_sms": True, "consent_note": "Written opt in"}
        ).status_code
        == 200
    )
    prefs = api.get("/api/settings").json()["data"]
    assert prefs["contact_start_hour"] == 0
    assert (
        api.patch(
            "/api/settings",
            json={k: v for k, v in prefs.items() if k != "mode"} | {"contact_end_hour": 0},
        ).status_code
        == 422
    )
    assert (
        api.patch(
            "/api/settings",
            json={k: v for k, v in prefs.items() if k != "mode"} | {"daily_sms_limit": 0},
        ).status_code
        == 200
    )
    assert (
        api.post("/api/leads/" + item["id"] + "/message", json={"text": "hello"}).json()["data"][
            "status"
        ]
        == "capped"
    )


def test_webhook_reply_dedup_and_optout_persists(fixture):
    api, _db, _config, key, _ = fixture
    item = lead(api)
    enroll(api, item)
    event = {
        "id": "inbound1",
        "event_type": "message.received",
        "payload": {
            "from": {"phone_number": item["phone"]},
            "to": [{"phone_number": "+15550000000"}],
            "text": "STOP",
        },
    }
    assert post_event(api, key, event).status_code == 200
    assert post_event(api, key, event).json()["data"]["duplicate"] is True
    event["id"] = "inbound2"
    event["payload"]["text"] = "Thanks"
    assert post_event(api, key, event).status_code == 200
    assert detail(api, item)["lead"]["status"] == "opted_out"
    for action in ("pause", "resume", "complete", "call"):
        assert api.post("/api/leads/" + item["id"] + "/" + action).status_code == 409
    assert (
        api.patch(
            "/api/leads/" + item["id"], json={"consent_sms": True, "consent_note": "new"}
        ).status_code
        == 409
    )
    assert api.post("/api/webhooks/telnyx", json={"data": event}).status_code == 401


@pytest.mark.parametrize(
    "text",
    [
        "STOP",
        "STOP.",
        " stop! ",
        "Stop please",
        "STOP STOP STOP",
        "opt-out",
        "Opt Out",
        "optout",
        "Unsubscribe me",
        "please stop texting me",
        "Stop calling this number",
        "Don’t text me again",
        "do not contact me",
        "Take me off your list",
        "remove me from this",
        "No more texts",
        "leave me alone",
        "Sorry, wrong number",
        "How do I unsubscribe?",
    ],
)
def test_opt_out_detected(text):
    assert is_opt_out(text)


@pytest.mark.parametrize(
    "text",
    [
        "Thanks",
        "I'll stop by the open house at 5",
        "When does the showing end?",
        "Can we cancel Tuesday and meet Wednesday instead?",
        "Is the seller willing to stop the other offer?",
        "Call me tomorrow",
        "",
    ],
)
def test_ordinary_reply_not_opt_out(text):
    assert not is_opt_out(text)


def test_webhook_phrase_optout(fixture):
    api, _db, _config, key, _ = fixture
    item = lead(api)
    enroll(api, item)
    event = {
        "id": "inbound-phrase",
        "event_type": "message.received",
        "payload": {
            "from": {"phone_number": item["phone"]},
            "to": [{"phone_number": "+15550000000"}],
            "text": "Please take me off your list.",
        },
    }
    assert post_event(api, key, event).status_code == 200
    current = detail(api, item)
    assert current["lead"]["status"] == "opted_out"
    assert not current["lead"]["consent_sms"] and not current["lead"]["consent_voice"]


def test_delivery_order_and_unknown_event(fixture):
    api, _db, _config, key, _ = fixture
    item = lead(api)
    enroll(api, item, [{"channel": "voice", "message": "Ask interest", "delay_minutes": 0}])
    api.post("/api/automation/run")
    job = detail(api, item)["jobs"][0]
    event = {
        "id": "call1",
        "event_type": "call.hangup",
        "payload": {"call_control_id": job["provider_id"], "hangup_cause": "normal_clearing"},
    }
    assert post_event(api, key, event).status_code == 200
    event["id"] = "call2"
    event["event_type"] = "call.answered"
    assert post_event(api, key, event).status_code == 200
    assert detail(api, item)["jobs"][0]["status"] == "completed"
    event["id"] = "unknown"
    event["payload"]["call_control_id"] = "other"
    assert post_event(api, key, event).json()["data"]["ignored"]
    assert post_event(api, key, {}).status_code == 422


def test_voice_outcomes_authenticated_idempotent_and_optout(fixture):
    api, _db, config, *_ = fixture
    item = lead(api)
    enroll(api, item, [{"channel": "voice", "message": "Ask interest", "delay_minutes": 0}])
    api.post("/api/automation/run")
    job = detail(api, item)["jobs"][0]
    body = {
        "dispatch_id": job["id"],
        "outcome_token": issue_outcome_token(
            config.voice_outcome_secret, config.tenant_id, job["id"]
        ),
        "outcome": "interested",
        "summary": "Wants an agent callback",
    }
    assert (
        api.post("/webhooks/assistant-outcome", json=body | {"outcome_token": "0" * 64}).status_code
        == 401
    )
    assert api.post("/webhooks/assistant-outcome", json=body).status_code == 200
    assert api.post("/webhooks/assistant-outcome", json=body).json()["data"]["duplicate"]
    assert (
        api.post(
            "/webhooks/assistant-outcome",
            json=body | {"outcome": "opt_out", "summary": "Please stop"},
        ).status_code
        == 200
    )
    assert detail(api, item)["lead"]["status"] == "opted_out"
    assert api.post("/webhooks/assistant-outcome", json=body).json()["data"]["duplicate"]


@pytest.mark.parametrize("safe", [True, False])
def test_uncertain_delivery_and_safe_retry(fixture, safe):
    api, db, config, *_ = fixture

    class Failing:
        async def send_sms(self, *args):
            raise ProviderError("failure", safe_to_retry=safe)

    item = lead(api)
    enroll(api, item, [{"channel": "sms", "message": "Hi", "delay_minutes": 0}])
    assert asyncio.run(run_due(db, config, Failing()))["sent"] == 0
    job = detail(api, item)["jobs"][0]
    assert job["status"] == ("pending" if safe else "needs_attention")
    assert asyncio.run(run_due(db, config, Failing()))["processed"] == 0


def test_claim_global_pause_caps_recovery_and_revoked_consent(fixture):
    api, db, _config, *_ = fixture
    item = lead(api)
    enroll(api, item, [{"channel": "sms", "message": "Hi", "delay_minutes": 0}])
    prefs = api.get("/api/settings").json()["data"]
    prefs.pop("mode")
    api.patch("/api/settings", json=prefs | {"automation_enabled": False})
    assert api.post("/api/automation/run").json()["data"]["results"] == ["deferred"]
    asyncio.run(db.run("UPDATE jobs SET due_at='2000-01-01'"))
    api.patch("/api/settings", json=prefs | {"daily_sms_limit": 0})
    assert api.post("/api/automation/run").json()["data"]["results"] == ["capped"]
    api.patch("/api/settings", json=prefs)
    asyncio.run(db.run("UPDATE jobs SET due_at='2000-01-01'"))
    api.patch("/api/leads/" + item["id"], json={"consent_sms": False})
    assert api.post("/api/automation/run").json()["data"]["results"] == ["needs_attention"]
    asyncio.run(db.run("UPDATE jobs SET status='sending',lease_until='2000-01-01'"))
    api.post("/api/automation/run")
    assert detail(api, item)["jobs"][0]["error"].startswith("Interrupted")


def test_claim_at_most_once_and_racing_optout(fixture):
    api, db, config, *_ = fixture
    item = lead(api)
    enroll(api, item, [{"channel": "sms", "message": "Hi", "delay_minutes": 0}])
    job = detail(api, item)["jobs"][0]

    class RacingProvider:
        count = 0

        async def send_sms(self, *args):
            self.count += 1
            await asyncio.sleep(0.01)
            return SendResult("one", "sent", {})

    provider = RacingProvider()

    async def race():
        return await asyncio.gather(
            dispatch(db, config, job, provider), dispatch(db, config, job, provider)
        )

    results = asyncio.run(race())
    assert sorted(results) == ["sent", "skipped"] and provider.count == 1


def test_settings_fail_closed_and_live_gating(fixture):
    _api, db, config, *_ = fixture
    with pytest.raises(ValueError):
        Settings.from_env({})
    with pytest.raises(ValueError):
        replace(config, users=({"id": "bad"},))
    live = replace(config, mode="live", provider_config=ProviderConfig(mode="live"))
    client = TestClient(
        create_app(db, live), headers={"Authorization": "Bearer " + TOKENS["admin"]}
    )
    assert client.get("/api/me").json()["data"]["sms_ready"] is False
    item = lead(client)
    assert (
        client.post("/api/leads/" + item["id"] + "/message", json={"text": "hi"}).status_code == 409
    )
    assert (
        client.post("/api/leads/" + item["id"] + "/demo-reply", json={"text": "hi"}).status_code
        == 404
    )
    assert TestClient(create_app()).get("/api/me").status_code == 503


def test_signature_timestamp_and_bad_encoding(fixture):
    *_, verifier = fixture
    assert not asyncio.run(verify_webhook("", str(int(time.time()) - 301), "", b"", verifier))
    assert not asyncio.run(verify_webhook("", "nonsense", "", b"", verifier))
    assert not asyncio.run(verify_webhook("", str(int(time.time())), "!", b"", verifier))


def test_sms_delivery_and_voice_client_state_callbacks(fixture):
    api, db, _config, key, _ = fixture
    item = lead(api)
    enroll(api, item, [{"channel": "sms", "message": "Hi", "delay_minutes": 0}])
    api.post("/api/automation/run")
    job = detail(api, item)["jobs"][0]
    asyncio.run(db.run("UPDATE jobs SET status='queued' WHERE id=?", job["id"]))
    event = {
        "id": "delivered",
        "event_type": "message.finalized",
        "payload": {"id": job["provider_id"], "to": [{"status": "delivered"}]},
    }
    assert post_event(api, key, event).status_code == 200
    event["id"] = "late-failure"
    event["payload"]["to"][0]["status"] = "delivery_failed"
    post_event(api, key, event)
    assert detail(api, item)["jobs"][0]["status"] == "delivered"
    other = lead(api, phone="+15551234568")
    enroll(api, other, [{"channel": "voice", "message": "Hi", "delay_minutes": 0}])
    voice = detail(api, other)["jobs"][0]
    asyncio.run(db.run("UPDATE jobs SET status='sending' WHERE id=?", voice["id"]))
    state = base64.b64encode(json.dumps({"dispatch_id": voice["id"]}).encode()).decode()
    event = {
        "id": "early-answer",
        "event_type": "call.answered",
        "payload": {"call_control_id": "early-provider", "client_state": state},
    }
    assert post_event(api, key, event).status_code == 200
    assert detail(api, other)["jobs"][0]["status"] == "answered"
    assert detail(api, other)["jobs"][0]["provider_id"] == "early-provider"


def test_rendered_message_and_uncertain_crash(fixture):
    api, db, config, *_ = fixture
    item = lead(api)
    enroll(
        api, item, [{"channel": "sms", "message": "Hello {{name}} and {name}", "delay_minutes": 0}]
    )

    class Capture:
        async def send_sms(self, to, text, dispatch_id):
            assert text == "Hello Ada Carrier and Ada Carrier"
            raise RuntimeError("transport disappeared")

    asyncio.run(run_due(db, config, Capture()))
    assert detail(api, item)["jobs"][0]["status"] == "needs_attention"


def test_dst_quiet_hours_and_pause_race(fixture, monkeypatch):
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from followup import automation

    api, db, config, *_ = fixture
    item = lead(api, timezone="America/New_York")
    enroll(api, item, [{"channel": "sms", "message": "Hi", "delay_minutes": 0}])
    # 12:30UTC is08:30 EDT in summer but07:30 EST in winter.
    assert (
        datetime(2026, 7, 1, 12, 30, tzinfo=UTC).astimezone(ZoneInfo("America/New_York")).hour == 8
    )
    assert (
        datetime(2026, 1, 1, 12, 30, tzinfo=UTC).astimezone(ZoneInfo("America/New_York")).hour == 7
    )

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, 12, 30, tzinfo=UTC).astimezone(tz or UTC)

    monkeypatch.setattr(automation, "datetime", Frozen)
    prefs = api.get("/api/settings").json()["data"]
    prefs.pop("mode")
    api.patch("/api/settings", json=prefs | {"contact_start_hour": 8, "contact_end_hour": 20})
    assert asyncio.run(run_due(db, config))["results"] == ["deferred"]
    asyncio.run(db.run("UPDATE jobs SET due_at='2000-01-01'"))
    api.post("/api/leads/" + item["id"] + "/pause")
    asyncio.run(db.run("UPDATE jobs SET status='pending'"))
    assert asyncio.run(run_due(db, config))["results"] == ["paused"]


def test_live_readiness_and_environment(fixture):
    from followup.automation import ready

    _api, _db, config, *_ = fixture
    env = {
        "PILOT_MODE": "live",
        "PILOT_TENANT_ID": "pilot",
        "PILOT_USERS_JSON": json.dumps(config.users),
        "ENABLE_LIVE_SEND": "true",
        "TELNYX_PUBLIC_KEY": config.webhook_public_key,
        "VOICE_OUTCOME_SECRET": "s" * 40,
        "TELNYX_API_KEY": "key",
        "TELNYX_FROM_NUMBER": "+15550000000",
        "TELNYX_MESSAGING_PROFILE_ID": "sms",
        "TELNYX_ASSISTANT_ID": "ai",
        "TELNYX_CONNECTION_ID": "voice",
    }
    live = Settings.from_env(env)
    assert ready(live, "sms") and ready(live, "voice")
    assert not ready(replace(live, webhook_public_key="!"), "sms")
    assert not ready(replace(live, voice_outcome_secret=""), "voice")
