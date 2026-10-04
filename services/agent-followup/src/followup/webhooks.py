"""Signed callback ingestion; terminal delivery states never regress."""

import base64
import json

from fastapi import HTTPException

from followup.automation import with_overrides
from followup.domain import (
    cancel_tasks,
    is_opt_out,
    mark_contacted,
    now,
    open_task,
    preferences,
    uid,
)
from followup.providers import ProviderError, build_provider
from followup.security import verify_webhook


async def connect_lead(db, config, job, call_control_id, event_id, timestamp, provider):
    """The agent answered a click-to-call: transfer their leg to the lead exactly once."""
    # The claim makes duplicate or concurrent call.answered deliveries a no-op.
    claimed = await db.run(
        "UPDATE jobs SET status='connecting' WHERE id=? AND status IN ('sending','queued')",
        job["id"],
    )
    lead = await db.first(
        "SELECT name,phone,status FROM leads WHERE id=? AND tenant_id=?",
        job["lead_id"],
        config.tenant_id,
    )
    text = None
    if claimed and (not lead or lead["status"] == "opted_out"):
        await db.run("UPDATE jobs SET status='cancelled' WHERE id=?", job["id"])
        text = "Lead opted out; call not connected"
    elif claimed:
        try:
            caller = with_overrides(config, await preferences(db, config))
            adapter = provider or build_provider(caller.provider_config)
            await adapter.transfer(call_control_id, lead["phone"], job["id"])
            text = "You answered; connecting to " + lead["name"]
        except ProviderError:
            await db.run(
                "UPDATE jobs SET status='needs_attention',error=? WHERE id=?",
                "Could not connect the lead; review provider activity",
                job["id"],
            )
            text = "Could not connect the lead; review provider activity"
    statements = []
    if text:
        statements.append(
            (
                "INSERT INTO activities VALUES (?,?,?,?,?,?,?,?,?)",
                uid(),
                config.tenant_id,
                job["lead_id"],
                job["id"],
                "bridge",
                "outbound",
                text,
                "connecting",
                timestamp,
            )
        )
    statements.append(
        (
            "INSERT OR IGNORE INTO provider_events VALUES (?,?,?,?)",
            event_id,
            config.tenant_id,
            "call.answered",
            timestamp,
        )
    )
    await db.batch(statements)
    return {"received": True}


async def ring_browser(db, config, event_id, payload, timestamp, provider):
    """Forward an incoming call to a dispatcher's browser dialer.

    The lead's own dispatcher gets it when they have signed in to the dialer;
    otherwise the first administrator who has. With nobody signed in, the call is
    left alone and rings out.
    """
    caller = payload.get("from")
    lead = await db.first(
        "SELECT id,name,agent_id FROM leads WHERE tenant_id=? AND phone=?",
        config.tenant_id,
        caller,
    )
    admins = [u["id"] for u in config.users if u["role"] == "admin"]
    candidates = ([lead["agent_id"]] if lead else []) + admins
    target = None
    for user_id in candidates:
        target = await db.first(
            "SELECT sip_username FROM webrtc_credentials WHERE tenant_id=? AND user_id=?",
            config.tenant_id,
            user_id,
        )
        if target:
            break
    statements = [
        (
            "INSERT OR IGNORE INTO provider_events VALUES (?,?,?,?)",
            event_id,
            config.tenant_id,
            "call.initiated",
            timestamp,
        )
    ]
    if not target:
        await db.batch(statements)
        return {"ignored": True}
    try:
        caller_config = with_overrides(config, await preferences(db, config))
        adapter = provider or build_provider(caller_config.provider_config)
        await adapter.forward_call(
            payload.get("call_control_id"),
            f"sip:{target['sip_username']}@sip.telnyx.com",
            caller,
        )
        text = "Incoming call; ringing the browser dialer"
    except ProviderError:
        text = "Incoming call could not be forwarded; call them back"
    if lead:
        statements.append(
            (
                "INSERT INTO activities VALUES (?,?,?,?,?,?,?,?,?)",
                uid(),
                config.tenant_id,
                lead["id"],
                None,
                "call",
                "inbound",
                text,
                "received",
                timestamp,
            )
        )
    await db.batch(statements)
    return {"received": True}


EMAIL_OPT_OUTS = {"email.unsubscribed", "email.complained"}


async def email_opt_out(db, config, event_id, event_type, payload, timestamp):
    """Unsubscribes and spam complaints stop email only; texts and calls keep their consent."""
    job = await db.first(
        "SELECT lead_id FROM jobs WHERE tenant_id=? AND provider_id=? AND channel='email'",
        config.tenant_id,
        payload.get("id"),
    )
    recipient = payload.get("to")
    address = recipient.get("email") if isinstance(recipient, dict) else None
    lead = (
        {"id": job["lead_id"]}
        if job
        else await db.first(
            "SELECT id FROM leads WHERE tenant_id=? AND email=? COLLATE NOCASE",
            config.tenant_id,
            address,
        )
        if isinstance(address, str) and address
        else None
    )
    statements = []
    if lead:
        text = (
            "Marked email as spam; email follow-up stopped"
            if event_type == "email.complained"
            else "Unsubscribed from email"
        )
        statements = [
            (
                "UPDATE leads SET consent_email=0 WHERE id=? AND tenant_id=?",
                lead["id"],
                config.tenant_id,
            ),
            (
                "UPDATE jobs SET status='cancelled' WHERE lead_id=? AND tenant_id=? AND channel='email' AND status IN ('pending','leased','paused')",
                lead["id"],
                config.tenant_id,
            ),
            (
                "INSERT INTO activities SELECT ?,?,?,?,?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM provider_events WHERE id=?)",
                uid(),
                config.tenant_id,
                lead["id"],
                None,
                "email",
                "inbound",
                text,
                "opted_out",
                timestamp,
                event_id,
            ),
        ]
    statements.append(
        (
            "INSERT OR IGNORE INTO provider_events VALUES (?,?,?,?)",
            event_id,
            config.tenant_id,
            event_type,
            timestamp,
        )
    )
    await db.batch(statements)
    return {"received": True} if lead else {"ignored": True}


async def receive_webhook(request, db, config, verifier, provider=None):
    body = await request.body()
    if not await verify_webhook(
        config.webhook_public_key,
        request.headers.get("telnyx-timestamp", ""),
        request.headers.get("telnyx-signature-ed25519", ""),
        body,
        verifier,
    ):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        data = json.loads(body)["data"]
        event_id, event_type, payload = data["id"], data["event_type"], data["payload"]
        if (
            not isinstance(payload, dict)
            or not isinstance(event_id, str)
            or not event_id
            or len(event_id) > 200
            or not isinstance(event_type, str)
        ):
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        raise HTTPException(422, "Invalid webhook payload") from None
    if await db.first("SELECT id FROM provider_events WHERE id=?", event_id):
        return {"duplicate": True}
    timestamp = now()
    if event_type == "message.received":
        sender = payload.get("from", {}).get("phone_number")
        recipients = payload.get("to", [])
        if config.mode == "live" and not any(
            r.get("phone_number") == config.provider_config.from_number for r in recipients
        ):
            return {"ignored": True}
        lead = await db.first(
            "SELECT id FROM leads WHERE tenant_id=? AND phone=?", config.tenant_id, sender
        )
        if not lead:
            return {"ignored": True}
        text = payload.get("text", "")
        if not isinstance(text, str) or len(text) > 16000:
            raise HTTPException(422, "Invalid webhook payload")
        # Event insert + lead/job suppression form one atomic batch.
        stopped = bool(payload.get("is_opt_out")) or is_opt_out(text)
        condition = " AND NOT EXISTS(SELECT 1 FROM provider_events WHERE id=?)"
        await db.batch(
            [
                (
                    "UPDATE leads SET status=?"
                    + (",consent_sms=0,consent_voice=0,consent_email=0" if stopped else "")
                    + " WHERE id=? AND tenant_id=? AND status!='opted_out'"
                    + condition,
                    "opted_out" if stopped else "replied",
                    lead["id"],
                    config.tenant_id,
                    event_id,
                ),
                (
                    "UPDATE enrollments SET status=? WHERE lead_id=? AND tenant_id=? AND status IN ('active','paused')"
                    + condition,
                    "completed" if stopped else "paused",
                    lead["id"],
                    config.tenant_id,
                    event_id,
                ),
                (
                    "UPDATE jobs SET status=? WHERE lead_id=? AND tenant_id=? AND status IN ('pending','leased','paused')"
                    + condition,
                    "cancelled" if stopped else "paused",
                    lead["id"],
                    config.tenant_id,
                    event_id,
                ),
                cancel_tasks(config, lead["id"])
                if stopped
                else open_task(
                    config, lead["id"], "Reply to text: " + text, "reply", "task-" + event_id
                ),
                mark_contacted(config, lead["id"]),
                (
                    "INSERT INTO activities SELECT ?,?,?,?,?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM provider_events WHERE id=?)",
                    uid(),
                    config.tenant_id,
                    lead["id"],
                    None,
                    "sms",
                    "inbound",
                    text,
                    "received",
                    timestamp,
                    event_id,
                ),
                (
                    "INSERT OR IGNORE INTO provider_events VALUES (?,?,?,?)",
                    event_id,
                    config.tenant_id,
                    event_type,
                    timestamp,
                ),
            ]
        )
        return {"received": True}
    if event_type == "call.initiated" and payload.get("direction") == "incoming":
        return await ring_browser(db, config, event_id, payload, timestamp, provider)
    if event_type in EMAIL_OPT_OUTS:
        return await email_opt_out(db, config, event_id, event_type, payload, timestamp)
    provider_id = (
        payload.get("id")
        if event_type.startswith(("message.", "email."))
        else payload.get("call_control_id")
    )
    job = await db.first(
        "SELECT * FROM jobs WHERE tenant_id=? AND provider_id=?", config.tenant_id, provider_id
    )
    state = {}
    if payload.get("client_state"):
        try:
            state = json.loads(base64.b64decode(payload["client_state"], validate=True))
        except (ValueError, TypeError):
            pass
        state = state if isinstance(state, dict) else {}
    if not job and isinstance(state.get("dispatch_id"), str):
        job = await db.first(
            "SELECT * FROM jobs WHERE tenant_id=? AND id=? AND channel IN ('voice','bridge')",
            config.tenant_id,
            state["dispatch_id"],
        )
    if not job:
        return {"ignored": True}
    bridge = job["channel"] == "bridge"
    lead_leg = state.get("leg") == "lead"
    if bridge and event_type == "call.answered" and not lead_leg:
        return await connect_lead(
            db, config, job, payload.get("call_control_id"), event_id, timestamp, provider
        )
    status = None
    text = None
    if event_type == "message.finalized":
        recipients = payload.get("to", [])
        delivery = recipients[0].get("status") if recipients else None
        status = (
            "delivered"
            if delivery == "delivered"
            else "needs_attention"
            if delivery in {"delivery_failed", "sending_failed"}
            else None
        )
        text = "SMS delivered" if status == "delivered" else "SMS delivery failed; review required"
    elif event_type == "email.delivered":
        status, text = "delivered", "Email delivered"
    elif event_type in {"email.bounced", "email.failed", "email.rejected"}:
        status, text = "needs_attention", "Email was not delivered; check the address"
    elif event_type == "call.answered":
        status, text = (
            ("connected", "Lead answered; call connected")
            if bridge
            else (
                "answered",
                "AI call answered",
            )
        )
    elif event_type == "call.hangup":
        status = "completed"
        text = "Call ended: " + str(payload.get("hangup_cause", "unknown"))[:100]
        if not bridge:
            text += "; review conversation outcome"
    if status:
        # Final statuses take precedence over answered/queued, including out-of-order events.
        terminal = (
            " AND status NOT IN ('completed','delivered','cancelled','needs_attention')"
            if status in {"answered", "connected"}
            else " AND status NOT IN ('completed','delivered','cancelled')"
        )
        statements = [
            (
                "UPDATE jobs SET status=?,provider_id=COALESCE(provider_id,?) WHERE id=?"
                + terminal
                + " AND NOT EXISTS(SELECT 1 FROM provider_events WHERE id=?)",
                status,
                provider_id,
                job["id"],
                event_id,
            ),
            (
                "INSERT INTO activities SELECT ?,?,?,?,?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM provider_events WHERE id=?)",
                uid(),
                config.tenant_id,
                job["lead_id"],
                job["id"],
                job["channel"],
                "outbound",
                text,
                status,
                timestamp,
                event_id,
            ),
        ]
        if event_type == "call.hangup":
            statements.extend(
                [
                    (
                        "UPDATE leads SET status='paused' WHERE id=? AND tenant_id=? AND status NOT IN ('opted_out','completed','replied')",
                        job["lead_id"],
                        config.tenant_id,
                    ),
                    (
                        "UPDATE enrollments SET status='paused' WHERE lead_id=? AND tenant_id=? AND status='active'",
                        job["lead_id"],
                        config.tenant_id,
                    ),
                    (
                        "UPDATE jobs SET status='paused' WHERE lead_id=? AND tenant_id=? AND status IN ('pending','leased')",
                        job["lead_id"],
                        config.tenant_id,
                    ),
                ]
            )
        statements.append(
            (
                "INSERT OR IGNORE INTO provider_events VALUES (?,?,?,?)",
                event_id,
                config.tenant_id,
                event_type,
                timestamp,
            )
        )
        await db.batch(statements)
    else:
        await db.run(
            "INSERT OR IGNORE INTO provider_events VALUES (?,?,?,?)",
            event_id,
            config.tenant_id,
            event_type,
            timestamp,
        )
    return {"received": True}
