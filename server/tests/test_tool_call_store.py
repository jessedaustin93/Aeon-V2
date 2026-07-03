"""Tests for Layer 5 — ToolCallStore (tool call traceability).

Coverage:
- ToolCallStore.create: JSON + Markdown written with correct fields
- Traceability: record links back to simulation_id and task_id
- Traceability: simulation record carries tool_call_id pointing to record
- tool_call_id is None in simulation when no tool matched
- ToolCallStore.get: returns record by ID, None for unknown
- ToolCallStore.list_tool_calls: all, filtered by status, filtered by tool_name
- Default status is "pending_review"
- Markdown: arguments section, traceability section, pending-review notice
- No execution primitives in tool_calls.py
- vault/core/ never touched
"""
import ast
import json
from pathlib import Path

import pytest

from aeon.core import Config, ToolCallStore, register_builtin_tools
from aeon.core.simulate import simulate_action
from aeon.core.tasks import TaskStore
from aeon.core.tools import ToolRegistry


SRC_DIR = Path(__file__).parent.parent / "src" / "aeon" / "core"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg(tmp_path):
    c = Config(base_path=tmp_path)
    c.ensure_dirs()
    return c


@pytest.fixture
def cfg_with_tools(cfg):
    registry = ToolRegistry(cfg)
    register_builtin_tools(registry)
    return cfg


@pytest.fixture
def store(cfg):
    return ToolCallStore(cfg)


def _make_task(cfg: Config, description: str) -> dict:
    s = TaskStore(cfg)
    task = s.create_task(
        description=description,
        source_reflection_id="test-ref",
        source_reflection_title="Test Reflection",
        confidence=0.7,
        tags=["test"],
    )
    assert task is not None
    return task


def _fake_tool_call(tool: str = "file_read", approval_required: bool = True) -> dict:
    return {
        "tool":               tool,
        "arguments":          {"path": "config.json"},
        "matched_by":         "keyword",
        "approval_required":  approval_required,
    }


# ---------------------------------------------------------------------------
# ToolCallStore.create — field completeness
# ---------------------------------------------------------------------------

def test_create_returns_dict(store):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    assert isinstance(r, dict)


def test_create_has_id(store):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    assert "id" in r and r["id"]


def test_create_has_tool_name(store):
    r = store.create(_fake_tool_call("file_write"), "sim-1", "task-1", "My Task")
    assert r["tool_name"] == "file_write"


def test_create_has_arguments(store):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    assert r["arguments"] == {"path": "config.json"}


def test_create_has_matched_by(store):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    assert r["matched_by"] == "keyword"


def test_create_has_simulation_id(store):
    r = store.create(_fake_tool_call(), "sim-abc", "task-1", "My Task")
    assert r["simulation_id"] == "sim-abc"


def test_create_has_task_id(store):
    r = store.create(_fake_tool_call(), "sim-1", "task-xyz", "My Task")
    assert r["task_id"] == "task-xyz"


def test_create_has_task_title(store):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "Special Task")
    assert r["task_title"] == "Special Task"


def test_create_status_is_pending_review(store):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    assert r["status"] == "pending_review"


def test_create_has_approval_required(store):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    assert r["approval_required"] is True


def test_approval_required_false_stored_correctly(store):
    r = store.create(_fake_tool_call(approval_required=False), "sim-1", "task-1", "My Task")
    assert r["approval_required"] is False


def test_approval_required_in_json_file(store, cfg):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    data = json.loads(
        (cfg.memory_path / "tool_calls" / f"{r['id']}.json").read_text(encoding="utf-8")
    )
    assert "approval_required" in data
    assert data["approval_required"] is True


def test_approval_required_in_markdown(store, cfg):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    md = (cfg.vault_path / "tool_calls" / f"{r['id']}.md").read_text(encoding="utf-8")
    assert "Approval Required" in md


def test_create_has_created_at(store):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    assert "created_at" in r and r["created_at"]


def test_create_has_source_links(store):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    assert isinstance(r["source_links"], list)
    assert len(r["source_links"]) == 2


def test_source_links_contain_simulation_id(store):
    r = store.create(_fake_tool_call(), "sim-abc", "task-1", "My Task")
    assert any("sim-abc" in lnk for lnk in r["source_links"])


def test_source_links_contain_task_id(store):
    r = store.create(_fake_tool_call(), "sim-1", "task-xyz", "My Task")
    assert any("task-xyz" in lnk for lnk in r["source_links"])


# ---------------------------------------------------------------------------
# Persistence — files on disk
# ---------------------------------------------------------------------------

def test_create_writes_json_file(store, cfg):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    json_path = cfg.memory_path / "tool_calls" / f"{r['id']}.json"
    assert json_path.exists()


def test_create_writes_markdown_file(store, cfg):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    md_path = cfg.vault_path / "tool_calls" / f"{r['id']}.md"
    assert md_path.exists()


def test_json_content_matches_record(store, cfg):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    data = json.loads(
        (cfg.memory_path / "tool_calls" / f"{r['id']}.json").read_text(encoding="utf-8")
    )
    assert data["tool_name"]     == r["tool_name"]
    assert data["simulation_id"] == r["simulation_id"]
    assert data["task_id"]       == r["task_id"]
    assert data["status"]        == "pending_review"


# ---------------------------------------------------------------------------
# ToolCallStore.get
# ---------------------------------------------------------------------------

def test_get_returns_record_by_id(store):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    fetched = store.get(r["id"])
    assert fetched is not None
    assert fetched["id"] == r["id"]


def test_get_returns_none_for_unknown(store):
    assert store.get("does-not-exist") is None


# ---------------------------------------------------------------------------
# ToolCallStore.list_tool_calls
# ---------------------------------------------------------------------------

def test_list_tool_calls_empty(store):
    assert store.list_tool_calls() == []


def test_list_tool_calls_returns_all(store):
    store.create(_fake_tool_call("file_read"),  "sim-1", "task-1", "T1")
    store.create(_fake_tool_call("file_write"), "sim-2", "task-2", "T2")
    assert len(store.list_tool_calls()) == 2


def test_list_tool_calls_filter_by_tool_name(store):
    store.create(_fake_tool_call("file_read"),  "sim-1", "task-1", "T1")
    store.create(_fake_tool_call("file_write"), "sim-2", "task-2", "T2")
    result = store.list_tool_calls(tool_name="file_read")
    assert len(result) == 1
    assert result[0]["tool_name"] == "file_read"


def test_list_tool_calls_filter_by_status(store):
    store.create(_fake_tool_call(), "sim-1", "task-1", "T1")
    result = store.list_tool_calls(status="pending_review")
    assert len(result) == 1
    assert store.list_tool_calls(status="approved") == []


def test_list_tool_calls_sorted_by_created_at(store):
    store.create(_fake_tool_call("file_read"),  "sim-1", "task-1", "T1")
    store.create(_fake_tool_call("file_write"), "sim-2", "task-2", "T2")
    records = store.list_tool_calls()
    timestamps = [r["created_at"] for r in records]
    assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# Traceability — simulate_action integration
# ---------------------------------------------------------------------------

def test_simulation_has_tool_call_id_when_match(cfg_with_tools):
    task = _make_task(cfg_with_tools, "Read the config.json file.")
    result = simulate_action(task, config=cfg_with_tools)
    assert result["simulation"]["tool_call_id"] is not None


def test_simulation_tool_call_id_is_none_when_no_match(cfg_with_tools):
    task = _make_task(cfg_with_tools, "Document the project patterns thoroughly.")
    result = simulate_action(task, config=cfg_with_tools)
    assert result["simulation"]["tool_call_id"] is None


def test_tool_call_id_stored_in_simulation_json(cfg_with_tools):
    task = _make_task(cfg_with_tools, "Read the config.json file.")
    result = simulate_action(task, config=cfg_with_tools)
    sim = result["simulation"]
    data = json.loads(
        (cfg_with_tools.memory_path / "simulations" / f"{sim['id']}.json")
        .read_text(encoding="utf-8")
    )
    assert "tool_call_id" in data
    assert data["tool_call_id"] == sim["tool_call_id"]


def test_tool_call_record_exists_for_matched_simulation(cfg_with_tools):
    task = _make_task(cfg_with_tools, "Read the config.json file.")
    result = simulate_action(task, config=cfg_with_tools)
    sim = result["simulation"]
    call_id = sim["tool_call_id"]
    assert call_id is not None
    call_path = cfg_with_tools.memory_path / "tool_calls" / f"{call_id}.json"
    assert call_path.exists()


def test_tool_call_record_simulation_id_matches(cfg_with_tools):
    task = _make_task(cfg_with_tools, "Read the config.json file.")
    result = simulate_action(task, config=cfg_with_tools)
    sim = result["simulation"]
    call_id = sim["tool_call_id"]
    call_store = ToolCallStore(cfg_with_tools)
    record = call_store.get(call_id)
    assert record["simulation_id"] == sim["id"]


def test_tool_call_record_task_id_matches(cfg_with_tools):
    task = _make_task(cfg_with_tools, "Read the config.json file.")
    result = simulate_action(task, config=cfg_with_tools)
    sim = result["simulation"]
    call_store = ToolCallStore(cfg_with_tools)
    record = call_store.get(sim["tool_call_id"])
    assert record["task_id"] == task["id"]


def test_no_tool_call_record_written_when_no_match(cfg_with_tools):
    task = _make_task(cfg_with_tools, "Document the project thoroughly.")
    simulate_action(task, config=cfg_with_tools)
    call_dir = cfg_with_tools.memory_path / "tool_calls"
    json_files = list(call_dir.glob("*.json")) if call_dir.exists() else []
    assert json_files == []


# ---------------------------------------------------------------------------
# Markdown content
# ---------------------------------------------------------------------------

def test_markdown_has_arguments_section(store, cfg):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    md = (cfg.vault_path / "tool_calls" / f"{r['id']}.md").read_text(encoding="utf-8")
    assert "## Arguments" in md
    assert "config.json" in md


def test_markdown_has_traceability_section(store, cfg):
    r = store.create(_fake_tool_call(), "sim-abc", "task-xyz", "My Task")
    md = (cfg.vault_path / "tool_calls" / f"{r['id']}.md").read_text(encoding="utf-8")
    assert "## Traceability" in md
    assert "sim-abc" in md
    assert "task-xyz" in md


def test_markdown_has_pending_review_notice(store, cfg):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    md = (cfg.vault_path / "tool_calls" / f"{r['id']}.md").read_text(encoding="utf-8")
    assert "PENDING REVIEW" in md


def test_markdown_frontmatter_has_required_fields(store, cfg):
    r = store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    md = (cfg.vault_path / "tool_calls" / f"{r['id']}.md").read_text(encoding="utf-8")
    assert "type: tool_call"   in md
    assert "tool_name:"        in md
    assert "status:"           in md
    assert "simulation_id:"    in md
    assert "task_id:"          in md


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def test_no_execution_primitives_in_tool_calls():
    source = (SRC_DIR / "tool_calls.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned = {
        "subprocess", "os.system", "os.popen", "exec", "eval",
        "shutil", "PowerShell", "bash", "shell",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in banned, f"Banned import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module not in banned, f"Banned import: {node.module}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in {"exec", "eval"}, f"Banned call: {node.func.id}"


def test_tool_call_store_never_touches_vault_core(store, cfg):
    core_dir = cfg.vault_path / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    before = set(core_dir.rglob("*"))
    store.create(_fake_tool_call(), "sim-1", "task-1", "My Task")
    after = set(core_dir.rglob("*"))
    assert before == after
