import { useState } from "react";
import { type Settings as SettingsType, type Session } from "./api";
import { Field, Notice } from "./components";
export function Settings({
  settings,
  session,
  onSave,
  onRun,
}: {
  settings: SettingsType;
  session: Session;
  onSave: (data: SettingsType) => Promise<void>;
  onRun: () => Promise<unknown>;
}) {
  const [draft, setDraft] = useState(settings);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  async function operation(fn: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await fn();
      setSuccess(message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Keep outreach in control</p>
          <h1>Automation settings</h1>
          <p>Set daily limits and respectful contact hours.</p>
        </div>
      </div>
      <div className="settings-layout">
        <form
          className="card"
          onSubmit={(e) => {
            e.preventDefault();
            operation(() => onSave(draft), "Settings saved.");
          }}
        >
          <h2>Outreach controls</h2>
          <label className="check">
            <input
              type="checkbox"
              checked={draft.automation_enabled}
              onChange={(e) =>
                setDraft({ ...draft, automation_enabled: e.target.checked })
              }
            />{" "}
            Enable scheduled follow-ups
          </label>
          <div className="form-grid">
            <Field label="Daily SMS limit">
              <input
                type="number"
                min="0"
                max="1000"
                required
                value={draft.daily_sms_limit}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    daily_sms_limit: Number(e.target.value),
                  })
                }
              />
            </Field>
            <Field label="Daily AI call limit">
              <input
                type="number"
                min="0"
                max="100"
                required
                value={draft.daily_call_limit}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    daily_call_limit: Number(e.target.value),
                  })
                }
              />
            </Field>
            <Field label="Start hour (0–23)">
              <input
                type="number"
                min="0"
                max="23"
                required
                value={draft.contact_start_hour}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    contact_start_hour: Number(e.target.value),
                  })
                }
              />
            </Field>
            <Field label="End hour (1–24)">
              <input
                type="number"
                min={draft.contact_start_hour + 1}
                max="24"
                required
                value={draft.contact_end_hour}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    contact_end_hour: Number(e.target.value),
                  })
                }
              />
            </Field>
          </div>
          <p className="muted">
            Contact hours use each lead’s timezone. Daily limits restrict
            attempts, not dollar spend. Carrier and voice charges vary.
          </p>
          {error && <Notice error>{error}</Notice>}
          {success && <Notice>{success}</Notice>}
          <footer className="actions">
            <button disabled={busy}>
              {busy ? "Working…" : "Save settings"}
            </button>
          </footer>
        </form>
        <div>
          <article className="card">
            <h2>Workspace readiness</h2>
            <div className="readiness">
              <span>Workspace mode</span>
              <strong>{session.mode === "demo" ? "Demo" : "Live"}</strong>
              <span>Text messaging</span>
              <strong>{session.sms_ready ? "Ready" : "Setup required"}</strong>
              <span>AI voice</span>
              <strong>
                {session.voice_ready ? "Ready" : "Setup required"}
              </strong>
            </div>
            <p className="muted">
              {session.mode === "demo"
                ? "All outreach is simulated. Explore the complete workflow without using your Telnyx credit."
                : "Real outreach can incur Telnyx charges. Start with a small daily limit."}
            </p>
          </article>
          <article className="card">
            <h2>Process due follow-ups</h2>
            <p className="muted">
              Run eligible, scheduled steps now. Future steps remain scheduled;
              contact hours and limits still apply.
            </p>
            <button
              className="secondary"
              disabled={busy}
              onClick={() =>
                operation(
                  onRun,
                  "Due follow-ups processed. Check lead timelines for results.",
                )
              }
            >
              Run due follow-ups
            </button>
          </article>
        </div>
      </div>
    </>
  );
}
