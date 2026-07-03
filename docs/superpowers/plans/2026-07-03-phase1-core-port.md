# Aeon-V2 Phase 1: Scaffold + Core Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Aeon-V2 repo skeleton and port aeon-v1's entire core package (memory engine, governance, LM Studio client) into `server/src/aeon/core/` with all existing tests green.

**Architecture:** aeon-v1 (`~/aeon-v1`, package `aeon_v1`, zero runtime dependencies, 34 pytest files) is copied wholesale into the new `aeon.core` subpackage. Internal relative imports (`from .config import Config`) survive the move unchanged; only absolute references and test imports need rewriting. A new `AEON_DATA_DIR` env var points the engine at its data root (`/home/t5810/aeon-data` in production), replacing aeon-v1's cwd-relative default.

**Tech Stack:** Python ≥3.11, setuptools, pytest, GitHub Actions. No runtime dependencies in Phase 1 (FastAPI arrives in Phase 2).

## Global Constraints

- License: MIT (aeon-v1 is Jesse's MIT code; NO code from Odysseus — it is AGPL-3.0).
- Python floor: `requires-python = ">=3.11"`.
- Zero runtime dependencies in Phase 1; dev deps: `pytest>=7.4`, `tzdata>=2024.1`.
- Package name: `aeon`; core subpackage: `aeon.core`; src layout under `server/`.
- Memory data lives OUTSIDE the repo, at the path given by `AEON_DATA_DIR`.
- Existing env vars keep the `AEON_V1_` prefix in Phase 1 (renaming is out of scope; the T5810 `.env` keeps working).
- Source of the port: `/home/jesse/aeon-v1` (do not modify that repo).
- All work in `/home/jesse/Aeon-V2` on branch `main`; commit after every task.

---

### Task 1: Repo scaffold + CI

**Files:**
- Create: `server/pyproject.toml`
- Create: `.gitignore`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: installable empty package `aeon` (`pip install -e server/[dev]`), CI that runs `pytest` in `server/`.

- [ ] **Step 1: Write `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.env
.pytest_cache/
dist/
build/
node_modules/
web/dist/
```

- [ ] **Step 2: Write `server/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "aeon"
version = "2.0.0a1"
description = "Aeon-V2 — self-hosted local-first AI workspace"
readme = "../README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
keywords = ["memory", "AI", "agents", "local-first", "obsidian"]
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=7.4", "tzdata>=2024.1"]
hardware = ["pyserial>=3.5"]

[project.scripts]
aeon-init-data = "aeon.cli:init_data"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Create the package root**

```bash
mkdir -p ~/Aeon-V2/server/src/aeon ~/Aeon-V2/server/tests
printf '"""Aeon-V2."""\n\n__version__ = "2.0.0a1"\n' > ~/Aeon-V2/server/src/aeon/__init__.py
```

- [ ] **Step 4: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  server-tests:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: server
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e .[dev]
      - run: pytest -q
```

- [ ] **Step 5: Verify install + empty test run**

```bash
cd ~/Aeon-V2/server && python3 -m venv .venv && .venv/bin/pip -q install -e .[dev] && .venv/bin/pytest -q
```

Expected: `no tests ran` (exit code 5 is fine at this stage).

- [ ] **Step 6: Commit**

```bash
cd ~/Aeon-V2 && git add -A && git commit -m "chore: scaffold server package and CI"
```

---

### Task 2: Port the aeon-v1 package into `aeon.core`

**Files:**
- Create: `server/src/aeon/core/` (every `.py` from `/home/jesse/aeon-v1/src/aeon_v1/`)

**Interfaces:**
- Consumes: `/home/jesse/aeon-v1/src/aeon_v1/*.py` (read-only source).
- Produces: importable `aeon.core.config.Config`, `aeon.core.memory_store.MemoryStore`, `aeon.core.llm`, etc. — same public names as aeon-v1, new package path.

- [ ] **Step 1: Copy the package**

```bash
mkdir -p ~/Aeon-V2/server/src/aeon/core
cp /home/jesse/aeon-v1/src/aeon_v1/*.py ~/Aeon-V2/server/src/aeon/core/
```

(Only `.py` files — leave `__pycache__` and `README.md` behind.)

- [ ] **Step 2: Rewrite any absolute `aeon_v1` references inside the package**

```bash
cd ~/Aeon-V2/server/src/aeon/core
grep -rln "aeon_v1" . | xargs -r sed -i 's/aeon_v1/aeon.core/g'
grep -rn "aeon_v1" . || echo CLEAN
```

Expected: `CLEAN`. (Relative imports `from .x import y` are untouched and keep working.)

- [ ] **Step 3: Fix the `.env` loader path in `config.py`**

aeon-v1 loads `.env` from "two levels up from this file" — that path is wrong in the new layout. Replace the module-level loader call at the bottom of the `_load_env` section:

```python
# OLD (delete):
# Load .env from project root (two levels up from this file: src/aeon_v1 -> project root)
_load_env(Path(__file__).parent.parent.parent / ".env")

# NEW:
# Load .env from the data root (AEON_DATA_DIR) if set, then from the cwd.
# _load_env never overwrites vars that are already set.
_data_root = os.environ.get("AEON_DATA_DIR", "").strip()
if _data_root:
    _load_env(Path(_data_root).expanduser() / ".env")
_load_env(Path.cwd() / ".env")
```

- [ ] **Step 4: Verify the package imports**

```bash
cd ~/Aeon-V2/server && .venv/bin/python -c "from aeon.core.config import Config; from aeon.core.memory_store import MemoryStore; import aeon.core.llm; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd ~/Aeon-V2 && git add -A && git commit -m "feat: port aeon-v1 core package to aeon.core"
```

---

### Task 3: Port the test suite

**Files:**
- Create: `server/tests/` (all `test_*.py` + `conftest.py` from `/home/jesse/aeon-v1/tests/`)

**Interfaces:**
- Consumes: `aeon.core.*` modules from Task 2.
- Produces: green pytest suite — the regression net for every later phase.

- [ ] **Step 1: Copy tests and rewrite imports**

```bash
cp /home/jesse/aeon-v1/tests/conftest.py /home/jesse/aeon-v1/tests/test_*.py ~/Aeon-V2/server/tests/
cd ~/Aeon-V2/server/tests && sed -i 's/aeon_v1/aeon.core/g' conftest.py test_*.py
grep -rn "aeon_v1" . || echo CLEAN
```

Expected: `CLEAN`

- [ ] **Step 2: Run the suite**

```bash
cd ~/Aeon-V2/server && .venv/bin/pytest -q 2>&1 | tail -5
```

Expected: all tests pass (aeon-v1's suite is green upstream). If any test fails on path assumptions (e.g., it resolves the repo root or `scripts/` dir), fix the test's path constant to the new layout — do NOT change `aeon.core` behavior to accommodate a test path.

- [ ] **Step 3: Commit**

```bash
cd ~/Aeon-V2 && git add -A && git commit -m "test: port aeon-v1 suite against aeon.core"
```

---

### Task 4: `AEON_DATA_DIR` data root + `aeon-init-data` CLI

**Files:**
- Modify: `server/src/aeon/core/config.py` (the `Config.__init__` signature)
- Create: `server/src/aeon/cli.py`
- Test: `server/tests/test_data_root.py`

**Interfaces:**
- Consumes: `aeon.core.config.Config`.
- Produces: `Config()` with no args resolves `base_path` from `AEON_DATA_DIR`; `init_data(argv: list[str] | None = None) -> int` console entry point that scaffolds the data tree.

- [ ] **Step 1: Write the failing tests**

`server/tests/test_data_root.py`:

```python
from pathlib import Path

from aeon.core.config import Config
from aeon.cli import init_data, MEMORY_SUBDIRS


def test_config_uses_aeon_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path / "data"))
    cfg = Config()
    assert cfg.base_path == tmp_path / "data"
    assert cfg.memory_path == tmp_path / "data" / "memory"
    assert cfg.vault_path == tmp_path / "data" / "vault"


def test_config_explicit_base_path_beats_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path / "env-root"))
    cfg = Config(base_path=tmp_path / "explicit")
    assert cfg.base_path == tmp_path / "explicit"


def test_config_default_without_env(monkeypatch):
    monkeypatch.delenv("AEON_DATA_DIR", raising=False)
    cfg = Config()
    assert cfg.base_path == Path(".")


def test_init_data_scaffolds_tree(monkeypatch, tmp_path):
    root = tmp_path / "aeon-data"
    monkeypatch.setenv("AEON_DATA_DIR", str(root))
    rc = init_data([])
    assert rc == 0
    for sub in MEMORY_SUBDIRS:
        assert (root / "memory" / sub).is_dir(), sub
    assert (root / "vault").is_dir()
    assert (root / "skills").is_dir()


def test_init_data_is_idempotent(monkeypatch, tmp_path):
    root = tmp_path / "aeon-data"
    monkeypatch.setenv("AEON_DATA_DIR", str(root))
    assert init_data([]) == 0
    assert init_data([]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/Aeon-V2/server && .venv/bin/pytest tests/test_data_root.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'aeon.cli'`.

- [ ] **Step 3: Change `Config.__init__` in `server/src/aeon/core/config.py`**

```python
# OLD:
#    def __init__(self, base_path: Path = Path(".")):
#        self.base_path = Path(base_path)

# NEW:
    def __init__(self, base_path: Path | None = None):
        if base_path is None:
            env_root = os.environ.get("AEON_DATA_DIR", "").strip()
            base_path = Path(env_root).expanduser() if env_root else Path(".")
        self.base_path = Path(base_path)
```

- [ ] **Step 4: Write `server/src/aeon/cli.py`**

```python
"""Aeon-V2 command-line entry points."""
import argparse
from pathlib import Path

from .core.config import Config

# Mirrors aeon-v1's memory/ layout (see aeon-v1/memory/README.md).
MEMORY_SUBDIRS = [
    "raw",
    "episodic",
    "semantic",
    "reflections",
    "consolidations",
    "media/uploads",
    "logs",
    "staging",
    "approved",
    "schemas",
    "tool_additions",
]

TOP_LEVEL_DIRS = ["vault", "skills", "research"]


def init_data(argv: list[str] | None = None) -> int:
    """Scaffold the Aeon data root (memory tree, vault mirror, skills, research)."""
    parser = argparse.ArgumentParser(
        prog="aeon-init-data",
        description="Create the Aeon-V2 data directory tree at AEON_DATA_DIR (or --root).",
    )
    parser.add_argument("--root", type=Path, default=None, help="Override AEON_DATA_DIR")
    args = parser.parse_args(argv)

    config = Config(base_path=args.root) if args.root else Config()
    root = config.base_path
    for sub in MEMORY_SUBDIRS:
        (root / "memory" / sub).mkdir(parents=True, exist_ok=True)
    for top in TOP_LEVEL_DIRS:
        (root / top).mkdir(parents=True, exist_ok=True)
    print(f"Aeon data root ready: {root.resolve()}")
    return 0
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd ~/Aeon-V2/server && .venv/bin/pytest tests/test_data_root.py -q
```

Expected: `5 passed`

- [ ] **Step 6: Run the FULL suite (the Config default change touches everything)**

```bash
cd ~/Aeon-V2/server && .venv/bin/pytest -q 2>&1 | tail -3
```

Expected: all pass. If a ported test breaks because it relied on `Config()` defaulting to `Path(".")` while `AEON_DATA_DIR` leaks from the environment, the fix is `monkeypatch.delenv("AEON_DATA_DIR", raising=False)` in that test or `conftest.py` — not a behavior change.

- [ ] **Step 7: Commit**

```bash
cd ~/Aeon-V2 && git add -A && git commit -m "feat: AEON_DATA_DIR data root and aeon-init-data CLI"
```

---

### Task 5: README + push + CI green

**Files:**
- Create: `README.md`

**Interfaces:**
- Produces: public repo front page; CI badge target.

- [ ] **Step 1: Write `README.md`**

```markdown
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
```

- [ ] **Step 2: Commit and push**

```bash
cd ~/Aeon-V2 && git add -A && git commit -m "docs: README" && git push
```

- [ ] **Step 3: Watch CI**

```bash
cd ~/Aeon-V2 && gh run watch --exit-status $(gh run list --limit 1 --json databaseId -q '.[0].databaseId')
```

Expected: CI passes. If it fails, read the log (`gh run view --log-failed`), fix, commit, push, re-watch.
