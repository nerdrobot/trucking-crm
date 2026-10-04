"""Bounded durable dispatch with atomic claims and conservative retry policy."""

import base64
import binascii
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from followup.domain import activity, now, preferences, render
from followup.providers import ProviderError, build_provider, valid_email
from followup.voice_outcomes import issue_outcome_token

OVERRIDES = (
    "from_number",
    "messaging_profile_id",
    "connection_id",
    "assistant_id",
    "email_from",
    "email_from_name",
)
LIMITS = {"sms": "daily_sms_limit", "voice": "daily_call_limit", "email": "daily_email_limit"}


def with_overrides(config, prefs):
    """Apply admin channel choices over the deployment defaults.

    A switched-off channel loses its provider identifiers, so readiness checks and
    the provider itself refuse it everywhere, including scheduled sequence steps.
    """
    changes = {key: prefs[key] for key in OVERRIDES if prefs.get(key)}
    if prefs.get("sms_enabled", 1) in (0, False):
        changes["messaging_profile_id"] = ""
    if prefs.get("voice_enabled", 1) in (0, False):
        changes["connection_id"] = changes["assistant_id"] = ""
    if prefs.get("email_enabled", 1) in (0, False):
        changes["email_from"] = ""
    if not changes:
        return config
    return replace(config, provider_config=replace(config.provider_config, **changes))


def ready(config, channel):
    if config.mode == "demo":
        return True
    p = config.provider_config
    try:
        key_ready = len(base64.b64decode(config.webhook_public_key, validate=True)) == 32
    except (ValueError, binascii.Error):
        key_ready = False
    common = (
        config.enable_live_send
        and p.enable_live_send
        and key_ready
        and bool(p.api_key and p.from_number)
    )
    if channel == "email":
        return bool(common and valid_email(p.email_from))
    if channel == "bridge":
        return bool(common and p.connection_id)
    if channel == "browser":
        return bool(common and p.connection_id and p.credential_connection_id)
    return bool(
        common
        and (
            p.messaging_profile_id
            if channel == "sms"
            else p.assistant_id
            and p.connection_id
            and len(config.voice_outcome_secret) >= 32
            and 30 <= p.max_call_duration_seconds <= 300
        )
    )


async def dispatch(db, config, job, provider=None, manual=False):
    timestamp = now()
    claimed = await db.run(
        "UPDATE jobs SET status='leased',lease_until=?,attempts=attempts+1 WHERE id=? AND tenant_id=? AND status='pending' AND due_at<=?",
        (datetime.now(UTC) + timedelta(minutes=5)).isoformat(timespec="seconds"),
        job["id"],
        config.tenant_id,
        timestamp,
    )
    if not claimed:
        return "skipped"
    lead = await db.first(
        "SELECT * FROM leads WHERE id=? AND tenant_id=?", job["lead_id"], config.tenant_id
    )
    prefs = await preferences(db, config)
    config = with_overrides(config, prefs)
    enrollment = (
        await db.first(
            "SELECT status FROM enrollments WHERE id=? AND tenant_id=?",
            job["enrollment_id"],
            config.tenant_id,
        )
        if job["enrollment_id"]
        else None
    )
    if (
        not lead
        or lead["status"] == "opted_out"
        or (not manual and lead["status"] in {"paused", "replied", "completed"})
        or (enrollment and enrollment["status"] != "active")
    ):
        await db.run("UPDATE jobs SET status='paused' WHERE id=? AND status='leased'", job["id"])
        return "paused"
    hour = datetime.now(ZoneInfo(lead["timezone"])).hour
    if (
        not prefs["automation_enabled"]
        or not prefs["contact_start_hour"] <= hour < prefs["contact_end_hour"]
    ):
        await db.run(
            "UPDATE jobs SET status='pending',due_at=? WHERE id=? AND status='leased'",
            (datetime.now(UTC) + timedelta(minutes=15)).isoformat(timespec="seconds"),
            job["id"],
        )
        return "deferred"
    if not lead["consent_" + job["channel"]] or not ready(config, job["channel"]):
        await db.run(
            "UPDATE jobs SET status='needs_attention',error=? WHERE id=? AND status='leased'",
            "Missing channel consent or provider configuration",
            job["id"],
        )
        return "needs_attention"
    if job["channel"] == "email" and not valid_email(lead["email"]):
        await db.run(
            "UPDATE jobs SET status='needs_attention',error=? WHERE id=? AND status='leased'",
            "Lead has no valid email address",
            job["id"],
        )
        return "needs_attention"
    day = timestamp[:10]
    limit = prefs[LIMITS[job["channel"]]]
    await db.run(
        "INSERT OR IGNORE INTO usage_counters VALUES (?,?,?,0)",
        config.tenant_id,
        day,
        job["channel"],
    )
    reserved = await db.run(
        "UPDATE usage_counters SET count=count+1 WHERE tenant_id=? AND day=? AND channel=? AND count<?",
        config.tenant_id,
        day,
        job["channel"],
        limit,
    )
    if not reserved:
        await db.run(
            "UPDATE jobs SET status='pending',due_at=?,error='Daily limit reached' WHERE id=? AND status='leased'",
            (datetime.now(UTC) + timedelta(days=1))
            .replace(hour=0, minute=0, second=0)
            .isoformat(timespec="seconds"),
            job["id"],
        )
        return "capped"
    # Commit uncertain state BEFORE network I/O: a process crash never blindly resends.
    sending = await db.run(
        "UPDATE jobs SET status='sending' WHERE id=? AND status='leased' AND EXISTS(SELECT 1 FROM leads WHERE id=? AND status!='opted_out' AND consent_"
        + job["channel"]
        + "=1"
        + ("" if manual else " AND status NOT IN ('paused','replied','completed')")
        + ") AND EXISTS(SELECT 1 FROM pilot_settings WHERE tenant_id=? AND automation_enabled=1)",
        job["id"],
        job["lead_id"],
        config.tenant_id,
    )
    if not sending:
        return "paused"
    agent_name = next(
        (u["name"] for u in config.users if u["id"] == lead["agent_id"]),
        "your dispatch team",
    )
    rendered = render(job["message"], lead, agent_name)
    subject = render(job["subject"], lead, agent_name)
    try:
        adapter = provider or build_provider(config.provider_config)
        result = (
            await adapter.send_sms(lead["phone"], rendered, job["id"])
            if job["channel"] == "sms"
            else await adapter.send_email(lead["email"], subject, rendered, job["id"])
            if job["channel"] == "email"
            else await adapter.start_call(
                lead["phone"],
                job["id"],
                {
                    "lead_name": lead["name"],
                    "agent_name": agent_name,
                    "followup_message": rendered,
                    "dispatch_id": job["id"],
                    "outcome_token": issue_outcome_token(
                        config.voice_outcome_secret, config.tenant_id, job["id"]
                    )
                    if config.mode == "live"
                    else "demo-not-used",
                },
            )
        )
        await db.run(
            "UPDATE jobs SET status=?,provider_id=?,error=NULL WHERE id=? AND status IN ('sending','needs_attention')",
            result.status,
            result.provider_id,
            job["id"],
        )
        await activity(
            db,
            config,
            lead["id"],
            (subject + "\n\n" + rendered)
            if job["channel"] == "email"
            else rendered or "AI follow-up call",
            job["channel"],
            "outbound",
            result.status,
            job["id"],
        )
        return "sent"
    except ProviderError as exc:
        retry = not manual and exc.safe_to_retry and job["attempts"] < 2
        await db.run(
            "UPDATE jobs SET status=?,due_at=?,error=? WHERE id=?",
            "pending" if retry else "needs_attention",
            (datetime.now(UTC) + timedelta(minutes=5)).isoformat(timespec="seconds"),
            "Provider rejected request"
            if exc.safe_to_retry
            else "Delivery uncertain; review before retrying",
            job["id"],
        )
        return "needs_attention"
    except Exception:  # noqa: BLE001 - uncertain transport failure must never trigger a retry
        await db.run(
            "UPDATE jobs SET status='needs_attention',error='Delivery uncertain; review provider activity' WHERE id=?",
            job["id"],
        )
        return "needs_attention"


async def run_due(db, config, provider=None):
    # Expired work cannot safely be resent after a crash.
    await db.run(
        "UPDATE jobs SET status='needs_attention',error='Interrupted dispatch; reconcile provider activity' WHERE tenant_id=? AND status IN ('leased','sending') AND lease_until<?",
        config.tenant_id,
        now(),
    )
    jobs = await db.all(
        "SELECT * FROM jobs WHERE tenant_id=? AND enrollment_id IS NOT NULL AND status='pending' AND due_at<=? ORDER BY due_at LIMIT 10",
        config.tenant_id,
        now(),
    )
    results = []
    for job in jobs:
        results.append(await dispatch(db, config, job, provider))
    await db.run(
        "UPDATE enrollments SET status='completed' WHERE tenant_id=? AND status='active' AND NOT EXISTS(SELECT 1 FROM jobs WHERE enrollment_id=enrollments.id AND status IN ('pending','paused','leased','sending','needs_attention','queued','initiated','answered','sent'))",
        config.tenant_id,
    )
    await db.run(
        "UPDATE leads SET status='completed' WHERE tenant_id=? AND status='active' AND EXISTS(SELECT 1 FROM enrollments WHERE lead_id=leads.id AND status='completed') AND NOT EXISTS(SELECT 1 FROM enrollments WHERE lead_id=leads.id AND status IN ('active','paused'))",
        config.tenant_id,
    )
    await db.run(
        "DELETE FROM rate_limits WHERE tenant_id=? AND minute<?",
        config.tenant_id,
        (datetime.now(UTC) - timedelta(hours=1)).isoformat(timespec="minutes"),
    )
    return {"processed": len(results), "sent": results.count("sent"), "results": results}
