import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowUpRight, ChevronDown, ChevronUp, PhoneCall } from "lucide-react";
import {
  carrierLine,
  type Detail,
  type Lead,
  type QueueData,
  OUTCOMES,
  QUEUE_TABS,
  ago,
  date,
  label,
} from "./api";
import { Empty, Field, Loading, Modal, Notice } from "./components";
type Api = <T>(path: string, method?: string, body?: unknown) => Promise<T>;
const CLOSING = ["not_interested", "wrong_number"];
const RETRY = ["no_answer", "voicemail"];
export function dayBounds(now = new Date()) {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  return { since: start.toISOString(), until: end.toISOString() };
}
export function LogCallForm({
  lead,
  onSubmit,
  onClose,
}: {
  lead: Lead;
  onSubmit: (body: unknown) => Promise<void>;
  onClose: () => void;
}) {
  const [outcome, setOutcome] = useState("connected");
  const [note, setNote] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onSubmit({
        outcome,
        ...(note.trim() ? { note: note.trim() } : {}),
        ...(followUp && !CLOSING.includes(outcome)
          ? { follow_up_at: new Date(followUp).toISOString() }
          : {}),
      });
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit}>
      <p className="muted">
        {lead.name} · {lead.phone}
      </p>
      <fieldset className="outcomes">
        <legend>How did the call go?</legend>
        {Object.entries(OUTCOMES).map(([value, name]) => (
          <label key={value} className={outcome === value ? "selected" : ""}>
            <input
              type="radio"
              name="outcome"
              value={value}
              checked={outcome === value}
              onChange={() => setOutcome(value)}
            />
            {name}
          </label>
        ))}
      </fieldset>
      {CLOSING.includes(outcome) ? (
        <Notice>This closes the lead and stops any automated follow-up.</Notice>
      ) : (
        <Field
          label={outcome === "call_back" ? "Call back at" : "Next follow-up"}
          hint={
            RETRY.includes(outcome)
              ? "Leave empty for 9am tomorrow in the lead's time zone."
              : outcome === "call_back"
                ? "Required."
                : "Optional."
          }
        >
          <input
            type="datetime-local"
            required={outcome === "call_back"}
            value={followUp}
            onChange={(e) => setFollowUp(e.target.value)}
          />
        </Field>
      )}
      <Field label="Note">
        <textarea
          rows={3}
          maxLength={1000}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Runs reefer in the Midwest, unhappy with current dispatcher…"
        />
      </Field>
      {error && <Notice error>{error}</Notice>}
      <footer className="actions">
        <button type="button" className="secondary" onClick={onClose}>
          Cancel
        </button>
        <button disabled={busy}>{busy ? "Saving…" : "Log call"}</button>
      </footer>
    </form>
  );
}
function overdue(value?: string | null) {
  return !!value && new Date(value) < new Date();
}
export function MyLeads({
  api,
  onOpen,
}: {
  api: Api;
  onOpen: (leadId: string) => void;
}) {
  const [tab, setTab] = useState("today");
  const [data, setData] = useState<QueueData | null>(null);
  const [expanded, setExpanded] = useState("");
  const [history, setHistory] = useState<Detail | null>(null);
  const [logging, setLogging] = useState<Lead | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    const { since, until } = dayBounds();
    return api<QueueData>(
      `/queue?tab=${tab}&since=${encodeURIComponent(since)}&until=${encodeURIComponent(until)}`,
    )
      .then((d) =>
        setData(
          Array.isArray(d?.items)
            ? d
            : {
                items: [],
                counts: {},
                summary: {
                  assigned_today: 0,
                  called_today: 0,
                  calls_today: 0,
                  untouched: 0,
                  follow_ups_due: 0,
                },
              },
        ),
      )
      .catch((e) => setError((e as Error).message));
  }, [api, tab]);
  useEffect(() => {
    load();
  }, [load]);
  async function toggle(lead: Lead) {
    if (expanded === lead.id) {
      setExpanded("");
      return;
    }
    setExpanded(lead.id);
    setHistory(null);
    try {
      setHistory(await api<Detail>(`/leads/${lead.id}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const summary = data?.summary;
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            Follow-ups first, then the ones you have not called
          </p>
          <h1>My leads</h1>
          {summary && (
            <p className="queue-summary">
              <span>
                <strong>{summary.assigned_today}</strong> assigned today
              </span>
              <span>
                <strong>{summary.called_today}</strong> called today (
                {summary.calls_today} calls)
              </span>
              <span>
                <strong>{summary.untouched}</strong> still untouched
              </span>
              <span className={summary.follow_ups_due ? "due" : ""}>
                <strong>{summary.follow_ups_due}</strong> follow-ups due
              </span>
            </p>
          )}
        </div>
      </div>
      {error && <Notice error>{error}</Notice>}
      <div className="queue-tabs" role="tablist" aria-label="Lead queue">
        {QUEUE_TABS.map(([id, name]) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? "active" : ""}
            onClick={() => {
              setTab(id);
              setExpanded("");
            }}
          >
            {name}
            {data?.counts[id] !== undefined && (
              <span className="count">{data.counts[id]}</span>
            )}
          </button>
        ))}
      </div>
      <section className="card queue">
        {!data ? (
          <Loading />
        ) : data.items.length ? (
          <ul className="queue-list">
            {data.items.map((lead) => (
              <li key={lead.id} className={expanded === lead.id ? "open" : ""}>
                <div className="queue-row">
                  <button
                    className="lead-link"
                    aria-expanded={expanded === lead.id}
                    onClick={() => toggle(lead)}
                  >
                    {expanded === lead.id ? (
                      <ChevronUp size={16} />
                    ) : (
                      <ChevronDown size={16} />
                    )}
                    <span>
                      <strong>{lead.company || lead.name}</strong>
                      <small>{carrierLine(lead)}</small>
                    </span>
                  </button>
                  <span>
                    <span className={`badge ${lead.status}`}>
                      {label(lead.stage || "new")}
                    </span>
                    <small>
                      {lead.last_outcome
                        ? OUTCOMES[lead.last_outcome] ||
                          label(lead.last_outcome)
                        : "Not called yet"}
                    </small>
                  </span>
                  <span className="phone">{lead.phone}</span>
                  <span
                    className={
                      overdue(lead.follow_up_at)
                        ? "follow-up overdue"
                        : "follow-up"
                    }
                  >
                    {lead.follow_up_at ? date(lead.follow_up_at) : "—"}
                  </span>
                  <small className="muted">{ago(lead.last_activity_at)}</small>
                  <span className="actions">
                    <button
                      disabled={lead.status === "opted_out"}
                      onClick={() => setLogging(lead)}
                    >
                      <PhoneCall size={15} /> Log call
                    </button>
                    <button
                      className="icon"
                      aria-label={`Open ${lead.name}`}
                      onClick={() => onOpen(lead.id)}
                    >
                      <ArrowUpRight size={17} />
                    </button>
                  </span>
                </div>
                {expanded === lead.id && (
                  <div className="queue-history">
                    {!history ? (
                      <Loading />
                    ) : history.activities.length ? (
                      <ul>
                        {history.activities.map((a) => (
                          <li key={a.id}>
                            <span>
                              <strong>
                                {label(
                                  a.channel === "system" ? "update" : a.channel,
                                )}
                              </strong>{" "}
                              {a.text}
                            </span>
                            <small>{date(a.created_at)}</small>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="muted">No activity yet.</p>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <Empty
            title={tab === "today" ? "You're all caught up" : "Nothing here"}
          >
            Follow-ups that are due and leads you have not called yet show up
            under Today.
          </Empty>
        )}
      </section>
      {logging && (
        <Modal title="Log a call" onClose={() => setLogging(null)}>
          <LogCallForm
            lead={logging}
            onClose={() => setLogging(null)}
            onSubmit={async (body) => {
              await api(`/leads/${logging.id}/log-call`, "POST", body);
              setExpanded("");
              await load();
            }}
          />
        </Modal>
      )}
    </>
  );
}
