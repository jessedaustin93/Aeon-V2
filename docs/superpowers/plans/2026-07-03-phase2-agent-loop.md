# Aeon-V2 Phase 2: Agent Loop + Tool Calling + API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working agent: OpenAI-compatible streaming client → model router → tool-calling agent loop with approval gating → built-in tools → FastAPI streaming API with token auth.

**Architecture:** New subpackages `aeon.models` (client + router), `aeon.agent` (executor, approvals, loop), `aeon.tools` (handlers), `aeon.api` (FastAPI). Reuses `aeon.core.tools.ToolRegistry/ToolDefinition` (definitions), `aeon.core.tool_calls.ToolCallStore` (journaling), `aeon.core.memory_store.MemoryStore` and `aeon.core.shared_vault` (tool backends). The client uses stdlib urllib (matches core style); FastAPI/uvicorn are the only new deps.

**Tech Stack:** Python ≥3.11, FastAPI, uvicorn, sse-starlette-free (plain StreamingResponse), pytest.

## Global Constraints

- New deps allowed: `fastapi>=0.110`, `uvicorn>=0.29` only. Client/tools stay stdlib.
- All new code in `server/src/aeon/{models,agent,tools,api}/`; do not modify `aeon.core` behavior except where a task explicitly says so.
- Every tool execution is journaled through `ToolCallStore`.
- Tools with `approval_required=True` never execute without an approval decision.
- Env: `AEON_LLM_BASE_URL` (default `http://localhost:1234/v1`), `AEON_LLM_CHAT_MODEL`, `AEON_LLM_DEEP_MODEL`, `AEON_LLM_EMBED_MODEL`, `AEON_API_TOKEN`. Fall back to the v1 `AEON_V1_LLM_*` vars when the new ones are unset (the T5810 `.env` keeps working).
- Commit after every task; full suite green before each commit.

---

### Task 1: `aeon.models.client` — OpenAI-compatible chat client with streaming + tools

**Files:**
- Create: `server/src/aeon/models/__init__.py`, `server/src/aeon/models/client.py`
- Test: `server/tests/test_models_client.py`

**Interfaces:**
- Produces:
  - `ChatDelta` dataclass: `kind: str` (`"text" | "tool_call" | "finish"`), `text: str = ""`, `tool_calls: list[dict] | None = None`, `finish_reason: str | None = None`
  - `class ChatClient(base_url: str, timeout: float = 120.0)`
  - `ChatClient.chat(model, messages, tools=None, stream=False, temperature=None) -> Iterator[ChatDelta]` — non-stream yields one text delta + finish; stream yields incremental deltas; tool calls aggregated into complete `{"id","type","function":{"name","arguments"}}` dicts on finish.
  - `ChatClient.list_models() -> list[str]`
  - `ChatClient.embed(model, texts: list[str]) -> list[list[float]]`
- Transport function `_post_json(url, payload, timeout, stream=False)` isolated so tests monkeypatch it.

Steps: write failing tests (mock `_post_json` returning canned non-stream JSON, canned SSE lines incl. split tool-call argument chunks), implement, full suite, commit `feat: OpenAI-compatible chat client`.

### Task 2: `aeon.models.router` — roles + worker registry

**Files:**
- Create: `server/src/aeon/models/router.py`
- Test: `server/tests/test_models_router.py`

**Interfaces:**
- Consumes: `ChatClient`.
- Produces:
  - `Worker` dataclass: `name, base_url, models: list[str], priority: int = 0, healthy: bool = True`
  - `class ModelRouter(config: Config)` — loads `<data>/models.json` if present, else builds a single `local` worker from env (`AEON_LLM_BASE_URL` → fallback `AEON_V1_LLM_BASE_URL` → default).
  - `ModelRouter.resolve(role: str) -> tuple[ChatClient, str]` — returns (client, model_name) for `"chat" | "deep" | "embed"`; role→model from env (`AEON_LLM_CHAT_MODEL` etc. → fallback `AEON_V1_LLM_MODEL`/`AEON_V1_LLM_DEEP_MODEL`/`AEON_V1_LLM_EMBEDDING_MODEL`) or `models.json` `roles` map; picks the highest-priority healthy worker serving that model.
  - `ModelRouter.health_check() -> dict[str, bool]` — calls each worker's `list_models`, updates `healthy`.
  - `ModelRouter.workers -> list[Worker]`

`models.json` shape:

```json
{
  "roles": {"chat": "qwen3-4b-instruct-2507", "deep": "qwen3-4b-thinking-2507", "embed": "text-embedding-nomic-embed-text-v1.5"},
  "workers": [{"name": "t5810", "base_url": "http://localhost:1234/v1", "models": ["*"], "priority": 10}]
}
```

`"*"` in `models` means the worker serves any model. Steps: failing tests (env fallback, json load, unhealthy worker skipped, `"*"` wildcard), implement, suite, commit `feat: model router with roles and mesh workers`.

### Task 3: `aeon.agent.approvals` — approval broker

**Files:**
- Create: `server/src/aeon/agent/__init__.py`, `server/src/aeon/agent/approvals.py`
- Test: `server/tests/test_approvals.py`

**Interfaces:**
- Produces:
  - `ApprovalRequest` dataclass: `id, tool, arguments: dict, created_at, status: str` (`"pending"|"approved"|"denied"|"expired"`)
  - `class ApprovalBroker(config: Config, ttl_seconds: float = 300.0)` — persists requests to `<data>/memory/staging/approvals.json`.
  - `.create(tool: str, arguments: dict) -> ApprovalRequest`
  - `.resolve(request_id: str, approved: bool) -> ApprovalRequest` (raises `KeyError` if unknown)
  - `.wait(request_id: str, timeout: float) -> str` — blocks (threading.Event) until resolved/expired; returns final status.
  - `.pending() -> list[ApprovalRequest]`

Steps: failing tests (create→pending, resolve→wait returns, timeout→expired, persistence across broker instances), implement, suite, commit `feat: approval broker`.

### Task 4: `aeon.tools` — built-in tool handlers

**Files:**
- Create: `server/src/aeon/tools/__init__.py`, `fs.py`, `shell.py`, `web.py`, `memory.py`, `vault.py`
- Test: `server/tests/test_v2_tools.py`

**Interfaces:**
- Each module exposes `HANDLERS: dict[str, callable]` and `DEFINITIONS: list[ToolDefinition]` (from `aeon.core.tools`). `aeon.tools.all_handlers(config) -> tuple[dict[str, callable], list[ToolDefinition]]` merges them; handlers take `(arguments: dict, config: Config)` and return a JSON-serializable dict.
- Tools (name → behavior → approval_required):
  - `fs_read(path)` → text (truncated 50KB) → False; `fs_list(path)` → entries → False. Both refuse paths outside `config.base_path` and `AEON_TOOLS_FS_ROOTS` (colon-separated allowlist env).
  - `shell_run(command, cwd=None)` → `{stdout, stderr, exit_code}` via `subprocess.run(timeout=60)` → **True**.
  - `web_fetch(url)` → `{title, text}` (urllib, html tags stripped, 100KB cap) → False; `web_search(query)` → DuckDuckGo HTML results `[{title,url,snippet}]` → False. Network function `_http_get(url)` isolated for test monkeypatching.
  - `memory_search(query, limit=5)` → wraps `aeon.core.search.search` → False; `memory_save(text, source)` → wraps `MemoryStore.ingest` staging path → False (write_guard still applies).
  - `vault_search(query)` / `vault_read(relative_path)` → wraps `aeon.core.shared_vault` read-only Master Vault access → False.

Steps: failing tests per module (fs scope-escape refused; shell marked approval_required; web parses fixture HTML via monkeypatched `_http_get`; memory round-trip against tmp data root; vault read refuses writes/escapes), implement, suite, commit `feat: built-in v2 tool handlers`.

### Task 5: `aeon.agent.loop` — the agent loop

**Files:**
- Create: `server/src/aeon/agent/loop.py`
- Test: `server/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `ModelRouter.resolve`, `ChatClient.chat`, `aeon.tools.all_handlers`, `ApprovalBroker`, `ToolCallStore`.
- Produces:
  - `AgentEvent` dataclass: `kind: str` (`"text" | "tool_call" | "tool_result" | "approval_pending" | "done" | "error"`), `data: dict`
  - `class AgentLoop(config, router, broker, max_iterations: int = 12, approval_timeout: float = 300.0)`
  - `.run(messages: list[dict], role: str = "chat") -> Iterator[AgentEvent]`:
    1. resolve(role) → stream chat with tool definitions (OpenAI function format built from `ToolDefinition.parameters`)
    2. yield `text` events for deltas
    3. on tool calls: for each — if `approval_required`: `broker.create`, yield `approval_pending`, `broker.wait`; denied/expired → tool result `{"error": "denied by user"}`
    4. execute handler (exceptions → `{"error": str(e)}` result, never raised), journal via `ToolCallStore`, yield `tool_result`, append `role:"tool"` message, loop
    5. no tool calls → yield `done`; iteration cap → `error` event `{"error": "max iterations reached"}`.

Steps: failing tests with a scripted fake client (text-only turn; one tool round-trip; approval-gated tool approved and denied; handler exception surfaces as error result; iteration cap), implement, suite, commit `feat: tool-calling agent loop`.

### Task 6: `aeon.api` — FastAPI app

**Files:**
- Create: `server/src/aeon/api/__init__.py`, `server/src/aeon/api/app.py`, `server/src/aeon/api/sessions.py`
- Modify: `server/pyproject.toml` (add fastapi, uvicorn; add script `aeon-server = "aeon.api.app:main"`)
- Test: `server/tests/test_api.py` (fastapi TestClient)

**Interfaces:**
- `sessions.SessionStore(config)` — JSON chat sessions in `<data>/memory/logs/sessions/`: `.create(title) -> dict`, `.get(id)`, `.list()`, `.append(id, message: dict)`.
- `app.create_app(config=None) -> FastAPI`; `main()` runs uvicorn on `AEON_API_HOST`/`AEON_API_PORT` (default `0.0.0.0:8900`).
- Auth: `Authorization: Bearer <AEON_API_TOKEN>` required on `/api/*` when the env var is set; 401 otherwise. If unset, only localhost connections allowed.
- Endpoints:
  - `GET /api/health` → `{status, version, workers: router.health_check()}`
  - `GET /api/models` → roles + workers
  - `GET/POST /api/sessions`, `GET /api/sessions/{id}`
  - `POST /api/chat` `{session_id, message, role?}` → `text/event-stream` of `AgentEvent`s as JSON lines (`data: {...}\n\n`); persists user + assistant messages to the session.
  - `GET /api/approvals` → pending; `POST /api/approvals/{id}` `{approved: bool}`.
- App state holds one `Config`, `ModelRouter`, `ApprovalBroker`, `AgentLoop` (created in `create_app`).

Steps: failing tests (401 without token, health OK with token, sessions CRUD, chat streams events from a monkeypatched fake AgentLoop, approvals resolve), implement, suite, commit `feat: FastAPI streaming API`.

### Task 7: Live smoke against LM Studio (manual gate) + push

- `pytest -q` full suite green.
- If an LM Studio endpoint is reachable (`curl -s $AEON_LLM_BASE_URL/models`), run a scripted `AgentLoop` one-shot to confirm real tool calling; otherwise note it as pending for the T5810 deploy phase.
- Push; CI green (`gh run watch`).
