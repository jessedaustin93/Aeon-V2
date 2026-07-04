# Aeon-V2 Phase 3: Skills Engine + Deep Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hermes-style human-gated skills (agentskills.io markdown format) loaded into the agent loop, plus a deep-research pipeline that produces cited markdown reports.

**Architecture:** `aeon.skills` reads/writes skill directories under `<data>/skills/`; approved skills are injected into the agent system prompt and a `skill_use` tool exposes their bodies on demand. Skill *proposals* (drafted by the model from a finished session) land in `<data>/skills/_proposals/` and require explicit approval via API. `aeon.research` runs plan→search→read→synthesize using the `deep` model role and the existing `web_search`/`web_fetch` handlers; reports are saved to `<data>/research/` and ingested into memory.

**Tech Stack:** unchanged (stdlib + FastAPI).

## Global Constraints

- Skill format: agentskills.io — a directory per skill with `SKILL.md` starting with YAML frontmatter (`name`, `description`); body is markdown instructions.
- Proposals never auto-activate; approval moves them from `_proposals/` into `skills/`.
- Research must record source URLs and include them in the report.
- Model access only via `ModelRouter.resolve`; tools only via existing handlers.
- Commit after every task; suite green.

---

### Task 1: `aeon.skills.store` — load/save/propose/approve

**Interfaces:**
- `Skill` dataclass: `name, description, body, path`
- `SkillStore(config)`:
  - `.list_active() -> list[Skill]` — valid skill dirs under `<data>/skills/` (skip `_proposals`)
  - `.list_proposals() -> list[Skill]`
  - `.get(name) -> Skill | None`
  - `.propose(name, description, body) -> Skill` — writes `<data>/skills/_proposals/<name>/SKILL.md`
  - `.approve(name) -> Skill` — moves proposal dir into active; `KeyError` if missing; refuses overwrite of an active skill unless `overwrite=True`
  - `.reject(name) -> None` — deletes proposal dir
  - parse/serialize YAML frontmatter with a small regex parser (no pyyaml dep; only flat `key: value` pairs needed)
- Tests: round-trip, malformed frontmatter skipped, approve/reject flows.

### Task 2: skills in the agent loop

- `SkillStore.prompt_block(skills) -> str` — "Available skills" list (name + description) appended to the system prompt.
- New tool `skill_use(name)` (approval_required=False) in `aeon/tools/skills.py` returning the skill body — the model pulls full instructions only when needed (keeps prompts small).
- `AgentLoop.__init__` gains `skill_store` and injects the block into SYSTEM_PROMPT at run() time.
- Tests: prompt contains active skill names; `skill_use` returns body; unknown skill → error dict.

### Task 3: skill proposal from a session

- `aeon.skills.learn.propose_from_transcript(messages, config, router) -> Skill | None` — asks the `chat` role model to distill a reusable skill (name/description/body) from a session transcript; returns the created proposal (or None if the model declines with `NO_SKILL`).
- API: `POST /api/skills/propose {session_id}`; `GET /api/skills` (active + proposals); `POST /api/skills/{name}/approve`; `POST /api/skills/{name}/reject`.
- Tests: fake client returns a canned skill → proposal file exists; NO_SKILL → 200 with `{"skill": null}`; approve/reject endpoints.

### Task 4: `aeon.research.pipeline` — deep research

**Interfaces:**
- `ResearchRun` dataclass: `id, question, status, report_path, sources: list[dict], created_at`
- `run_research(question, config, router, max_sources=6, max_rounds=2) -> Iterator[AgentEvent]` reusing `AgentEvent` kinds (`text` for progress notes, `done` with report path):
  1. `deep` model plans 2-4 search queries (JSON list; on parse failure fall back to the raw question)
  2. `web_search` each query; dedupe URLs; `web_fetch` top results (per-source failures recorded and skipped)
  3. `deep` model writes the report from fetched excerpts: markdown with `## Sources` section listing every used URL
  4. save to `<data>/research/<id>-<slug>.md`; ingest a summary into memory (`source="research"`)
- API: `POST /api/research {question}` → SSE stream; `GET /api/research` → list of saved reports; `GET /api/research/{id}` → report content.
- Tests: fake router/client with scripted plan + report, monkeypatched web handlers → report file exists with sources; fetch failure skipped; API endpoints with fake pipeline.

### Task 5: full suite + push + CI
