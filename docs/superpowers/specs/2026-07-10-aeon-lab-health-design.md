# Aeon `lab_health`: grounded, live world-view

- **Date:** 2026-07-10
- **Status:** Approved design (pending spec review)
- **Author:** Jesse + Claude

## Problem

Aeon's health/status answers hallucinate. In one "lab health overview" it invented
a machine (`t4400s`), claimed **5** model workers when there is **1**, and put the
Aeon agent on the wrong host — even though `mesh_map` exists and the system prompt
already tells Aeon to use it and "never invent tool output."

Root cause: the local model (`ornith-1.0` via LM Studio, a ~9B model) embellishes
correct tool JSON while composing prose. Prompting alone cannot reliably stop a
small model from fabricating entities and numbers.

## Goal

Aeon reports the **actual** state of the lab — which machines are connected/active
and what programs/processes are running — by observing live data and presenting a
**deterministically-formatted** report it cannot embellish. Confirm Aeon also
references the shared Master Vault.

## Non-goals

- No model change (`ornith-1.0` via LM Studio stays).
- No SSH into **hp** (standalone use box, vaultwarden only) or **x1** (off unless
  in use) — both are shown as online/offline only, from the hub.
- Not replacing `mesh_map`; adding a focused, deterministic tool.

## Design

### New tool: `lab_health`

- Read-only, **non-gated** (like `service_status`) — it runs only fixed, read-only
  commands, so it needs no per-call approval.
- Returns `{ "report": <markdown string>, "data": <structured dict> }`.
- Parameter: `include_processes: bool = true`.

### Data sources

1. **Grid kernel hub** (`http://127.0.0.1:8787`, already local; existing MeshClient
   + `AEON_MESH_TOKEN`):
   - `/api/agents` → machines, agents, `last_seen`.
   - `/api/telemetry` → host metrics + per-service liveness records.
   - `/api/kernel/programs` → registered programs per host.
2. **Live OS probe** — only for hosts that are **online AND SSH-reachable**
   (`t5810` local, `t3610`, `t5810b`). Fixed, read-only command per host with a
   short per-host timeout (~8s), `ssh -o BatchMode=yes -o ConnectTimeout=5`:
   - `systemctl --user list-units --type=service --state=running --no-legend`
     (aeon/grid units), plus a bounded `ps` snapshot (top by CPU/mem, capped rows).
   - `t5810` is probed locally (no SSH).

### Online/offline

A machine is **online** if any of its agents' `last_seen` is within a freshness
window (default 120s); otherwise **offline**. Computed from data, never guessed.

### Host coverage

| Host | Status | Programs | Live processes |
|------|--------|----------|----------------|
| t5810 (local) | ✅ | ✅ | ✅ (local) |
| t3610 | ✅ | ✅ | ✅ (ssh) |
| t5810b | ✅ | ✅ | ✅ (ssh) |
| hp | ✅ online/offline only | — | — |
| x1 | ✅ online/offline only | — | — |

Unreachable/timed-out hosts degrade gracefully: shown with status +
`processes: unavailable (unreachable)`. Never hang, never fabricate.

### Deterministic output

The markdown `report` is assembled entirely in code:
- Header line with **computed** counts (machines online/total, agents active,
  programs running).
- One section per machine: name, online/offline, agents, running grid/aeon
  services, and (for probed hosts) top processes.
- Contains no machine, agent, or number not present in the source data.

`data` mirrors the report as a structured dict for programmatic callers.

### Prompt reinforcement (`loop.py` `SYSTEM_PROMPT`)

Add: for lab/machine/health/process/status questions, call `lab_health` and present
its `report` field directly; do not add, rename, or re-count machines, agents,
programs, or processes beyond the tool output. Keep existing `mesh_map` guidance.

### Master Vault

`AEON_V1_MASTER_VAULT_PATH` is already set to `/home/t5810/Master-Vault` and enabled.
Verify `vault_search` returns real hits end-to-end, and add a prompt nudge to consult
`vault_search`/`vault_read` for "how is X set up / documented" questions. No new tool.

## Error handling

- Hub unreachable → report notes the grid hub is unavailable but still shows
  Aeon-local health (model workers, version).
- Per-host SSH timeout/unreachable → that host degrades; others unaffected.
- All probes bounded by timeouts; total tool runtime capped.

## Testing

- **Unit:** format function over fixed fixture data → exact expected markdown; a
  fabricated name never appears (regression guard for the `t4400s` class of bug).
- **Unit:** online/offline freshness boundary (just inside / just outside window).
- **Unit:** unreachable host → graceful "unavailable", no exception.
- **Integration (T5810):** call `lab_health` live; assert only real machines
  (`t5810/t3610/t5810b/hp/x1`) appear and live processes are present for reachable
  hosts.
- **Vault:** `vault_search` returns ≥1 hit for a known term.
- Full `server-tests` suite green before push.

## Out of scope / future

- SSH into **hp** (revisit when it's integrated off the standalone setup).
- Mesh-native process dispatch (asking each peer to self-report) instead of direct
  SSH, if SSH coverage becomes a maintenance burden.
