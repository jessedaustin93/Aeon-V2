import { useEffect, useState } from "react";
import { api, type Skill } from "../api";
import "./views.css";

export function SkillsView() {
  const [active, setActive] = useState<Skill[]>([]);
  const [proposals, setProposals] = useState<Skill[]>([]);
  const [open, setOpen] = useState<Skill | null>(null);

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

  return (
    <div className="view">
      <div className="view-head">
        <span className="readout eyebrow">learned procedures</span>
        <h1>Skills</h1>
        <p>Reusable procedures Aeon builds from experience. Every one is yours to approve.</p>
      </div>
      <div className="view-body">
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
