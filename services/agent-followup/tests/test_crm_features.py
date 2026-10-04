"""Pipeline stages, agent tasks and agent-first click-to-call."""

import asyncio
import base64
import json
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from test_flow import TOKENS, detail, enroll, lead, post_event
from test_providers import LIVE

from followup.app import create_app
from followup.providers import ProviderConfig, ProviderRejected, SendResult, build_provider
from followup.voice_outcomes import issue_outcome_token

AGENT = {"Authorization": "Bearer " + TOKENS["agent"]}
ALL_HOURS = {
    "automation_enabled": False,
    "daily_sms_limit": 1,
    "daily_call_limit": 1,
    "contact_start_hour": 0,
    "contact_end_hour": 24,
}


def state(dispatch_id, leg):
    return base64.b64encode(json.dumps({"dispatch_id": dispatch_id, "leg": leg}).encode()).decode()


def reply(api, key, item, event_id, text):
    return post_event(
        api,
        key,
        {
            "id": event_id,
            "event_type": "message.received",
            "payload": {
                "from": {"phone_number": item["phone"]},
                "to": [{"phone_number": "+15550000000"}],
                "text": text,
            },
        },
    )


def open_tasks(api, item):
    return [t for t in detail(api, item)["tasks"] if t["status"] == "open"]


def test_pipeline_stage_filter_and_atomic_validation(fixture):
    api, *_ = fixture
    item = lead(api)
    assert item["stage"] == "new"
    assert api.patch("/api/leads/" + item["id"], json={"stage": "qualified"}).status_code == 200
    current = detail(api, item)
    assert current["lead"]["stage"] == "qualified"
    assert any(a["text"] == "Stage changed to qualified" for a in current["activities"])
    assert api.get("/api/leads?stage=qualified").json()["data"]["total"] == 1
    assert api.get("/api/leads?stage=new").json()["data"]["total"] == 0
    assert api.patch("/api/leads/" + item["id"], json={"stage": "sold"}).status_code == 422
    # A rejected edit must not leave a partial stage change behind.
    rejected = api.patch(
        "/api/leads/" + item["id"], json={"stage": "agreement_sent", "timezone": "Mars/Base"}
    )
    assert rejected.status_code == 422
    assert detail(api, item)["lead"]["stage"] == "qualified"


def test_manual_tasks_scoping_completion_and_dashboard(fixture):
    api, *_ = fixture
    item = lead(api)
    created = api.post(
        "/api/leads/" + item["id"] + "/tasks",
        json={"title": "Send rate confirmation", "due_at": "2020-01-01T09:00:00"},
    )
    assert created.status_code == 201
    task = created.json()["data"]
    assert task["due_at"] == "2020-01-01T09:00:00+00:00" and task["source"] == "manual"
    listed = api.get("/api/tasks").json()["data"]
    assert [t["lead_name"] for t in listed] == ["Ada Carrier"]
    stats = api.get("/api/dashboard").json()["data"]
    assert stats["open_tasks"] == 1 and stats["overdue_tasks"] == 1
    assert api.get("/api/tasks", headers=AGENT).json()["data"] == []
    assert (
        api.patch("/api/tasks/" + task["id"], json={"status": "done"}, headers=AGENT).status_code
        == 404
    )
    done = api.patch("/api/tasks/" + task["id"], json={"status": "done"}).json()["data"]
    assert done["status"] == "done" and done["completed_at"]
    assert api.get("/api/tasks").json()["data"] == []
    assert len(api.get("/api/tasks?status=").json()["data"]) == 1
    reopened = api.patch("/api/tasks/" + task["id"], json={"status": "open"}).json()["data"]
    assert reopened["status"] == "open" and reopened["completed_at"] is None
    assert api.patch("/api/tasks/missing", json={"status": "done"}).status_code == 404
    assert api.post("/api/leads/" + item["id"] + "/tasks", json={"title": ""}).status_code == 422


def test_reply_creates_one_task_and_optout_cancels(fixture):
    api, _db, _config, key, _ = fixture
    item = lead(api)
    enroll(api, item)
    assert reply(api, key, item, "r1", "Can you call me after 5?").status_code == 200
    assert reply(api, key, item, "r1", "Can you call me after 5?").json()["data"]["duplicate"]
    assert reply(api, key, item, "r2", "Also, is parking included?").status_code == 200
    tasks = open_tasks(api, item)
    assert len(tasks) == 1 and tasks[0]["source"] == "reply"
    assert tasks[0]["title"] == "Reply to text: Can you call me after 5?"
    assert detail(api, item)["lead"]["stage"] == "contacted"
    assert reply(api, key, item, "r3", "Please take me off your list").status_code == 200
    current = detail(api, item)
    assert current["lead"]["status"] == "opted_out"
    assert [t["status"] for t in current["tasks"]] == ["cancelled"]
    assert api.patch("/api/tasks/" + tasks[0]["id"], json={"status": "open"}).status_code == 409
    # A later reply from an opted-out lead never reopens agent work.
    assert reply(api, key, item, "r4", "Hello?").status_code == 200
    assert open_tasks(api, item) == []


def test_demo_reply_creates_task_and_stop_cancels(fixture):
    api, *_ = fixture
    item = lead(api)
    path = "/api/leads/" + item["id"] + "/demo-reply"
    assert api.post(path, json={"text": "Yes"}).status_code == 200
    assert [t["source"] for t in open_tasks(api, item)] == ["reply"]
    assert api.post(path, json={"text": "STOP"}).status_code == 200
    assert [t["status"] for t in detail(api, item)["tasks"]] == ["cancelled"]


@pytest.mark.parametrize(
    ("outcome", "title"),
    [
        ("human_requested", "Call back; asked for a person: Call me at 3pm"),
        ("appointment_requested", "Confirm requested onboarding call: Call me at 3pm"),
        ("not_now", "Check in later: Call me at 3pm"),
    ],
)
def test_call_outcome_creates_task_then_optout_cancels(fixture, outcome, title):
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
        "outcome": outcome,
        "summary": "Call me at 3pm",
    }
    assert api.post("/webhooks/assistant-outcome", json=body).status_code == 200
    assert [t["title"] for t in open_tasks(api, item)] == [title]
    assert detail(api, item)["lead"]["stage"] == "contacted"
    body |= {"outcome": "opt_out", "summary": "Stop calling"}
    assert api.post("/webhooks/assistant-outcome", json=body).status_code == 200
    assert [t["status"] for t in detail(api, item)["tasks"]] == ["cancelled"]


def with_agent_phone(config, phone="+15559876543"):
    return replace(
        config,
        users=tuple(u | {"phone": phone} if u["id"] == "admin" else u for u in config.users),
    )


def client(db, config, verifier, provider=None):
    return TestClient(
        create_app(db, config, verifier, provider),
        headers={"Authorization": "Bearer " + TOKENS["admin"]},
    )


def test_bridge_demo_requires_phone_and_eligible_lead(fixture):
    api, db, config, _key, verifier = fixture
    item = lead(api)
    assert api.post("/api/leads/" + item["id"] + "/connect").status_code == 409
    assert not api.get("/api/me").json()["data"]["bridge_ready"]
    phoned = client(db, with_agent_phone(config), verifier)
    assert phoned.get("/api/me").json()["data"]["bridge_ready"]
    result = phoned.post("/api/leads/" + item["id"] + "/connect")
    assert result.json()["data"]["status"] == "completed"
    current = detail(phoned, item)
    assert current["lead"]["status"] == "paused"
    assert [j["channel"] for j in current["jobs"]] == ["bridge"]
    assert "Simulated" in current["activities"][0]["text"]
    phoned.post("/api/leads/" + item["id"] + "/demo-reply", json={"text": "STOP"})
    assert phoned.post("/api/leads/" + item["id"] + "/connect").status_code == 409
    with pytest.raises(ValueError):
        with_agent_phone(config, "555-1234")


class FakeBridge:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    async def start_bridge(self, agent_phone, dispatch_id):
        if self.fail:
            raise self.fail
        self.calls.append(("dial", agent_phone, dispatch_id))
        return SendResult("ccid-agent", "queued")

    async def transfer(self, call_control_id, to, dispatch_id):
        self.calls.append(("transfer", call_control_id, to, dispatch_id))
        return SendResult("", "queued")


def live(config):
    return replace(
        with_agent_phone(config),
        mode="live",
        enable_live_send=True,
        provider_config=ProviderConfig(
            mode="live",
            enable_live_send=True,
            api_key="key",
            from_number="+15550000000",
            connection_id="voice",
        ),
    )


def answered(api, key, event_id, job_id, ccid, leg, event_type="call.answered", **payload):
    return post_event(
        api,
        key,
        {
            "id": event_id,
            "event_type": event_type,
            "payload": {"call_control_id": ccid, "client_state": state(job_id, leg), **payload},
        },
    )


def test_bridge_live_rings_agent_then_transfers_once(fixture):
    _api, db, config, key, verifier = fixture
    provider = FakeBridge()
    api = client(db, live(config), verifier, provider)
    api.patch("/api/settings", json=ALL_HOURS)
    # Agent calls are human calls: no AI voice consent or automation switch is needed.
    item = lead(api, consent_voice=False, consent_sms=False, consent_note="")
    started = api.post("/api/leads/" + item["id"] + "/connect").json()["data"]
    assert started["status"] == "queued"
    job_id = started["id"]
    assert provider.calls == [("dial", "+15559876543", job_id)]
    assert answered(api, key, "a1", job_id, "ccid-agent", "agent").status_code == 200
    assert answered(api, key, "a1", job_id, "ccid-agent", "agent").json()["data"]["duplicate"]
    assert answered(api, key, "a2", job_id, "ccid-agent", "agent").status_code == 200
    assert provider.calls[1:] == [("transfer", "ccid-agent", item["phone"], job_id)]
    assert answered(api, key, "l1", job_id, "ccid-lead", "lead").status_code == 200
    assert detail(api, item)["jobs"][0]["status"] == "connected"
    hangup = answered(
        api, key, "h1", job_id, "ccid-lead", "lead", "call.hangup", hangup_cause="normal_clearing"
    )
    assert hangup.status_code == 200
    current = detail(api, item)
    assert current["jobs"][0]["status"] == "completed"
    assert current["activities"][0]["text"] == "Call ended: normal_clearing"
    assert "connecting to Ada Carrier" in " ".join(a["text"] for a in current["activities"])


def test_bridge_live_skips_opted_out_lead_and_records_failures(fixture):
    _api, db, config, key, verifier = fixture
    api = client(db, live(config), verifier, FakeBridge())
    api.patch("/api/settings", json=ALL_HOURS)
    item = lead(api)
    job_id = api.post("/api/leads/" + item["id"] + "/connect").json()["data"]["id"]
    db.connection.execute("UPDATE leads SET status='opted_out' WHERE id=?", (item["id"],))
    answered(api, key, "a1", job_id, "ccid-agent", "agent")
    current = detail(api, item)
    assert current["jobs"][0]["status"] == "cancelled"
    assert current["activities"][0]["text"] == "Lead opted out; call not connected"

    other = lead(api, phone="+15551230000")
    for error, message in [
        (ProviderRejected("bad"), "Call was not placed; check calling setup"),
        (TimeoutError(), "Call outcome uncertain; review provider activity"),
    ]:
        failing = client(db, live(config), verifier, FakeBridge(error))
        response = failing.post("/api/leads/" + other["id"] + "/connect")
        assert response.json()["data"]["status"] == "needs_attention"
        assert detail(failing, other)["jobs"][-1]["error"] == message


def test_bridge_live_blocked_outside_contact_hours(fixture):
    _api, db, config, _key, verifier = fixture
    api = client(db, live(config), verifier, FakeBridge())
    item = lead(api, timezone="America/Chicago")
    hour = datetime.now(ZoneInfo("America/Chicago")).hour
    window = (0, 23) if hour == 23 else (hour + 1, 24)
    api.patch(
        "/api/settings",
        json=ALL_HOURS | {"contact_start_hour": window[0], "contact_end_hour": window[1]},
    )
    response = api.post("/api/leads/" + item["id"] + "/connect")
    assert response.status_code == 409
    assert response.json()["error"] == "Outside the lead's contact hours"


def run(awaitable):
    return asyncio.run(awaitable)


def test_provider_bridge_and_transfer_payloads():
    seen = []

    async def request(method, url, headers, payload):
        seen.append((url, payload))
        return 200, {"data": {"call_control_id": "agent-leg", "result": "ok"}}

    provider = build_provider(LIVE, request)
    dialed = run(provider.start_bridge("+13125550199", "job-1"))
    assert dialed.provider_id == "agent-leg"
    url, payload = seen[0]
    assert url == "https://api.telnyx.com/v2/calls" and payload["to"] == "+13125550199"
    assert "assistant" not in payload and payload["connection_id"] == "connection"
    assert json.loads(base64.b64decode(payload["client_state"])) == {
        "dispatch_id": "job-1",
        "leg": "agent",
    }
    moved = run(provider.transfer("v3:abc-123", "+13125550101", "job-1"))
    assert moved.status == "queued"
    url, payload = seen[1]
    assert url == "https://api.telnyx.com/v2/calls/v3:abc-123/actions/transfer"
    assert payload["to"] == "+13125550101" and payload["from"] == "+13125550100"
    assert json.loads(base64.b64decode(payload["client_state"]))["leg"] == "lead"
    with pytest.raises(ProviderRejected):
        run(provider.transfer("../../calls", "+13125550101", "job-1"))
    no_app = build_provider(replace(LIVE, connection_id=""), request)
    with pytest.raises(ProviderRejected):
        run(no_app.start_bridge("+13125550199", "job-3"))
    demo = run(build_provider(ProviderConfig()).start_bridge("+13125550199", "job-2"))
    assert demo.status == "completed" and demo.metadata["simulated"]


class FakeNumbers(FakeBridge):
    def __init__(self, fail=None):
        super().__init__()
        self.ordered, self.fail_order = [], fail

    async def list_numbers(self):
        return [
            {"phone_number": "+13215550100", "status": "active", "label": "Pilot"},
            {"phone_number": "+13215550199", "status": "purchase_pending", "label": ""},
        ]

    async def search_numbers(self, state, area_code=""):
        return [{"phone_number": "+13215550111", "state": state, "monthly_cost": "1.00"}]

    async def order_number(self, phone_number):
        if self.fail_order:
            raise self.fail_order
        self.ordered.append(phone_number)
        return SendResult("order-1", "pending")


def numbers_app(db, config, verifier, provider, monkeypatch):
    monkeypatch.setattr("followup.app.number_client", lambda _config: provider)
    return client(db, live(config), verifier, provider)


def test_caller_number_selection_drives_calls(fixture, monkeypatch):
    _api, db, config, _key, verifier = fixture
    provider = FakeNumbers()
    api = numbers_app(db, config, verifier, provider, monkeypatch)
    api.patch("/api/settings", json=ALL_HOURS)
    listed = api.get("/api/numbers").json()["data"]
    assert listed["selected"] == "+15550000000" and len(listed["numbers"]) == 2
    assert "from_number" not in api.get("/api/settings").json()["data"]
    assert api.get("/api/numbers/available?state=FL").json()["data"][0]["state"] == "FL"
    assert api.get("/api/numbers/available?state=Florida").status_code == 422
    assert api.get("/api/numbers/available?area_code=12").status_code == 422
    pending = api.post("/api/numbers/select", json={"phone_number": "+13215550199"})
    assert pending.status_code == 409
    unknown = api.post("/api/numbers/select", json={"phone_number": "+13215559999"})
    assert unknown.status_code == 409
    chosen = api.post("/api/numbers/select", json={"phone_number": "+13215550100"})
    assert chosen.json()["data"]["selected"] == "+13215550100"
    assert api.get("/api/numbers").json()["data"]["selected"] == "+13215550100"
    # Saving automation settings must not reset the chosen caller number.
    api.patch("/api/settings", json=ALL_HOURS)
    assert api.get("/api/numbers").json()["data"]["selected"] == "+13215550100"
    assert api.get("/api/numbers", headers=AGENT).status_code == 403
    assert (
        api.post("/api/numbers/order", json={"phone_number": "+13215550111"}, headers=AGENT)
    ).status_code == 403
    ordered = api.post("/api/numbers/order", json={"phone_number": "+13215550111"})
    assert ordered.json()["data"] == {"order_id": "order-1", "status": "pending"}
    assert provider.ordered == ["+13215550111"]


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (TimeoutError(), 502, "Order outcome unknown"),
        (ProviderRejected("no"), 409, "nothing was bought"),
    ],
)
def test_number_order_failures_are_explicit(fixture, monkeypatch, error, status, message):
    from followup.providers import ProviderAmbiguousError

    _api, db, config, _key, verifier = fixture
    failure = ProviderAmbiguousError("unknown") if isinstance(error, TimeoutError) else error
    api = numbers_app(db, config, verifier, FakeNumbers(failure), monkeypatch)
    response = api.post("/api/numbers/order", json={"phone_number": "+13215550111"})
    assert response.status_code == status and message in response.json()["error"]


def test_selected_caller_used_for_dispatch(fixture, monkeypatch):
    from followup.automation import ready, with_overrides

    _api, _db, config, *_ = fixture
    base = live(config)
    assert with_overrides(base, {"from_number": ""}) is base
    chosen = with_overrides(base, {"from_number": "+13215550100"})
    assert chosen.provider_config.from_number == "+13215550100"
    assert ready(chosen, "bridge")


def test_provider_number_requests():
    seen = []

    async def request(method, url, headers, payload):
        seen.append((method, url, payload))
        if "available_phone_numbers" in url and "national_destination_code" in url:
            return 400, {}
        if "available_phone_numbers" in url:
            return 200, {
                "data": [
                    {
                        "phone_number": "+13214041064",
                        "region_information": [
                            {"region_type": "location", "region_name": "TITUSVILLE"},
                            {"region_type": "state", "region_name": "FL"},
                        ],
                        "cost_information": {"upfront_cost": "1.00000", "monthly_cost": "1.00000"},
                    }
                ]
            }
        if url.endswith("number_orders"):
            return 200, {"data": {"id": "order-9"}}
        return 200, {"data": [{"phone_number": "+14155550100", "status": "active"}, "junk"]}

    from followup.providers import number_client

    numbers = number_client(replace(LIVE, enable_live_send=False), request)
    owned = run(numbers.list_numbers())
    assert owned == [{"phone_number": "+14155550100", "status": "active", "label": ""}]
    assert seen[0][0] == "GET" and seen[0][2] is None
    found = run(numbers.search_numbers("FL"))
    assert found[0]["locality"] == "Titusville" and found[0]["monthly_cost"] == "1.00000"
    assert "filter%5Bfeatures%5D=voice&filter%5Bfeatures%5D=sms" in seen[1][1]
    assert run(numbers.search_numbers("FL", "305")) == []
    order = run(numbers.order_number("+13214041064"))
    assert order.provider_id == "order-9" and order.status == "pending"
    assert seen[-1][2] == {
        "phone_numbers": [{"phone_number": "+13214041064"}],
        "connection_id": "connection",
        "messaging_profile_id": "profile",
    }
    with pytest.raises(ProviderRejected):
        number_client(replace(LIVE, api_key=""))
    demo = number_client(ProviderConfig())
    assert run(demo.order_number("+13055550101")).metadata["simulated"]
    assert len(run(demo.search_numbers("FL"))) == 3 and run(demo.list_numbers())


def test_carrier_fields_search_and_csv_import(fixture):
    api, *_ = fixture
    item = lead(
        api,
        company="Garden State Haulers LLC",
        mc_number="123456",
        dot_number="7654321",
        kind="fleet",
        fleet_size=12,
        niche="Car hauler",
        city="Newark",
        state="NJ",
    )
    assert item["company"] == "Garden State Haulers LLC" and item["fleet_size"] == 12
    for term in ("Garden", "Newark", "123456", "7654321"):
        assert api.get("/api/leads?search=" + term).json()["data"]["total"] == 1
    assert (
        api.post(
            "/api/leads", json={"name": "X", "phone": "+15550001111", "mc_number": "MC12"}
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/api/leads", json={"name": "X", "phone": "+15550001111", "kind": "buyer"}
        ).status_code
        == 422
    )
    updated = api.patch("/api/leads/" + item["id"], json={"fleet_size": 14, "niche": "Reefer"})
    assert (
        updated.json()["data"]["fleet_size"] == 14 and updated.json()["data"]["niche"] == "Reefer"
    )
    imported = api.post(
        "/api/leads/import",
        json={
            "csv": "name,phone,company,mc_number,kind,city,state\nBo Driver,+15559876543,Bo Trucking,998877,owner_operator,Dallas,TX\n"
        },
    ).json()["data"]
    assert imported == {"created": 1, "errors": []}
    assert api.get("/api/leads?search=Bo Trucking").json()["data"]["items"][0]["city"] == "Dallas"
