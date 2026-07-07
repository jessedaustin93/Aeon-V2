import pytest

from aeon.core.config import Config
from aeon.cli import lint_skills, add_skill, seed_runtime_skills
from aeon.skills import SkillStore


@pytest.fixture
def data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    (tmp_path / "skills").mkdir()
    return tmp_path


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ------------------------------------------------------------------ lint

def test_lint_empty_is_ok(data_root, capsys):
    assert lint_skills([]) == 0


def test_lint_passes_valid_skill(data_root, capsys):
    _write(data_root / "skills" / "good" / "SKILL.md",
           "---\nname: good\ndescription: a good skill\n---\n1. do a thing\n")
    assert lint_skills([]) == 0
    assert "ok   [active] good" in capsys.readouterr().out


def test_lint_flags_missing_frontmatter(data_root, capsys):
    _write(data_root / "skills" / "bad" / "SKILL.md", "no frontmatter here")
    assert lint_skills([]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_lint_flags_name_folder_mismatch(data_root, capsys):
    _write(data_root / "skills" / "folder-name" / "SKILL.md",
           "---\nname: other-name\ndescription: d\n---\nbody\n")
    assert lint_skills([]) == 1
    assert "does not match folder" in capsys.readouterr().out


def test_lint_flags_bad_name(data_root, capsys):
    _write(data_root / "skills" / "_proposals" / "Bad_Name" / "SKILL.md",
           "---\nname: Bad_Name\ndescription: d\n---\nbody\n")
    assert lint_skills([]) == 1
    assert "invalid name" in capsys.readouterr().out


# ------------------------------------------------------------------ add

def test_add_creates_active_skill(data_root, capsys):
    assert add_skill(["--name", "mesh-check", "--description", "check mesh",
                      "--body", "1. ping the hub"]) == 0
    skill = SkillStore(Config()).get("mesh-check")
    assert skill is not None
    assert skill.body == "1. ping the hub"


def test_add_proposal(data_root):
    assert add_skill(["--name", "draft-skill", "--description", "d",
                      "--body", "1. step", "--proposal"]) == 0
    store = SkillStore(Config())
    assert store.get("draft-skill") is None
    assert [s.name for s in store.list_proposals()] == ["draft-skill"]


def test_add_rejects_bad_name(data_root):
    assert add_skill(["--name", "Bad Name", "--description", "d", "--body", "x"]) == 2


def test_add_requires_body(data_root):
    assert add_skill(["--name", "x", "--description", "d"]) == 2


def test_add_refuses_overwrite_without_force(data_root):
    args = ["--name", "dup", "--description", "d", "--body", "1. a"]
    assert add_skill(args) == 0
    assert add_skill(args) == 1
    assert add_skill(args + ["--force"]) == 0


def test_add_then_lint_passes(data_root):
    add_skill(["--name", "roundtrip", "--description", "d", "--body", "1. step"])
    assert lint_skills([]) == 0


def test_seed_runtime_skills_creates_model_skills(data_root):
    assert seed_runtime_skills([]) == 0
    store = SkillStore(Config())
    names = {s.name for s in store.list_active()}
    assert "local-model-awareness" in names
    assert "designated-model-routing" in names
    assert "grid-kernel-map" in names
    assert lint_skills([]) == 0
