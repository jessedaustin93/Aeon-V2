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
- **Model awareness:** Aeon can inspect current role→model routing and delegate
  bounded subtasks to configured roles such as `chat` or `deep`.
- **Self-scaffolded tasks:** background Tasks can ask the routed local model to
  draft a task-specific scaffold before Aeon executes it through tools,
  approvals, and logs.

## Status

Feature-complete v2.0-alpha: streaming chat with tool calling, human-gated
approvals, self-scaffolded background Tasks, skills + learning loop, deep
research, Agent Mesh peer + multi-machine LLM routing, and the "Signals Console"
web UI (PWA). 820+ server tests.

- Design & plans: `docs/superpowers/specs/` and `docs/superpowers/plans/`
- Architecture: [`docs/architecture.md`](docs/architecture.md)
- Deploy: [`docs/deployment.md`](docs/deployment.md)
- API: [`docs/api.md`](docs/api.md)
- Memory model: [`docs/memory-model.md`](docs/memory-model.md)

## Quick start

Full T5810 setup: [`docs/deployment.md`](docs/deployment.md), or `./deploy/install.sh`.

Server only:

    cd server
    python3 -m venv .venv && .venv/bin/pip install -e .[dev]
    export AEON_DATA_DIR=~/aeon-data
    .venv/bin/aeon-init-data
    .venv/bin/aeon-seed-runtime-skills
    .venv/bin/pytest -q
    .venv/bin/aeon-server        # API + web on :8900

Web dev server (proxies /api to :8900):

    cd web && npm install && npm run dev

## Lineage

Product shape inspired by [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus)
(ideas only — no AGPL code). Agent internals inspired by / adapted from
[Hermes Agent](https://github.com/NousResearch/hermes-agent) (MIT). Core memory
engine is [aeon-v1](https://github.com/jessedaustin93/aeon-v1) (MIT).

## License

MIT
