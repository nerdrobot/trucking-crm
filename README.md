# Trucking CRM

A lead-management and follow-up CRM for truck dispatch sales teams. Working brand: **Haulbase** (placeholder).

Dispatchers work a daily call queue of carrier leads (owner-operators and fleets): call, log the outcome, set the next follow-up. Automated SMS, email and AI voice sequences run in the background.

Forked from `~/personal/real-estate-ai-platform` and retargeted from buyer/seller leads to carriers. The architecture, consent handling, Telnyx adapters and deployment tooling are unchanged.

## What's in it

- **Carrier leads:** company, contact, phone, email, MC and DOT numbers, owner-operator or fleet, truck count, niche (dry van, reefer, car hauler…), city and state. Search covers company, contact, phone, city, MC and DOT.
- **Pipeline:** new → contacted → interested → qualified → agreement sent → onboarded, plus lost.
- **My leads queue:** Today, Untouched, Follow ups, In progress and Closed tabs. **Log call** outcomes move the stage forward and schedule the next follow-up.
- **Sequences and templates:** multi-step SMS, AI voice and email outreach. Placeholders: `{{first_name}}`, `{{name}}`, `{{company}}`, `{{agent_name}}`.
- **Tasks**, CSV import (up to 200 rows), per-channel consent records, opt-out detection, daily send limits and contact hours.
- **Calling:** "Call me first" rings the dispatcher, then connects the lead. A Telnyx AI assistant can also call; its script is in [docs/telnyx-assistant.template.json](docs/telnyx-assistant.template.json).
- **Demo mode** runs every workflow with simulated communications, with no Telnyx spend.

## Stack

- Frontend: React + TypeScript (Vite), deployed on Cloudflare Pages: `apps/web/`
- Backend: Python + FastAPI on Cloudflare Python Workers, D1 database, minute Cron dispatcher: `services/agent-followup/`
- Communications: Telnyx SMS, Voice/Call Control, hosted Voice AI and email

## Run locally

Install Python 3.13+, uv, and Node 22+. Run `uv sync --locked --all-groups` in `services/agent-followup`, and `npm ci` in `apps/web`. Then, from the repository root:

```sh
python3 services/agent-followup/scripts/setup_local.py
python3 scripts/dev.py
```

Open http://127.0.0.1:5173 and sign in using a generated key from `services/agent-followup/.local-pilot-keys.json`.

### CSV import columns

Required: `name`, `phone` (E.164, e.g. `+13125550123`). Optional: `email`, `company`, `mc_number`, `dot_number`, `kind` (`owner_operator` or `fleet`), `fleet_size`, `niche`, `city`, `state`, `timezone`, `agent_id`, `consent_sms`, `consent_voice`, `consent_email`, `consent_note`.

## Tests

```sh
cd services/agent-followup && uv run pytest     # API, queue, providers, webhooks
cd apps/web && npm test && npm run build         # UI tests, type-check, build
python3 -m pytest tests                          # deploy script
```

## Deploy

See [infra/README.md](infra/README.md). This repo needs its **own** Cloudflare Pages project, Worker, D1 database and tenant ID. Do not reuse the real estate platform's resources.

## Repository layout

```text
apps/web/                 React dispatcher dashboard
services/agent-followup/  FastAPI follow-up and lead service
packages/                 Future shared contracts
infra/                    Deployment runbook
scripts/                  Local launcher and deploy helper
docs/                     Architecture, Telnyx integration, workflow plan
```

## Not built yet

- FMCSA lookup (auto-fill company and authority from an MC/DOT number)
- Admin lead pool with bulk assign and stage changes
- Manager overview dashboard (per-dispatcher calls and conversions)
- Lead folders and uploads history

These come from Rolt; [docs/agent-workflow-plan.md](docs/agent-workflow-plan.md) describes them.
