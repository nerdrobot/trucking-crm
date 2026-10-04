"""Outcome-based call logging and the agent work queue."""

from datetime import UTC, datetime, timedelta

import pytest
from test_flow import TOKENS, detail, enroll, lead

from followup.queue import next_stage, tomorrow_morning

AGENT = {"Authorization": "Bearer " + TOKENS["agent"]}


def log(api, item, outcome, **body):
    return api.post("/api/leads/" + item["id"] + "/log-call", json={"outcome": outcome, **body})


@pytest.mark.parametrize(
    ("outcome", "stage", "status"),
    [
        ("connected", "contacted", "paused"),
        ("no_answer", "contacted", "active"),
        ("voicemail", "contacted", "active"),
        ("interested", "interested", "paused"),
        ("not_interested", "lost", "completed"),
        ("wrong_number", "lost", "completed"),
        ("appointment_set", "qualified", "paused"),
    ],
)
def test_outcome_sets_stage_and_automation(fixture, outcome, stage, status):
    api, *_ = fixture
    item = lead(api)
    enroll(api, item)
    response = log(api, item, outcome, note="Spoke briefly")
    assert response.status_code == 200, response.text
    current = detail(api, item)
    assert current["lead"]["stage"] == stage
    assert current["lead"]["status"] == status
    assert current["lead"]["last_outcome"] == outcome and current["lead"]["last_called_at"]
    assert any(
        a["channel"] == "call" and a["text"].endswith(": Spoke briefly")
        for a in current["activities"]
    )
    pending = [j for j in current["jobs"] if j["status"] == "pending"]
    assert bool(pending) == (status == "active")


def test_follow_up_dates(fixture):
    api, *_ = fixture
    item = lead(api, timezone="America/New_York")
    retry = log(api, item, "no_answer").json()["data"]
    assert retry["follow_up_at"] == tomorrow_morning("America/New_York")
    assert retry["follow_up_at"].endswith(("13:00:00+00:00", "14:00:00+00:00"))
    assert log(api, item, "call_back").status_code == 422
    chosen = log(api, item, "call_back", follow_up_at="2030-01-02T15:30:00Z").json()["data"]
    assert chosen["follow_up_at"] == "2030-01-02T15:30:00+00:00"
    assert log(api, item, "interested").json()["data"]["follow_up_at"] is None
    closed = log(api, item, "wrong_number", follow_up_at="2030-01-02T15:30:00Z").json()["data"]
    assert closed["follow_up_at"] is None and closed["stage"] == "lost"


def test_call_logging_guards(fixture):
    api, *_ = fixture
    item = lead(api)
    assert log(api, item, "sold").status_code == 422
    assert log(api, item, "connected").status_code == 200
    assert (
        api.post(
            "/api/leads/" + item["id"] + "/log-call", json={"outcome": "connected"}, headers=AGENT
        ).status_code
        == 404
    )
    api.post("/api/leads/" + item["id"] + "/demo-reply", json={"text": "STOP"})
    assert log(api, item, "connected").status_code == 409


def test_stage_only_moves_forward_unless_lost():
    assert next_stage("qualified", "contacted") == "qualified"
    assert next_stage("new", "qualified") == "qualified"
    assert next_stage("onboarded", "qualified") == "onboarded"
    assert next_stage("lost", "contacted") == "contacted"
    assert next_stage("agreement_sent", "lost") == "lost"


def queue(api, tab="today", **params):
    return api.get("/api/queue", params={"tab": tab, **params}).json()["data"]


def test_queue_tabs_order_and_summary(fixture):
    api, *_ = fixture
    fresh = lead(api, name="Fresh Lead", phone="+15550000001")
    due = lead(api, name="Due Lead", phone="+15550000002")
    later = lead(api, name="Later Lead", phone="+15550000003")
    lost = lead(api, name="Lost Lead", phone="+15550000004")
    past = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    log(api, due, "call_back", follow_up_at=past)
    log(api, later, "call_back", follow_up_at=future)
    log(api, lost, "not_interested")
    today = queue(api)
    assert [i["name"] for i in today["items"]] == ["Due Lead", "Fresh Lead"]
    assert today["items"][0]["last_activity"].startswith("Stage changed")
    assert today["counts"] == {
        "today": 2,
        "untouched": 1,
        "followups": 2,
        "in_progress": 2,
        "closed": 1,
    }
    assert [i["name"] for i in queue(api, "followups")["items"]] == ["Due Lead", "Later Lead"]
    assert [i["name"] for i in queue(api, "untouched")["items"]] == ["Fresh Lead"]
    assert [i["name"] for i in queue(api, "closed")["items"]] == ["Lost Lead"]
    summary = today["summary"]
    assert summary == {
        "assigned_today": 4,
        "called_today": 3,
        "calls_today": 3,
        "untouched": 1,
        "follow_ups_due": 1,
    }
    # The day window comes from the agent's browser so "today" matches their clock.
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    shifted = queue(api, since=tomorrow, until=(datetime.now(UTC) + timedelta(days=4)).isoformat())
    assert shifted["summary"]["called_today"] == 0 and shifted["counts"]["today"] == 3
    assert fresh["id"] in {i["id"] for i in shifted["items"]}
    assert api.get("/api/queue?tab=board").status_code == 422
    assert queue(api.__class__(api.app, headers=AGENT))["items"] == []


def test_reassignment_resets_assigned_at(fixture):
    api, db, *_ = fixture
    item = lead(api)
    db.connection.execute("UPDATE leads SET assigned_at='2020-01-01T00:00:00+00:00'")
    assert queue(api)["summary"]["assigned_today"] == 0
    api.patch("/api/leads/" + item["id"], json={"name": "Renamed"})
    assert queue(api)["summary"]["assigned_today"] == 0
    api.patch("/api/leads/" + item["id"], json={"agent_id": "agent"})
    assert queue(api)["summary"]["assigned_today"] == 1
