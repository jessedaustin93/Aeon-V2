import { useEffect, useRef, useState, useCallback } from "react";
import { api, stream, type AgentEvent, type Message, type SessionMeta } from "../api";
import { Waveform } from "../components/Waveform";
import "./chat.css";

interface LogEntry {
  id: string;
  tool: string;
  args?: Record<string, unknown>;
  result?: unknown;
  approvalId?: string;
  status: "running" | "ok" | "error" | "await";
}

export function ChatView() {
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [live, setLive] = useState("");
  const [log, setLog] = useState<LogEntry[]>([]);
  const [logH, setLogH] = useState(160);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Drag the handle above the signal log to size it up/down (stacked layout).
  function startLogResize(e: React.PointerEvent) {
    e.preventDefault();
    const startY = e.clientY;
    const startH = logH;
    const move = (ev: PointerEvent) =>
      setLogH(Math.min(520, Math.max(52, startH + (startY - ev.clientY))));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  const loadSessions = useCallback(() => {
    api.sessions().then((r) => setSessions(r.sessions)).catch(() => {});
  }, []);
  useEffect(loadSessions, [loadSessions]);

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    api.session(activeId).then((s) => setMessages(s.messages)).catch(() => {});
  }, [activeId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, live, log]);

  async function resolveApproval(entry: LogEntry, approved: boolean) {
    if (!entry.approvalId) return;
    await api.resolveApproval(entry.approvalId, approved).catch(() => {});
    setLog((l) =>
      l.map((e) => (e.id === entry.id ? { ...e, status: approved ? "running" : "error" } : e)),
    );
  }

  async function send() {
    const text = draft.trim();
    if (!text || streaming) return;
    let sessionId = activeId;
    if (!sessionId) {
      const s = await api.createSession();
      sessionId = s.id;
      setActiveId(s.id);
      loadSessions();
    }
    setMessages((m) => [...m, { role: "user", content: text }]);
    setDraft("");
    setLive("");
    setLog([]);
    setStreaming(true);

    let acc = "";
    try {
      await stream("/api/chat", { session_id: sessionId, message: text }, (ev: AgentEvent) => {
        handleEvent(ev, (t) => {
          acc += t;
          // Local models tend to prepend blank lines; trim the leading
          // whitespace so replies don't start with 2-3 empty lines.
          setLive(acc.replace(/^\s+/, ""));
        });
      });
    } catch {
      acc += "\n\n[connection lost]";
    }
    setStreaming(false);
    const reply = acc.trim();
    if (reply) setMessages((m) => [...m, { role: "assistant", content: reply }]);
    setLive("");
    loadSessions();
  }

  function handleEvent(ev: AgentEvent, appendText: (t: string) => void) {
    switch (ev.kind) {
      case "text":
        appendText(String(ev.data.text ?? ""));
        break;
      case "tool_call":
        setLog((l) => [
          ...l,
          {
            id: String(ev.data.id ?? Math.random()),
            tool: String(ev.data.tool),
            args: ev.data.arguments as Record<string, unknown>,
            status: "running",
          },
        ]);
        break;
      case "approval_pending":
        setLog((l) =>
          l.map((e) =>
            e.tool === ev.data.tool && e.status === "running"
              ? { ...e, status: "await", approvalId: String(ev.data.approval_id) }
              : e,
          ),
        );
        break;
      case "tool_result": {
        const result = ev.data.result as Record<string, unknown>;
        const errored = result && "error" in result;
        setLog((l) =>
          l.map((e) =>
            e.id === String(ev.data.id)
              ? { ...e, result, status: errored ? "error" : "ok" }
              : e,
          ),
        );
        break;
      }
    }
  }

  return (
    <div className="view chat" style={{ "--log-h": `${logH}px` } as React.CSSProperties}>
      <div className="chat-sessions">
        <button className="btn-primary new-chat" onClick={() => setActiveId(null)}>
          + New session
        </button>
        <div className="readout session-head">Sessions</div>
        {sessions.length === 0 && <div className="empty" style={{ padding: 24 }}>No sessions</div>}
        {sessions.map((s) => (
          <button
            key={s.id}
            className={`session-item ${s.id === activeId ? "active" : ""}`}
            onClick={() => setActiveId(s.id)}
          >
            <span className="session-title">{s.title}</span>
            <span className="readout">{s.message_count} msg</span>
          </button>
        ))}
      </div>

      <div className="chat-main">
        <header className="chat-scope">
          <Waveform active={streaming} />
          <div className="chat-scope-label readout">
            {streaming ? "transmitting" : "standby"}
          </div>
        </header>

        <div className="chat-scroll" ref={scrollRef}>
          {messages.length === 0 && !live && (
            <div className="empty">
              Aeon standing by. Ask about the lab, the mesh, or the field.
            </div>
          )}
          {messages.map((m, i) => (
            <Bubble key={i} role={m.role} text={m.content} />
          ))}
          {live && <Bubble role="assistant" text={live} pulsing />}
        </div>

        <div className="chat-compose">
          <textarea
            value={draft}
            placeholder="Message Aeon…"
            rows={1}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <button className="btn-primary" onClick={send} disabled={streaming || !draft.trim()}>
            Send
          </button>
        </div>
      </div>

      <aside className="chat-log">
        <div className="log-resize" onPointerDown={startLogResize} title="Drag to resize" />
        <div className="readout log-head">Signal log</div>
        {log.length === 0 && <div className="empty" style={{ padding: 24 }}>No tool activity</div>}
        {log.map((e) => (
          <div key={e.id} className={`log-entry log-${e.status}`}>
            <div className="log-entry-top">
              <span className="mono log-tool">{e.tool}</span>
              <StatusChip status={e.status} />
            </div>
            {e.args && Object.keys(e.args).length > 0 && (
              <pre className="log-args">{JSON.stringify(e.args, null, 1)}</pre>
            )}
            {e.status === "await" && (
              <div className="log-approve">
                <span className="readout">approval required</span>
                <div className="log-approve-btns">
                  <button className="btn-primary" onClick={() => resolveApproval(e, true)}>
                    Approve
                  </button>
                  <button className="btn-danger" onClick={() => resolveApproval(e, false)}>
                    Deny
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </aside>
    </div>
  );
}

function StatusChip({ status }: { status: LogEntry["status"] }) {
  const map = {
    running: ["chip", "running"],
    ok: ["chip chip-ok", "done"],
    error: ["chip chip-alert", "error"],
    await: ["chip chip-amber", "awaiting"],
  } as const;
  const [cls, label] = map[status];
  return <span className={cls}>{label}</span>;
}

function Bubble({ role, text, pulsing }: { role: string; text: string; pulsing?: boolean }) {
  const isUser = role === "user";
  return (
    <div className={`bubble ${isUser ? "bubble-user" : "bubble-aeon"}`}>
      <div className="bubble-tag readout">{isUser ? "you" : "aeon"}</div>
      <div className={`bubble-body ${pulsing ? "pulsing" : ""}`}>{text}</div>
    </div>
  );
}
