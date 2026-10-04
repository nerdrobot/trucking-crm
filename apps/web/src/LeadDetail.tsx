import { useState } from "react";
import {
  ArrowLeft,
  CalendarClock,
  MessageSquare,
  Phone,
  Pause,
  Play,
  Check,
  Pencil,
  PhoneForwarded,
  CalendarPlus,
  Mail,
} from "lucide-react";
import {
  type Detail,
  type Sequence,
  type Agent,
  type Session,
  STAGES,
  carrierLine,
  date,
  label,
} from "./api";
import { Empty, Field, Modal, Notice } from "./components";
import { TaskRow } from "./Workboard";
import { LogCallForm } from "./Queue";
export function LeadDetail({
  detail,
  sequences,
  agents,
  session,
  onBack,
  onEdit,
  action,
  send,
}: {
  detail: Detail;
  sequences: Sequence[];
  agents: Agent[];
  session: Session;
  onBack: () => void;
  onEdit: () => void;
  action: (name: string, body?: unknown) => Promise<void>;
  send: (path: string, method: string, body?: unknown) => Promise<void>;
}) {
  const [modal, setModal] = useState("");
  const [text, setText] = useState("");
  const [sequenceId, setSequenceId] = useState(sequences[0]?.id || "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [due, setDue] = useState("");
  const [subject, setSubject] = useState("");
  const { lead, activities, jobs } = detail;
  const tasks = detail.tasks ?? [];
  const locked = ["completed", "opted_out"].includes(lead.status);
  async function run(name: string, body?: unknown) {
    setBusy(true);
    setError("");
    try {
      await action(name, body);
      setModal("");
      setText("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function update(path: string, method: string, body?: unknown) {
    setBusy(true);
    setError("");
    try {
      await send(path, method, body);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function open(name: string) {
    setError("");
    setText("");
    setDue("");
    setSubject("");
    setModal(name);
  }
  return (
    <>
      <button className="text-button back" onClick={onBack}>
        <ArrowLeft size={16} /> All leads
      </button>
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            {carrierLine(lead)} ·{" "}
            {agents.find((a) => a.id === lead.agent_id)?.name ||
              "Assigned dispatcher"}
          </p>
          <h1>{lead.company || lead.name}</h1>
          <p>
            {lead.company && `${lead.name} · `}
            {lead.dot_number && `DOT ${lead.dot_number} · `}
            {!!lead.fleet_size &&
              `${lead.fleet_size} truck${lead.fleet_size === 1 ? "" : "s"} · `}
            {lead.phone}
            {lead.email && ` · ${lead.email}`}
          </p>
        </div>
        <div className="actions">
          <button className="secondary" onClick={onEdit}>
            <Pencil size={15} /> Edit lead
          </button>
          <button
            disabled={locked || !sequences.length}
            onClick={() => open("enroll")}
          >
            <CalendarClock size={16} /> Schedule follow-up
          </button>
        </div>
      </div>
      {!sequences.length && (
        <Notice>
          Create your first follow-up sequence in Sequences, then return here to
          schedule outreach.
        </Notice>
      )}
      {error && !modal && <Notice error>{error}</Notice>}
      <div className="detail-layout">
        <section>
          <article className="card lead-summary">
            <div className="row">
              <span className={`badge ${lead.status}`}>
                {label(lead.status)}
              </span>
              <select
                aria-label="Pipeline stage"
                value={lead.stage || "new"}
                disabled={busy}
                onChange={(e) =>
                  update(`/leads/${lead.id}`, "PATCH", {
                    stage: e.target.value,
                  })
                }
              >
                {STAGES.map((s) => (
                  <option key={s} value={s}>
                    {label(s)}
                  </option>
                ))}
              </select>
              <small>{lead.timezone}</small>
            </div>
            <div className="next-action">
              <CalendarClock size={22} />
              <div>
                <span>Next follow-up</span>
                <strong>
                  {date(
                    lead.next_followup_at ||
                      jobs.find((j) => j.status === "pending")?.due_at,
                  )}
                </strong>
              </div>
            </div>
            <div className="actions wrap">
              <button
                className="secondary"
                disabled={
                  busy || locked || !lead.consent_sms || !session.sms_ready
                }
                onClick={() => open("message")}
              >
                <MessageSquare size={16} /> Send SMS
              </button>
              <button
                className="secondary"
                disabled={
                  busy ||
                  locked ||
                  !lead.email ||
                  !lead.consent_email ||
                  !session.email_ready
                }
                onClick={() => open("email")}
              >
                <Mail size={16} /> Send email
              </button>
              <button
                className="secondary"
                disabled={
                  busy || locked || !lead.consent_voice || !session.voice_ready
                }
                onClick={() => open("call")}
              >
                <Phone size={16} /> AI call
              </button>
              <button
                className="secondary"
                disabled={busy || lead.status === "opted_out"}
                onClick={() => setModal("log-call")}
              >
                <PhoneForwarded size={16} /> Log call
              </button>
              <button
                className="secondary"
                disabled={
                  busy || lead.status === "opted_out" || !session.bridge_ready
                }
                title={
                  session.bridge_ready
                    ? undefined
                    : "Ask an administrator to add your phone number"
                }
                onClick={() => open("connect")}
              >
                <PhoneForwarded size={16} /> Call me first
              </button>
              {lead.status === "paused" ? (
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => run("resume")}
                >
                  <Play size={16} /> Resume
                </button>
              ) : (
                <button
                  className="secondary"
                  disabled={busy || locked}
                  onClick={() => run("pause")}
                >
                  <Pause size={16} /> Pause
                </button>
              )}
              <button
                className="secondary"
                disabled={busy || locked}
                onClick={() => open("complete")}
              >
                <Check size={16} /> Complete
              </button>
            </div>
            {(!lead.consent_sms || !lead.consent_voice) && (
              <p className="muted">
                Channels without recorded permission are unavailable.
              </p>
            )}
          </article>
          <article className="card">
            <div className="row">
              <h2>Conversation & activity</h2>
              {session.mode === "demo" && (
                <button
                  className="text-button"
                  disabled={locked}
                  onClick={() => open("demo-reply")}
                >
                  Simulate reply
                </button>
              )}
            </div>
            {activities.length ? (
              <div className="timeline">
                {[...activities]
                  .sort((a, b) => b.created_at.localeCompare(a.created_at))
                  .map((a) => (
                    <div className="activity" key={a.id}>
                      <span className={`activity-icon ${a.direction}`}>
                        {a.channel === "email" ? (
                          <Mail size={16} />
                        ) : a.channel === "bridge" || a.channel === "call" ? (
                          <PhoneForwarded size={16} />
                        ) : a.channel === "voice" ? (
                          <Phone size={16} />
                        ) : a.channel === "sms" ? (
                          <MessageSquare size={16} />
                        ) : (
                          <Check size={16} />
                        )}
                      </span>
                      <div>
                        <div className="row">
                          <strong>
                            {a.channel === "system"
                              ? "Lead update"
                              : a.channel === "bridge"
                                ? "Agent call"
                                : a.channel === "call"
                                  ? "Logged call"
                                  : a.channel === "email"
                                    ? a.direction === "inbound"
                                      ? "Email update"
                                      : "Outgoing email"
                                    : `${a.direction === "inbound" ? "Received" : "Outgoing"} ${a.channel === "voice" ? "call" : "message"}`}
                          </strong>
                          <small>{date(a.created_at)}</small>
                        </div>
                        <p>{a.text}</p>
                        <span className="muted">{label(a.status)}</span>
                      </div>
                    </div>
                  ))}
              </div>
            ) : (
              <Empty title="A fresh start">
                Messages, calls, and lead updates will appear here.
              </Empty>
            )}
          </article>
        </section>
        <aside>
          <article className="card">
            <div className="row">
              <h2>Tasks</h2>
              <button
                className="text-button"
                disabled={lead.status === "opted_out"}
                onClick={() => open("task")}
              >
                <CalendarPlus size={15} /> Add task
              </button>
            </div>
            {tasks.length ? (
              <ul className="task-list">
                {tasks.map((task) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    onToggle={() =>
                      update(`/tasks/${task.id}`, "PATCH", {
                        status: task.status === "open" ? "done" : "open",
                      })
                    }
                  />
                ))}
              </ul>
            ) : (
              <p className="muted">
                Replies and AI call outcomes that need you appear here.
              </p>
            )}
          </article>
          <article className="card">
            <h2>Scheduled outreach</h2>
            {jobs.length ? (
              <ul className="job-list">
                {[...jobs]
                  .sort((a, b) => a.due_at.localeCompare(b.due_at))
                  .map((j) => (
                    <li key={j.id}>
                      <div className="row">
                        <strong>
                          {j.channel === "sms"
                            ? "SMS"
                            : j.channel === "bridge"
                              ? "Agent call"
                              : j.channel === "email"
                                ? "Email"
                                : "AI voice"}
                        </strong>
                        <span className="badge">{label(j.status)}</span>
                      </div>
                      <small>{date(j.due_at)}</small>
                      <p>{j.message}</p>
                      {j.error && <p className="error-text">{j.error}</p>}
                    </li>
                  ))}
              </ul>
            ) : (
              <p className="muted">
                Enroll this lead in a sequence to plan their next conversation.
              </p>
            )}
          </article>
          <article className="card">
            <h2>Contact permissions</h2>
            <p>
              SMS:{" "}
              <strong>{lead.consent_sms ? "Recorded" : "Not recorded"}</strong>
            </p>
            <p>
              Email:{" "}
              <strong>
                {lead.consent_email ? "Recorded" : "Not recorded"}
              </strong>
            </p>
            <p>
              AI voice:{" "}
              <strong>
                {lead.consent_voice ? "Recorded" : "Not recorded"}
              </strong>
            </p>
            <p className="muted">
              {lead.consent_note || "No consent record added."}
            </p>
          </article>
        </aside>
      </div>
      {modal === "log-call" && (
        <Modal title="Log a call" onClose={() => setModal("")}>
          <LogCallForm
            lead={lead}
            onClose={() => setModal("")}
            onSubmit={(body) =>
              send(`/leads/${lead.id}/log-call`, "POST", body)
            }
          />
        </Modal>
      )}
      {modal && modal !== "log-call" && (
        <Modal
          title={
            modal === "enroll"
              ? "Schedule a follow-up"
              : modal === "message"
                ? "Send a text message"
                : modal === "call"
                  ? "Start an AI call"
                  : modal === "connect"
                    ? "Call me first"
                    : modal === "task"
                      ? "Add a task"
                      : modal === "email"
                        ? "Send an email"
                        : modal === "complete"
                          ? "Complete this lead?"
                          : "Simulate a lead reply"
          }
          onClose={() => setModal("")}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              run(
                modal === "task" ? "tasks" : modal,
                modal === "enroll"
                  ? { sequence_id: sequenceId }
                  : ["message", "demo-reply"].includes(modal)
                    ? { text }
                    : modal === "email"
                      ? { subject, text }
                      : modal === "task"
                        ? {
                            title: text,
                            ...(due
                              ? { due_at: new Date(due).toISOString() }
                              : {}),
                          }
                        : {},
              );
            }}
          >
            {modal === "enroll" ? (
              <>
                <Field label="Sequence">
                  <select
                    required
                    value={sequenceId}
                    onChange={(e) => setSequenceId(e.target.value)}
                  >
                    <option value="" disabled>
                      Select a sequence
                    </option>
                    {sequences.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <p className="muted">
                  Scheduling replaces pending follow-ups for this lead. Sending
                  respects permission, contact hours, and daily limits.
                </p>
              </>
            ) : modal === "call" ? (
              <p>
                {session.mode === "demo"
                  ? "This creates a simulated call. No real number will be contacted."
                  : `The AI assistant will call ${lead.name} at ${lead.phone}. This uses your calling budget.`}
              </p>
            ) : modal === "email" ? (
              <>
                <p className="muted">To {lead.email}</p>
                <Field label="Subject">
                  <input
                    autoFocus
                    required
                    maxLength={200}
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                  />
                </Field>
                <Field label="Email message">
                  <textarea
                    required
                    rows={8}
                    maxLength={5000}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                  />
                </Field>
                <p className="muted">
                  Leads can unsubscribe from email; that stops email only, not
                  calls or texts.
                </p>
              </>
            ) : modal === "connect" ? (
              <p>
                {session.mode === "demo"
                  ? "This simulates ringing your phone and connecting you to the lead. No real call is placed."
                  : `We'll call your phone first. When you answer, ${lead.name} at ${lead.phone} is dialed and connected to you. Automated follow-up pauses while you take over.`}
              </p>
            ) : modal === "task" ? (
              <>
                <Field label="Task">
                  <input
                    autoFocus
                    required
                    maxLength={300}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder="Send dispatch agreement and rate sheet"
                  />
                </Field>
                <Field label="Due" hint="Leave empty to make it due now.">
                  <input
                    type="datetime-local"
                    value={due}
                    onChange={(e) => setDue(e.target.value)}
                  />
                </Field>
              </>
            ) : modal === "complete" ? (
              <p>
                Close this lead and cancel their remaining automated follow-ups.
              </p>
            ) : (
              <Field label={modal === "demo-reply" ? "Lead reply" : "Message"}>
                <textarea
                  autoFocus
                  required
                  maxLength={1200}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={
                    modal === "demo-reply"
                      ? "I would like to book a viewing…"
                      : "Write your message…"
                  }
                />
              </Field>
            )}
            {modal === "demo-reply" && (
              <p className="muted">
                A reply stops scheduled outreach. Use STOP to test an opt-out.
              </p>
            )}
            {session.mode === "demo" && ["message", "call"].includes(modal) && (
              <Notice>Demo mode · no real messages or calls.</Notice>
            )}
            {error && <Notice error>{error}</Notice>}
            <footer className="actions">
              <button
                type="button"
                className="secondary"
                onClick={() => setModal("")}
              >
                Cancel
              </button>
              <button disabled={busy}>
                {busy
                  ? "Working…"
                  : modal === "enroll"
                    ? "Schedule follow-up"
                    : modal === "message"
                      ? "Send message"
                      : modal === "call"
                        ? "Start call"
                        : modal === "connect"
                          ? "Call my phone"
                          : modal === "email"
                            ? "Send email"
                            : modal === "task"
                              ? "Add task"
                              : modal === "complete"
                                ? "Complete lead"
                                : "Record demo reply"}
              </button>
            </footer>
          </form>
        </Modal>
      )}
    </>
  );
}
