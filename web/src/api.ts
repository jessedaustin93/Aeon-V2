// Thin client for the Aeon-V2 API. The token is stored in localStorage and
// sent as a Bearer header. Streaming endpoints (chat, research) are consumed
// as newline-delimited SSE.

const TOKEN_KEY = "aeon.token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}
export function setToken(t: string) {
  localStorage.setItem(TOKEN_KEY, t);
}

function headers(): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const t = getToken();
  if (t) h["Authorization"] = `Bearer ${t}`;
  return h;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: headers(),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(res.status, `${method} ${path} failed (${res.status})`);
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

export const api = {
  health: () => req<Health>("GET", "/api/health"),
  models: () => req<ModelsInfo>("GET", "/api/models"),
  sessions: () => req<{ sessions: SessionMeta[] }>("GET", "/api/sessions"),
  createSession: (title = "") => req<Session>("POST", "/api/sessions", { title }),
  session: (id: string) => req<Session>("GET", `/api/sessions/${id}`),
  approvals: () => req<{ pending: Approval[] }>("GET", "/api/approvals"),
  resolveApproval: (id: string, approved: boolean) =>
    req<Approval>("POST", `/api/approvals/${id}`, { approved }),
  skills: () => req<{ active: Skill[]; proposals: Skill[] }>("GET", "/api/skills"),
  proposeSkill: (session_id: string) =>
    req<{ skill: Skill | null }>("POST", "/api/skills/propose", { session_id }),
  approveSkill: (name: string) => req<Skill>("POST", `/api/skills/${name}/approve`),
  rejectSkill: (name: string) => req("POST", `/api/skills/${name}/reject`),
  forgeSkill: (topic: string, onEvent: (e: AgentEvent) => void) =>
    stream("/api/skills/forge", { topic }, onEvent),
  research: () => req<{ runs: ResearchRun[] }>("GET", "/api/research"),
  researchRun: (id: string) => req<ResearchRun & { report: string }>("GET", `/api/research/${id}`),
  mesh: () => req<MeshInfo>("GET", "/api/mesh"),
  memorySearch: (q: string) =>
    req<{ query: string; results: MemoryHit[] }>(
      "GET",
      `/api/memory/search?q=${encodeURIComponent(q)}`,
    ),
};

// Consume a streaming endpoint, invoking onEvent for each SSE data payload.
export async function stream(
  path: string,
  body: unknown,
  onEvent: (event: AgentEvent) => void,
): Promise<void> {
  const res = await fetch(path, { method: "POST", headers: headers(), body: JSON.stringify(body) });
  if (!res.ok || !res.body) throw new ApiError(res.status, `stream ${path} failed`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const line = part.trim();
      if (line.startsWith("data:")) {
        try {
          onEvent(JSON.parse(line.slice(5).trim()));
        } catch {
          /* ignore keepalives / partial frames */
        }
      }
    }
  }
}

// ---- types ---------------------------------------------------------------

export interface Health {
  status: string;
  version: string;
  workers: Record<string, boolean>;
}
export interface Worker {
  name: string;
  base_url: string;
  models: string[];
  priority: number;
  healthy: boolean;
}
export interface ModelsInfo {
  roles: Record<string, string>;
  workers: Worker[];
}
export interface SessionMeta {
  id: string;
  title: string;
  updated_at: string;
  message_count: number;
}
export interface Message {
  role: string;
  content: string;
}
export interface Session {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: Message[];
}
export interface Approval {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  created_at: string;
  status: string;
}
export interface SkillEvidence {
  topic?: string;
  sources?: { url: string; title: string }[];
  scores?: Record<string, number>;
  ab?: { with_better: boolean; reason: string; task: string };
  report_excerpt?: string;
}
export interface Skill {
  name: string;
  description: string;
  body: string;
  path?: string;
  evidence?: SkillEvidence | null;
}
export interface ResearchRun {
  id: string;
  question: string;
  status: string;
  report_path: string;
  sources: { url: string; title: string }[];
  created_at: string;
}
export interface MeshInfo {
  agent_id: string;
  machine: string;
  configured: boolean;
  workers: { name: string; base_url: string; healthy: boolean }[];
}
export interface MemoryHit {
  id: string | null;
  type: string | null;
  text: string;
  score?: number;
}
export interface AgentEvent {
  kind: "text" | "tool_call" | "tool_result" | "approval_pending" | "done" | "error";
  data: Record<string, unknown>;
}
