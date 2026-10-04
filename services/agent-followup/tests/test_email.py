"""Email follow-ups, templates and email-only unsubscribes."""

import asyncio
from dataclasses import replace

import pytest
from test_crm_features import AGENT, client, live
from test_flow import detail, enroll, lead, post_event
from test_providers import LIVE

from followup.automation import ready, with_overrides
from followup.domain import render
from followup.providers import ProviderRejected, SendResult, build_provider

EMAIL_STEP = {
    "channel": "email",
    "subject": "Homes for {{first_name}}",
    "message": "Hi {{first_name}}, {{agent_name}} found three listings.",
    "delay_minutes": 0,
}


def email_lead(api, **kwargs):
    return lead(api, email=kwargs.pop("email", "ada@example.com"), consent_email=True, **kwargs)


def test_provider_sends_idempotent_email_from_configured_sender():
    seen = {}

    async def request(method, url, headers, payload):
        seen.update(url=url, headers=headers, payload=payload)
        return 202, {"data": {"id": "email-id", "status": "queued"}}

    config = replace(LIVE, email_from="team@homes.test", email_from_name="Fortune Homes")
    result = asyncio.run(
        build_provider(config, request).send_email("ada@example.com", "Hi", "Body", "dispatch")
    )
    assert result.provider_id == "email-id" and result.status == "queued"
    assert seen["url"] == "https://api.telnyx.com/v2/email_messages"
    assert seen["headers"]["Idempotency-Key"] == "dispatch"
    assert seen["payload"]["from"] == {"email": "team@homes.test", "name": "Fortune Homes"}
    assert seen["payload"]["to"] == ["ada@example.com"]
    assert seen["payload"]["text_body"] == "Body"


@pytest.mark.parametrize(
    "to,subject,text",
    [("not-an-email", "Hi", "Body"), ("a@b.co", "", "Body"), ("a@b.co", "A\nB", "Body")],
)
def test_bad_email_inputs_and_missing_sender_rejected(to, subject, text):
    async def forbidden(*args):
        raise AssertionError("network forbidden")

    sender = replace(LIVE, email_from="team@homes.test")
    with pytest.raises(ProviderRejected):
        asyncio.run(build_provider(sender, forbidden).send_email(to, subject, text, "d"))
    with pytest.raises(ProviderRejected):
        asyncio.run(build_provider(LIVE, forbidden).send_email("a@b.co", "Hi", "Body", "d"))


def test_render_fills_known_placeholders_only():
    person = {"name": "Ada Lovelace"}
    assert (
        render("{{ first_name }} / {name} / {{agent_name}} / {{unknown}}", person, "Sam")
        == "Ada / Ada Lovelace / Sam / {{unknown}}"
    )


def test_email_validation_for_leads_and_steps(fixture):
    api, *_ = fixture
    base = {"name": "B", "phone": "+15550001111", "consent_note": "Web form"}
    assert api.post("/api/leads", json=base | {"consent_email": True}).status_code == 422
    assert api.post("/api/leads", json=base | {"email": "nope"}).status_code == 422
    no_subject = {"name": "S", "steps": [EMAIL_STEP | {"subject": ""}]}
    assert api.post("/api/sequences", json=no_subject).status_code == 422
    item = lead(api)
    sequence = api.post("/api/sequences", json={"name": "E", "steps": [EMAIL_STEP]}).json()
    enrolled = api.post(
        "/api/leads/" + item["id"] + "/enroll", json={"sequence_id": sequence["data"]["id"]}
    )
    assert enrolled.status_code == 409  # no email consent


def test_demo_email_sequence_renders_and_delivers(fixture):
    api, *_ = fixture
    item = email_lead(api)
    assert item["consent_email"] is True
    assert api.get("/api/me").json()["data"]["email_ready"]
    enroll(api, item, [EMAIL_STEP])
    api.post("/api/automation/run")
    current = detail(api, item)
    job = current["jobs"][0]
    assert job["channel"] == "email" and job["status"] == "delivered"
    sent = next(a for a in current["activities"] if a["channel"] == "email")
    assert sent["text"] == "Homes for Ada\n\nHi Ada, Admin found three listings."
    manual = api.post(
        "/api/leads/" + item["id"] + "/email", json={"subject": "Quick one", "text": "Hello"}
    )
    assert manual.json()["data"]["status"] == "sent"


def test_templates_crud_is_admin_only(fixture):
    api, *_ = fixture
    body = {"name": "Intro", "channel": "email", "subject": "Hello", "body": "Hi {{name}}"}
    created = api.post("/api/templates", json=body)
    assert created.status_code == 201
    template_id = created.json()["data"]["id"]
    assert api.post("/api/templates", json=body | {"subject": ""}).status_code == 422
    sms = api.post("/api/templates", json=body | {"channel": "sms", "name": "Text"}).json()
    assert sms["data"]["subject"] == ""
    assert api.post("/api/templates", json=body, headers=AGENT).status_code == 403
    names = [t["name"] for t in api.get("/api/templates", headers=AGENT).json()["data"]]
    assert names == ["Intro", "Text"]
    updated = api.put("/api/templates/" + template_id, json=body | {"name": "Welcome"})
    assert updated.json()["data"]["name"] == "Welcome"
    assert api.put("/api/templates/missing", json=body).status_code == 404
    assert api.delete("/api/templates/" + template_id, headers=AGENT).status_code == 403
    assert api.delete("/api/templates/" + template_id).status_code == 200
    assert api.delete("/api/templates/" + template_id).status_code == 404


class FakeEmail:
    def __init__(self):
        self.sent = []

    async def send_email(self, to, subject, text, dispatch_id):
        self.sent.append((to, subject, text))
        return SendResult("email-" + dispatch_id, "queued")


def live_email(config):
    settings = live(config)
    return replace(
        settings,
        provider_config=replace(settings.provider_config, email_from="team@homes.test"),
    )


def live_api(fixture):
    _api, db, config, key, verifier = fixture
    provider = FakeEmail()
    api = client(db, live_email(config), verifier, provider)
    api.patch(
        "/api/settings",
        json={
            "automation_enabled": True,
            "daily_sms_limit": 10,
            "daily_call_limit": 10,
            "daily_email_limit": 10,
            "contact_start_hour": 0,
            "contact_end_hour": 24,
        },
    )
    return api, provider, key


def email_event(api, key, event_id, event_type, provider_id, address="ada@example.com"):
    return post_event(
        api,
        key,
        {
            "id": event_id,
            "event_type": event_type,
            "payload": {"id": provider_id, "to": {"email": address}},
        },
    )


def test_live_email_delivery_and_bounce(fixture):
    api, provider, key = live_api(fixture)
    item = email_lead(api)
    enroll(api, item, [EMAIL_STEP, EMAIL_STEP])
    api.post("/api/automation/run")
    assert [to for to, *_ in provider.sent] == ["ada@example.com", "ada@example.com"]
    first, second = detail(api, item)["jobs"]
    assert first["status"] == "queued"
    email_event(api, key, "ev-1", "email.delivered", first["provider_id"])
    email_event(api, key, "ev-2", "email.bounced", second["provider_id"])
    jobs = {j["id"]: j["status"] for j in detail(api, item)["jobs"]}
    assert jobs == {first["id"]: "delivered", second["id"]: "needs_attention"}
    # Delivered never regresses on a late bounce.
    email_event(api, key, "ev-3", "email.bounced", first["provider_id"])
    assert detail(api, item)["jobs"][0]["status"] == "delivered"


def test_unsubscribe_stops_email_only(fixture):
    api, _provider, key = live_api(fixture)
    item = email_lead(api)
    enroll(api, item, [EMAIL_STEP, EMAIL_STEP | {"delay_minutes": 600}])
    api.post("/api/automation/run")
    sent = detail(api, item)["jobs"][0]
    result = email_event(api, key, "ev-u", "email.unsubscribed", sent["provider_id"])
    assert result.json()["data"] == {"received": True}
    current = detail(api, item)
    assert current["lead"]["consent_email"] is False
    assert current["lead"]["consent_sms"] is True
    assert current["jobs"][1]["status"] == "cancelled"
    assert current["activities"][0]["text"] == "Unsubscribed from email"
    blocked = api.post("/api/leads/" + item["id"] + "/email", json={"subject": "Hi", "text": "Hi"})
    assert blocked.status_code == 409
    # Complaints about an unknown message fall back to the recipient address.
    other = email_lead(api, phone="+15557654321", email="bo@example.com")
    email_event(api, key, "ev-c", "email.complained", "unknown", "BO@example.com")
    assert detail(api, other)["lead"]["consent_email"] is False
    ignored = email_event(api, key, "ev-x", "email.complained", "x", "nobody@x.test")
    assert ignored.json()["data"] == {"ignored": True}


def test_email_channel_switch_and_readiness(fixture):
    _api, _db, config, _key, _verifier = fixture
    settings = live_email(config)
    assert ready(settings, "email")
    assert not ready(with_overrides(settings, {"email_enabled": 0}), "email")
    no_sender = replace(settings, provider_config=replace(settings.provider_config, email_from=""))
    assert not ready(no_sender, "email")
