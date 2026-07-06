# Aeon Capability Pack 1 — Design

- **Date:** 2026-07-06
- **Status:** Approved by Jesse
- **North star:** Aeon does the heavy, routine work on local models; Claude Code
  and Codex act as admins/escalation over the mesh; Jesse's paid cloud usage is
  spent on oversight, not grind. These tools are Aeon's *hands* — the local
  equivalents of what a cloud AI can do — and the foundation the later autonomy
  (sub-agents, plan→execute, admin escalation) builds on.

## Scope

Five GPU-independent tools/CLIs, each following the existing `aeon.tools` pattern
(`DEFINITIONS` + `HANDLERS`, per-tool `approval_required`). Register in
`aeon/tools/__init__.py`.

**Deferred (own passes):** all image generation (SVG/blueprint/raster) — held
until the P104-100 8GB is installed, then SD is pinned to that card via
`CUDA_VISIBLE_DEVICES` while LM Studio keeps the 1080. Also deferred: bounded
sub-agent spawning, autonomous crypto trading.

## Components

### 1. Skill CLI (`aeon/cli.py`)
- `aeon-lint-skills`: scan `<data>/skills` (active + `_proposals`), parse each
  `SKILL.md`, print each as OK or the specific defect (no frontmatter, missing
  `name`/`description`, bad name per `^[a-z0-9][a-z0-9-]{0,63}$`, dir name ≠
  frontmatter name). Exit 1 if any invalid — hand-authoring fails silently today,
  so this is the missing feedback loop.
- `aeon-add-skill --name N --description D (--body B | --body-file F) [--proposal]
  [--force]`: validate, scaffold a well-formed skill dir (active, or under
  `_proposals/` with `--proposal`), print the path. Refuse overwrite without
  `--force`.

### 2. Crypto prices (`aeon/tools/crypto.py`)
- `crypto_price(symbol)` → `{symbol, price, change_24h, high_24h, low_24h}`.
- `crypto_market(symbol)` → adds `bid, ask, volume_24h`.
- Source: Crypto.com public REST `https://api.crypto.com/exchange/v1/public/
  get-tickers?instrument_name=<INSTR>`. No API key (public market data).
- Symbol normalization: `BTC` → `BTC_USD`; pass through anything containing `_`.
- Injectable `_http_get`; only the crypto.com host is contacted.
- `approval_required=False` (read-only public data). Foundation for later trading.

### 3. Safe CLI (`aeon/tools/safecli.py`)
- `safe_shell(command)` → `{command, exit_code, stdout, stderr}`.
- **Read-only allowlist, subcommand-aware.** Whole-command allowed:
  `df free uptime uname ps ip ss lsblk whoami hostname date nvidia-smi sensors
  journalctl`. Subcommand-restricted:
  `systemctl {status,is-active,is-enabled,list-units,list-unit-files,show}`,
  `docker {ps,images,stats,logs,inspect,version,info}`,
  `git {status,log,diff,show,branch}`.
- **Refuses any command containing a shell metacharacter** (`; | & > < ` $ ( ) `
  newline`), so it can't chain into something off-list. Parsed with `shlex`,
  run without `shell=True`, 30s timeout, output capped at 20 KB.
- Non-allowlisted command → error dict pointing at `shell_run` (the gated tool).
- `approval_required=False` (cannot mutate state).

### 4. Service control (`aeon/tools/services.py`)
- `service_status(service)` → active state + recent status lines
  (`systemctl --user status/is-active`). `approval_required=False`.
- `service_control(action, service)`, action ∈ `{start,stop,restart}`
  (`systemctl --user <action> <service>`). `approval_required=True` — routes
  through the existing approval broker, same as `shell_run`.
- Service name validated against `^[A-Za-z0-9@._-]+$`. Scope: `--user` units on
  the T5810 (no sudo). Cross-machine control is deferred (needs the mesh executor).

### 5. Plan generation (`aeon/tools/planning.py`)
- `generate_plan(goal)` → `{goal, title, steps:[{step, detail}], risks:[...]}`,
  saved to `<data>/plans/<id>.json` and summarized into memory.
- Robust delimiter format (`TITLE:` / numbered `STEPS:` / `RISKS:` lines), not
  JSON-with-multiline — same lesson as the skill forge. `approval_required=False`.

## Testing

Pytest per tool with injected HTTP/subprocess (no real network or side effects):
allowlist enforcement + metacharacter rejection, subcommand gating, crypto symbol
normalization + parse, service-name validation + control gating, plan parse +
save, and CLI lint/add happy + failure paths. Then a live smoke on the T5810.

## Deferred follow-ons (noted, not built here)

- **Image gen** (next, on card arrival): `aeon/tools/graphics.py` with
  `generate_svg`/`generate_diagram` (LLM-written SVG, no GPU) and a raster
  backend calling a local SD server pinned to the P104-100.
- **Bounded sub-agent spawning** — depth/concurrency guardrails, own design.
- **Autonomous trading** — exchange keys, order execution, hard risk limits.
