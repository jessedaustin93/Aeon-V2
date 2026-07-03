"""Integration foundation tests for Aeon-V1.

Verifies:
- Obsidian vault structural requirements (index.md, all layer dirs, wikilinks)
- MemPalace-style append-only raw memory guarantees
- Complete pipeline: raw → episodic → semantic → reflection → tasks → decision → simulation
- Core memory protection throughout
- LLM swap-point markers exist in source
"""
import ast
import json
from pathlib import Path

import pytest

from aeon.core import (
    Config,
    MemoryStore,
    SimulationStore,
    TaskStore,
    ingest,
    reflect,
    select_next_task,
    simulate_action,
)
from aeon.core.exceptions import CoreMemoryProtectedError
from aeon.core.memory_store import _write_markdown as _mem_write_markdown


REPO_ROOT = Path(__file__).parent.parent
VAULT_DIR = REPO_ROOT / "vault"
SRC_DIR   = REPO_ROOT / "src" / "aeon" / "core"


# ---------------------------------------------------------------------------
# Obsidian vault structure
# ---------------------------------------------------------------------------

def test_vault_index_exists():
    assert (VAULT_DIR / "index.md").exists(), "vault/index.md is missing"


def test_vault_index_links_all_layers():
    content = (VAULT_DIR / "index.md").read_text(encoding="utf-8")
    required_links = [
        "[[Raw Memory]]",
        "[[Episodic Memory]]",
        "[[Semantic Memory]]",
        "[[Reflections]]",
        "[[Tasks]]",
        "[[Decisions]]",
        "[[Simulations]]",
        "[[Core Memory]]",
    ]
    missing = [lnk for lnk in required_links if lnk not in content]
    assert missing == [], f"vault/index.md missing wikilinks: {missing}"


def test_vault_layer_directories_exist():
    """All memory-layer subdirectories must exist under vault/."""
    required_dirs = [
        "raw", "episodic", "semantic", "reflections",
        "tasks", "decisions", "simulations", "core", "agents",
    ]
    missing = [d for d in required_dirs if not (VAULT_DIR / d).is_dir()]
    assert missing == [], f"vault/ is missing directories: {missing}"


def test_vault_index_has_memory_flow():
    """vault/index.md should explain the memory flow (raw → episodic chain)."""
    content = (VAULT_DIR / "index.md").read_text(encoding="utf-8")
    assert "Raw" in content and "Episodic" in content and "Reflection" in content
    assert "Simulation" in content


# ---------------------------------------------------------------------------
# MemPalace-style raw memory guarantees
# ---------------------------------------------------------------------------

def test_raw_memory_is_immutable_after_ingest(tmp_path):
    """Raw memories must never be modified after creation."""
    config = _tmp_config(tmp_path)
    result = ingest("Hello, world — raw memory capture.", config=config)
    raw = result["raw"]
    raw_path = config.memory_path / "raw" / f"{raw['id']}.json"

    mtime_before = raw_path.stat().st_mtime
    # Trigger reflect and other operations — raw file must stay untouched
    ingest("Another entry for context.", config=config)
    config.allow_low_value_reflections = True
    config.min_reflection_sources = 1
    ingest(
        'I learned a critical key insight: "Persistent Memory" is an important concept.',
        config=config,
    )
    reflect(config=config)

    mtime_after = raw_path.stat().st_mtime
    assert mtime_before == mtime_after, (
        "Raw memory file was modified after initial creation — immutability violated"
    )


def test_raw_memory_preserved_verbatim(tmp_path):
    """The text field of a raw memory must equal the ingested text exactly."""
    config = _tmp_config(tmp_path)
    text = "Exact text: spacing,  punctuation, and\nnewlines preserved."
    result = ingest(text, config=config)
    assert result["raw"]["text"] == text


def test_episodic_links_back_to_raw(tmp_path):
    """Every episodic record must have a raw_ref pointing to its source raw."""
    config = _tmp_config(tmp_path)
    result = ingest(
        'I learned a critical key insight: "Recursive Memory" is an important concept.',
        config=config,
    )
    ep = result["episodic"]
    assert ep is not None, "Expected episodic promotion for high-importance text"
    assert ep.get("raw_ref") == result["raw"]["id"], (
        f"Episodic raw_ref {ep.get('raw_ref')!r} does not match raw id {result['raw']['id']!r}"
    )


def test_raw_records_accumulate_not_replace(tmp_path):
    """Multiple ingest calls must create multiple raw files, not overwrite."""
    config = _tmp_config(tmp_path)
    ingest("First raw entry.", config=config)
    ingest("Second raw entry.", config=config)
    ingest("Third raw entry.", config=config)
    raw_dir = config.memory_path / "raw"
    raw_files = list(raw_dir.glob("*.json"))
    assert len(raw_files) == 3, f"Expected 3 raw files, found {len(raw_files)}"


# ---------------------------------------------------------------------------
# Full pipeline integration test
# ---------------------------------------------------------------------------

def test_full_pipeline_raw_to_simulation(tmp_path):
    """
    End-to-end: raw → episodic → semantic → reflection → tasks → decision → simulation.
    Verifies each layer produces a stored record.
    """
    config = _tmp_config(tmp_path)
    config.allow_low_value_reflections = True
    config.min_reflection_sources = 1

    # Layer 1: ingest
    r = ingest(
        'I learned a critical key insight: "Pipeline Memory" is an important concept. '
        'Need to implement the next step in the pipeline.',
        config=config,
    )
    assert r["raw"] is not None,      "Layer 1: raw missing"
    assert r["episodic"] is not None, "Layer 1: episodic missing"
    assert r["semantic"] is not None, "Layer 1: semantic missing"

    # Layer 2: reflect
    ref_result = reflect(config=config)
    assert ref_result["reflection"] is not None, "Layer 2: reflection missing"
    reflection = ref_result["reflection"]

    # Layer 3: tasks from reflection
    task_store = TaskStore(config)
    tasks = task_store.list_tasks()
    assert len(tasks) > 0, "Layer 3: no tasks created from reflection"

    # Layer 3: decision
    decision_result = select_next_task(config=config)
    assert decision_result["task"] is not None,     "Layer 3: no task selected"
    assert decision_result["decision"] is not None, "Layer 3: no decision record"

    # Layer 3: simulation
    selected_task = decision_result["task"]
    sim_result = simulate_action(selected_task, config=config)
    assert sim_result["simulation"] is not None, "Layer 3: simulation record missing"
    sim = sim_result["simulation"]
    assert sim["task_id"] == selected_task["id"]
    assert sim["proposed_action"]
    assert sim["expected_outcome"]
    assert isinstance(sim["risks"], list) and len(sim["risks"]) > 0

    # Verify all JSON files exist
    assert (config.memory_path / "raw").glob("*.json")
    assert (config.memory_path / "episodic").glob("*.json")
    assert (config.memory_path / "semantic").glob("*.json")
    assert (config.memory_path / "reflections").glob("*.json")
    assert (config.memory_path / "tasks").glob("*.json")
    assert (config.memory_path / "decisions").glob("*.json")
    assert (config.memory_path / "simulations").glob("*.json")


# ---------------------------------------------------------------------------
# Core memory protection
# ---------------------------------------------------------------------------

def test_core_memory_protected_during_pipeline(tmp_path):
    """CoreMemoryProtectedError is raised on any attempt to write to vault/core/."""
    config = _tmp_config(tmp_path)
    (tmp_path / "vault" / "core").mkdir(parents=True, exist_ok=True)
    core_path = tmp_path / "vault" / "core" / "test-id.md"
    with pytest.raises(CoreMemoryProtectedError):
        _mem_write_markdown(
            path=core_path,
            frontmatter={"id": "test-id", "type": "raw"},
            body="Attempting to write core",
            config=config,
        )


def test_core_memory_not_written_by_reflect(tmp_path):
    """reflect() must not create any files under vault/core/."""
    config = _tmp_config(tmp_path)
    config.allow_low_value_reflections = True
    config.min_reflection_sources = 1

    ingest(
        'I learned a critical key insight: "Core Guard" is an important concept.',
        config=config,
    )
    reflect(config=config)

    core_dir = config.vault_path / "core"
    core_files = [f for f in core_dir.iterdir() if f.is_file()] if core_dir.exists() else []
    assert core_files == [], (
        f"reflect() wrote to vault/core/: {[f.name for f in core_files]}"
    )


# ---------------------------------------------------------------------------
# LLM swap-point markers
# ---------------------------------------------------------------------------

def test_llm_integration_in_reflect():
    """reflect.py must import and use generate_text from llm module (Layer 4)."""
    src = (SRC_DIR / "reflect.py").read_text(encoding="utf-8")
    assert "generate_text" in src, "reflect.py must import generate_text from llm"
    assert "_generate_reflection" in src, "reflect.py must define _generate_reflection"
    assert "llm_used" in src, "reflect.py must set llm_used metadata"


def test_llm_integration_in_simulate():
    """simulate.py must import and use generate_text from llm module (Layer 4)."""
    src = (SRC_DIR / "simulate.py").read_text(encoding="utf-8")
    assert "generate_text" in src, "simulate.py must import generate_text from llm"
    assert "_propose_action" in src and "_expected_outcome" in src
    assert "llm_used" in src, "simulate.py must set llm_used metadata"


def test_no_real_execution_in_simulate():
    """simulate.py must not import any execution primitive."""
    tree = ast.parse((SRC_DIR / "simulate.py").read_text(encoding="utf-8"))
    forbidden = {"subprocess", "os.system", "os.popen", "shutil", "exec", "eval"}
    imports_found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in forbidden:
                    imports_found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in forbidden:
                imports_found.add(node.module)
    assert imports_found == set(), (
        f"simulate.py imports execution primitives: {imports_found}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_config(tmp_path: Path) -> Config:
    config = Config()
    config.memory_path = tmp_path / "memory"
    config.vault_path  = tmp_path / "vault"
    return config
