"""Admin channel switches and Telnyx channel choices."""

from dataclasses import replace

import pytest
from test_crm_features import AGENT, FakeNumbers, client, live
from test_flow import detail, enroll, lead
from test_providers import LIVE

from followup.automation import ready, with_overrides
from followup.providers import build_provider, number_client


class FakeChannels(FakeNumbers):
    async def channel_options(self):
        return {
            "messaging_profiles": [{"id": "profile-1", "name": "Pilot texts"}],
            "voice_apps": [
                {"id": "voice", "name": "Pilot calls"},
                {"id": "app-2", "name": "Other"},
            ],
            "assistants": [{"id": "ai-1", "name": "Lead follow-up"}],
        }


def channels_app(db, config, verifier, monkeypatch, settings=None):
    provider = FakeChannels()
    monkeypatch.setattr("followup.app.number_client", lambda _config: provider)
    return client(db, settings or live(config), verifier, provider)


def save(api, **body):
    return api.put("/api/channels", json={"sms_enabled": False, "voice_enabled": True, **body})


def test_channels_list_options_and_validate_choices(fixture, monkeypatch):
    _api, db, config, _key, verifier = fixture
    api = channels_app(db, config, verifier, monkeypatch)
    view = api.get("/api/channels").json()["data"]
    assert view["sms_enabled"] and view["voice_enabled"]
    assert view["connection_id"] == "voice" and view["messaging_profile_id"] == ""
    assert [o["name"] for o in view["voice_apps"]] == ["Pilot calls", "Other"]
    assert api.get("/api/channels", headers=AGENT).status_code == 403
    assert save(api, connection_id="unknown").status_code == 409
    assert save(api, assistant_id="bad id!").status_code == 422
    # Texts cannot be switched on without a messaging profile.
    texts = save(api, sms_enabled=True)
    assert texts.status_code == 409 and "messaging profile" in texts.json()["error"]
    saved = save(api, sms_enabled=True, messaging_profile_id="profile-1", connection_id="app-2")
    assert saved.status_code == 200
    data = saved.json()["data"]
    assert data["messaging_profile_id"] == "profile-1" and data["connection_id"] == "app-2"
    assert "sms_enabled" not in api.get("/api/settings").json()["data"]


def test_switching_calls_off_blocks_every_call_path(fixture, monkeypatch):
    _api, db, config, _key, verifier = fixture
    api = channels_app(db, config, verifier, monkeypatch)
    api.patch(
        "/api/settings",
        json={
            "automation_enabled": True,
            "daily_sms_limit": 5,
            "daily_call_limit": 5,
            "contact_start_hour": 0,
            "contact_end_hour": 24,
        },
    )
    item = lead(api)
    assert api.get("/api/me").json()["data"]["bridge_ready"]
    assert save(api, voice_enabled=False).status_code == 200
    me = api.get("/api/me").json()["data"]
    assert not me["voice_ready"] and not me["bridge_ready"]
    assert api.post("/api/leads/" + item["id"] + "/call").status_code == 409
    assert api.post("/api/leads/" + item["id"] + "/connect").status_code == 409
    enroll(api, item, [{"channel": "voice", "message": "Ask", "delay_minutes": 0}])
    api.post("/api/automation/run")
    job = detail(api, item)["jobs"][0]
    assert job["status"] == "needs_attention"
    assert save(api, voice_enabled=False, sms_enabled=False).status_code == 200
    assert not api.get("/api/me").json()["data"]["sms_ready"]


def test_overrides_apply_choices_and_switches(fixture):
    _api, _db, config, *_ = fixture
    base = live(config)
    assert with_overrides(base, {"from_number": "", "sms_enabled": 1, "voice_enabled": 1}) is base
    chosen = with_overrides(base, {"connection_id": "app-2", "assistant_id": "ai-9"})
    assert chosen.provider_config.connection_id == "app-2"
    assert chosen.provider_config.assistant_id == "ai-9"
    off = with_overrides(base, {"voice_enabled": 0, "connection_id": "app-2"})
    assert off.provider_config.connection_id == "" and not ready(off, "bridge")
    texts = with_overrides(
        replace(base, provider_config=replace(base.provider_config, messaging_profile_id="p")),
        {"sms_enabled": 0},
    )
    assert texts.provider_config.messaging_profile_id == "" and not ready(texts, "sms")


def run(awaitable):
    import asyncio

    return asyncio.run(awaitable)


def test_provider_channel_options():
    seen = []

    async def request(method, url, headers, payload):
        seen.append(url)
        if "messaging_profiles" in url:
            return 200, {"data": [{"id": "mp", "name": "Texts"}, {"name": "no id"}]}
        if "call_control_applications" in url:
            return 200, {"data": [{"id": 123, "application_name": "Calls"}]}
        return 200, {"data": [{"id": "assistant-1", "name": ""}]}

    options = run(number_client(LIVE, request).channel_options())
    assert options == {
        "messaging_profiles": [{"id": "mp", "name": "Texts"}],
        "voice_apps": [{"id": "123", "name": "Calls"}],
        "assistants": [{"id": "assistant-1", "name": "assistant-1"}],
    }
    assert any(u.endswith("/ai/assistants?") for u in seen)
    demo = run(build_provider(replace(LIVE, mode="demo")).channel_options())
    assert demo["assistants"][0]["id"] == "demo-assistant"


@pytest.mark.parametrize("disabled", ["sms_enabled", "voice_enabled"])
def test_demo_channels_endpoint(fixture, disabled):
    api, *_ = fixture
    view = api.get("/api/channels").json()["data"]
    assert view["voice_apps"][0]["id"] == "demo-voice-app"
    body = {"sms_enabled": True, "voice_enabled": True, disabled: False}
    body |= {"messaging_profile_id": "demo-profile", "connection_id": "demo-voice-app"}
    assert api.put("/api/channels", json=body).json()["data"][disabled] is False
