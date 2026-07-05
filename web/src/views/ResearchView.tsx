import { useEffect, useState } from "react";
import { api, stream, type AgentEvent, type ResearchRun } from "../api";
import "./views.css";

export function ResearchView() {
  const [question, setQuestion] = useState("");
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [runs, setRuns] = useState<ResearchRun[]>([]);
  const [openReport, setOpenReport] = useState<string | null>(null);

  const load = () => api.research().then((r) => setRuns(r.runs)).catch(() => {});
  useEffect(() => {
    load();
  }, []);

  async function go() {
    const q = question.trim();
    if (!q || running) return;
    setRunning(true);
    setProgress([]);
    try {
      await stream("/api/research", { question: q }, (ev: AgentEvent) => {
        if (ev.kind === "text") setProgress((p) => [...p, String(ev.data.text).trim()].filter(Boolean));
        if (ev.kind === "error") setProgress((p) => [...p, `error: ${ev.data.error}`]);
      });
    } catch {
      setProgress((p) => [...p, "connection lost"]);
    }
    setRunning(false);
    setQuestion("");
    load();
  }

  async function view(id: string) {
    const r = await api.researchRun(id).catch(() => null);
    if (r) setOpenReport(r.report);
  }

  return (
    <div className="view">
      <div className="view-head">
        <span className="readout eyebrow">deep research</span>
        <h1>Research desk</h1>
        <p>Aeon plans queries, reads sources, and writes a cited report.</p>
      </div>
      <div className="view-body">
        <div className="panel research-ask">
          <textarea
            value={question}
            rows={2}
            placeholder="What should Aeon investigate?"
            onChange={(e) => setQuestion(e.target.value)}
          />
          <button className="btn-primary" onClick={go} disabled={running || !question.trim()}>
            {running ? "Researching…" : "Run research"}
          </button>
        </div>

        {progress.length > 0 && (
          <div className="panel research-progress">
            <div className="readout">live trace</div>
            {progress.map((p, i) => (
              <div key={i} className="mono trace-line">
                <span className="trace-mark">›</span> {p}
              </div>
            ))}
          </div>
        )}

        <div className="readout section-label">Report library</div>
        {runs.length === 0 && <div className="empty">No reports yet</div>}
        <div className="card-grid">
          {runs.map((r) => (
            <button key={r.id} className="panel report-card" onClick={() => view(r.id)}>
              <div className="report-q">{r.question}</div>
              <div className="report-meta">
                <span className={`chip ${r.status === "complete" ? "chip-ok" : "chip-alert"}`}>
                  {r.status}
                </span>
                <span className="readout">{r.sources.length} sources</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {openReport !== null && (
        <div className="modal" onClick={() => setOpenReport(null)}>
          <div className="modal-panel panel" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={() => setOpenReport(null)}>
              ✕
            </button>
            <pre className="report-body">{openReport}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
