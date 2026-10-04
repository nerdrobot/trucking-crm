import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  Truck,
  LayoutDashboard,
  Users,
  Workflow,
  Settings as SettingsIcon,
  LogOut,
  Plus,
  Upload,
  Search,
  ArrowUpRight,
  RefreshCw,
  MessageSquare,
  PhoneCall,
  ListTodo,
  FileText,
} from "lucide-react";
import {
  request,
  type Session,
  type Agent,
  carrierLine,
  type Lead,
  type Detail,
  type Sequence,
  type Template,
  type Settings as SettingsType,
  initialLead,
  date,
  label,
} from "./api";
import { Empty, Field, Loading, Modal, Notice } from "./components";
import { LeadForm } from "./LeadForm";
import { LeadDetail } from "./LeadDetail";
import { Sequences } from "./Sequences";
import { Settings } from "./Settings";
import { Tasks } from "./Workboard";
import { MyLeads } from "./Queue";
import { CallerNumbers } from "./CallerNumbers";
import { Channels } from "./Channels";
import { Templates, type TemplateDraft } from "./Templates";
type Stats = {
  total_leads: number;
  active_followups: number;
  due_today: number;
  needs_attention: number;
  sent_today: number;
  paused: number;
  open_tasks?: number;
  overdue_tasks?: number;
};
export default function App() {
  const requestVersion = useRef(0);
  const [key, setKey] = useState("");
  const [session, setSession] = useState<Session | null>(null);
  const [loginKey, setLoginKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState("overview");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<Stats | null>(null);
  const [sequences, setSequences] = useState<Sequence[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [settings, setSettings] = useState<SettingsType | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [modal, setModal] = useState("");
  const [csv, setCsv] = useState("");
  const [importResult, setImportResult] = useState<{
    created: number;
    errors: { row: number; error: string }[];
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [modalError, setModalError] = useState("");
  const api = useCallback(
    <T,>(path: string, method = "GET", body?: unknown) =>
      request<T>(path, key, method, body),
    [key],
  );
  const refresh = useCallback(async () => {
    const version = ++requestVersion.current;
    const [a, l, d, s, leadDetail, prefs, t] = await Promise.all([
      api<Agent[]>("/agents"),
      api<{ items: Lead[]; total: number }>(
        `/leads?search=${encodeURIComponent(search)}&status=${status}&offset=${offset}&limit=25`,
      ),
      api<Stats>("/dashboard"),
      api<Sequence[]>("/sequences"),
      selectedId ? api<Detail>(`/leads/${selectedId}`) : Promise.resolve(null),
      session?.user.role === "admin"
        ? api<SettingsType>("/settings")
        : Promise.resolve(null),
      api<Template[]>("/templates"),
    ]);
    if (version !== requestVersion.current) return;
    setAgents(a);
    setLeads(l.items);
    setTotal(l.total);
    setStats(d);
    setSequences(s);
    setDetail(leadDetail);
    setSettings(prefs);
    setTemplates(Array.isArray(t) ? t : []);
  }, [api, search, status, offset, selectedId, session?.user.role]);
  useEffect(() => {
    if (!session) return;
    let active = true;
    setLoading(true);
    setError("");
    const timer = setTimeout(
      () =>
        refresh()
          .catch((e) => {
            if (active) setError(e.message);
          })
          .finally(() => {
            if (active) setLoading(false);
          }),
      150,
    );
    return () => {
      active = false;
      requestVersion.current++;
      clearTimeout(timer);
    };
  }, [refresh, session]);
  function signOut() {
    requestVersion.current++;
    setKey("");
    setSession(null);
    setLoading(false);
    setBusy(false);
    setLeads([]);
    setAgents([]);
    setSettings(null);
    setSequences([]);
    setDetail(null);
    setStats(null);
    setSelectedId("");
    setError("");
    setModal("");
    setSearch("");
    setStatus("");
    setOffset(0);
    setPage("overview");
  }
  async function login(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const me = await request<Session>("/me", loginKey.trim());
      setKey(loginKey.trim());
      setLoginKey("");
      setPage(me.user.role === "admin" ? "overview" : "queue");
      setSession(me);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }
  function navigate(next: string) {
    setPage(next);
    setSelectedId("");
    setDetail(null);
    setError("");
  }
  function selectLead(id: string) {
    setSelectedId(id);
    setDetail(null);
    setPage("leads");
  }
  async function saveLead(data: typeof initialLead) {
    const { phone: _phone, ...editableData } = data;
    await api(
      modal === "edit" ? `/leads/${selectedId}` : "/leads",
      modal === "edit" ? "PATCH" : "POST",
      modal === "edit" ? editableData : data,
    );
    await refresh();
  }
  function openModal(value: string) {
    setModalError("");
    setImportResult(null);
    setCsv("");
    setModal(value);
  }
  if (!session)
    return (
      <main className="login-screen">
        <section className="login-story">
          <div className="brand">
            <Truck /> haulbase<span>DISPATCH SALES</span>
          </div>
          <div>
            <p className="eyebrow">
              Every carrier called. Every follow-up on time.
            </p>
            <h1>
              Keep your pipeline
              <br />
              rolling.
            </h1>
            <p>
              Carrier leads, call outcomes, and follow-ups.
              <br />
              Together in one dispatch sales workspace.
            </p>
          </div>
          <small>TRUCKING CRM · PILOT</small>
        </section>
        <section className="login-panel">
          <form onSubmit={login}>
            <span className="brand-mark">
              <Truck size={26} />
            </span>
            <h2>Welcome to your workspace</h2>
            <p className="muted">
              Sign in with the personal access key provided by your workspace
              administrator.
            </p>
            <Field label="Personal access key">
              <input
                type="password"
                autoComplete="off"
                required
                value={loginKey}
                onChange={(e) => setLoginKey(e.target.value)}
                placeholder="Enter your access key"
              />
            </Field>
            {error && <Notice error>{error}</Notice>}
            <button disabled={loading} className="full">
              {loading ? "Signing in…" : "Open workspace"}
              <ArrowUpRight size={18} />
            </button>
            <small className="login-note">
              Your key is kept only for this open session. Refreshing the page
              signs you out.
            </small>
          </form>
        </section>
      </main>
    );
  const admin = session.user.role === "admin";
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Truck size={27} /> haulbase<span>DISPATCH SALES</span>
        </div>
        <nav aria-label="Main navigation">
          {[
            { id: "queue", name: "My leads", icon: PhoneCall },
            { id: "overview", name: "Overview", icon: LayoutDashboard },
            { id: "leads", name: "Leads", icon: Users },
            { id: "tasks", name: "Tasks", icon: ListTodo },
            { id: "sequences", name: "Sequences", icon: Workflow },
            { id: "templates", name: "Templates", icon: FileText },
            ...(admin
              ? [{ id: "settings", name: "Automation", icon: SettingsIcon }]
              : []),
          ].map((item) => (
            <button
              key={item.id}
              className={page === item.id ? "active" : ""}
              onClick={() => navigate(item.id)}
            >
              <item.icon size={19} />
              {item.name}
              {item.id === "leads" && stats && <span>{stats.total_leads}</span>}
              {item.id === "tasks" && stats?.open_tasks ? (
                <span>{stats.open_tasks}</span>
              ) : null}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="pilot-note">
            <span className={`mode-dot ${session.mode}`} />
            <strong>
              {session.mode === "demo" ? "Demo workspace" : "Live workspace"}
            </strong>
            <p>
              {session.mode === "demo"
                ? "Explore safely. No real messages or calls."
                : "Keep every connection moving."}
            </p>
          </div>
          <div className="account">
            <span className="avatar">
              {session.user.name?.slice(0, 1) || "A"}
            </span>
            <div>
              <strong>{session.user.name}</strong>
              <small>{admin ? "Administrator" : "Agent"}</small>
            </div>
            <button className="icon" aria-label="Sign out" onClick={signOut}>
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <span>YOUR FOLLOW-UP WORKSPACE</span>
          <div className="actions">
            <span className={`badge ${session.mode}`}>
              {session.mode === "demo"
                ? "DEMO · NO REAL SENDS"
                : "LIVE OUTREACH"}
            </span>
            <button
              className="icon"
              aria-label="Refresh workspace"
              disabled={loading}
              onClick={() => {
                setLoading(true);
                refresh()
                  .catch((e) => setError(e.message))
                  .finally(() => setLoading(false));
              }}
            >
              <RefreshCw size={17} />
            </button>
            <button
              className="icon mobile-signout"
              aria-label="Sign out of workspace"
              onClick={signOut}
            >
              <LogOut size={17} />
            </button>
          </div>
        </header>
        <main className="content">
          {error && <Notice error>{error}</Notice>}
          {loading && !stats ? (
            <Loading />
          ) : selectedId ? (
            detail ? (
              <LeadDetail
                detail={detail}
                sequences={sequences}
                agents={agents}
                session={session}
                onBack={() => navigate("leads")}
                onEdit={() => openModal("edit")}
                action={async (name, body = {}) => {
                  await api(`/leads/${selectedId}/${name}`, "POST", body);
                  await refresh();
                }}
                send={async (path, method, body) => {
                  await api(path, method, body);
                  await refresh();
                }}
              />
            ) : (
              <Loading />
            )
          ) : page === "queue" ? (
            <MyLeads api={api} onOpen={selectLead} />
          ) : page === "tasks" ? (
            <Tasks api={api} onOpen={selectLead} />
          ) : page === "templates" ? (
            <Templates
              templates={templates}
              admin={admin}
              onSave={async ({ id, ...draft }: TemplateDraft) => {
                await api(
                  id ? `/templates/${id}` : "/templates",
                  id ? "PUT" : "POST",
                  draft,
                );
                await refresh();
              }}
              onDelete={async (id) => {
                await api(`/templates/${id}`, "DELETE");
                await refresh();
              }}
            />
          ) : page === "sequences" ? (
            <Sequences
              sequences={sequences}
              templates={templates}
              admin={admin}
              onSave={async (data) => {
                await api("/sequences", "POST", data);
                await refresh();
              }}
            />
          ) : page === "settings" ? (
            settings && (
              <>
                <Settings
                  settings={settings}
                  session={session}
                  onSave={async (data) => {
                    const { mode: _, ...changes } = data;
                    await api("/settings", "PATCH", changes);
                    await refresh();
                  }}
                  onRun={async () => {
                    const result = await api("/automation/run", "POST", {});
                    await refresh();
                    return result;
                  }}
                />
                <Channels
                  api={api}
                  onSaved={() =>
                    request<Session>("/me", key).then(
                      setSession,
                      () => undefined,
                    )
                  }
                />
                <CallerNumbers api={api} demo={session.mode === "demo"} />
              </>
            )
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">
                    {page === "overview"
                      ? "Every relationship starts with a conversation"
                      : "Your next conversation starts here"}
                  </p>
                  <h1>
                    {page === "overview"
                      ? `Good to see you, ${session.user.name?.split(" ")[0] || "there"}.`
                      : "Your leads"}
                  </h1>
                  <p>
                    {page === "overview"
                      ? "A clear view of your pipeline. A thoughtful next step for every lead."
                      : "Keep every contact, conversation, and follow-up in view."}
                  </p>
                </div>
                <div className="actions">
                  <button
                    className="secondary"
                    onClick={() => openModal("import")}
                  >
                    <Upload size={16} /> Import CSV
                  </button>
                  <button onClick={() => openModal("new")}>
                    <Plus size={17} /> Add lead
                  </button>
                </div>
              </div>
              {page === "overview" && stats && (
                <>
                  <div className="stats-grid">
                    {[
                      {
                        name: "Total leads",
                        value: stats.total_leads,
                        sub: "Relationships in your workspace",
                      },
                      {
                        name: "Active follow-ups",
                        value: stats.active_followups,
                        sub: "Keeping the conversation going",
                      },
                      {
                        name: "Due by today",
                        value: stats.due_today,
                        sub: "Scheduled outreach steps",
                      },
                      {
                        name: "Needs attention",
                        value: stats.needs_attention,
                        sub: "Ready for a personal touch",
                      },
                    ].map((s, i) => (
                      <article className={`stat-card stat-${i}`} key={s.name}>
                        <span>{s.name}</span>
                        <strong>{s.value}</strong>
                        <small>{s.sub}</small>
                      </article>
                    ))}
                  </div>
                  <div className="overview-strip">
                    <div>
                      <MessageSquare size={20} />
                      <span>
                        <strong>{stats.sent_today}</strong> outreach attempts
                        today
                      </span>
                    </div>
                    <div>
                      <ListTodo size={20} />
                      <span>
                        <strong>{stats.open_tasks ?? 0}</strong> open tasks
                        {stats.overdue_tasks
                          ? `, ${stats.overdue_tasks} overdue`
                          : ""}
                      </span>
                    </div>
                    <div>
                      <span className="mode-dot" />
                      <span>
                        <strong>{stats.paused}</strong> leads paused
                      </span>
                    </div>
                  </div>
                </>
              )}
              <section className="card leads-card">
                <div className="table-heading">
                  <h2>
                    {page === "overview" ? "Lead workspace" : "All leads"}{" "}
                    <span className="count">{total}</span>
                  </h2>
                  <div className="filters">
                    <label className="search">
                      <Search size={17} />
                      <input
                        aria-label="Search leads"
                        placeholder="Company, contact, city, MC or DOT…"
                        value={search}
                        onChange={(e) => {
                          setSearch(e.target.value);
                          setOffset(0);
                        }}
                      />
                    </label>
                    <select
                      aria-label="Filter lead status"
                      value={status}
                      onChange={(e) => {
                        setStatus(e.target.value);
                        setOffset(0);
                      }}
                    >
                      <option value="">All statuses</option>
                      {[
                        "new",
                        "active",
                        "replied",
                        "paused",
                        "completed",
                        "opted_out",
                      ].map((s) => (
                        <option key={s} value={s}>
                          {label(s)}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                {leads.length ? (
                  <>
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Carrier</th>
                            <th>Details</th>
                            <th>Status</th>
                            <th>Dispatcher</th>
                            <th>Next follow-up</th>
                            <th>
                              <span className="sr-only">Open</span>
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {leads.map((lead) => (
                            <tr key={lead.id}>
                              <td>
                                <button
                                  className="lead-link"
                                  onClick={() => selectLead(lead.id)}
                                >
                                  <span className="avatar">
                                    {(lead.company || lead.name).slice(0, 1)}
                                  </span>
                                  <span>
                                    <strong>{lead.company || lead.name}</strong>
                                    <small>
                                      {lead.company && `${lead.name} · `}
                                      {lead.phone}
                                    </small>
                                  </span>
                                </button>
                              </td>
                              <td className="muted">{carrierLine(lead)}</td>
                              <td>
                                <span className={`badge ${lead.status}`}>
                                  {label(lead.status)}
                                </span>
                              </td>
                              <td>
                                {agents.find((a) => a.id === lead.agent_id)
                                  ?.name || "—"}
                              </td>
                              <td className="muted">
                                {date(
                                  lead.follow_up_at || lead.next_followup_at,
                                )}
                              </td>
                              <td>
                                <button
                                  className="icon"
                                  aria-label={`Open ${lead.name}`}
                                  onClick={() => selectLead(lead.id)}
                                >
                                  <ArrowUpRight size={18} />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <footer className="pagination">
                      <span>
                        {offset + 1}–{Math.min(offset + 25, total)} of {total}{" "}
                        leads
                      </span>
                      <div className="actions">
                        <button
                          className="secondary"
                          disabled={!offset}
                          onClick={() => setOffset(Math.max(0, offset - 25))}
                        >
                          Previous
                        </button>
                        <button
                          className="secondary"
                          disabled={offset + 25 >= total}
                          onClick={() => setOffset(offset + 25)}
                        >
                          Next
                        </button>
                      </div>
                    </footer>
                  </>
                ) : (
                  <Empty
                    title={
                      search || status
                        ? "No matching leads"
                        : "Make your first connection"
                    }
                  >
                    {search || status
                      ? "Try another search or status filter."
                      : "Add a lead or import your contacts to start following up."}
                  </Empty>
                )}
              </section>
            </>
          )}
        </main>
        <footer className="app-footer">
          Haulbase pilot <span>Built for dispatch sales teams.</span>
        </footer>
      </div>
      {["new", "edit"].includes(modal) && (
        <Modal
          title={modal === "edit" ? "Edit lead" : "Add a new lead"}
          onClose={() => setModal("")}
        >
          <LeadForm
            lead={modal === "edit" ? detail?.lead : undefined}
            agents={
              admin ? agents : agents.filter((a) => a.id === session.user.id)
            }
            onSave={saveLead}
            onClose={() => setModal("")}
          />
        </Modal>
      )}
      {modal === "import" && (
        <Modal title="Import your leads" onClose={() => setModal("")}>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setModalError("");
              try {
                setImportResult(await api("/leads/import", "POST", { csv }));
                await refresh();
              } catch (err) {
                setModalError((err as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <p className="muted">
              Import up to 200 leads. Required columns: name, phone. Optional:
              email, company, mc_number, dot_number, kind (owner_operator or
              fleet), fleet_size, niche, city, state, timezone, agent_id,
              consent_sms, consent_voice, consent_email, consent_note. Use true
              or false for permissions.
            </p>
            <Field label="CSV file">
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (f) {
                    if (f.size > 200000) {
                      setModalError("Choose a CSV smaller than 200 KB.");
                      return;
                    }
                    setCsv(await f.text());
                  }
                }}
              />
            </Field>
            <Field label="CSV contents">
              <textarea
                required
                rows={8}
                value={csv}
                onChange={(e) => setCsv(e.target.value)}
                placeholder={
                  "name,phone,email\nAlex Morgan,+13125550123,alex@example.com"
                }
              />
            </Field>
            {modalError && <Notice error>{modalError}</Notice>}
            {importResult && (
              <Notice>
                <strong>{importResult.created} leads imported.</strong>
                {importResult.errors.length > 0 && (
                  <ul>
                    {importResult.errors.map((e, i) => (
                      <li key={i}>
                        Row {e.row}: {e.error}
                      </li>
                    ))}
                  </ul>
                )}
              </Notice>
            )}
            <footer className="actions">
              <button
                type="button"
                className="secondary"
                onClick={() => setModal("")}
              >
                Close
              </button>
              <button disabled={busy || !csv.trim()}>
                {busy ? "Importing…" : "Import leads"}
              </button>
            </footer>
          </form>
        </Modal>
      )}
    </div>
  );
}
