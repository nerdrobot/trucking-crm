# Agent follow-up backend

Python/FastAPI service for the trucking CRM pilot, deployed independently from the React dashboard. One dispatch company per deployment, named admin/agent access keys, D1 persistence and a minute Cron dispatcher. Demo mode exercises SMS and Voice AI workflows without contacting Telnyx.

## Local pilot

From the repository root:

```sh
python3 services/agent-followup/scripts/setup_local.py
python3 scripts/dev.py
```

Requirements: Python 3.13+, uv 0.12.3+, Node 22+. Install the backend dependencies first with `uv sync --locked --all-groups` in this directory and the dashboard dependencies with `npm ci` in `apps/web` (see root README for the current frontend path). The local setup writes separate admin/agent keys to ignored `.local-pilot-keys.json`, mode 0600. `.dev.vars` contains only token hashes. Open the frontend and enter a key; it stays in memory until refresh/sign-out. `--force` backs up an existing config before replacing it.

The root launcher applies local migrations, starts the real Python Worker on localhost:8787 and polls its local scheduled-event endpoint every 15 seconds. No account credentials or Telnyx credit are needed. Create a lead with explicitly recorded channel consent, create a sequence, and enroll the lead. Demo steps can use zero delay. Simulated replies pause future jobs; STOP permanently opts out both channels.

For CPython-only tooling, `uvicorn followup.local:local_app --factory --app-dir src` uses `PILOT_SQLITE_PATH` and ordinary environment variables. This adapter does not run Cron automatically.

## Configuration

- `PILOT_MODE`: `demo` by default; `live` must be explicit.
- `PILOT_TENANT_ID`: fixed deployment company, never supplied by requests.
- `PILOT_USERS_JSON`: array of `{id,name,role,token_sha256}`, plus an optional E.164 `phone` that enables that user's **Call me first** button. Admins can switch texting and calling on or off and choose the Telnyx messaging profile, voice app, AI assistant and caller number under **Automation → Channels / Caller number**; those choices override the `TELNYX_*` defaults. `TELNYX_MESSAGING_PROFILE_ID` is optional for voice-only pilots. Roles `admin`/`agent`; keys should contain at least 32 random bytes. No plaintext keys or passwords in the server configuration.
- `FRONTEND_ORIGINS`: exact comma-separated frontend origins.
- `ENABLE_LIVE_SEND=true`: explicit live dispatch gate.
- `TELNYX_API_KEY`, `TELNYX_PUBLIC_KEY`, `TELNYX_FROM_NUMBER`, `TELNYX_MESSAGING_PROFILE_ID`: SMS configuration and signed callback verification.
- `TELNYX_CONNECTION_ID`, `TELNYX_ASSISTANT_ID`, `TELNYX_MAX_CALL_SECONDS` (default120): hosted voice configuration.
- `VOICE_OUTCOME_SECRET`: at least32 characters, independent random secret signing per-call assistant outcome tokens.

Use Worker secrets for credentials/user hashes. Never expose any of these credentials in the browser. See [Telnyx setup](../../docs/telnyx-integration.md) and deployment documentation. The committed Wrangler configuration uses a placeholder D1 identifier and disables the public workers.dev route; it is not deployed by local setup.

## API

Authenticated endpoints use `/api`, `Authorization: Bearer <individual key>`, and `{success,data,error}` envelopes. Agents see and modify assigned leads only; admins can assign leads, create sequences, change limits and manually trigger the scheduler.

- `GET /api/me`, `/api/agents`, `/api/dashboard`.
- `GET/POST /api/leads`, `POST /api/leads/import` (CSV, up to200 rows).
- `GET/PATCH /api/leads/{id}` with activity timeline, durable jobs and enrollment.
- `GET/POST /api/sequences`; steps snapshot into immutable scheduled jobs on enrollment.
- `POST /api/leads/{id}/enroll`, `/pause`, `/resume`, `/complete`.
- `POST /api/leads/{id}/message`, `/call`: consent-gated agent takeover, under the same quiet hours and spending caps.
- `POST /api/leads/{id}/demo-reply`: demo only.
- `GET/PATCH /api/settings`, `POST /api/automation/run`.
- `POST /api/webhooks/telnyx`: timestamped Ed25519 signature against raw body; `/webhooks/telnyx` alias.
- `POST /api/webhooks/assistant-outcome`: per-dispatch HMAC authorization; `/webhooks/assistant-outcome` alias.

Lead phone numbers must use E.164 format. Channel consent defaults false and requires a note when enabled. The pilot does not allow reactivating opted-out contacts. Live mode defaults automation off,8:00–20:00 in each lead's IANA timezone; demo defaults0:00–24:00. DST is handled by timezone data. Limits count dispatch reservations, not carrier-billed segments or dollars, and reset at UTC midnight. A failed/uncertain reservation still consumes budget conservatively.

## Reliability and limits

Jobs are conditionally claimed and marked sending before network I/O. Expired leases and ambiguous provider failures require human reconciliation; they are never blindly resent. Only explicit retry-safe errors are retried, up to3 total attempts. Each Cron tick processes at most10 due jobs. Enrollment snapshots preserve step content; overlapping active enrollments are prohibited.

Inbound replies pause automation. Opt-out suppresses both channels. Manual outreach pauses the sequence. Telnyx callbacks deduplicate event IDs and prevent terminal delivery regression. Voice calls pause for agent review when they end; the configured assistant outcome tool records interest/handoff requests or verbal opt-out. **Call me first** rings the agent's own phone, then transfers the call to the lead once the agent answers; it needs the voice application but not the AI assistant, blocks opted-out leads and respects contact hours. Replies and AI call outcomes create agent tasks (opt-out cancels them), and each lead has a pipeline stage. Agents work from **My leads** (`/api/queue`): Today, Untouched, Follow ups, In progress and Closed tabs. **Log call** (`/api/leads/{id}/log-call`) records an outcome that moves the stage forward, sets the next follow-up (no answer and voicemail default to 9am tomorrow in the lead's time zone), pauses automation after a conversation and stops it for not interested or wrong number. Actual appointment booking is not implemented. A send already accepted by the provider can complete after a pause; the API cannot retract it.

The pilot stores basic contact data, consent notes, message text and structured call summaries. It does not fetch recordings/transcripts or provide automatic account recovery, SSO or key rotation UI. Admins manage users by updating the server-side user list. Cloud free-tier CPU and production account delivery still require deployed measurements and account-specific verification.

## Verification

```sh
uv run ruff check src tests scripts
uv run pytest
uv run python scripts/smoke.py prepare
uv run pywrangler d1 migrations apply DB --local
uv run pywrangler dev --ip 127.0.0.1 --port 8787 --test-scheduled
# another terminal
uv run python scripts/smoke.py run
```

The smoke test creates synthetic contacts, triggers actual local Cron, persists simulated SMS and voice outcomes in D1, verifies Ed25519 through native Workers WebCrypto, and checks permanent opt-out. It never contacts Telnyx. `prepare --force` backs up existing local configuration before creating smoke credentials. Restore the previous `.dev.vars` or rerun `setup_local.py --force` before returning to the dashboard.

Runtime dependencies use the WebAssembly `pylock.toml`; CPython tooling uses `uv.lock`. Cryptography is dev-only; production signatures use native WebCrypto. Coverage is enforced at80% minimum.
