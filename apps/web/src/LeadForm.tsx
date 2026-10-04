import { useState, type FormEvent } from "react";
import {
  initialLead,
  KINDS,
  NICHES,
  validPhone,
  type Lead,
  type Agent,
} from "./api";
import { Field, Notice } from "./components";
export function LeadForm({
  lead,
  agents,
  onSave,
  onClose,
}: {
  lead?: Lead;
  agents: Agent[];
  onSave: (data: typeof initialLead) => Promise<void>;
  onClose: () => void;
}) {
  const [data, setData] = useState({
    ...initialLead,
    ...lead,
    agent_id: lead?.agent_id || agents[0]?.id || "",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const change = (key: string, value: string | number | boolean) =>
    setData((prev) => ({ ...prev, [key]: value }));
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!validPhone(data.phone)) {
      setError("Use an international phone number, for example +13125550123.");
      return;
    }
    if (
      (data.consent_sms || data.consent_voice || data.consent_email) &&
      !data.consent_note.trim()
    ) {
      setError("Record where and when this lead agreed to be contacted.");
      return;
    }
    setBusy(true);
    try {
      await onSave(
        Object.fromEntries(
          Object.keys(initialLead).map((k) => [
            k,
            data[k as keyof typeof initialLead],
          ]),
        ) as typeof initialLead,
      );
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit}>
      <datalist id="niches">
        {NICHES.map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>
      <div className="form-grid">
        <Field label="Company">
          <input
            maxLength={150}
            value={data.company || ""}
            onChange={(e) => change("company", e.target.value)}
            placeholder="Garden State Haulers LLC"
          />
        </Field>
        <Field label="Contact name">
          <input
            required
            maxLength={100}
            value={data.name}
            onChange={(e) => change("name", e.target.value)}
          />
        </Field>
        <Field
          label="Phone"
          hint={
            lead
              ? "Phone is fixed to preserve its consent record. Add a new contact for a different number."
              : "Include country code, e.g. +13125550123"
          }
        >
          <input
            required
            type="tel"
            disabled={!!lead}
            value={data.phone}
            onChange={(e) => change("phone", e.target.value)}
          />
        </Field>
        <Field label="Email">
          <input
            type="email"
            value={data.email || ""}
            onChange={(e) => change("email", e.target.value)}
          />
        </Field>
        <Field label="Carrier type">
          <select
            value={data.kind}
            onChange={(e) => change("kind", e.target.value)}
          >
            {Object.entries(KINDS).map(([value, name]) => (
              <option key={value} value={value}>
                {name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Trucks">
          <input
            type="number"
            min={0}
            max={10000}
            value={data.fleet_size ?? 1}
            onChange={(e) => change("fleet_size", Number(e.target.value))}
          />
        </Field>
        <Field label="MC number" hint="Digits only">
          <input
            inputMode="numeric"
            pattern="\\d{0,8}"
            value={data.mc_number || ""}
            onChange={(e) => change("mc_number", e.target.value.trim())}
          />
        </Field>
        <Field label="DOT number" hint="Digits only">
          <input
            inputMode="numeric"
            pattern="\\d{0,8}"
            value={data.dot_number || ""}
            onChange={(e) => change("dot_number", e.target.value.trim())}
          />
        </Field>
        <Field label="Niche">
          <input
            list="niches"
            maxLength={60}
            value={data.niche || ""}
            onChange={(e) => change("niche", e.target.value)}
            placeholder="Dry van, reefer, car hauler…"
          />
        </Field>
        <Field label="City">
          <input
            maxLength={80}
            value={data.city || ""}
            onChange={(e) => change("city", e.target.value)}
          />
        </Field>
        <Field label="State">
          <input
            maxLength={40}
            value={data.state || ""}
            onChange={(e) => change("state", e.target.value)}
            placeholder="TX"
          />
        </Field>
        <Field label="Assigned dispatcher">
          <select
            value={data.agent_id}
            onChange={(e) => change("agent_id", e.target.value)}
          >
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Lead timezone" hint="For example America/Chicago">
          <input
            required
            value={data.timezone}
            onChange={(e) => change("timezone", e.target.value)}
          />
        </Field>
      </div>
      <div className="consent-box">
        <h3>Permission to follow up</h3>
        <p>Record permission separately for each communication channel.</p>
        <label className="check">
          <input
            type="checkbox"
            checked={data.consent_sms}
            onChange={(e) => change("consent_sms", e.target.checked)}
          />{" "}
          Lead has agreed to SMS follow-ups
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={data.consent_voice}
            onChange={(e) => change("consent_voice", e.target.checked)}
          />{" "}
          Lead has agreed to AI voice calls
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={!!data.consent_email}
            onChange={(e) => change("consent_email", e.target.checked)}
          />{" "}
          Lead has agreed to email
        </label>
        <Field label="Consent record">
          <textarea
            maxLength={1000}
            value={data.consent_note}
            onChange={(e) => change("consent_note", e.target.value)}
            placeholder="Source, date, and what the lead agreed to"
          />
        </Field>
      </div>
      {error && <Notice error>{error}</Notice>}
      <footer className="actions">
        <button type="button" className="secondary" onClick={onClose}>
          Cancel
        </button>
        <button disabled={busy}>
          {busy ? "Saving…" : lead ? "Save changes" : "Add lead"}
        </button>
      </footer>
    </form>
  );
}
