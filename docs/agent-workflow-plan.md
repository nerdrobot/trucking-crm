# Agent calling workflow plan

Updated: 2026-10-03

Source: screenshots of Rolt, a calling CRM used by a truck dispatch sales team (kept outside the repo in `~/personal/real-estate/rolt-screenshots/`; they contain coworker names and real business numbers). Rolt is built around one daily loop: here are your leads, call them, log what happened, set the next follow-up. This CRM already has the automation (AI calls, sequences, opt-out handling) but is weak on that loop.

Decision from the project owner: **no drag-and-drop board.** Replace the Pipeline board with list-and-tab views; stage becomes a column and a filter.

## Phase 1: the agent's daily loop (done)

1. **My leads queue** replaces the Pipeline page and becomes the agent's home screen.
   - Tabs with counts: Today · Untouched · Follow ups · In progress · Closed.
   - Header counts: assigned today, called today, still untouched, follow-ups due.
   - Sort: overdue and due follow-ups first, then leads never called.
   - Each row: company, carrier type and niche, stage with the last outcome under it, phone, next follow-up (red when overdue), last activity, and a **Log call** button.
2. **Log call with an outcome.** Outcomes: connected, no answer, voicemail, interested, not interested, wrong number, call back, appointment set.
   - The outcome sets the stage automatically (for example no answer → contacted, wrong number → lost, appointment set → showing) and asks for the next follow-up date.
   - Works for manual calls and "Call me first" calls; records an activity on the timeline.
   - Wrong number should mark the phone as bad rather than an opt-out (closes the gap noted in the opt-out fix).
3. **One follow-up date per lead.** Store `next_followup_at` on the lead; keep tasks as the detail behind it. Show it in every list; overdue in red.
4. **Expandable rows.** Clicking a row shows the lead's timeline inline (calls, stage changes, notes, messages, sequence enrollments) without leaving the list.
5. **Remove the Pipeline board** (`Pipeline` in `apps/web/src/Workboard.tsx` and its nav item). Keep stages, the stage column and the `?stage=` filter.

## Phase 2: manager tools

- **Lead pool** for admins: filters (stage, dispatcher, carrier type, niche, source), checkboxes, and bulk actions: assign, take back, change stage, enroll in sequence, remove.
- **Manager overview**: totals for calls, interested, appointments, won, waiting to be assigned, overdue follow-ups, idle 14+ days; a per-agent table (assigned today, called today, untouched, due, calls, interested, appointments, call backs, no answer, not interested); calls-per-day chart; date ranges Today / 7 days / 30 days / this month.

## Phase 3: later

- Uploads tracked as named datasets (imported, skipped, worked X of Y, interested, won, uploaded by).
- Message templates: SMS first (after 10DLC), email once an email channel exists. Fields fill from the lead and sender; editable before sending.
- Per-person, per-day activity view.

## Out of scope

Time off, pay, policies, training and "reveals" in Rolt are HR or data-vendor features, not CRM.

## Constraints to keep

- Rolt cold-calls purchased business lists. Here, AI calls and texts still require recorded consent, opt-out stays permanent, and contact hours apply. Agents calling leads themselves can follow Rolt's workflow.
- Existing tests: backend `services/agent-followup/tests`, frontend `apps/web/src/*.test.tsx`. Keep both suites green and add tests for each new behaviour.
