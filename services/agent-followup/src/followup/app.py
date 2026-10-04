"""Pilot API: named users, assigned leads and consent-gated communications."""

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from followup.automation import dispatch, ready, run_due, with_overrides
from followup.domain import (
    activity,
    cancel_tasks,
    get_lead,
    inbound,
    lead_view,
    mark_contacted,
    now,
    open_task,
    preferences,
    public_preferences,
    public_user,
    scope,
    sequence_view,
    stop_lead,
    uid,
)
from followup.models import (
    CallLog,
    ChannelSettings,
    EmailInput,
    EnrollmentInput,
    ImportInput,
    LeadInput,
    LeadPatch,
    MessageInput,
    NumberChoice,
    Preferences,
    SequenceInput,
    TaskInput,
    TaskPatch,
    TemplateInput,
)
from followup.providers import (
    ProviderAmbiguousError,
    ProviderError,
    ProviderRejected,
    build_provider,
    number_client,
)
from followup.queue import TABS, log_call, work_queue
from followup.security import Settings, webcrypto_verify
from followup.storage import D1Database
from followup.voice_outcomes import AssistantOutcome, verify_outcome_token
from followup.webhooks import receive_webhook

OUTCOME_TASKS = {
    "human_requested": "Call back; asked for a person",
    "appointment_requested": "Confirm requested onboarding call",
    "interested": "Follow up; interested",
    "not_now": "Check in later",
}


def envelope(data):
    return {"success": True, "data": data, "error": None}


class RequestGuard:
    """Bound the body while streaming, before FastAPI parses JSON; enforce CORS."""

    def __init__(self, app, config=None):
        self.app, self.config = app, config

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode()
        config = self.config
        if config is None:
            try:
                config = Settings.from_env(scope["env"])
            except (KeyError, ValueError, AttributeError, TypeError):
                config = None
        allowed = bool(origin and config and origin in config.frontend_origins)

        async def wrapped_send(message):
            if message["type"] == "http.response.start" and allowed:
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"access-control-allow-origin", origin.encode()),
                        (b"vary", b"Origin"),
                        (b"access-control-allow-methods", b"GET,POST,PUT,PATCH,DELETE,OPTIONS"),
                        (b"access-control-allow-headers", b"Authorization,Content-Type"),
                    ],
                }
            await send(message)

        if scope["method"] == "OPTIONS":
            return await JSONResponse({}, 200 if allowed else 403)(scope, receive, wrapped_send)
        if origin and not allowed:
            return await JSONResponse(
                {"success": False, "data": None, "error": "Origin is not allowed"}, 403
            )(scope, receive, send)
        size = 0
        messages = []
        while True:
            message = await receive()
            size += len(message.get("body", b""))
            if size > 262144:
                return await JSONResponse(
                    {"success": False, "data": None, "error": "Payload too large"}, 413
                )(scope, receive, wrapped_send)
            messages.append(message)
            if not message.get("more_body", False):
                break
        iterator = iter(messages)

        async def bounded_receive():
            return next(iterator, {"type": "http.request", "body": b"", "more_body": False})

        return await self.app(scope, bounded_receive, wrapped_send)


def create_app(database=None, settings=None, verifier=webcrypto_verify, provider=None):
    app = FastAPI(title="Trucking CRM follow-up", docs_url=None, redoc_url=None)
    app.add_middleware(RequestGuard, config=settings)

    async def resources(request: Request):
        if database is not None and settings is not None:
            return database, settings
        try:
            env = request.scope["env"]
            return D1Database(env.DB), Settings.from_env(env)
        except (KeyError, ValueError, AttributeError, TypeError):
            raise HTTPException(503, "Service is not configured") from None

    async def authenticated(request: Request, res=Depends(resources)):
        db, config = res
        user = config.authenticate(request.headers.get("authorization", ""))
        if not user:
            raise HTTPException(401, "Authentication required")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            minute = now()[:16]
            await db.run(
                "INSERT OR IGNORE INTO rate_limits VALUES (?,?,?,0)",
                config.tenant_id,
                user["id"],
                minute,
            )
            if not await db.run(
                "UPDATE rate_limits SET count=count+1 WHERE tenant_id=? AND user_id=? AND minute=? AND count<60",
                config.tenant_id,
                user["id"],
                minute,
            ):
                raise HTTPException(429, "Too many requests; try again shortly")
        return db, config, user

    def admin(user):
        if user["role"] != "admin":
            raise HTTPException(403, "Administrator access required")

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse({"success": False, "data": None, "error": exc.detail}, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"success": False, "data": None, "error": "Invalid input"}, 422)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return JSONResponse(
            {"success": False, "data": None, "error": "Request could not be completed"}, 500
        )

    @app.get("/health")
    async def health():
        return envelope({"status": "ok"})

    @app.get("/api/me")
    async def me(res=Depends(authenticated)):
        db, config, user = res
        live = with_overrides(config, await preferences(db, config))
        return envelope(
            {
                "user": public_user(user),
                "mode": config.mode,
                "sms_ready": ready(live, "sms"),
                "voice_ready": ready(live, "voice"),
                "email_ready": ready(live, "email"),
                "bridge_ready": ready(live, "bridge") and bool(user.get("phone")),
            }
        )

    @app.get("/api/agents")
    async def agents(res=Depends(authenticated)):
        return envelope([public_user(u) for u in res[1].users])

    @app.get("/api/leads")
    async def list_leads(
        search: str = Query(default="", max_length=100),
        status: str = Query(default="", max_length=30),
        stage: str = Query(default="", max_length=30),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        res=Depends(authenticated),
    ):
        db, config, user = res
        clause, args = scope(user)
        where = (
            " WHERE tenant_id=?"
            + clause
            + " AND (?='' OR name LIKE ? OR phone LIKE ? OR company LIKE ? OR city LIKE ? OR mc_number LIKE ? OR dot_number LIKE ?) AND (?='' OR status=?) AND (?='' OR stage=?)"
        )
        values = (
            config.tenant_id,
            *args,
            search,
            *["%" + search + "%"] * 6,
            status,
            status,
            stage,
            stage,
        )
        rows = await db.all(
            "SELECT leads.*,(SELECT MIN(due_at) FROM jobs WHERE lead_id=leads.id AND status='pending') AS next_followup_at FROM leads"
            + where
            + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
            *values,
            limit,
            offset,
        )
        count = await db.first("SELECT COUNT(*) AS count FROM leads" + where, *values)
        return envelope({"items": [lead_view(row) for row in rows], "total": count["count"]})

    async def insert_lead(body, res):
        db, config, user = res
        agent = body.agent_id or user["id"]
        if agent not in {u["id"] for u in config.users} or (
            user["role"] != "admin" and agent != user["id"]
        ):
            raise HTTPException(403, "Invalid lead assignment")
        if await db.first(
            "SELECT id FROM leads WHERE tenant_id=? AND phone=?", config.tenant_id, body.phone
        ):
            raise HTTPException(409, "Phone number already exists")
        lead_id = uid()
        await db.run(
            "INSERT INTO leads(id,tenant_id,name,status,phone,email,kind,company,mc_number,dot_number,fleet_size,niche,city,state,agent_id,timezone,consent_sms,consent_voice,consent_email,consent_note,created_at,assigned_at) VALUES (?,?,?,'new',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            lead_id,
            config.tenant_id,
            body.name,
            body.phone,
            body.email,
            body.kind,
            body.company,
            body.mc_number,
            body.dot_number,
            body.fleet_size,
            body.niche,
            body.city,
            body.state,
            agent,
            body.timezone,
            int(body.consent_sms),
            int(body.consent_voice),
            int(body.consent_email),
            body.consent_note,
            now(),
            now(),
        )
        await activity(db, config, lead_id, "Lead added")
        return await get_lead(db, config, user, lead_id)

    @app.post("/api/leads", status_code=201)
    async def create_lead(body: LeadInput, res=Depends(authenticated)):
        return envelope(await insert_lead(body, res))

    @app.post("/api/leads/import")
    async def import_leads(body: ImportInput, res=Depends(authenticated)):
        rows = list(csv.DictReader(io.StringIO(body.csv)))
        if len(rows) > 200 or not rows:
            raise HTTPException(422, "CSV must contain between 1 and 200 leads")
        created, errors = 0, []
        for number, row in enumerate(rows, 2):
            try:
                lead = LeadInput.model_validate(
                    {k: v for k, v in row.items() if k is not None and v != ""}
                )
                await insert_lead(lead, res)
                created += 1
            except (ValidationError, HTTPException):
                errors.append(
                    {"row": number, "error": "Invalid lead, duplicate phone or assignment"}
                )
        return envelope({"created": created, "errors": errors})

    @app.get("/api/leads/{lead_id}")
    async def detail(lead_id: str, res=Depends(authenticated)):
        db, config, user = res
        lead = await get_lead(db, config, user, lead_id)
        activities = await db.all(
            "SELECT * FROM activities WHERE tenant_id=? AND lead_id=? ORDER BY created_at DESC,rowid DESC LIMIT 200",
            config.tenant_id,
            lead_id,
        )
        jobs = await db.all(
            "SELECT * FROM jobs WHERE tenant_id=? AND lead_id=? ORDER BY due_at",
            config.tenant_id,
            lead_id,
        )
        enrollment = await db.first(
            "SELECT * FROM enrollments WHERE tenant_id=? AND lead_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
            config.tenant_id,
            lead_id,
        )
        tasks = await db.all(
            "SELECT * FROM tasks WHERE tenant_id=? AND lead_id=? ORDER BY status='open' DESC,due_at LIMIT 100",
            config.tenant_id,
            lead_id,
        )
        pending = [job["due_at"] for job in jobs if job["status"] == "pending"]
        return envelope(
            {
                "lead": lead | {"next_followup_at": min(pending) if pending else None},
                "activities": activities,
                "jobs": jobs,
                "tasks": tasks,
                "enrollment": enrollment,
            }
        )

    @app.patch("/api/leads/{lead_id}")
    async def update_lead(lead_id: str, body: LeadPatch, res=Depends(authenticated)):
        db, config, user = res
        old = await get_lead(db, config, user, lead_id)
        values = body.model_dump(exclude_none=True)
        stage = values.pop("stage", None)
        combined = {k: old[k] for k in LeadInput.model_fields} | values
        try:
            validated = LeadInput.model_validate(combined)
        except ValidationError:
            raise HTTPException(422, "Invalid lead or missing consent evidence") from None
        if old["status"] == "opted_out" and (
            validated.consent_sms or validated.consent_voice or validated.consent_email
        ):
            raise HTTPException(409, "Opted-out leads cannot be reactivated in the pilot")
        if validated.agent_id not in {u["id"] for u in config.users} or (
            user["role"] != "admin" and validated.agent_id != user["id"]
        ):
            raise HTTPException(403, "Invalid lead assignment")
        if stage and stage != old["stage"]:
            await db.run(
                "UPDATE leads SET stage=? WHERE tenant_id=? AND id=?",
                stage,
                config.tenant_id,
                lead_id,
            )
            await activity(db, config, lead_id, "Stage changed to " + stage.replace("_", " "))
        if values.get("agent_id", old["agent_id"]) != old["agent_id"]:
            values["assigned_at"] = now()
        if values:
            await db.run(
                "UPDATE leads SET "
                + ",".join(k + "=?" for k in values)
                + " WHERE tenant_id=? AND id=?",
                *(int(v) if isinstance(v, bool) else v for v in values.values()),
                config.tenant_id,
                lead_id,
            )
            await activity(db, config, lead_id, "Lead details updated")
        return envelope(await get_lead(db, config, user, lead_id))

    @app.get("/api/sequences")
    async def sequences(res=Depends(authenticated)):
        return envelope(
            [
                sequence_view(row)
                for row in await res[0].all(
                    "SELECT * FROM sequences WHERE tenant_id=? ORDER BY created_at",
                    res[1].tenant_id,
                )
            ]
        )

    @app.post("/api/sequences", status_code=201)
    async def create_sequence(body: SequenceInput, res=Depends(authenticated)):
        db, config, user = res
        admin(user)
        for step in body.steps:
            if step.channel == "sms" and not step.message:
                raise HTTPException(422, "SMS steps require a message")
        row = {
            "id": uid(),
            "tenant_id": config.tenant_id,
            "name": body.name,
            "steps": [s.model_dump() for s in body.steps],
            "created_at": now(),
        }
        await db.run(
            "INSERT INTO sequences VALUES (?,?,?,?,?)",
            row["id"],
            config.tenant_id,
            row["name"],
            json.dumps(row["steps"]),
            row["created_at"],
        )
        return envelope(row)

    @app.get("/api/templates")
    async def templates(res=Depends(authenticated)):
        return envelope(
            await res[0].all(
                "SELECT * FROM templates WHERE tenant_id=? ORDER BY channel,name",
                res[1].tenant_id,
            )
        )

    @app.post("/api/templates", status_code=201)
    async def create_template(body: TemplateInput, res=Depends(authenticated)):
        db, config, user = res
        admin(user)
        row = {"id": uid(), "tenant_id": config.tenant_id, **body.model_dump()}
        row["created_at"] = row["updated_at"] = now()
        await db.run(
            "INSERT INTO templates(id,tenant_id,name,channel,subject,body,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            *row.values(),
        )
        return envelope(row)

    @app.put("/api/templates/{template_id}")
    async def update_template(template_id: str, body: TemplateInput, res=Depends(authenticated)):
        db, config, user = res
        admin(user)
        changed = await db.run(
            "UPDATE templates SET name=?,channel=?,subject=?,body=?,updated_at=? WHERE id=? AND tenant_id=?",
            *body.model_dump().values(),
            now(),
            template_id,
            config.tenant_id,
        )
        if not changed:
            raise HTTPException(404, "Template not found")
        return envelope(
            await db.first(
                "SELECT * FROM templates WHERE id=? AND tenant_id=?", template_id, config.tenant_id
            )
        )

    @app.delete("/api/templates/{template_id}")
    async def delete_template(template_id: str, res=Depends(authenticated)):
        db, config, user = res
        admin(user)
        if not await db.run(
            "DELETE FROM templates WHERE id=? AND tenant_id=?", template_id, config.tenant_id
        ):
            raise HTTPException(404, "Template not found")
        return envelope({"deleted": True})

    @app.post("/api/leads/{lead_id}/enroll")
    async def enroll(lead_id: str, body: EnrollmentInput, res=Depends(authenticated)):
        db, config, user = res
        lead = await get_lead(db, config, user, lead_id)
        if lead["status"] == "opted_out":
            raise HTTPException(409, "Lead opted out")
        if await db.first(
            "SELECT id FROM enrollments WHERE tenant_id=? AND lead_id=? AND status IN ('active','paused')",
            config.tenant_id,
            lead_id,
        ):
            raise HTTPException(409, "Lead already has an enrollment")
        sequence = await db.first(
            "SELECT * FROM sequences WHERE id=? AND tenant_id=?", body.sequence_id, config.tenant_id
        )
        if not sequence:
            raise HTTPException(404, "Sequence not found")
        steps = json.loads(sequence["steps"])
        if any(not lead["consent_" + step["channel"]] for step in steps):
            raise HTTPException(409, "Consent is required for every sequence channel")
        enrollment_id = uid()
        timestamp = now()
        statements = [
            (
                "INSERT INTO enrollments SELECT ?,?,?,?,?,? WHERE EXISTS(SELECT 1 FROM leads WHERE id=? AND tenant_id=? AND status!='opted_out')",
                enrollment_id,
                config.tenant_id,
                lead_id,
                sequence["id"],
                "active",
                timestamp,
                lead_id,
                config.tenant_id,
            ),
            (
                "UPDATE leads SET status='active' WHERE tenant_id=? AND id=? AND status!='opted_out'",
                config.tenant_id,
                lead_id,
            ),
        ]
        due = datetime.now(UTC)
        for step in steps:
            due += timedelta(minutes=step["delay_minutes"])
            statements.append(
                (
                    "INSERT INTO jobs(id,tenant_id,lead_id,enrollment_id,channel,message,subject,due_at,status,created_at) SELECT ?,?,?,?,?,?,?,?,'pending',? WHERE EXISTS(SELECT 1 FROM enrollments WHERE id=? AND status='active')",
                    uid(),
                    config.tenant_id,
                    lead_id,
                    enrollment_id,
                    step["channel"],
                    step["message"],
                    step.get("subject", ""),
                    due.isoformat(timespec="seconds"),
                    timestamp,
                    enrollment_id,
                )
            )
        await db.batch(statements)
        if not await db.first("SELECT id FROM enrollments WHERE id=?", enrollment_id):
            raise HTTPException(409, "Lead opted out")
        await activity(db, config, lead_id, "Enrolled in " + sequence["name"])
        return envelope({"id": enrollment_id, "status": "active"})

    @app.post("/api/leads/{lead_id}/pause")
    async def pause(lead_id: str, res=Depends(authenticated)):
        lead = await get_lead(*res, lead_id)
        if lead["status"] == "opted_out":
            raise HTTPException(409, "Lead opted out")
        await stop_lead(res[0], res[1], lead_id, "paused", "Agent paused automation")
        return envelope({"status": "paused"})

    @app.post("/api/leads/{lead_id}/complete")
    async def complete(lead_id: str, res=Depends(authenticated)):
        lead = await get_lead(*res, lead_id)
        if lead["status"] == "opted_out":
            raise HTTPException(409, "Lead opted out")
        await stop_lead(res[0], res[1], lead_id, "completed", "Agent completed follow-up")
        return envelope({"status": "completed"})

    @app.post("/api/leads/{lead_id}/resume")
    async def resume(lead_id: str, res=Depends(authenticated)):
        db, config, _user = res
        lead = await get_lead(*res, lead_id)
        if lead["status"] == "opted_out":
            raise HTTPException(409, "Lead opted out")
        enrollment = await db.first(
            "SELECT id FROM enrollments WHERE lead_id=? AND tenant_id=? AND status='paused'",
            lead_id,
            config.tenant_id,
        )
        if not enrollment:
            raise HTTPException(409, "No paused enrollment")
        await db.batch(
            [
                (
                    "UPDATE leads SET status='active' WHERE id=? AND tenant_id=? AND status!='opted_out'",
                    lead_id,
                    config.tenant_id,
                ),
                (
                    "UPDATE enrollments SET status='active' WHERE id=? AND status='paused' AND EXISTS(SELECT 1 FROM leads WHERE id=enrollments.lead_id AND status='active')",
                    enrollment["id"],
                ),
                (
                    "UPDATE jobs SET status='pending',due_at=MAX(due_at,?) WHERE enrollment_id=? AND status='paused' AND EXISTS(SELECT 1 FROM enrollments WHERE id=jobs.enrollment_id AND status='active')",
                    now(),
                    enrollment["id"],
                ),
            ]
        )
        await activity(db, config, lead_id, "Agent resumed automation")
        return envelope({"status": "active"})

    async def manual(lead_id, channel, text, res, subject=""):
        db, config, _user = res
        lead = await get_lead(*res, lead_id)
        if lead["status"] == "opted_out" or not lead["consent_" + channel]:
            raise HTTPException(409, "Lead is not eligible for this channel")
        if not ready(with_overrides(config, await preferences(db, config)), channel):
            raise HTTPException(409, "Channel is not configured")
        await stop_lead(db, config, lead_id, "paused", "Agent took over follow-up")
        job_id = uid()
        await db.run(
            "INSERT INTO jobs(id,tenant_id,lead_id,channel,message,subject,due_at,status,created_at) VALUES (?,?,?,?,?,?,?,'pending',?)",
            job_id,
            config.tenant_id,
            lead_id,
            channel,
            text,
            subject,
            now(),
            now(),
        )
        job = await db.first("SELECT * FROM jobs WHERE id=?", job_id)
        result = await dispatch(db, config, job, provider, manual=True)
        if result in {"deferred", "capped"}:
            await db.run("UPDATE jobs SET status='paused' WHERE id=? AND status='pending'", job_id)
        return envelope({"id": job_id, "status": result})

    @app.post("/api/leads/{lead_id}/message")
    async def message(lead_id: str, body: MessageInput, res=Depends(authenticated)):
        return await manual(lead_id, "sms", body.text, res)

    @app.post("/api/leads/{lead_id}/email")
    async def email(lead_id: str, body: EmailInput, res=Depends(authenticated)):
        return await manual(lead_id, "email", body.text, res, body.subject)

    @app.post("/api/leads/{lead_id}/call")
    async def call(lead_id: str, res=Depends(authenticated)):
        return await manual(lead_id, "voice", "AI follow-up call", res)

    @app.post("/api/leads/{lead_id}/connect")
    async def connect(lead_id: str, res=Depends(authenticated)):
        """Click-to-call: ring the agent's own phone, then bridge to the lead once they answer."""
        db, config, user = res
        lead = await get_lead(db, config, user, lead_id)
        if lead["status"] == "opted_out":
            raise HTTPException(409, "Lead opted out")
        if not user.get("phone"):
            raise HTTPException(409, "Your phone number is not configured; ask an administrator")
        prefs = await preferences(db, config)
        config = with_overrides(config, prefs)
        if not ready(config, "bridge"):
            raise HTTPException(409, "Calling is not configured")
        hour = datetime.now(ZoneInfo(lead["timezone"])).hour
        if not prefs["contact_start_hour"] <= hour < prefs["contact_end_hour"]:
            raise HTTPException(409, "Outside the lead's contact hours")
        await stop_lead(db, config, lead_id, "paused", "Agent took over follow-up")
        job_id = uid()
        await db.run(
            "INSERT INTO jobs(id,tenant_id,lead_id,channel,message,due_at,status,created_at) VALUES (?,?,?,'bridge','Agent call',?,'sending',?)",
            job_id,
            config.tenant_id,
            lead_id,
            now(),
            now(),
        )
        try:
            adapter = provider or build_provider(config.provider_config)
            result = await adapter.start_bridge(user["phone"], job_id)
        except Exception as exc:  # noqa: BLE001 - an unknown transport failure must never be retried blindly
            await db.run(
                "UPDATE jobs SET status='needs_attention',error=? WHERE id=?",
                "Call was not placed; check calling setup"
                if isinstance(exc, ProviderRejected)
                else "Call outcome uncertain; review provider activity",
                job_id,
            )
            return envelope({"id": job_id, "status": "needs_attention"})
        await db.run("UPDATE leads SET last_called_at=? WHERE id=?", now(), lead_id)
        # The answered webhook may already have claimed the job; only advance it from 'sending'.
        await db.run(
            "UPDATE jobs SET provider_id=?,status=CASE WHEN status='sending' THEN ? ELSE status END WHERE id=?",
            result.provider_id,
            result.status,
            job_id,
        )
        await activity(
            db,
            config,
            lead_id,
            result.metadata.get("summary")
            or "Calling your phone; the lead is connected when you answer",
            "bridge",
            "outbound",
            result.status,
            job_id,
        )
        return envelope({"id": job_id, "status": result.status})

    @app.post("/api/leads/{lead_id}/log-call")
    async def log_call_route(lead_id: str, body: CallLog, res=Depends(authenticated)):
        db, config, user = res
        lead = await get_lead(db, config, user, lead_id)
        return envelope(await log_call(db, config, lead, body))

    @app.get("/api/queue")
    async def queue(
        tab: str = Query(default="today"),
        since: datetime | None = None,
        until: datetime | None = None,
        res=Depends(authenticated),
    ):
        if tab not in TABS:
            raise HTTPException(422, "Unknown queue tab")
        db, config, user = res
        start = since or datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return envelope(
            await work_queue(db, config, user, tab, start, until or start + timedelta(days=1))
        )

    @app.get("/api/tasks")
    async def list_tasks(
        status: str = Query(default="open", max_length=20), res=Depends(authenticated)
    ):
        db, config, user = res
        clause, args = scope(user)
        rows = await db.all(
            "SELECT tasks.*,leads.name AS lead_name,leads.phone AS lead_phone FROM tasks JOIN leads ON leads.id=tasks.lead_id AND leads.tenant_id=tasks.tenant_id WHERE tasks.tenant_id=?"
            + clause
            + " AND (?='' OR tasks.status=?) ORDER BY tasks.due_at LIMIT 200",
            config.tenant_id,
            *args,
            status,
            status,
        )
        return envelope(rows)

    @app.post("/api/leads/{lead_id}/tasks", status_code=201)
    async def create_task(lead_id: str, body: TaskInput, res=Depends(authenticated)):
        db, config, user = res
        await get_lead(db, config, user, lead_id)
        due = body.due_at or datetime.now(UTC)
        due = due if due.tzinfo else due.replace(tzinfo=UTC)
        task_id = uid()
        await db.run(
            "INSERT INTO tasks(id,tenant_id,lead_id,title,due_at,status,source,created_at) VALUES (?,?,?,?,?,'open','manual',?)",
            task_id,
            config.tenant_id,
            lead_id,
            body.title,
            due.astimezone(UTC).isoformat(timespec="seconds"),
            now(),
        )
        await activity(db, config, lead_id, "Task added: " + body.title)
        return envelope(await db.first("SELECT * FROM tasks WHERE id=?", task_id))

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, body: TaskPatch, res=Depends(authenticated)):
        db, config, user = res
        clause, args = scope(user)
        task = await db.first(
            "SELECT tasks.* FROM tasks JOIN leads ON leads.id=tasks.lead_id AND leads.tenant_id=tasks.tenant_id WHERE tasks.tenant_id=? AND tasks.id=?"
            + clause,
            config.tenant_id,
            task_id,
            *args,
        )
        if not task:
            raise HTTPException(404, "Task not found")
        if task["status"] == "cancelled":
            raise HTTPException(409, "Task was cancelled")
        await db.run(
            "UPDATE tasks SET status=?,completed_at=? WHERE id=?",
            body.status,
            now() if body.status == "done" else None,
            task_id,
        )
        return envelope(await db.first("SELECT * FROM tasks WHERE id=?", task_id))

    @app.post("/api/leads/{lead_id}/demo-reply")
    async def demo_reply(lead_id: str, body: MessageInput, res=Depends(authenticated)):
        await get_lead(*res, lead_id)
        if res[1].mode != "demo":
            raise HTTPException(404, "Not found")
        await inbound(res[0], res[1], lead_id, body.text)
        return envelope({"received": True})

    @app.get("/api/settings")
    async def settings_get(res=Depends(authenticated)):
        return envelope(public_preferences(await preferences(res[0], res[1])))

    @app.patch("/api/settings")
    async def settings_patch(body: Preferences, res=Depends(authenticated)):
        db, config, user = res
        admin(user)
        await preferences(db, config)
        values = body.model_dump()
        await db.run(
            "UPDATE pilot_settings SET "
            + ",".join(k + "=?" for k in values)
            + " WHERE tenant_id=?",
            *(int(v) if isinstance(v, bool) else v for v in values.values()),
            config.tenant_id,
        )
        return envelope(public_preferences(await preferences(db, config)))

    async def numbers_client(res):
        _db, config, user = res
        admin(user)
        try:
            return number_client(config.provider_config)
        except ProviderRejected:
            raise HTTPException(409, "Add the Telnyx API key to manage numbers") from None

    async def channel_view(db, config, client):
        try:
            options = await client.channel_options()
        except ProviderError:
            raise HTTPException(
                502, "Could not load channel options from Telnyx; try again"
            ) from None
        prefs = await preferences(db, config)
        base = config.provider_config
        return {
            "sms_enabled": bool(prefs["sms_enabled"]),
            "voice_enabled": bool(prefs["voice_enabled"]),
            "email_enabled": bool(prefs["email_enabled"]),
            "email_from": prefs["email_from"] or base.email_from,
            "email_from_name": prefs["email_from_name"] or base.email_from_name,
            "email_ready": ready(with_overrides(config, prefs), "email"),
            "messaging_profile_id": prefs["messaging_profile_id"] or base.messaging_profile_id,
            "connection_id": prefs["connection_id"] or base.connection_id,
            "assistant_id": prefs["assistant_id"] or base.assistant_id,
            "sms_ready": ready(with_overrides(config, prefs), "sms"),
            "voice_ready": ready(with_overrides(config, prefs), "voice"),
            **options,
        }

    @app.get("/api/channels")
    async def channels(res=Depends(authenticated)):
        client = await numbers_client(res)
        return envelope(await channel_view(res[0], res[1], client))

    @app.put("/api/channels")
    async def save_channels(body: ChannelSettings, res=Depends(authenticated)):
        client = await numbers_client(res)
        db, config, _user = res
        try:
            options = await client.channel_options()
        except ProviderError:
            raise HTTPException(502, "Could not verify channels with Telnyx; try again") from None
        for field, group in (
            ("messaging_profile_id", "messaging_profiles"),
            ("connection_id", "voice_apps"),
            ("assistant_id", "assistants"),
        ):
            value = getattr(body, field)
            if value and value not in {o["id"] for o in options[group]}:
                raise HTTPException(409, "Choose an option from your Telnyx account")
        base = config.provider_config
        if body.sms_enabled and not (body.messaging_profile_id or base.messaging_profile_id):
            raise HTTPException(409, "Choose a messaging profile before turning texts on")
        if body.voice_enabled and not (body.connection_id or base.connection_id):
            raise HTTPException(409, "Choose a voice app before turning calls on")
        if body.email_enabled and not (body.email_from or base.email_from):
            raise HTTPException(409, "Enter a sender address before turning email on")
        await preferences(db, config)
        await db.run(
            "UPDATE pilot_settings SET sms_enabled=?,voice_enabled=?,email_enabled=?,messaging_profile_id=?,connection_id=?,assistant_id=?,email_from=?,email_from_name=? WHERE tenant_id=?",
            int(body.sms_enabled),
            int(body.voice_enabled),
            int(body.email_enabled),
            body.messaging_profile_id,
            body.connection_id,
            body.assistant_id,
            body.email_from,
            body.email_from_name,
            config.tenant_id,
        )
        return envelope(await channel_view(db, config, client))

    @app.get("/api/numbers")
    async def numbers(res=Depends(authenticated)):
        client = await numbers_client(res)
        db, config, _user = res
        try:
            owned = await client.list_numbers()
        except ProviderError:
            raise HTTPException(502, "Could not load numbers from Telnyx; try again") from None
        selected = with_overrides(config, await preferences(db, config)).provider_config.from_number
        return envelope({"selected": selected or None, "numbers": owned})

    @app.get("/api/numbers/available")
    async def available_numbers(
        state: str = Query(default="FL", pattern=r"^[A-Z]{2}$"),
        area_code: str = Query(default="", pattern=r"^(\d{3})?$"),
        res=Depends(authenticated),
    ):
        client = await numbers_client(res)
        try:
            return envelope(await client.search_numbers(state, area_code))
        except ProviderError:
            raise HTTPException(502, "Could not search Telnyx numbers; try again") from None

    @app.post("/api/numbers/order")
    async def order_number(body: NumberChoice, res=Depends(authenticated)):
        client = await numbers_client(res)
        try:
            result = await client.order_number(body.phone_number)
        except ProviderAmbiguousError:
            # A purchase may have gone through: never let the dashboard silently retry it.
            raise HTTPException(
                502, "Order outcome unknown; check your Telnyx numbers before trying again"
            ) from None
        except ProviderError:
            raise HTTPException(
                409, "Telnyx did not accept the order; nothing was bought"
            ) from None
        return envelope({"order_id": result.provider_id, "status": result.status})

    @app.post("/api/numbers/select")
    async def select_number(body: NumberChoice, res=Depends(authenticated)):
        client = await numbers_client(res)
        db, config, _user = res
        try:
            owned = await client.list_numbers()
        except ProviderError:
            raise HTTPException(502, "Could not verify the number with Telnyx; try again") from None
        if not any(
            n["phone_number"] == body.phone_number and n["status"] == "active" for n in owned
        ):
            raise HTTPException(409, "Choose an active number from your Telnyx account")
        await preferences(db, config)
        await db.run(
            "UPDATE pilot_settings SET from_number=? WHERE tenant_id=?",
            body.phone_number,
            config.tenant_id,
        )
        return envelope({"selected": body.phone_number})

    @app.post("/api/automation/run")
    async def automation_run(res=Depends(authenticated)):
        admin(res[2])
        return envelope(await run_due(res[0], res[1], provider))

    @app.get("/api/dashboard")
    async def dashboard(res=Depends(authenticated)):
        db, config, user = res
        clause, args = scope(user)
        leads = await db.all(
            "SELECT id,status FROM leads WHERE tenant_id=?" + clause, config.tenant_id, *args
        )
        ids = {lead["id"] for lead in leads}
        jobs = [
            j
            for j in await db.all(
                "SELECT lead_id,status,due_at,created_at FROM jobs WHERE tenant_id=?",
                config.tenant_id,
            )
            if j["lead_id"] in ids
        ]
        tasks = await db.all(
            "SELECT due_at FROM tasks JOIN leads ON leads.id=tasks.lead_id AND leads.tenant_id=tasks.tenant_id WHERE tasks.tenant_id=? AND tasks.status='open'"
            + clause,
            config.tenant_id,
            *args,
        )
        return envelope(
            {
                "total_leads": len(leads),
                "active_followups": sum(l["status"] == "active" for l in leads),
                "due_today": sum(
                    j["status"] == "pending" and j["due_at"][:10] <= now()[:10] for j in jobs
                ),
                "needs_attention": sum(j["status"] == "needs_attention" for j in jobs),
                "sent_today": sum(
                    j["status"] in {"sent", "delivered", "initiated", "completed"}
                    and j["created_at"][:10] == now()[:10]
                    for j in jobs
                ),
                "paused": sum(l["status"] in {"paused", "replied"} for l in leads),
                "open_tasks": len(tasks),
                "overdue_tasks": sum(t["due_at"] < now() for t in tasks),
            }
        )

    @app.post("/api/webhooks/telnyx")
    @app.post("/webhooks/telnyx")
    async def webhook(request: Request, res=Depends(resources)):
        return envelope(await receive_webhook(request, res[0], res[1], verifier, provider))

    @app.post("/webhooks/assistant-outcome")
    @app.post("/api/webhooks/assistant-outcome")
    async def assistant_outcome(body: AssistantOutcome, res=Depends(resources)):
        db, config = res
        if not verify_outcome_token(
            body.outcome_token, config.voice_outcome_secret, config.tenant_id, body.dispatch_id
        ):
            raise HTTPException(401, "Invalid outcome authorization")
        job = await db.first(
            "SELECT * FROM jobs WHERE id=? AND tenant_id=? AND channel='voice'",
            body.dispatch_id,
            config.tenant_id,
        )
        if not job:
            raise HTTPException(404, "Call not found")
        existing = await db.first("SELECT outcome FROM voice_outcomes WHERE job_id=?", job["id"])
        if existing and (existing["outcome"] == "opt_out" or body.outcome != "opt_out"):
            return envelope({"duplicate": True})
        opted_out = body.outcome == "opt_out"
        # Atomic durable recording and suppression, with optout strongest precedence.
        await db.batch(
            [
                (
                    "INSERT INTO voice_outcomes VALUES (?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET outcome=excluded.outcome,summary=excluded.summary WHERE voice_outcomes.outcome!='opt_out' AND excluded.outcome='opt_out'",
                    job["id"],
                    config.tenant_id,
                    body.outcome,
                    body.summary,
                    now(),
                ),
                (
                    "UPDATE leads SET status=?"
                    + (",consent_sms=0,consent_voice=0,consent_email=0" if opted_out else "")
                    + " WHERE id=? AND tenant_id=? AND status!='opted_out'",
                    "opted_out" if opted_out else "replied",
                    job["lead_id"],
                    config.tenant_id,
                ),
                (
                    "UPDATE enrollments SET status=? WHERE lead_id=? AND tenant_id=? AND status IN ('active','paused')",
                    "completed" if opted_out else "paused",
                    job["lead_id"],
                    config.tenant_id,
                ),
                (
                    "UPDATE jobs SET status=? WHERE lead_id=? AND tenant_id=? AND status IN ('pending','leased','paused')",
                    "cancelled" if opted_out else "paused",
                    job["lead_id"],
                    config.tenant_id,
                ),
                (
                    "INSERT OR IGNORE INTO activities VALUES (?,?,?,?,?,?,?,?,?)",
                    "outcome-" + job["id"] + "-" + body.outcome,
                    config.tenant_id,
                    job["lead_id"],
                    job["id"],
                    "voice",
                    "inbound",
                    body.summary,
                    body.outcome,
                    now(),
                ),
                mark_contacted(config, job["lead_id"]),
                cancel_tasks(config, job["lead_id"])
                if opted_out
                else open_task(
                    config,
                    job["lead_id"],
                    OUTCOME_TASKS.get(body.outcome, "Review AI call") + ": " + body.summary,
                    "call_outcome",
                    "task-outcome-" + job["id"],
                ),
            ]
        )
        return envelope({"recorded": True})

    return app
