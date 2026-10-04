import { useState } from "react";
import { Mail, MessageSquare, Phone, Plus, Trash2 } from "lucide-react";
import {
  type Channel,
  type Template,
  CHANNEL_NAMES,
  PLACEHOLDERS,
} from "./api";
import { Empty, Field, Modal, Notice } from "./components";
export type TemplateDraft = Pick<
  Template,
  "name" | "channel" | "subject" | "body"
> & { id?: string };
export const ChannelIcon = ({ channel }: { channel: string }) =>
  channel === "email" ? (
    <Mail size={17} />
  ) : channel === "voice" ? (
    <Phone size={17} />
  ) : (
    <MessageSquare size={17} />
  );
const blank: TemplateDraft = {
  name: "",
  channel: "email",
  subject: "",
  body: "",
};
export function Templates({
  templates,
  admin,
  onSave,
  onDelete,
}: {
  templates: Template[];
  admin: boolean;
  onSave: (draft: TemplateDraft) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState<TemplateDraft | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function work(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      setDraft(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Write it once, reuse it everywhere</p>
          <h1>Message templates</h1>
          <p>
            Reusable emails, texts and call scripts for sequences and one-off
            messages.
          </p>
        </div>
        {admin && (
          <button
            onClick={() => {
              setError("");
              setDraft({ ...blank });
            }}
          >
            <Plus size={16} /> New template
          </button>
        )}
      </div>
      <div className="sequence-grid">
        {templates.map((t) => (
          <article className="card" key={t.id}>
            <div className="row">
              <h2>{t.name}</h2>
              <span className="muted">
                <ChannelIcon channel={t.channel} /> {CHANNEL_NAMES[t.channel]}
              </span>
            </div>
            {t.subject && <strong>{t.subject}</strong>}
            <p className="template-body">{t.body}</p>
            {admin && (
              <button
                className="secondary"
                onClick={() => {
                  setError("");
                  setDraft({ ...t });
                }}
              >
                Edit template
              </button>
            )}
          </article>
        ))}
      </div>
      {!templates.length && (
        <Empty title="No templates yet">
          {admin
            ? "Create a template to reuse your best messages."
            : "Ask an administrator to add message templates."}
        </Empty>
      )}
      {draft && (
        <Modal
          title={draft.id ? "Edit template" : "Create template"}
          onClose={() => setDraft(null)}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              work(() => onSave(draft));
            }}
          >
            <div className="form-grid">
              <Field label="Template name">
                <input
                  required
                  maxLength={100}
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
              </Field>
              <Field label="Channel">
                <select
                  value={draft.channel}
                  onChange={(e) =>
                    setDraft({ ...draft, channel: e.target.value as Channel })
                  }
                >
                  <option value="email">Email</option>
                  <option value="sms">Text message</option>
                  <option value="voice">AI call script</option>
                </select>
              </Field>
            </div>
            {draft.channel === "email" && (
              <Field label="Subject">
                <input
                  required
                  maxLength={200}
                  value={draft.subject}
                  onChange={(e) =>
                    setDraft({ ...draft, subject: e.target.value })
                  }
                />
              </Field>
            )}
            <Field
              label={draft.channel === "voice" ? "Call context" : "Message"}
              hint={`Placeholders: ${PLACEHOLDERS}`}
            >
              <textarea
                required
                rows={draft.channel === "email" ? 10 : 4}
                maxLength={draft.channel === "email" ? 5000 : 1200}
                value={draft.body}
                onChange={(e) => setDraft({ ...draft, body: e.target.value })}
              />
            </Field>
            {draft.channel === "email" && (
              <p className="muted">
                Marketing emails must include your company's postal address.
                Recipients can unsubscribe from their email app; that stops
                email only.
              </p>
            )}
            {error && <Notice error>{error}</Notice>}
            <footer className="actions">
              {draft.id && (
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => work(() => onDelete(draft.id as string))}
                >
                  <Trash2 size={16} /> Delete
                </button>
              )}
              <button disabled={busy}>
                {busy ? "Saving…" : "Save template"}
              </button>
            </footer>
          </form>
        </Modal>
      )}
    </>
  );
}
