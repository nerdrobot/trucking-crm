import { useCallback, useEffect, useState } from "react";
import { Circle, CircleCheck } from "lucide-react";
import { type Task, date, label, overdue } from "./api";
import { Empty, Loading, Notice } from "./components";
type Api = <T>(path: string, method?: string, body?: unknown) => Promise<T>;
const SOURCES: Record<string, string> = {
  reply: "Text reply",
  call_outcome: "AI call",
  manual: "Added by agent",
};
export function Tasks({
  api,
  onOpen,
}: {
  api: Api;
  onOpen: (leadId: string) => void;
}) {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [show, setShow] = useState("open");
  const [error, setError] = useState("");
  const load = useCallback(
    () =>
      api<Task[]>(`/tasks?status=${show}`)
        .then((t) => setTasks(Array.isArray(t) ? t : []))
        .catch((e) => setError((e as Error).message)),
    [api, show],
  );
  useEffect(() => {
    load();
  }, [load]);
  async function toggle(task: Task) {
    setError("");
    try {
      await api(`/tasks/${task.id}`, "PATCH", {
        status: task.status === "open" ? "done" : "open",
      });
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Never miss a next step</p>
          <h1>Tasks</h1>
          <p>Callbacks, replies, and follow-ups that need a personal touch.</p>
        </div>
        <select
          aria-label="Filter tasks"
          value={show}
          onChange={(e) => setShow(e.target.value)}
        >
          <option value="open">Open</option>
          <option value="done">Done</option>
          <option value="">All</option>
        </select>
      </div>
      {error && <Notice error>{error}</Notice>}
      <section className="card">
        {!tasks ? (
          <Loading />
        ) : tasks.length ? (
          <ul className="task-list">
            {tasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                onToggle={() => toggle(task)}
                onOpen={() => onOpen(task.lead_id)}
              />
            ))}
          </ul>
        ) : (
          <Empty title={show === "open" ? "All caught up" : "No tasks"}>
            Replies and AI call outcomes that need you will appear here.
          </Empty>
        )}
      </section>
    </>
  );
}
export function TaskRow({
  task,
  onToggle,
  onOpen,
}: {
  task: Task;
  onToggle?: () => void;
  onOpen?: () => void;
}) {
  const done = task.status !== "open";
  return (
    <li className={`task-row ${task.status}`}>
      <button
        className="icon"
        disabled={!onToggle || task.status === "cancelled"}
        aria-label={`${done ? "Reopen" : "Complete"} task: ${task.title}`}
        onClick={onToggle}
      >
        {done ? <CircleCheck size={19} /> : <Circle size={19} />}
      </button>
      <div>
        <strong>{task.title}</strong>
        <small>
          {task.lead_name && onOpen ? (
            <button className="text-button" onClick={onOpen}>
              {task.lead_name}
            </button>
          ) : null}
          {SOURCES[task.source] || label(task.source)} · Due {date(task.due_at)}
        </small>
      </div>
      {overdue(task) ? (
        <span className="badge overdue">Overdue</span>
      ) : (
        task.status !== "open" && (
          <span className="badge">{label(task.status)}</span>
        )
      )}
    </li>
  );
}
