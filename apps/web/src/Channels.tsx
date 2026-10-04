import { useEffect, useState, type FormEvent } from "react";
import { Field, Loading, Notice } from "./components";
type Api = <T>(path: string, method?: string, body?: unknown) => Promise<T>;
type Option = { id: string; name: string };
export interface ChannelView {
  sms_enabled: boolean;
  voice_enabled: boolean;
  email_enabled?: boolean;
  email_from?: string;
  email_from_name?: string;
  email_ready?: boolean;
  messaging_profile_id: string;
  connection_id: string;
  assistant_id: string;
  sms_ready: boolean;
  voice_ready: boolean;
  messaging_profiles: Option[];
  voice_apps: Option[];
  assistants: Option[];
}
function Choice({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  options: Option[];
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const known = options.some((o) => o.id === value);
  return (
    <Field label={label}>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Choose…</option>
        {!known && value && <option value={value}>{value} (current)</option>}
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
      </select>
    </Field>
  );
}
export function Channels({ api, onSaved }: { api: Api; onSaved: () => void }) {
  const [view, setView] = useState<ChannelView | null>(null);
  const [form, setForm] = useState({
    sms_enabled: false,
    voice_enabled: false,
    email_enabled: false,
    email_from: "",
    email_from_name: "",
    messaging_profile_id: "",
    connection_id: "",
    assistant_id: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  function show(data: ChannelView) {
    setView(data);
    setForm({
      sms_enabled: data.sms_enabled,
      voice_enabled: data.voice_enabled,
      email_enabled: !!data.email_enabled,
      email_from: data.email_from || "",
      email_from_name: data.email_from_name || "",
      messaging_profile_id: data.messaging_profile_id || "",
      connection_id: data.connection_id || "",
      assistant_id: data.assistant_id || "",
    });
  }
  useEffect(() => {
    api<ChannelView>("/channels")
      .then((data) =>
        Array.isArray(data?.voice_apps)
          ? show(data)
          : setError("Channels unavailable"),
      )
      .catch((e) => setError((e as Error).message));
  }, [api]);
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      show(await api<ChannelView>("/channels", "PUT", form));
      setSaved(true);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const set = (patch: Partial<typeof form>) => {
    setSaved(false);
    setForm({ ...form, ...patch });
  };
  return (
    <section className="card channels">
      <h2>Channels</h2>
      <p className="muted">
        Turn texting and calling on or off for everyone, and choose which Telnyx
        resources they use.
      </p>
      {error && <Notice error>{error}</Notice>}
      {!view ? (
        !error && <Loading />
      ) : (
        <form onSubmit={save}>
          <fieldset className="channel">
            <label className="switch">
              <input
                type="checkbox"
                checked={form.sms_enabled}
                onChange={(e) => set({ sms_enabled: e.target.checked })}
              />
              Text messages
              <span className={`badge ${view.sms_ready ? "active" : ""}`}>
                {view.sms_ready ? "Ready" : "Off"}
              </span>
            </label>
            <Choice
              label="Messaging profile"
              value={form.messaging_profile_id}
              options={view.messaging_profiles}
              disabled={!form.sms_enabled}
              onChange={(v) => set({ messaging_profile_id: v })}
            />
            <small className="muted">
              Texting US numbers requires an approved 10DLC campaign on this
              profile; without it carriers block messages.
            </small>
          </fieldset>
          <fieldset className="channel">
            <label className="switch">
              <input
                type="checkbox"
                checked={form.voice_enabled}
                onChange={(e) => set({ voice_enabled: e.target.checked })}
              />
              Calls (AI calls and Call me first)
              <span className={`badge ${view.voice_ready ? "active" : ""}`}>
                {view.voice_ready ? "Ready" : "Off"}
              </span>
            </label>
            <Choice
              label="Voice app"
              value={form.connection_id}
              options={view.voice_apps}
              disabled={!form.voice_enabled}
              onChange={(v) => set({ connection_id: v })}
            />
            <Choice
              label="AI assistant"
              value={form.assistant_id}
              options={view.assistants}
              disabled={!form.voice_enabled}
              onChange={(v) => set({ assistant_id: v })}
            />
          </fieldset>
          <fieldset className="channel">
            <label className="switch">
              <input
                type="checkbox"
                checked={form.email_enabled}
                onChange={(e) => set({ email_enabled: e.target.checked })}
              />
              Email
              <span className={`badge ${view.email_ready ? "active" : ""}`}>
                {view.email_ready ? "Ready" : "Off"}
              </span>
            </label>
            <Field label="Sender address">
              <input
                type="email"
                disabled={!form.email_enabled}
                value={form.email_from}
                onChange={(e) => set({ email_from: e.target.value })}
                placeholder="dispatch@haulbase.example"
              />
            </Field>
            <Field label="Sender name">
              <input
                maxLength={100}
                disabled={!form.email_enabled}
                value={form.email_from_name}
                onChange={(e) => set({ email_from_name: e.target.value })}
                placeholder="Haulbase Dispatch"
              />
            </Field>
            <small className="muted">
              The sender's domain must be verified under Telnyx Email; leads can
              unsubscribe from email without affecting calls or texts.
            </small>
          </fieldset>
          {saved && <Notice>Channels saved.</Notice>}
          <footer className="actions">
            <button disabled={busy}>
              {busy ? "Saving…" : "Save channels"}
            </button>
          </footer>
        </form>
      )}
    </section>
  );
}
