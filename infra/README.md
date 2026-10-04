# Cloudflare pilot deployment

The React frontend deploys to Pages; the Python/FastAPI API deploys independently to Workers with D1 and a once-per-minute Cron Trigger. Telnyx runs the live voice AI. No container or paid VM is required. Start with a separate **demo** database and Worker. Local tests do not establish cloud CPU feasibility or live provider delivery.

## Prerequisites

- Python 3.13+, uv 0.12.3+, Node 22+, and installed locked dependencies. Run `uv sync --locked --all-groups` in `services/agent-followup` and `npm ci` in `apps/web` (plus the repository-root install when its toolchain lock is present).
- A Cloudflare account with an existing D1 database (record its UUID), enabled Workers subdomain, and an existing **Direct Upload** Pages project with production branch `main`.
- `CLOUDFLARE_API_TOKEN` provided through the terminal/CI secret environment. Scope it to your account and the needed **Workers Scripts: Edit**, **D1: Edit**, and **Cloudflare Pages: Edit** permissions; add **Account Settings: Read** if account discovery requires it. No DNS permission is needed for `workers.dev` and `pages.dev` URLs. Tokens must never be placed in this repository or frontend variables.
- The account ID, Worker name, Pages project name, exact HTTPS API origin, and exact HTTPS Pages production origin. Origin values must not have trailing slashes. Preview URLs are intentionally excluded from the backend CORS allowlist.
- A private secret JSON file outside the checkout, with restrictive local permissions. Do not paste it into terminal command arguments, issue comments, screenshots, or this repository.

The helper **does not create resources, buy phone numbers, enable paid subscriptions, change DNS, or delete resources**. Provision the named free resources through your account first. Consult [D1 setup](https://developers.cloudflare.com/d1/get-started/), [Pages direct upload](https://developers.cloudflare.com/pages/get-started/direct-upload/), and [API token permissions](https://developers.cloudflare.com/fundamentals/api/reference/permissions/).

## Credentials and mode

For demo, the secret file contains these two string values:

| Key | Value |
| --- | --- |
| `PILOT_TENANT_ID` | Stable company identifier; keep unchanged for the same database |
| `PILOT_USERS_JSON` | JSON **encoded as a string**, containing users with `id`, `name`, `role` (`admin`/`agent`), `token_sha256`, and optionally `phone` (E.164, for agent-first calling) |

Generate an independent high-entropy bearer token for each agent. Store only its lowercase SHA-256 hex digest in the user configuration; give the original token privately to that agent. Include at least one administrator. These are pilot credentials, not Cloudflare tokens or Telnyx keys. Replacing `PILOT_USERS_JSON` replaces the complete allowed user list; preserve existing users when adding a user. User IDs and tenant IDs must remain stable so historical ownership remains valid.

The secret-file whitelist additionally accepts `TELNYX_API_KEY`, `TELNYX_PUBLIC_KEY`, `TELNYX_FROM_NUMBER`, `TELNYX_MESSAGING_PROFILE_ID`, `TELNYX_ASSISTANT_ID`, `TELNYX_CONNECTION_ID`, `VOICE_OUTCOME_SECRET` (at least 32 characters), and `TELNYX_MAX_CALL_SECONDS` (30–300; provider default 120). All are string values. Provider identifiers are accepted as secrets to keep a single private deployment input. Omitted existing Worker secrets are not deleted by bulk upload.

The deployment owns `PILOT_MODE`, `FRONTEND_ORIGINS`, and `ENABLE_LIVE_SEND` as non-secret Wrangler vars. Do not put those in the secret file or create conflicting Worker secrets. `--mode live` alone keeps sending disabled. **Both** `--mode live --enable-live-send` and valid provider configuration are required to enable paid outreach. Application-level campaign approval, lead consent, suppression, and budget controls still apply.

## Review a deployment plan

Run from repository root, substituting your actual resource identifiers:

```sh
python3 scripts/deploy.py \
  --account-id YOUR_32_HEX_ACCOUNT_ID \
  --database-id YOUR_EXISTING_D1_UUID \
  --worker-name followup-demo \
  --pages-project followup-demo-web \
  --api-origin https://followup-demo.YOUR_SUBDOMAIN.workers.dev \
  --frontend-origin https://followup-demo-web.pages.dev \
  --secrets-file /absolute/private/path/pilot-secrets.json
```

Default behavior validates inputs and prints the command plan only. It writes no configuration and runs no subprocess. The secret file is validated without logging contents. `--target backend` or `--target frontend` deploys one side independently; resource arguments remain explicit for both targets. A frontend-only apply does not require a secret file.

When the plan matches the intended account and resources, add `--apply`. This is the explicit remote mutation switch. The backend path generates ignored `services/agent-followup/.wrangler.deploy.jsonc`, applies remote migrations, deploys a fail-closed Worker, and uploads the supplied secrets. The frontend builds with `VITE_API_BASE_URL` and deploys its `dist/` to Pages production. This build-time URL is public; no secret is bundled in the UI. With explicit live sending enabled, the script deploys the enabled Worker only after the preceding steps succeed.

On an existing live instance, pause active sequences before maintenance: remote migrations happen before deployment and do not pause the old Worker. Deployments are not atomic across D1, Worker, and Pages. On failure, sending remains disabled if the fail-closed Worker deployment completed, but earlier changes are **not** automatically rolled back. Subprocess output is suppressed to avoid secret leakage. Review deployment status in Cloudflare before retrying. Use forward database migrations; do not delete a populated D1 database to fix a deployment.

Commands follow Cloudflare's [D1 CLI](https://developers.cloudflare.com/workers/wrangler/commands/d1/), [Worker secret bulk upload](https://developers.cloudflare.com/workers/configuration/secrets/), and [Pages CLI](https://developers.cloudflare.com/workers/wrangler/commands/pages/). The checked-in service configuration remains strict JSON despite the `.jsonc` suffix so the helper can safely parse it without another dependency.

## Acceptance before real outreach

1. Open the Pages URL, sign in, create a synthetic lead, create and approve a demo sequence, and verify its timeline after scheduling.
2. Verify the browser calls the intended API origin. An unauthenticated request must fail; agent access must respect ownership. Ensure the database persists after a Worker redeploy.
3. Verify Cron delivery in the Cloudflare dashboard and that a due demo step executes once. Cron changes may take time to propagate. Measure request errors, CPU time, and D1 usage on the actual account before promising free hosting.
4. Configure Telnyx using the [provider runbook](../docs/telnyx-integration.md). The public signed webhook URL is `API_ORIGIN/api/webhooks/telnyx`; keep it reachable by Telnyx if adding an Access layer.
5. Use a separate live database/Worker, test only with consenting pilot recipients, verify inbound reply/STOP handling, and check delivery/call outcomes against Telnyx logs. Confirm credit eligibility and account spend controls in Telnyx. The application counters are guardrails, not authoritative billing.

Cloudflare credentials, resource IDs, provider provisioning, remote deployment, and live delivery testing remain external prerequisites. A successful local demo does not mean they have been completed.

## Automatic deployment

`.github/workflows/deploy.yml` runs on every push to `main` (including merged pull requests) and on demand from the Actions tab. It reruns the backend, deployment-script and frontend checks, then runs `scripts/deploy.py --apply` and checks `API_ORIGIN/health`. Deployments never overlap and are never cancelled halfway. The deploy job is **skipped** until the `production` environment has `CLOUDFLARE_ACCOUNT_ID`, so merging before setup is safe.

Create a GitHub environment named `production` (Settings → Environments; add required reviewers there if every deploy should wait for approval) with:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `CLOUDFLARE_API_TOKEN` | The scoped token described above, plus Zone **Workers Routes: Edit** and **DNS: Edit** for a custom API domain |
| Secret | `PILOT_SECRETS_JSON` | The full contents of the private secret JSON file |
| Variable | `CLOUDFLARE_ACCOUNT_ID` | 32-character account ID |
| Variable | `D1_DATABASE_ID` | Existing D1 UUID |
| Variable | `WORKER_NAME` / `PAGES_PROJECT` | Existing resource names |
| Variable | `API_ORIGIN` / `FRONTEND_ORIGIN` | Exact HTTPS origins, no trailing slash |
| Variable | `PILOT_MODE` | `demo` (default) or `live` |
| Variable | `ENABLE_LIVE_SEND` | `true` only for real outreach; anything else keeps sending off |

With the GitHub CLI, secrets can be set from files so they never appear in shell history:

```sh
gh secret set PILOT_SECRETS_JSON --env production < /absolute/private/path/pilot-secrets.json
gh secret set CLOUDFLARE_API_TOKEN --env production   # paste when prompted
gh variable set API_ORIGIN --env production --body https://api.example.com
```

A custom `API_ORIGIN` hostname (anything other than `*.workers.dev`) is attached to the Worker as a custom domain on every deploy. Attach the dashboard's custom domain once under the Pages project (Custom domains). Updating `PILOT_SECRETS_JSON` takes effect on the next deploy; rerun the workflow to apply it immediately.
