import pytest

from aeon.core.config import Config
from aeon.skills import SkillStore


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    return SkillStore(Config())


def test_propose_and_list(store):
    store.propose("mesh-health", "Check agent mesh health", "1. Ping the hub.")
    assert store.list_active() == []
    proposals = store.list_proposals()
    assert len(proposals) == 1
    assert proposals[0].name == "mesh-health"
    assert proposals[0].body == "1. Ping the hub."


def test_approve_moves_to_active(store):
    store.propose("mesh-health", "Check mesh", "steps")
    skill = store.approve("mesh-health")
    assert skill.name == "mesh-health"
    assert store.list_proposals() == []
    assert store.get("mesh-health").body == "steps"


def test_approve_missing_raises(store):
    with pytest.raises(KeyError):
        store.approve("nope")


def test_approve_refuses_overwrite(store):
    store.propose("s", "d", "v1")
    store.approve("s")
    store.propose("s", "d", "v2")
    with pytest.raises(FileExistsError):
        store.approve("s")
    assert store.approve("s", overwrite=True).body == "v2"


def test_reject_deletes(store):
    store.propose("bad", "desc", "body")
    store.reject("bad")
    assert store.list_proposals() == []
    with pytest.raises(KeyError):
        store.reject("bad")


def test_invalid_name_rejected(store):
    with pytest.raises(ValueError):
        store.propose("../evil", "d", "b")
    with pytest.raises(ValueError):
        store.propose("Bad Name", "d", "b")


def test_malformed_skill_md_skipped(store, tmp_path):
    bad = store.root / "broken"
    bad.mkdir(parents=True)
    (bad / "SKILL.md").write_text("no frontmatter here", encoding="utf-8")
    assert store.list_active() == []


def test_propose_with_evidence_sidecar(store):
    store.propose("t", "d", "body", evidence={"sources": ["http://a"], "ab": {"with_better": True}})
    ev = store.evidence("t")
    assert ev["sources"] == ["http://a"]
    assert ev["ab"]["with_better"] is True


def test_evidence_none_when_absent(store):
    store.propose("plain", "d", "b")
    assert store.evidence("plain") is None


def test_evidence_survives_approve(store):
    store.propose("t", "d", "b", evidence={"ok": 1})
    store.approve("t")
    assert store.evidence("t") == {"ok": 1}


def test_prompt_block(store):
    assert store.prompt_block() == ""
    store.propose("mesh-health", "Check mesh health", "steps")
    store.approve("mesh-health")
    block = store.prompt_block()
    assert "mesh-health: Check mesh health" in block
    assert "skill_use" in block
