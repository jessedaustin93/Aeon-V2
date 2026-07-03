"""Tests for Layer 5 — tool registry (definition only).

Coverage:
- Config: allow_tool_override default and toggle
- ToolDefinition: validation (name, description, parameters.type), defaults, roundtrip
- ToolRegistry.register: JSON + Markdown written, duplicate raises, override allowed
- ToolRegistry.get: returns None for unknown, returns correct definition
- ToolRegistry.list_tools: empty, all, filtered by tag / layer / enabled
- ToolRegistry.unregister: returns True/False, removes both files
- Markdown: frontmatter fields present, definition-only notice present
- JSON: parameters schema stored correctly
- Safety: no execution primitives in tools.py, vault/core/ never touched
"""
import ast
import json
from pathlib import Path

import pytest

from aeon.core import Config, ToolAlreadyRegisteredError, ToolDefinition, ToolRegistry


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
def registry(cfg):
    return ToolRegistry(cfg)


def _simple_tool(name="search_memory", layer=1, tags=None, enabled=True):
    return ToolDefinition(
        name=name,
        description="Search the memory store for a keyword.",
        parameters={
            "type": "object",
            "properties": {
                "query":    {"type": "string", "description": "Search term"},
                "max_results": {"type": "integer", "description": "Result limit"},
            },
            "required": ["query"],
        },
        tags=tags or ["search", "memory"],
        layer=layer,
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_allow_tool_override_default_false():
    assert Config().allow_tool_override is False


def test_allow_tool_override_can_be_set():
    cfg = Config()
    cfg.allow_tool_override = True
    assert cfg.allow_tool_override is True


# ---------------------------------------------------------------------------
# ToolDefinition — validation
# ---------------------------------------------------------------------------

def test_tool_definition_requires_nonempty_name():
    with pytest.raises(ValueError, match="name"):
        ToolDefinition(name="", description="Something")


def test_tool_definition_requires_nonempty_description():
    with pytest.raises(ValueError, match="description"):
        ToolDefinition(name="my_tool", description="")


def test_tool_definition_parameters_not_a_dict_raises():
    with pytest.raises(ValueError):
        ToolDefinition(name="t", description="d", parameters=["not", "a", "dict"])


def test_tool_definition_parameters_wrong_type_raises():
    with pytest.raises(ValueError, match="object"):
        ToolDefinition(name="t", description="d", parameters={"type": "string"})


def test_tool_definition_parameters_type_object_accepted():
    td = ToolDefinition(name="t", description="d", parameters={"type": "object"})
    assert td.parameters == {"type": "object"}


def test_tool_definition_empty_parameters_accepted():
    td = ToolDefinition(name="t", description="d", parameters={})
    assert td.parameters == {}


# ---------------------------------------------------------------------------
# ToolDefinition — defaults and roundtrip
# ---------------------------------------------------------------------------

def test_tool_definition_defaults():
    td = ToolDefinition(name="my_tool", description="Does something")
    assert td.enabled is True
    assert td.layer == 0
    assert td.tags == []
    assert td.parameters == {}
    assert td.registered_at  # non-empty timestamp


def test_tool_definition_to_dict_roundtrip():
    original = _simple_tool()
    restored = ToolDefinition.from_dict(original.to_dict())
    assert restored.name          == original.name
    assert restored.description   == original.description
    assert restored.parameters    == original.parameters
    assert restored.tags          == original.tags
    assert restored.layer         == original.layer
    assert restored.enabled       == original.enabled
    assert restored.registered_at == original.registered_at


def test_tool_definition_whitespace_stripped():
    td = ToolDefinition(name="  my_tool  ", description="  Desc  ")
    assert td.name == "my_tool"
    assert td.description == "Desc"


def test_approval_required_default_true():
    td = ToolDefinition(name="t", description="d")
    assert td.approval_required is True


def test_approval_required_can_be_false():
    td = ToolDefinition(name="t", description="d", approval_required=False)
    assert td.approval_required is False


def test_approval_required_in_to_dict():
    td = ToolDefinition(name="t", description="d", approval_required=False)
    assert td.to_dict()["approval_required"] is False


def test_approval_required_roundtrip():
    td = ToolDefinition(name="t", description="d", approval_required=False)
    restored = ToolDefinition.from_dict(td.to_dict())
    assert restored.approval_required is False


def test_approval_required_defaults_true_when_missing_from_dict():
    data = {"name": "t", "description": "d"}
    td = ToolDefinition.from_dict(data)
    assert td.approval_required is True


# ---------------------------------------------------------------------------
# ToolRegistry — register
# ---------------------------------------------------------------------------

def test_register_markdown_includes_approval_required(registry, cfg):
    registry.register(_simple_tool())
    md = (cfg.vault_path / "agents" / "search_memory.md").read_text(encoding="utf-8")
    assert "approval_required:" in md
    assert "Approval Required" in md


def test_register_creates_json_file(registry, cfg):
    tool = _simple_tool()
    registry.register(tool)
    json_path = cfg.memory_path / "schemas" / "tools" / "search_memory.json"
    assert json_path.exists()


def test_register_creates_markdown_file(registry, cfg):
    tool = _simple_tool()
    registry.register(tool)
    md_path = cfg.vault_path / "agents" / "search_memory.md"
    assert md_path.exists()


def test_register_duplicate_raises(registry):
    tool = _simple_tool()
    registry.register(tool)
    with pytest.raises(ToolAlreadyRegisteredError):
        registry.register(_simple_tool())


def test_register_override_when_allowed(registry, cfg):
    cfg.allow_tool_override = True
    registry.register(_simple_tool(name="t"))
    updated = ToolDefinition(name="t", description="Updated description")
    registry.register(updated)
    stored = registry.get("t")
    assert stored.description == "Updated description"


def test_register_returns_the_tool(registry):
    tool = _simple_tool()
    result = registry.register(tool)
    assert result is tool


# ---------------------------------------------------------------------------
# ToolRegistry — get
# ---------------------------------------------------------------------------

def test_get_returns_none_for_unknown(registry):
    assert registry.get("nonexistent") is None


def test_get_returns_registered_tool(registry):
    tool = _simple_tool()
    registry.register(tool)
    retrieved = registry.get("search_memory")
    assert retrieved is not None
    assert retrieved.name        == tool.name
    assert retrieved.description == tool.description
    assert retrieved.parameters  == tool.parameters
    assert retrieved.tags        == tool.tags
    assert retrieved.layer       == tool.layer
    assert retrieved.enabled     == tool.enabled


# ---------------------------------------------------------------------------
# ToolRegistry — list_tools
# ---------------------------------------------------------------------------

def test_list_tools_empty(registry):
    assert registry.list_tools() == []


def test_list_tools_returns_all(registry):
    registry.register(_simple_tool("tool_a", layer=1))
    registry.register(_simple_tool("tool_b", layer=2))
    assert len(registry.list_tools()) == 2


def test_list_tools_filter_by_tag(registry):
    registry.register(_simple_tool("tool_a", tags=["search"]))
    registry.register(ToolDefinition(name="tool_b", description="b", tags=["write"]))
    result = registry.list_tools(tag="search")
    assert len(result) == 1
    assert result[0].name == "tool_a"


def test_list_tools_filter_by_layer(registry):
    registry.register(_simple_tool("tool_a", layer=1))
    registry.register(_simple_tool("tool_b", layer=2))
    result = registry.list_tools(layer=2)
    assert len(result) == 1
    assert result[0].name == "tool_b"


def test_list_tools_filter_by_enabled(registry):
    registry.register(_simple_tool("tool_on",  enabled=True))
    registry.register(_simple_tool("tool_off", enabled=False))
    enabled_only = registry.list_tools(enabled=True)
    assert all(t.enabled for t in enabled_only)
    assert not any(t.name == "tool_off" for t in enabled_only)


def test_list_tools_sorted_by_registered_at(registry):
    registry.register(_simple_tool("tool_a"))
    registry.register(_simple_tool("tool_b"))
    names = [t.name for t in registry.list_tools()]
    assert names == sorted(names) or names == ["tool_a", "tool_b"]


# ---------------------------------------------------------------------------
# ToolRegistry — unregister
# ---------------------------------------------------------------------------

def test_unregister_returns_true_for_existing(registry):
    registry.register(_simple_tool())
    assert registry.unregister("search_memory") is True


def test_unregister_returns_false_for_unknown(registry):
    assert registry.unregister("never_registered") is False


def test_unregister_removes_json_file(registry, cfg):
    registry.register(_simple_tool())
    registry.unregister("search_memory")
    assert not (cfg.memory_path / "schemas" / "tools" / "search_memory.json").exists()


def test_unregister_removes_markdown_file(registry, cfg):
    registry.register(_simple_tool())
    registry.unregister("search_memory")
    assert not (cfg.vault_path / "agents" / "search_memory.md").exists()


def test_unregister_makes_get_return_none(registry):
    registry.register(_simple_tool())
    registry.unregister("search_memory")
    assert registry.get("search_memory") is None


# ---------------------------------------------------------------------------
# Markdown content
# ---------------------------------------------------------------------------

def test_markdown_has_frontmatter_fields(registry, cfg):
    registry.register(_simple_tool())
    md = (cfg.vault_path / "agents" / "search_memory.md").read_text(encoding="utf-8")
    assert "name: search_memory"   in md
    assert "type: tool_definition" in md
    assert "layer:"                in md
    assert "enabled:"              in md
    assert "registered_at:"        in md
    assert "tags:"                 in md


def test_markdown_has_definition_only_notice(registry, cfg):
    registry.register(_simple_tool())
    md = (cfg.vault_path / "agents" / "search_memory.md").read_text(encoding="utf-8")
    assert "DEFINITION ONLY" in md


def test_markdown_includes_description(registry, cfg):
    registry.register(_simple_tool())
    md = (cfg.vault_path / "agents" / "search_memory.md").read_text(encoding="utf-8")
    assert "Search the memory store for a keyword." in md


# ---------------------------------------------------------------------------
# JSON storage
# ---------------------------------------------------------------------------

def test_json_stores_full_parameters_schema(registry, cfg):
    tool = _simple_tool()
    registry.register(tool)
    data = json.loads(
        (cfg.memory_path / "schemas" / "tools" / "search_memory.json")
        .read_text(encoding="utf-8")
    )
    assert data["parameters"]["type"] == "object"
    assert "query" in data["parameters"]["properties"]
    assert data["parameters"]["required"] == ["query"]


def test_json_stores_all_fields(registry, cfg):
    tool = _simple_tool()
    registry.register(tool)
    data = json.loads(
        (cfg.memory_path / "schemas" / "tools" / "search_memory.json")
        .read_text(encoding="utf-8")
    )
    for field in ("name", "description", "parameters", "tags", "layer", "enabled", "registered_at"):
        assert field in data


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def test_no_execution_primitives_in_tools():
    source = (SRC_DIR / "tools.py").read_text(encoding="utf-8")
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


def test_tool_registry_never_touches_vault_core(registry, cfg):
    core_dir = cfg.vault_path / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    before = set(core_dir.rglob("*"))
    registry.register(_simple_tool("core_check_tool"))
    after = set(core_dir.rglob("*"))
    assert before == after, "ToolRegistry must not write to vault/core/"
