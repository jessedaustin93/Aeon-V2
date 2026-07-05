import { useEffect, useState } from "react";
import { api, getToken, setToken, type Health } from "../api";
import "./views.css";

export function SettingsView() {
  const [token, setTok] = useState(getToken());
  const [saved, setSaved] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [err, setErr] = useState(false);

  function testConnection() {
    setErr(false);
    api.health().then(setHealth).catch(() => setErr(true));
  }
  useEffect(testConnection, []);

  function save() {
    setToken(token.trim());
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
    testConnection();
  }

  return (
    <div className="view">
      <div className="view-head">
        <span className="readout eyebrow">console configuration</span>
        <h1>Settings</h1>
        <p>Connect this console to your Aeon server.</p>
      </div>
      <div className="view-body">
        <div className="panel settings-block">
          <label className="readout">Access token</label>
          <p className="settings-help">
            Set on the server as <span className="mono">AEON_API_TOKEN</span>. Stored only in this
            browser.
          </p>
          <div className="settings-row">
            <input
              type="password"
              value={token}
              placeholder="paste server token"
              onChange={(e) => setTok(e.target.value)}
            />
            <button className="btn-primary" onClick={save}>
              {saved ? "Saved ✓" : "Save"}
            </button>
          </div>
        </div>

        <div className="panel settings-block">
          <div className="settings-status-head">
            <label className="readout">Server status</label>
            <button onClick={testConnection}>Test</button>
          </div>
          {health && !err && (
            <div className="settings-status">
              <span className="chip chip-ok">online</span>
              <span className="mono">Aeon v{health.version}</span>
              <span className="readout">
                {Object.values(health.workers).filter(Boolean).length}/
                {Object.keys(health.workers).length} workers up
              </span>
            </div>
          )}
          {err && (
            <div className="settings-status">
              <span className="chip chip-alert">unreachable</span>
              <span className="settings-help">Check the token and that the server is running.</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
