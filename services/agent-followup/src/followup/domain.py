"""Tenant-scoped persistence and eligibility helpers."""

import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def uid():
    return str(uuid4())


def public_user(user):
    return {key: user[key] for key in ("id", "name", "role")}


def lead_view(row):
    return {
        **row,
        "consent_sms": bool(row["consent_sms"]),
        "consent_voice": bool(row["consent_voice"]),
        "consent_email": bool(row["consent_email"]),
    }


PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}|\{(name)\}")


def render(text, lead, agent_name):
    """Fill template placeholders; unknown placeholders are left as written."""
    values = {
        "name": lead["name"],
        "first_name": lead["name"].split()[0] if lead["name"].split() else lead["name"],
        "agent_name": agent_name,
        "company": lead.get("company") or lead["name"],
    }
    return PLACEHOLDER.sub(lambda m: values.get(m.group(1) or m.group(2), m.group(0)), text or "")


def scope(user):
    return ("", ()) if user["role"] == "admin" else (" AND agent_id=?", (user["id"],))


async def get_lead(db, config, user, lead_id):
    clause, args = scope(user)
    row = await db.first(
        "SELECT * FROM leads WHERE tenant_id=? AND id=?" + clause, config.tenant_id, lead_id, *args
    )
    if not row:
        raise HTTPException(404, "Lead not found")
    return lead_view(row)


async def preferences(db, config):
    await db.run(
        "INSERT OR IGNORE INTO pilot_settings(tenant_id,automation_enabled,contact_start_hour,contact_end_hour) VALUES (?,?,?,?)",
        config.tenant_id,
        1 if config.mode == "demo" else 0,
        0 if config.mode == "demo" else 8,
        24 if config.mode == "demo" else 20,
    )
    row = await db.first("SELECT * FROM pilot_settings WHERE tenant_id=?", config.tenant_id)
    return {
        k: (bool(v) if k == "automation_enabled" else v) for k, v in row.items() if k != "tenant_id"
    } | {"mode": config.mode}


CHANNEL_FIELDS = (
    "from_number",
    "sms_enabled",
    "voice_enabled",
    "email_enabled",
    "messaging_profile_id",
    "connection_id",
    "assistant_id",
    "email_from",
    "email_from_name",
)


def public_preferences(prefs):
    # Channels have their own endpoints so a stale settings form cannot overwrite them.
    return {k: v for k, v in prefs.items() if k not in CHANNEL_FIELDS}


async def activity(
    db,
    config,
    lead_id,
    text,
    channel="system",
    direction="internal",
    status="recorded",
    job_id=None,
):
    await db.run(
        "INSERT INTO activities VALUES (?,?,?,?,?,?,?,?,?)",
        uid(),
        config.tenant_id,
        lead_id,
        job_id,
        channel,
        direction,
        text,
        status,
        now(),
    )


async def stop_lead(db, config, lead_id, status, text):
    current = await db.first(
        "SELECT status FROM leads WHERE id=? AND tenant_id=?", lead_id, config.tenant_id
    )
    if current and current["status"] == "opted_out" and status != "opted_out":
        return
    await db.batch(
        [
            (
                "UPDATE leads SET status=? WHERE id=? AND tenant_id=? AND (status!='opted_out' OR ?='opted_out')",
                status,
                lead_id,
                config.tenant_id,
                status,
            ),
            (
                "UPDATE enrollments SET status=? WHERE lead_id=? AND tenant_id=? AND status IN ('active','paused')",
                "completed" if status in {"completed", "opted_out"} else "paused",
                lead_id,
                config.tenant_id,
            ),
            (
                "UPDATE jobs SET status=? WHERE lead_id=? AND tenant_id=? AND status IN ('pending','leased')",
                "cancelled" if status in {"completed", "opted_out"} else "paused",
                lead_id,
                config.tenant_id,
            ),
        ]
    )
    if status == "opted_out":
        await db.batch(
            [
                (
                    "UPDATE leads SET consent_sms=0,consent_voice=0,consent_email=0 WHERE id=? AND tenant_id=?",
                    lead_id,
                    config.tenant_id,
                ),
                cancel_tasks(config, lead_id),
            ]
        )
    await activity(db, config, lead_id, text)


def open_task(config, lead_id, title, source, task_id=None):
    """Statement adding an agent task; skipped for opted-out leads or an open task from the same source."""
    timestamp = now()
    return (
        "INSERT OR IGNORE INTO tasks(id,tenant_id,lead_id,title,due_at,status,source,created_at) SELECT ?,?,?,?,?,'open',?,? WHERE EXISTS(SELECT 1 FROM leads WHERE id=? AND tenant_id=? AND status!='opted_out') AND NOT EXISTS(SELECT 1 FROM tasks WHERE tenant_id=? AND lead_id=? AND source=? AND status='open')",
        task_id or uid(),
        config.tenant_id,
        lead_id,
        title[:300],
        timestamp,
        source,
        timestamp,
        lead_id,
        config.tenant_id,
        config.tenant_id,
        lead_id,
        source,
    )


def cancel_tasks(config, lead_id):
    return (
        "UPDATE tasks SET status='cancelled',completed_at=? WHERE tenant_id=? AND lead_id=? AND status='open'",
        now(),
        config.tenant_id,
        lead_id,
    )


def mark_contacted(config, lead_id):
    return (
        "UPDATE leads SET stage='contacted' WHERE id=? AND tenant_id=? AND stage='new'",
        lead_id,
        config.tenant_id,
    )


STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit", "revoke", "optout"}
# Words that may accompany a stop word without changing its meaning ("Stop please").
STOP_FILLER = {"please", "pls", "plz", "now", "thanks", "thank", "you", "me", "it", "this", "all"}
# Opt-out and wrong-number phrases honoured anywhere in a longer reply.
OPT_OUT_PHRASES = re.compile(
    r"\b(?:"
    r"unsubscribe|optout|stopall|revoke"
    r"|stop (?:texting|messaging|calling|contacting|sending|emailing|bothering|harassing|spamming)"
    r"|(?:dont|do not|never) (?:text|txt|message|call|contact|email) (?:me|this number)"
    r"|(?:take|remove|delete) (?:me|my number|this number) (?:off|from)"
    r"|remove me|delete my number|lose my number|leave me alone"
    r"|no more (?:texts|messages|calls)"
    r"|wrong (?:number|person)"
    r")\b"
)


def is_opt_out(text):
    """Conservative opt-out detection; favours suppression over missing a revocation."""
    normalized = re.sub(r"[‘’']", "", text.lower())
    normalized = re.sub(r"\bopt\W*out\b", "optout", normalized)
    normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())
    words = set(normalized.split())
    if words & STOP_WORDS and words <= STOP_WORDS | STOP_FILLER:
        return True
    return bool(OPT_OUT_PHRASES.search(normalized))


async def inbound(db, config, lead_id, text, opted_out=False):
    stop = opted_out or is_opt_out(text)
    await stop_lead(
        db,
        config,
        lead_id,
        "opted_out" if stop else "replied",
        "Opt-out received" if stop else "Reply received; automation paused",
    )
    if not stop:
        await db.batch(
            [
                open_task(config, lead_id, "Reply to text: " + text, "reply"),
                mark_contacted(config, lead_id),
            ]
        )
    await activity(db, config, lead_id, text, "sms", "inbound", "received")


def sequence_view(row):
    return {**row, "steps": json.loads(row["steps"])}
