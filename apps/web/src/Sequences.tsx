import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import {
  type Sequence,
  type Step,
  type Template,
  CHANNEL_NAMES,
  PLACEHOLDERS,
} from "./api";
import { Empty, Field, Modal, Notice } from "./components";
import { ChannelIcon } from "./Templates";
export function Sequences({
  sequences,
  onSave,
  admin,
  templates = [],
}: {
  sequences: Sequence[];
  onSave: (data: { name: string; steps: Step[] }) => Promise<void>;
  admin: boolean;
  templates?: Template[];
}) {
  const [draft, setDraft] = useState<{ name: string; steps: Step[] } | null>(
    null,
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Consistent, thoughtful outreach</p>
          <h1>Follow-up sequences</h1>
          <p>Give every lead a clear next step.</p>
        </div>
        {admin && (
          <button
            onClick={() => {
              setError("");
              setDraft({
                name: "",
                steps: [
                  {
                    channel: "sms",
                    delay_minutes: 0,
                    message:
                      "Hi {{name}}, thanks for your interest. When would be a good time to connect?",
                  },
                ],
              });
            }}
          >
            <Plus size={16} /> New sequence
          </button>
        )}
      </div>
      <div className="sequence-grid">
        {sequences.map((s) => (
          <article className="card" key={s.id}>
            <div className="row">
              <h2>{s.name}</h2>
              <span className="muted">{s.steps.length} steps</span>
            </div>
            <ol className="steps">
              {s.steps.map((step, i) => (
                <li key={i}>
                  <span className="step-icon">
                    <ChannelIcon channel={step.channel} />
                  </span>
                  <div>
                    <strong>{CHANNEL_NAMES[step.channel]}</strong>
                    <small>
                      {step.delay_minutes === 0
                        ? "Immediately"
                        : `${step.delay_minutes} minutes after previous step`}
                    </small>
                    {step.subject && <p>Subject: {step.subject}</p>}
                    <p>{step.message}</p>
                  </div>
                </li>
              ))}
            </ol>
            {admin && (
              <button
                className="secondary"
                onClick={() => {
                  setError("");
                  setDraft({
                    name: `${s.name} (updated)`,
                    steps: s.steps.map((x) => ({ ...x })),
                  });
                }}
              >
                Create updated version
              </button>
            )}
          </article>
        ))}
      </div>
      {!sequences.length && (
        <Empty title="No sequences yet">
          Create a sequence to schedule your first follow-up.
        </Empty>
      )}
      {draft && (
        <Modal title="Create follow-up sequence" onClose={() => setDraft(null)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              try {
                await onSave(draft);
                setDraft(null);
              } catch (err) {
                setError((err as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <Field label="Sequence name">
              <input
                required
                value={draft.name}
                maxLength={100}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </Field>
            <p className="muted">
              Delays are measured from the previous step; the first delay starts
              at enrollment. Existing enrollments keep their original sequence.
              Personalize with {PLACEHOLDERS}.
            </p>
            {draft.steps.map((step, i) => {
              const set = (patch: Partial<Step>) =>
                setDraft({
                  ...draft,
                  steps: draft.steps.map((s, n) =>
                    n === i ? { ...s, ...patch } : s,
                  ),
                });
              const choices = templates.filter(
                (t) => t.channel === step.channel,
              );
              return (
                <div className="step-editor" key={i}>
                  <div className="row">
                    <h3>Step {i + 1}</h3>
                    <button
                      type="button"
                      className="icon"
                      disabled={draft.steps.length === 1}
                      aria-label={`Remove step ${i + 1}`}
                      onClick={() =>
                        setDraft({
                          ...draft,
                          steps: draft.steps.filter((_, n) => n !== i),
                        })
                      }
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                  <div className="form-grid">
                    <Field label="Channel">
                      <select
                        value={step.channel}
                        onChange={(e) =>
                          set({ channel: e.target.value as Step["channel"] })
                        }
                      >
                        <option value="sms">SMS</option>
                        <option value="email">Email</option>
                        <option value="voice">AI voice</option>
                      </select>
                    </Field>
                    <Field label="Wait after previous step (minutes)">
                      <input
                        type="number"
                        min="0"
                        max="525600"
                        required
                        value={step.delay_minutes}
                        onChange={(e) =>
                          set({ delay_minutes: Number(e.target.value) })
                        }
                      />
                    </Field>
                  </div>
                  {choices.length > 0 && (
                    <Field label="Start from template">
                      <select
                        value=""
                        onChange={(e) => {
                          const t = choices.find(
                            (c) => c.id === e.target.value,
                          );
                          if (t) set({ message: t.body, subject: t.subject });
                        }}
                      >
                        <option value="">Choose a template…</option>
                        {choices.map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.name}
                          </option>
                        ))}
                      </select>
                    </Field>
                  )}
                  {step.channel === "email" && (
                    <Field label="Subject">
                      <input
                        required
                        maxLength={200}
                        value={step.subject || ""}
                        onChange={(e) => set({ subject: e.target.value })}
                      />
                    </Field>
                  )}
                  <Field
                    label={
                      step.channel === "voice" ? "Call context" : "Message"
                    }
                  >
                    <textarea
                      required
                      maxLength={step.channel === "email" ? 5000 : 1200}
                      value={step.message}
                      onChange={(e) => set({ message: e.target.value })}
                    />
                  </Field>
                </div>
              );
            })}
            <button
              type="button"
              className="secondary"
              disabled={draft.steps.length >= 8}
              onClick={() =>
                setDraft({
                  ...draft,
                  steps: [
                    ...draft.steps,
                    { channel: "sms", delay_minutes: 1440, message: "" },
                  ],
                })
              }
            >
              <Plus size={16} /> Add step
            </button>
            {error && <Notice error>{error}</Notice>}
            <footer className="actions">
              <button disabled={busy}>
                {busy ? "Saving…" : "Save sequence"}
              </button>
            </footer>
          </form>
        </Modal>
      )}
    </>
  );
}
