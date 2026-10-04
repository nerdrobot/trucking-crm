"""Agent call logging and the daily work queue."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from followup.domain import activity, lead_view, now, scope, stop_lead

STAGE_ORDER = ["new", "contacted", "interested", "qualified", "agreement_sent", "onboarded"]
# outcome: (timeline label, stage it moves the lead toward, effect on automation)
OUTCOMES = {
    "connected": ("Connected", "contacted", "pause"),
    "no_answer": ("No answer", "contacted", None),
    "voicemail": ("Left voicemail", "contacted", None),
    "interested": ("Interested", "interested", "pause"),
    "not_interested": ("Not interested", "lost", "complete"),
    "wrong_number": ("Wrong number", "lost", "complete"),
    "call_back": ("Call back requested", "contacted", "pause"),
    "appointment_set": ("Onboarding call set", "qualified", "pause"),
}
RETRY_OUTCOMES = {"no_answer", "voicemail"}

OPEN = "status NOT IN ('opted_out','completed') AND stage NOT IN ('onboarded','lost')"
UNTOUCHED = "last_called_at IS NULL AND " + OPEN
FOLLOW_UPS = "follow_up_at IS NOT NULL AND " + OPEN
# tab: (condition, whether it takes the end-of-day bound, ordering)
TABS = {
    "today": (
        f"(({FOLLOW_UPS} AND follow_up_at<=?) OR ({UNTOUCHED}))",
        True,
        "follow_up_at IS NULL, follow_up_at, created_at DESC",
    ),
    "untouched": (UNTOUCHED, False, "created_at DESC"),
    "followups": (FOLLOW_UPS, False, "follow_up_at"),
    "in_progress": ("last_called_at IS NOT NULL AND " + OPEN, False, "last_called_at DESC"),
    "closed": (
        "(status IN ('opted_out','completed') OR stage IN ('onboarded','lost'))",
        False,
        "COALESCE(last_called_at,created_at) DESC",
    ),
}


def iso(value):
    value = value if value.tzinfo else value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds")


def tomorrow_morning(timezone):
    zone = ZoneInfo(timezone)
    day = datetime.now(zone).date() + timedelta(days=1)
    return iso(datetime.combine(day, time(9), zone))


def next_stage(current, target):
    """Calls move a lead forward, never backward; losing it is always explicit."""
    if target == "lost" or current == "lost":
        return target
    if current == "onboarded":
        return current
    return target if STAGE_ORDER.index(target) > STAGE_ORDER.index(current) else current


async def log_call(db, config, lead, body):
    if lead["status"] == "opted_out":
        raise HTTPException(409, "Lead opted out")
    if body.outcome == "call_back" and not body.follow_up_at:
        raise HTTPException(422, "Choose when to call back")
    label, target, automation = OUTCOMES[body.outcome]
    if automation == "complete":
        follow_up = None
    elif body.follow_up_at:
        follow_up = iso(body.follow_up_at)
    elif body.outcome in RETRY_OUTCOMES:
        follow_up = tomorrow_morning(lead["timezone"])
    else:
        follow_up = None
    if automation:
        await stop_lead(
            db,
            config,
            lead["id"],
            "completed" if automation == "complete" else "paused",
            "Automated follow-up stopped after call"
            if automation == "complete"
            else "Agent took over follow-up",
        )
    stage = next_stage(lead["stage"], target)
    await db.run(
        "UPDATE leads SET stage=?,last_outcome=?,last_called_at=?,follow_up_at=? WHERE id=? AND tenant_id=?",
        stage,
        body.outcome,
        now(),
        follow_up,
        lead["id"],
        config.tenant_id,
    )
    await activity(
        db,
        config,
        lead["id"],
        "Call logged: " + label + (": " + body.note if body.note else ""),
        "call",
        "outbound",
        body.outcome,
    )
    if stage != lead["stage"]:
        await activity(db, config, lead["id"], "Stage changed to " + stage.replace("_", " "))
    return {"stage": stage, "follow_up_at": follow_up, "last_outcome": body.outcome}


async def work_queue(db, config, user, tab, since, until):
    clause, args = scope(user)
    base = " FROM leads WHERE tenant_id=?" + clause
    since, until = iso(since), iso(until)

    def condition(name):
        sql, bounded, _order = TABS[name]
        return " AND " + sql, (until,) if bounded else ()

    counts = {}
    for name in TABS:
        sql, params = condition(name)
        row = await db.first("SELECT COUNT(*) AS n" + base + sql, config.tenant_id, *args, *params)
        counts[name] = row["n"]
    sql, params = condition(tab)
    rows = await db.all(
        "SELECT leads.*,(SELECT text FROM activities WHERE lead_id=leads.id AND tenant_id=leads.tenant_id ORDER BY created_at DESC,rowid DESC LIMIT 1) AS last_activity,"
        "(SELECT MAX(created_at) FROM activities WHERE lead_id=leads.id AND tenant_id=leads.tenant_id) AS last_activity_at"
        + base
        + sql
        + " ORDER BY "
        + TABS[tab][2]
        + " LIMIT 200",
        config.tenant_id,
        *args,
        *params,
    )

    async def count(where, *values):
        row = await db.first(
            "SELECT COUNT(*) AS n" + base + where, config.tenant_id, *args, *values
        )
        return row["n"]

    calls = await db.first(
        "SELECT COUNT(*) AS n FROM activities a JOIN leads ON leads.id=a.lead_id AND leads.tenant_id=a.tenant_id WHERE a.tenant_id=? AND a.channel='call' AND a.created_at>=?"
        + clause,
        config.tenant_id,
        since,
        *args,
    )
    return {
        "items": [lead_view(row) for row in rows],
        "counts": counts,
        "summary": {
            "assigned_today": await count(" AND assigned_at>=?", since),
            "called_today": await count(" AND last_called_at>=?", since),
            "calls_today": calls["n"],
            "untouched": counts["untouched"],
            "follow_ups_due": await count(" AND " + FOLLOW_UPS + " AND follow_up_at<=?", until),
        },
    }
