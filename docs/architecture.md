# Aeon-V2 Architecture

Aeon-V2 is a self-hosted AI workspace that runs on Jesse's own hardware. One
server (the Dell T5810, GTX 1080 FE) holds the brain and memory; every other
device is a browser client.

```
┌────────────────────────────────────────────────────────────┐
│  Clients:  laptop browser · phone (PWA) · other machines    │
└───────────────────────────────┬────────────────────────────┘
                                 │  HTTPS over tailnet, Bearer token
┌───────────────────────────────▼────────────────────────────┐
│  T5810  ── Aeon-V2 server (FastAPI, aeon-server) ──         │
│                                                             │
│   api/        REST + SSE, token auth, serves the web app    │
│   agent/      agent loop · approvals · tool journal         │
│   tools/      fs · shell · web · memory · vault · mesh · …   │
│   models/     ChatClient + ModelRouter (roles, workers)     │
│   skills/     agentskills.io skills + learning loop         │
│   research/   deep-research pipeline                         │
│   mesh/       native Agent Mesh peer + worker discovery      │
│   core/       aeon-v1 memory engine (append-only, governed) │
│                                                             │
│   LM Studio (localhost:1234)  ── GTX 1080 FE                 │
│   AEON_DATA_DIR=/home/t5810/aeon-data  ── Aeon's memory      │
└───────────────────────────────┬────────────────────────────┘
                                 │  optional: extra LLM workers
              ┌──────────────────┼───────────────────┐
              ▼                  ▼                   ▼
          t3610 LM Studio    t5810b LM Studio     Agent Mesh hub
```

## Layers

**Model layer (`aeon.models`).** `ChatClient` speaks the OpenAI-compatible API
(streaming + tool calls) over stdlib HTTP. `ModelRouter` maps roles
(`chat`/`deep`/`embed`) to models and picks the highest-priority healthy worker
that serves the model. Extra machines running LM Studio are registered as
workers (via `models.json` or `AEON_MESH_LLM_WORKERS`) and used automatically —
this is the "more machines = more LLM power" path.

**Agent layer (`aeon.agent`).** The loop streams model output, executes tool
calls, feeds results back, and repeats until the model stops calling tools.
`approval_required` tools block on the `ApprovalBroker` until a human approves
in the UI. Every execution is journaled.

**Tools (`aeon.tools`).** `fs_read`/`fs_list` (scoped), `shell_run` (gated),
`web_fetch`/`web_search`, `memory_search`/`memory_save`, `vault_search`/
`vault_read` (read-only), `skill_use`, `mesh_post` (gated). Outward-facing or
destructive tools require approval.

**Memory (`aeon.core`).** The aeon-v1 engine, unchanged: append-only raw memory,
episodic/semantic/reflection/consolidation layers, write guard, protected core,
Obsidian-readable mirror. Lives at `AEON_DATA_DIR` on the T5810 — never in this
repo, never in the Master Vault.

**Skills (`aeon.skills`).** Reusable procedures in the agentskills.io markdown
format. Aeon proposes a skill from a finished session; a human approves it before
it loads. Active skills are advertised in the system prompt; the model pulls full
instructions with `skill_use`.

**Research (`aeon.research`).** Plan queries → search → read sources → write a
cited markdown report, using the `deep` role.

**Mesh (`aeon.mesh`).** Aeon registers as a native Agent Mesh peer, replacing the
old PTY bridge. It answers addressed messages by running its own loop (tools
disabled by default — remote input is untrusted and the peer is headless).

## Two memories, one boundary

- **Aeon's memory** (`AEON_DATA_DIR`, local to the T5810) is primary and private.
- **Master Vault** is read-only shared context across all of Jesse's assistants.
  Aeon reads it via `vault_*` tools; writes are explicit, never automatic.

See [memory-model.md](memory-model.md) and the ADR in the Master Vault.
