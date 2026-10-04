"""Browser dialer logins, browser click-to-call, incoming calls and the number purchase cap."""

from dataclasses import replace

import pytest
from test_crm_features import ALL_HOURS, FakeBridge, client, live, run
from test_flow import lead, post_event
from test_providers import LIVE

from followup.providers import (
    ProviderConfig,
    ProviderRejected,
    SendResult,
    build_provider,
    number_client,
)


class FakeDialer(FakeBridge):
    def __init__(self, missing=False):
        super().__init__()
        self.missing, self.created = missing, 0

    async def create_credential(self, name):
        self.created += 1
        return {"id": f"cred-{self.created}", "sip_username": f"gencred{self.created}"}

    async def credential_token(self, credential_id):
        if self.missing:
            self.missing = False
            raise ProviderRejected("Provider rejected request (HTTP 404)")
        return "jwt-" + credential_id

    async def forward_call(self, call_control_id, to, caller):
        self.calls.append(("forward", call_control_id, to, caller))
        return SendResult("", "queued")

    async def order_number(self, phone_number):
        self.calls.append(("order", phone_number))
        return SendResult("order-1", "pending")


def browser(config):
    base = live(config)
    return replace(
        base,
        provider_config=replace(base.provider_config, credential_connection_id="webrtc"),
    )


def test_token_creates_one_credential_and_replaces_a_deleted_one(fixture):
    _api, db, config, _key, verifier = fixture
    provider = FakeDialer()
    api = client(db, browser(config), verifier, provider)
    assert api.get("/api/me").json()["data"]["browser_ready"]
    first = api.get("/api/webrtc/token").json()["data"]
    assert first == {"login_token": "jwt-cred-1", "sip_username": "gencred1", "demo": False}
    assert api.get("/api/webrtc/token").json()["data"]["login_token"] == "jwt-cred-1"
    assert provider.created == 1
    provider.missing = True
    renewed = api.get("/api/webrtc/token").json()["data"]
    assert renewed["sip_username"] == "gencred2" and provider.created == 2
    unconfigured = client(db, live(config), verifier, provider)
    assert unconfigured.get("/api/webrtc/token").status_code == 409
    assert not unconfigured.get("/api/me").json()["data"]["browser_ready"]


def test_browser_call_rings_the_dialer_and_keeps_the_safety_checks(fixture):
    _api, db, config, _key, verifier = fixture
    provider = FakeDialer()
    api = client(db, browser(config), verifier, provider)
    api.patch("/api/settings", json=ALL_HOURS)
    item = lead(api, consent_voice=False, consent_sms=False, consent_note="")
    path = "/api/leads/" + item["id"] + "/connect"
    assert (
        api.post(path, json={"via": "browser"}).json()["error"] == "Open the browser dialer first"
    )
    api.get("/api/webrtc/token")
    started = api.post(path, json={"via": "browser"}).json()["data"]
    assert provider.calls == [("dial", "sip:gencred1@sip.telnyx.com", started["id"])]
    # The phone flow is unchanged when no body is sent.
    api.post(path)
    assert provider.calls[-1][1] == "+15559876543"
    db.connection.execute("UPDATE leads SET status='opted_out' WHERE id=?", (item["id"],))
    assert api.post(path, json={"via": "browser"}).status_code == 409
    assert api.post(path, json={"via": "carrier pigeon"}).status_code == 422


def test_incoming_call_rings_the_leads_dispatcher_or_an_admin(fixture):
    _api, db, config, key, verifier = fixture
    provider = FakeDialer()
    api = client(db, browser(config), verifier, provider)
    item = lead(api)

    def incoming(event_id, caller):
        return post_event(
            api,
            key,
            {
                "id": event_id,
                "event_type": "call.initiated",
                "payload": {
                    "call_control_id": "in-" + event_id,
                    "direction": "incoming",
                    "from": caller,
                },
            },
        )

    # Nobody has opened the dialer yet: the call is left to ring out.
    assert incoming("i1", item["phone"]).json()["data"] == {"ignored": True}
    api.get("/api/webrtc/token")
    assert incoming("i2", item["phone"]).json()["data"] == {"received": True}
    assert incoming("i2", item["phone"]).json()["data"] == {"duplicate": True}
    assert incoming("i3", "+15550001234").json()["data"] == {"received": True}
    assert provider.calls == [
        ("forward", "in-i2", "sip:gencred1@sip.telnyx.com", item["phone"]),
        ("forward", "in-i3", "sip:gencred1@sip.telnyx.com", "+15550001234"),
    ]
    texts = [a["text"] for a in api.get("/api/leads/" + item["id"]).json()["data"]["activities"]]
    assert "Incoming call; ringing the browser dialer" in texts


def test_number_purchase_cap(fixture, monkeypatch):
    _api, db, config, _key, verifier = fixture
    provider = FakeDialer()
    monkeypatch.setattr("followup.app.number_client", lambda _config: provider)
    api = client(db, browser(config), verifier, provider)
    settings = {**ALL_HOURS, "max_numbers": 1}
    assert api.patch("/api/settings", json=settings).status_code == 200
    assert api.post("/api/numbers/order", json={"phone_number": "+13125550101"}).status_code == 200
    again = api.post("/api/numbers/order", json={"phone_number": "+13125550101"})
    assert again.json()["error"] == "This number was already ordered"
    blocked = api.post("/api/numbers/order", json={"phone_number": "+13125550102"})
    assert blocked.status_code == 409 and "Number limit reached (1)" in blocked.json()["error"]
    assert provider.calls == [("order", "+13125550101")]
    assert api.patch("/api/settings", json={**ALL_HOURS, "max_numbers": 21}).status_code == 422


def test_rejected_order_frees_its_slot(fixture, monkeypatch):
    _api, db, config, _key, verifier = fixture

    class Refusing(FakeDialer):
        async def order_number(self, phone_number):
            raise ProviderRejected("Provider rejected request (HTTP 422)")

    monkeypatch.setattr("followup.app.number_client", lambda _config: Refusing())
    api = client(db, browser(config), verifier, Refusing())
    api.patch("/api/settings", json={**ALL_HOURS, "max_numbers": 1})
    assert api.post("/api/numbers/order", json={"phone_number": "+13125550101"}).status_code == 409
    used = db.connection.execute("SELECT COUNT(*) FROM ordered_numbers").fetchone()[0]
    assert used == 0


def test_provider_credential_token_and_forward_payloads():
    seen = []

    async def request(method, url, headers, payload):
        seen.append((url, payload))
        if url.endswith("/token"):
            return 201, {"text": "header.payload.signature"}
        if url.endswith("telephony_credentials"):
            return 201, {"data": {"id": "c-1", "sip_username": "gencredAbc"}}
        return 200, {"data": {"result": "ok", "call_control_id": "agent-leg"}}

    config = replace(LIVE, credential_connection_id="webrtc")
    provider = build_provider(config, request)
    assert run(provider.create_credential("pilot-admin")) == {
        "id": "c-1",
        "sip_username": "gencredAbc",
    }
    assert seen[0][1] == {"connection_id": "webrtc", "name": "pilot-admin"}
    assert run(provider.credential_token("c-1")) == "header.payload.signature"
    with pytest.raises(ProviderRejected):
        run(provider.credential_token("../api_keys"))
    run(provider.forward_call("v3:in-1", "sip:gencredAbc@sip.telnyx.com", "+13125550111"))
    assert seen[-1] == (
        "https://api.telnyx.com/v2/calls/v3:in-1/actions/transfer",
        {"to": "sip:gencredAbc@sip.telnyx.com", "timeout_secs": 30, "from": "+13125550111"},
    )
    with pytest.raises(ProviderRejected):
        run(provider.forward_call("v3:in-1", "sip:someone@evil.example", "+13125550111"))
    with pytest.raises(ProviderRejected):
        run(build_provider(LIVE, request).create_credential("x"))
    run(provider.start_bridge("sip:gencredAbc@sip.telnyx.com", "job-9"))
    assert seen[-1][1]["to"] == "sip:gencredAbc@sip.telnyx.com"
    with pytest.raises(ProviderRejected):
        run(provider.start_bridge("sip:x@other.example", "job-9"))
    demo = number_client(ProviderConfig())
    assert run(demo.create_credential("x"))["sip_username"] == "demo"
    browser_demo = run(
        build_provider(ProviderConfig()).start_bridge("sip:demo@sip.telnyx.com", "j")
    )
    assert "browser" in browser_demo.metadata["summary"]
