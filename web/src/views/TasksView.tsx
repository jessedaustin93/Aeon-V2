import { useEffect, useMemo, useState } from "react";
import { api, type Approval, type TaskRun } from "../api";

export function TasksView() {
  const [tasks, setTasks] = useState<TaskRun[]>([]);
  const [activeId, setActiveId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [role, setRole] = useState("chat");
  const [selfScaffold, setSelfScaffold] = useState(true);
  const [busy, setBusy] = useState(false);
  const [approvals, setApprovals] = useState<Approval[]>([]);

  const active = useMemo(
    () => tasks.find((t) => t.id === activeId) || tasks[0] || null,
    [tasks, activeId],
  );

  function load() {
    api.tasks().then((r) => {
      setTasks(r.tasks);
      if (!activeId && r.tasks[0]) setActiveId(r.tasks[0].id);
    }).catch(() => {});
    api.approvals().then((r) => setApprovals(r.pending)).catch(() => {});
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 2500);
    return () => clearInterval(id);
  }, []);

  async function create() {
    const text = prompt.trim();
    if (!text || busy) return;
    setBusy(true);
    try {
      const task = await api.createTask(text, text.slice(0, 80), role, selfScaffold);
      setTasks((items) => [task, ...items]);
      setActiveId(task.id);
      setPrompt("");
    } finally {
      setBusy(false);
    }
  }

  async function resolveApproval(approval: Approval, approved: boolean) {
    await api.resolveApproval(approval.id, approved).catch(() => {});
    load();
  }

  return (
    <div className="view tasks">
      <header className="view-head">
        <span className="eyebrow readout">background checks</span>
        <h1>Tasks</h1>
        <p>Run checks outside chat and keep the result here.</p>
      </header>

      <div className="tasks-layout">
        <aside className="task-list">
          <div className="task-create panel">
            <label className="readout">new check</label>
            <textarea
              value={prompt}
              rows={4}
              placeholder="Check what qBittorrent finished in the last 48 hours…"
              onChange={(e) => setPrompt(e.target.value)}
            />
            <div className="task-create-row">
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="chat">chat</option>
                <option value="deep">deep</option>
              </select>
              <button className="btn-primary" onClick={create} disabled={busy || !prompt.trim()}>
                Run
              </button>
            </div>
            <label className="task-toggle">
              <input
                type="checkbox"
                checked={selfScaffold}
                onChange={(e) => setSelfScaffold(e.target.checked)}
              />
              <span>self-scaffold</span>
            </label>
          </div>

          {tasks.map((task) => (
            <button
              key={task.id}
              className={`task-item ${task.id === active?.id ? "active" : ""}`}
              onClick={() => setActiveId(task.id)}
            >
              <span className="task-title">{task.title}</span>
              <span className={`chip ${chipClass(task.status)}`}>{task.status}</span>
            </button>
          ))}
          {tasks.length === 0 && <div className="empty">No tasks yet</div>}
        </aside>

        <main className="task-detail">
          {approvals.length > 0 && (
            <section className="task-approvals panel">
              <div className="readout">approvals waiting</div>
              {approvals.map((a) => (
                <div key={a.id} className="approval-row">
                  <span className="mono">{a.tool}</span>
                  <div className="approval-actions">
                    <button className="btn-primary" onClick={() => resolveApproval(a, true)}>
                      Approve
                    </button>
                    <button className="btn-danger" onClick={() => resolveApproval(a, false)}>
                      Deny
                    </button>
                  </div>
                </div>
              ))}
            </section>
          )}

          {!active && <div className="empty">Select or start a task</div>}
          {active && (
            <>
              <section className="task-result panel">
                <div className="task-result-head">
                  <div>
                    <div className="readout">{active.role} role</div>
                    <h2>{active.title}</h2>
                  </div>
                  <div className="task-status-stack">
                    {active.self_scaffold && <span className="chip chip-amber">self-scaffold</span>}
                    <span className={`chip ${chipClass(active.status)}`}>{active.status}</span>
                  </div>
                </div>
                <p className="task-prompt">{active.prompt}</p>
                {active.error && <pre className="task-error">{active.error}</pre>}
                <pre className="task-output">
                  {active.result || (active.status === "running" ? "running…" : "no result yet")}
                </pre>
              </section>

              <section className="task-events panel">
                <div className="readout">event trail</div>
                {(active.events ?? []).length === 0 && <div className="empty">No events yet</div>}
                {(active.events ?? []).slice().reverse().map((event, index) => (
                  <div key={`${event.kind}-${index}`} className="task-event">
                    <span className="chip">{event.kind}</span>
                    <pre>{JSON.stringify(event.data, null, 1)}</pre>
                  </div>
                ))}
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function chipClass(status: TaskRun["status"]): string {
  if (status === "done") return "chip-ok";
  if (status === "error") return "chip-alert";
  if (status === "running") return "chip-amber";
  return "";
}
