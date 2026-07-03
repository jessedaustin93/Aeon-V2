# Aeon-V2 Design

- **Date:** 2026-07-03
- **Status:** Approved by Jesse
- **Repo:** `jessedaustin93/Aeon-V2` (public)

## Summary

Aeon-V2 is a self-hosted AI workspace: Odysseus's product shape, Hermes Agent's
agent internals, and Aeon-V1's memory and governance. It runs as a server on the
**Dell T5810** (GTX 1080 FE, LM Studio at `localhost:1234`) with a professional
React PWA usable from any browser on the tailnet — including Jesse's phone — and
designed to wrap into an Android app via Capacitor later.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Chassis | New build on aeon-v1 core; lift code from Hermes (MIT) only; take ideas, not code, from Odysseus (AGPL-3.0) | Keeps the repo freely licensable and Aeon's identity; avoids AGPL contamination |
| Topology | Server on T5810; laptop/phone/other machines are browser clients | One brain, many screens; matches vault Aeon-Architecture |
| UI stack | React + Vite + TypeScript PWA | Paid-SaaS polish, phone-usable day one, Capacitor wrap later |
| v2.0 feature scope | Deep research + skills/learning loop (in); cron + docs editor (out) | YAGNI; Obsidian covers notes |
| Memory location | `/home/t5810/aeon-data/` on T5810 — local, never in repo or Master Vault | Per 2026-06-29 vault boundary decision |
| Master Vault | Read-only context; writes only via explicit UI "promotions" | Per 2026-06-29 vault boundary decision |

## Repo layout

```
Aeon-V2/
├── server/                 # Python 3.11+, FastAPI
│   └── aeon/
│       ├── core/           # ported from aeon-v1: memory engine, schemas,
│       │                   #   write_guard, approval, embeddings, time utils
│       ├── models/         # model router: LM Studio + remote mesh workers
│       ├── agent/          # agent loop, tool registry, tool execution
│       ├── tools/          # built-in tools (fs, shell, web, memory, vault, mesh)
│       ├── skills/         # Hermes-style skills engine (agentskills.io format)
│       ├── research/       # deep research pipeline
│       ├── mesh/           # agent-mesh peer bridge + worker discovery
│       ├── vaultlink/      # Master Vault read-only context + promotion flow
│       └── api/            # REST + WebSocket, auth, static serving
├── web/                    # React + Vite + TypeScript PWA
├── deploy/                 # systemd units, install script for T5810
├── docs/                   # architecture, memory model, API, mesh, UI
└── tests/                  # pytest (server), vitest (web)
```

## Components

### 1. Model layer

Model router with named roles, all speaking the OpenAI-compatible API:

| Role | Default (LM Studio @ t5810:1234) |
|---|---|
| chat | `qwen3-4b-instruct-2507` |
| deep | `qwen3-4b-thinking-2507` |
| embed | `text-embedding-nomic-embed-text-v1.5` |

The router also holds a **worker registry**: any mesh machine exposing an
OpenAI-compatible endpoint is registered with its models and priority. The
router health-checks workers and dispatches per role; parallel agent/research
subtasks fan out across workers when more than one is online. Adding a machine
is a config entry, not an integration.

### 2. Agent loop + tool calling

Native OpenAI function calling through LM Studio (qwen3 supports tools), with a
prompted-JSON fallback for models without tool support. Loop: user message →
model streams → tool calls executed → results fed back → repeat until done.
Every step streams to the UI as a tool-call timeline.

Built-in tools at launch:

- **filesystem** — scoped to configured allowed directories
- **shell** — approval-gated via aeon-v1's approval agent + mesh approve/deny
  pattern; nothing destructive runs without explicit approval in the UI
- **web search + fetch**
- **memory search / save** — save is write-guarded
- **vault read** — Master Vault retrieval, read-only
- **mesh message** — post to agent-mesh threads
- **research** — launch a deep-research run
- **skills** — load/use skills

### 3. Memory

The aeon-v1 memory engine ports intact: raw/episodic/semantic/reflections/
consolidations, append-only raw, write guard, protected core memory,
deterministic search + embedding search, Obsidian-readable mirror. Data root:
`/home/t5810/aeon-data/`. The Master Vault is a separate read-only context
source; vault writes are explicit human-triggered promotions.

### 4. Skills + learning loop

Skills are markdown+frontmatter directories (agentskills.io standard) under
`~/aeon-data/skills/`. After a complex task, Aeon proposes a distilled skill;
Jesse approves it in the UI before it loads into future runs. When a skill
stumbles in use, Aeon proposes an edit. All human-gated.

### 5. Deep research

Question → query plan → search → fetch/read sources → iterate → cited markdown
report, stored in memory, viewable/exportable in the UI. Uses the `deep` model
role; fans source-reading subtasks across mesh workers when available.

### 6. Agent mesh integration

Aeon-V2 natively registers as a mesh peer, replacing the `aeon@t5810` bridge
script. It can be addressed by other agents (claude@x1, claude@t3610), post to
threads, request approvals through the existing hub flow, and discover LLM
workers. The UI mesh dashboard shows peers, workers, and health.

### 7. UI

Dark futuristic-tactical theme defined as design tokens (also recorded in the
vault's `UIStandards.md`). Layout: slim icon sidebar (Chat / Agents / Research /
Memory / Skills / Mesh / Settings), main content area, right panel for
tool-call timeline and approvals. Streaming markdown chat with code blocks,
model picker, session history. PWA manifest + service worker for
add-to-home-screen on Android. Single-user token login screen.

### 8. Error handling

- LM Studio down → chat degrades gracefully; deterministic memory search and UI
  keep working; a banner shows model status.
- Worker offline → router falls back to T5810 local; mesh dashboard flags it.
- Tool failure → the error becomes a tool result the model sees and can recover
  from; never silently swallowed.
- Memory writes → guarded, journaled; append-only raw preserved.

### 9. Testing

Pytest for core (port aeon-v1's tests), agent loop (mocked model), tools, and
router failover. Vitest + a smoke Playwright run for the web app. GitHub
Actions CI.

### 10. Documentation

- Repo: README with screenshots; `docs/` for architecture, memory model, mesh,
  API, deployment.
- Master Vault: new `Projects/Aeon-V2/` section (README, Architecture, TODO,
  Sessions, Changelog), `AI/AEON.md` updated to point at V2, UI tokens in
  `UIStandards.md`, chassis/license ADR in `Decisions/`, session log +
  CHANGELOG entry, commit and push.

## Build order

1. **Scaffold + core port** — repo skeleton, port memory engine + LM Studio
   client from aeon-v1, tests green.
2. **Agent loop + tools** — function calling, registry, approval gating,
   streaming API.
3. **Skills + research** — the two headline features.
4. **Mesh** — peer bridge + worker routing.
5. **Web UI** — the polish pass.
6. **Deploy + docs** — systemd on T5810, vault section, repo docs, push.

## Licensing constraint (load-bearing)

Odysseus is AGPL-3.0-or-later. **No code may be copied from it** — only product
and architecture ideas. Hermes Agent is MIT: code may be lifted with attribution
preserved. aeon-v1 is Jesse's own code.
