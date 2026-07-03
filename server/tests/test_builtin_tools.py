"""Tests for Layer 5 — built-in tool schema definitions.

Coverage:
- FILE_READ: required fields, parameter schema, tags, layer
- FILE_WRITE: required fields, parameter schema, tags, layer
- COMMAND_PREVIEW: required fields, parameter schema, tags, layer
- BUILTIN_TOOLS list contains all three
- register_builtin_tools: registers all three, skips duplicates gracefully
- No file is opened, no command is executed (AST + vault/core/ check)
- All three tools are valid ToolDefinition instances
"""
import ast
from pathlib import Path

import pytest

from aeon.core import (
    BUILTIN_TOOLS,
    COMMAND_PREVIEW,
    Config,
    FILE_READ,
    FILE_WRITE,
    ToolDefinition,
    ToolRegistry,
    register_builtin_tools,
)


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


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

def test_file_read_is_tool_definition():
    assert isinstance(FILE_READ, ToolDefinition)


def test_file_write_is_tool_definition():
    assert isinstance(FILE_WRITE, ToolDefinition)


def test_command_preview_is_tool_definition():
    assert isinstance(COMMAND_PREVIEW, ToolDefinition)


def test_builtin_tools_list_contains_all_three():
    names = {t.name for t in BUILTIN_TOOLS}
    assert names == {"file_read", "file_write", "command_preview"}


def test_builtin_tools_list_length():
    assert len(BUILTIN_TOOLS) == 3


# ---------------------------------------------------------------------------
# FILE_READ schema
# ---------------------------------------------------------------------------

def test_file_read_name():
    assert FILE_READ.name == "file_read"


def test_file_read_has_description():
    assert len(FILE_READ.description) > 20


def test_file_read_layer():
    assert FILE_READ.layer == 5


def test_file_read_tags():
    assert "file" in FILE_READ.tags
    assert "read" in FILE_READ.tags
    assert "io"   in FILE_READ.tags


def test_file_read_required_path():
    assert "path" in FILE_READ.parameters["required"]


def test_file_read_has_path_property():
    assert "path" in FILE_READ.parameters["properties"]


def test_file_read_has_offset_and_limit():
    props = FILE_READ.parameters["properties"]
    assert "offset" in props
    assert "limit"  in props


def test_file_read_offset_minimum():
    assert FILE_READ.parameters["properties"]["offset"]["minimum"] == 1


def test_file_read_has_encoding():
    assert "encoding" in FILE_READ.parameters["properties"]


def test_file_read_enabled_by_default():
    assert FILE_READ.enabled is True


def test_file_read_approval_required():
    assert FILE_READ.approval_required is True


# ---------------------------------------------------------------------------
# FILE_WRITE schema
# ---------------------------------------------------------------------------

def test_file_write_name():
    assert FILE_WRITE.name == "file_write"


def test_file_write_has_description():
    assert len(FILE_WRITE.description) > 20


def test_file_write_layer():
    assert FILE_WRITE.layer == 5


def test_file_write_tags():
    assert "file"  in FILE_WRITE.tags
    assert "write" in FILE_WRITE.tags
    assert "io"    in FILE_WRITE.tags


def test_file_write_required_fields():
    required = FILE_WRITE.parameters["required"]
    assert "path"    in required
    assert "content" in required


def test_file_write_mode_enum():
    mode = FILE_WRITE.parameters["properties"]["mode"]
    assert set(mode["enum"]) == {"overwrite", "append"}


def test_file_write_mode_default():
    assert FILE_WRITE.parameters["properties"]["mode"]["default"] == "overwrite"


def test_file_write_has_encoding():
    assert "encoding" in FILE_WRITE.parameters["properties"]


def test_file_write_enabled_by_default():
    assert FILE_WRITE.enabled is True


def test_file_write_approval_required():
    assert FILE_WRITE.approval_required is True


# ---------------------------------------------------------------------------
# COMMAND_PREVIEW schema
# ---------------------------------------------------------------------------

def test_command_preview_name():
    assert COMMAND_PREVIEW.name == "command_preview"


def test_command_preview_has_description():
    assert len(COMMAND_PREVIEW.description) > 20


def test_command_preview_layer():
    assert COMMAND_PREVIEW.layer == 5


def test_command_preview_tags():
    assert "command"    in COMMAND_PREVIEW.tags
    assert "preview"    in COMMAND_PREVIEW.tags
    assert "simulation" in COMMAND_PREVIEW.tags


def test_command_preview_required_command():
    assert "command" in COMMAND_PREVIEW.parameters["required"]


def test_command_preview_has_working_directory():
    assert "working_directory" in COMMAND_PREVIEW.parameters["properties"]


def test_command_preview_has_shell():
    assert "shell" in COMMAND_PREVIEW.parameters["properties"]


def test_command_preview_shell_default():
    assert COMMAND_PREVIEW.parameters["properties"]["shell"]["default"] == "bash"


def test_command_preview_has_environment():
    assert "environment" in COMMAND_PREVIEW.parameters["properties"]


def test_command_preview_description_mentions_no_execution():
    assert any(
        word in COMMAND_PREVIEW.description.lower()
        for word in ("without executing", "no command is run", "definition")
    )


def test_command_preview_enabled_by_default():
    assert COMMAND_PREVIEW.enabled is True


def test_command_preview_approval_required():
    assert COMMAND_PREVIEW.approval_required is True


# ---------------------------------------------------------------------------
# register_builtin_tools
# ---------------------------------------------------------------------------

def test_register_builtin_tools_returns_all_three(registry):
    result = register_builtin_tools(registry)
    assert len(result) == 3


def test_register_builtin_tools_persists_to_registry(registry):
    register_builtin_tools(registry)
    names = {t.name for t in registry.list_tools()}
    assert "file_read"       in names
    assert "file_write"      in names
    assert "command_preview" in names


def test_register_builtin_tools_skips_duplicates(registry):
    register_builtin_tools(registry)
    second = register_builtin_tools(registry)
    assert second == [], "Second call should skip all (already registered)"


def test_register_builtin_tools_does_not_raise_on_duplicate(registry):
    register_builtin_tools(registry)
    register_builtin_tools(registry)  # must not raise


def test_register_builtin_tools_creates_json_files(registry, cfg):
    register_builtin_tools(registry)
    tool_dir = cfg.memory_path / "schemas" / "tools"
    names = {f.stem for f in tool_dir.glob("*.json")}
    assert {"file_read", "file_write", "command_preview"}.issubset(names)


def test_register_builtin_tools_creates_markdown_files(registry, cfg):
    register_builtin_tools(registry)
    agent_dir = cfg.vault_path / "agents"
    names = {f.stem for f in agent_dir.glob("*.md")}
    assert {"file_read", "file_write", "command_preview"}.issubset(names)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def test_no_execution_primitives_in_builtin_tools():
    source = (SRC_DIR / "builtin_tools.py").read_text(encoding="utf-8")
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


def test_builtin_tools_never_touch_vault_core(registry, cfg):
    core_dir = cfg.vault_path / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    before = set(core_dir.rglob("*"))
    register_builtin_tools(registry)
    after = set(core_dir.rglob("*"))
    assert before == after, "register_builtin_tools must not write to vault/core/"
