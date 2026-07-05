import { useEffect, useState } from "react";
import { api, type MeshInfo, type ModelsInfo } from "../api";
import "./views.css";

export function MeshView() {
  const [mesh, setMesh] = useState<MeshInfo | null>(null);
  const [models, setModels] = useState<ModelsInfo | null>(null);

  useEffect(() => {
    const load = () => {
      api.mesh().then(setMesh).catch(() => {});
      api.models().then(setModels).catch(() => {});
    };
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="view">
      <div className="view-head">
        <span className="readout eyebrow">distributed compute</span>
        <h1>Mesh</h1>
        <p>Aeon's identity on the Agent Mesh and the LLM workers it can reach.</p>
      </div>
      <div className="view-body">
        <div className="mesh-identity panel">
          <div>
            <div className="readout">this node</div>
            <div className="mono mesh-id">{mesh?.agent_id ?? "···"}</div>
          </div>
          <span className={`chip ${mesh?.configured ? "chip-ok" : "chip-alert"}`}>
            {mesh?.configured ? "mesh linked" : "mesh offline"}
          </span>
        </div>

        <div className="readout section-label">LLM workers</div>
        <div className="worker-band">
          {(models?.workers ?? []).map((w) => (
            <div key={w.base_url} className={`panel worker-station ${w.healthy ? "" : "worker-down"}`}>
              <div className="worker-top">
                <span className={`dot ${w.healthy ? "dot-ok" : "dot-off"}`} />
                <span className="mono worker-name">{w.name}</span>
              </div>
              <div className="readout worker-url">{w.base_url}</div>
              <div className="worker-meta">
                <span className="readout">prio {w.priority}</span>
                <span className="chip">{w.models.join(", ")}</span>
              </div>
            </div>
          ))}
          {(models?.workers ?? []).length === 0 && <div className="empty">No workers configured</div>}
        </div>

        <div className="readout section-label">Model roles</div>
        <div className="role-table panel">
          {Object.entries(models?.roles ?? {}).map(([role, model]) => (
            <div key={role} className="role-row">
              <span className="chip chip-cyan">{role}</span>
              <span className="mono role-model">{model}</span>
            </div>
          ))}
          {Object.keys(models?.roles ?? {}).length === 0 && (
            <div className="empty">No roles configured</div>
          )}
        </div>
      </div>
    </div>
  );
}
