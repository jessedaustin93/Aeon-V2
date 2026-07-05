import { useState } from "react";
import { api, type MemoryHit } from "../api";
import "./views.css";

const LAYERS: Record<string, string> = {
  raw: "chip",
  episodic: "chip chip-cyan",
  semantic: "chip chip-amber",
  reflections: "chip chip-ok",
  consolidations: "chip chip-ok",
};

export function MemoryView() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<MemoryHit[]>([]);
  const [searched, setSearched] = useState(false);

  async function search() {
    if (!q.trim()) return;
    const r = await api.memorySearch(q).catch(() => ({ results: [] as MemoryHit[] }));
    setHits(r.results);
    setSearched(true);
  }

  return (
    <div className="view">
      <div className="view-head">
        <span className="readout eyebrow">local recall · lives on the t5810</span>
        <h1>Memory</h1>
        <p>Aeon's own append-only memory. Separate from the shared Master Vault.</p>
      </div>
      <div className="view-body">
        <div className="mem-search">
          <input
            value={q}
            placeholder="Search raw, episodic, semantic, reflections…"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
          />
          <button className="btn-primary" onClick={search} disabled={!q.trim()}>
            Search
          </button>
        </div>

        {searched && hits.length === 0 && <div className="empty">No memories matched</div>}
        <div className="mem-list">
          {hits.map((h, i) => (
            <div key={h.id ?? i} className="panel mem-item">
              <div className="mem-top">
                <span className={LAYERS[h.type ?? "raw"] ?? "chip"}>{h.type ?? "memory"}</span>
                {h.id && <span className="readout">{h.id}</span>}
              </div>
              <div className="mem-text">{h.text}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
