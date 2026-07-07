import { NavLink, Route, Routes, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { api, getToken } from "./api";
import { ChatView } from "./views/ChatView";
import { ResearchView } from "./views/ResearchView";
import { TasksView } from "./views/TasksView";
import { MemoryView } from "./views/MemoryView";
import { SkillsView } from "./views/SkillsView";
import { MeshView } from "./views/MeshView";
import { SettingsView } from "./views/SettingsView";
import "./app.css";

const NAV = [
  { to: "/chat", label: "Chat", glyph: "◈" },
  { to: "/tasks", label: "Tasks", glyph: "☷" },
  { to: "/research", label: "Research", glyph: "❋" },
  { to: "/memory", label: "Memory", glyph: "▦" },
  { to: "/skills", label: "Skills", glyph: "✳" },
  { to: "/mesh", label: "Mesh", glyph: "⬡" },
  { to: "/settings", label: "Settings", glyph: "⚙" },
];

export default function App() {
  const [online, setOnline] = useState<boolean | null>(null);
  const [version, setVersion] = useState("");

  useEffect(() => {
    let alive = true;
    const ping = () =>
      api
        .health()
        .then((h) => {
          if (alive) {
            setOnline(true);
            setVersion(h.version);
          }
        })
        .catch(() => alive && setOnline(false));
    ping();
    const id = setInterval(ping, 15000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const hasToken = !!getToken();

  return (
    <div className="shell">
      <nav className="rail">
        <div className="brand">
          <span className="brand-mark">AE</span>
        </div>
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} className="rail-item" title={n.label}>
            <span className="rail-glyph">{n.glyph}</span>
            <span className="rail-label">{n.label}</span>
          </NavLink>
        ))}
        <div className="rail-status" title={online ? "server online" : "server offline"}>
          <span className={`dot ${online ? "dot-ok" : online === false ? "dot-off" : ""}`} />
          <span className="readout">{version ? `v${version}` : "···"}</span>
        </div>
      </nav>

      <main className="stage">
        {!hasToken && online !== false && <TokenBanner />}
        <Routes>
          <Route path="/" element={<Navigate to="/chat" replace />} />
          <Route path="/chat" element={<ChatView />} />
          <Route path="/chat/:sessionId" element={<ChatView />} />
          <Route path="/tasks" element={<TasksView />} />
          <Route path="/research" element={<ResearchView />} />
          <Route path="/memory" element={<MemoryView />} />
          <Route path="/skills" element={<SkillsView />} />
          <Route path="/mesh" element={<MeshView />} />
          <Route path="/settings" element={<SettingsView />} />
        </Routes>
      </main>
    </div>
  );
}

function TokenBanner() {
  return (
    <div className="token-banner">
      <span className="readout">no access token set</span>
      <span>
        Add your server token in <NavLink to="/settings">Settings</NavLink> to connect.
      </span>
    </div>
  );
}
