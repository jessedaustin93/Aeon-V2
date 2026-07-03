---
id: core-protected-notice
title: core-memory-protection-notice
type: core
created: 2024-01-01T00:00:00
source: human
importance: 1.0
tags:
  - core
  - protection
  - safety
links: []
---

# Core Memory — Protected Zone

> **No automated process may create, edit, or delete files in this directory.**

This `vault/core/` directory is the **long-term stable memory** of the system.  
It holds identity, rules, goals, and preferences that have been explicitly approved by a human.

---

## Protection Rules

| Actor | Allowed? |
|---|---|
| Human (manual edit) | **Yes** |
| `ingest()` | **No** |
| `reflect()` | **No** — may only write *suggestions* inside a reflection note |
| Any automated script | **No** — not without explicit human override |

---

## How Core Memory Gets Updated

1. Run `python scripts/run_reflection.py`
2. Open the new reflection note in `vault/reflections/`
3. Read the **Suggested Core Memory Updates** section
4. Decide manually which suggestions (if any) to accept
5. Create or edit files in this directory yourself

The reflection engine never writes here automatically.  
Suggestions are written in reflection notes only, and they require human review before becoming core memory.

---

## Files in This Directory

| File | Purpose |
|---|---|
| `identity.md` | Stable identity, core principles, and design philosophy |
| `PROTECTED.md` | This notice |
| `goals.md` | Long-term goals (create manually when ready) |
| `rules.md` | Behavioral rules and constraints (create manually when ready) |
| `concepts.md` | Curated reusable concepts promoted from semantic memory |

---

## Why This Matters

Core memory corruption — even accidental — cannot be undone without checking git history.  
By keeping it human-gated, the system remains under full human control at the highest level of abstraction.

[[Core Memory]] | [[index]] | [[Reflections]]
