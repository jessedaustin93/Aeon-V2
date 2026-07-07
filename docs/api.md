# Aeon-V2 API

Base URL: `http://<host>:8900`. All `/api/*` routes require
`Authorization: Bearer <AEON_API_TOKEN>` (when the token is set; otherwise only
loopback is allowed). Streaming endpoints return `text/event-stream` with
newline-delimited `data: {json}` frames carrying `AgentEvent`s.

| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/health` | status, version, worker health |
| GET  | `/api/models` | role→model map and worker list |
| GET  | `/api/sessions` | list chat sessions |
| POST | `/api/sessions` | create a session `{title?}` |
| GET  | `/api/sessions/{id}` | full session with messages |
| POST | `/api/chat` | **stream** `{session_id, message, role?}` |
| GET  | `/api/tasks` | list background task runs |
| POST | `/api/tasks` | start a background task `{prompt, title?, role?}` |
| GET  | `/api/tasks/{id}` | one background task with result + event trail |
| GET  | `/api/approvals` | pending tool approvals |
| POST | `/api/approvals/{id}` | resolve `{approved: bool}` |
| GET  | `/api/skills` | active skills + proposals |
| POST | `/api/skills/propose` | distill a skill from `{session_id}` |
| POST | `/api/skills/forge` | **stream** research → validated skill from `{topic}` |
| POST | `/api/skills/{name}/approve` | activate a proposal |
| POST | `/api/skills/{name}/reject` | discard a proposal |
| POST | `/api/research` | **stream** a deep-research run `{question}` |
| GET  | `/api/research` | list saved reports |
| GET  | `/api/research/{id}` | one report with body |
| GET  | `/api/memory/search?q=` | search Aeon's local memory |
| GET  | `/api/mesh` | this node's mesh identity + workers |
| POST | `/api/mesh/message` | post to a thread `{recipient, content, thread_id?}` |

## AgentEvent kinds

`text` (streamed token), `tool_call` (`{id, tool, arguments}`),
`approval_pending` (`{approval_id, tool, arguments}`), `tool_result`
(`{id, tool, result}`), `done` (`{text}`), `error` (`{error}`).

The **forge** stream emits `text` progress lines and ends in either `done`
(`{skill, evidence}` — a validated proposal) or `error` (`{error, ...}` — the
skill was rejected by the critique or A/B gate; no proposal is created).

## Example

```bash
TOKEN=...; H="Authorization: Bearer $TOKEN"
SID=$(curl -s -XPOST -H "$H" -H 'Content-Type: application/json' \
      -d '{}' localhost:8900/api/sessions | jq -r .id)
curl -N -XPOST -H "$H" -H 'Content-Type: application/json' \
     -d "{\"session_id\":\"$SID\",\"message\":\"hello\"}" \
     localhost:8900/api/chat
```
