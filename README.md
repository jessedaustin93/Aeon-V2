# Aeon-V2

Self-hosted, local-first AI workspace: chat, agents with tool calling, deep
research, skills, and persistent memory — served from your own hardware.

- **Server:** Python/FastAPI on a Dell T5810 (GTX 1080 FE) with LM Studio for
  local models. Any OpenAI-compatible endpoint works.
- **Clients:** React PWA — desktop browser, phone, and (later) Android app.
- **Memory:** append-only, human-governed, Obsidian-readable. Lives on the
  server at `AEON_DATA_DIR`, never in this repo.
- **Mesh:** peers with the Agent Mesh hub; can route model calls to other
  machines' LLM endpoints.

## Status

Phase 1 — core engine ported from [aeon-v1](https://github.com/jessedaustin93/aeon-v1)
with the full test suite. See `docs/superpowers/specs/` for the design and
`docs/superpowers/plans/` for the build plans.

## Quick start (server)

    cd server
    python3 -m venv .venv && .venv/bin/pip install -e .[dev]
    export AEON_DATA_DIR=~/aeon-data
    .venv/bin/aeon-init-data
    .venv/bin/pytest -q

## Lineage

Product shape inspired by [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus)
(ideas only — no AGPL code). Agent internals inspired by / adapted from
[Hermes Agent](https://github.com/NousResearch/hermes-agent) (MIT). Core memory
engine is [aeon-v1](https://github.com/jessedaustin93/aeon-v1) (MIT).

## License

MIT
