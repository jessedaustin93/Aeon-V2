import { useEffect, useState } from "react";
import { api, type AgentEvent, type Skill } from "../api";
import "./views.css";

export function SkillsView() {
  const [active, setActive] = useState<Skill[]>([]);
  const [proposals, setProposals] = useState<Skill[]>([]);
  const [open, setOpen] = useState<Skill | null>(null);
  const [topic, setTopic] = useState("");
  const [forging, setForging] = useState(false);
  const [trace, setTrace] = useState<string[]>([]);

  const load = () =>
    api.skills().then((r) => {
      setActive(r.active);
      setProposals(r.proposals);
    }).catch(() => {});
  useEffect(() => {
    load();
  }, []);

  async function approve(name: string) {
    await api.approveSkill(name).catch(() => {});
    load();
  }
  async function reject(name: string) {
    await api.rejectSkill(name).catch(() => {});
    load();
  }

  async function forge() {
    const t = topic.trim();
    if (!t || forging) return;
    setForging(true);
    setTrace([]);
    await api
      .forgeSkill(t, (e: AgentEvent) => {
        if (e.kind === "text") setTrace((x) => [...x, String(e.data.text).trim()].filter(Boolean));
        else if (e.kind === "error") setTrace((x) => [...x, `rejected: ${e.data.error}`]);
        else if (e.kind === "done")
          setTrace((x) => [...x, `forged: ${(e.data.skill as { name: string }).name}`]);
      })
      .catch(() => setTrace((x) => [...x, "connection lost"]));
    setForging(false);
    setTopic("");
    load();
  }

  return (
    <div className="view">
      <div className="view-head">
        <span className="readout eyebrow">learned procedures</span>
        <h1>Skills</h1>
        <p>Reusable procedures Aeon builds from experience. Every one is yours to approve.</p>
      </div>
      <div className="view-body">
        <div className="panel forge-box">
          <div className="readout">Forge a skill from research</div>
          <p className="skill-desc" style={{ margin: 0 }}>
            Aeon researches the topic, drafts a skill, and only offers it if it passes a
            critique and beats a no-skill baseline on a live test.
          </p>
          <div className="forge-row">
            <input
              value={topic}
              placeholder="Topic to research and turn into a skill…"
              onChange={(e) => setTopic(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && forge()}
            />
            <button className="btn-primary" onClick={forge} disabled={forging || !topic.trim()}>
              {forging ? "Forging…" : "Forge"}
            </button>
          </div>
          {trace.length > 0 && (
            <div className="forge-trace">
              {trace.map((t, i) => (
                <div key={i} className="mono trace-line">
                  <span className="trace-mark">›</span> {t}
                </div>
              ))}
            </div>
          )}
        </div>

        {proposals.length > 0 && (
          <>
            <div className="readout section-label">Awaiting your review</div>
            <div className="card-grid">
              {proposals.map((s) => (
                <div key={s.name} className="panel skill-card skill-proposal">
                  <div className="skill-top">
                    <span className="mono skill-name">{s.name}</span>
                    <span className="chip chip-amber">proposed</span>
                  </div>
                  <p className="skill-desc">{s.description}</p>
                  {s.evidence && (
                    <div className="evidence">
                      {s.evidence.ab && (
                        <span
                          className={`chip ${s.evidence.ab.with_better ? "chip-ok" : "chip-alert"}`}
                        >
                          A/B {s.evidence.ab.with_better ? "passed" : "failed"}
                        </span>
                      )}
                      {s.evidence.scores &&
                        Object.entries(s.evidence.scores).map(([k, v]) => (
                          <span key={k} className="chip">
                            {k} {v}/5
                          </span>
                        ))}
                      {s.evidence.sources && s.evidence.sources.length > 0 && (
                        <span className="readout">{s.evidence.sources.length} sources</span>
                      )}
                    </div>
                  )}
                  <div className="skill-actions">
                    <button className="btn-primary" onClick={() => approve(s.name)}>
                      Approve
                    </button>
                    <button className="btn-danger" onClick={() => reject(s.name)}>
                      Reject
                    </button>
                    <button onClick={() => setOpen(s)}>View</button>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        <div className="readout section-label">Active skills</div>
        {active.length === 0 && <div className="empty">No active skills yet</div>}
        <div className="card-grid">
          {active.map((s) => (
            <button key={s.name} className="panel skill-card" onClick={() => setOpen(s)}>
              <div className="skill-top">
                <span className="mono skill-name">{s.name}</span>
                <span className="chip chip-ok">active</span>
              </div>
              <p className="skill-desc">{s.description}</p>
            </button>
          ))}
        </div>
      </div>

      {open && (
        <div className="modal" onClick={() => setOpen(null)}>
          <div className="modal-panel panel" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={() => setOpen(null)}>
              ✕
            </button>
            <div className="mono skill-name" style={{ fontSize: 15 }}>
              {open.name}
            </div>
            <p className="skill-desc">{open.description}</p>
            <pre className="report-body">{open.body}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
