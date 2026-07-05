# Memory model

Aeon-V2 has two distinct memory surfaces. Keeping them separate is a hard rule.

## 1. Aeon's own memory — local, primary, private

Lives at `AEON_DATA_DIR` (`/home/t5810/aeon-data` in production). This is the
aeon-v1 engine, ported unchanged into `aeon.core`:

```
aeon-data/
├── memory/
│   ├── raw/            append-only, verbatim, never modified after write
│   ├── episodic/       promoted from raw when important
│   ├── semantic/       concept-level knowledge
│   ├── reflections/    Aeon's own consolidated insights
│   ├── consolidations/ merged/aged memory
│   ├── logs/           sessions, tool journal
│   └── staging/        approvals, pending writes
├── vault/              Obsidian-readable mirror of the above
├── skills/             approved skills + _proposals/
└── research/           saved reports
```

Governance carried over from aeon-v1: **raw memory is append-only and sacred**,
a write guard gates all writes, and `vault/core/` is protected from automatic
modification. The `memory_save` tool goes through this same guard.

## 2. Master Vault — shared, read-only context

The cross-assistant vault (`~/Master-Vault`) is shared by Claude Code, Codex,
ChatGPT, and Aeon. Aeon treats it as **read-only context**, reached through the
`vault_search` / `vault_read` tools. Retrieved notes keep their source and are
**never** auto-imported, mirrored, reflected, or aged into Aeon's local memory.

Writes to the Master Vault are explicit human-driven promotions (a handoff, an
accepted decision, a durable fact), never automatic memory writes. This is the
boundary set in the vault's `Decisions/2026-06-29-aeon-master-vault-boundary.md`.

## Why the split

Aeon experiences and generates a lot (chats, tool runs, reflections). All of that
belongs in its own local store, which can grow freely. The Master Vault stays
small, curated, and shared — it is the operating manual, not a second Aeon brain.
