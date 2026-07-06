import json

import pytest

from aeon.core.config import Config
from aeon.models.client import ChatDelta
from aeon.tools import planning
from aeon.tools.planning import generate_plan, _parse_plan


class ReplyClient:
    def __init__(self, reply):
        self.reply = reply
        self.base_url = "http://fake/v1"

    def chat(self, model, messages, tools=None, stream=False, temperature=None):
        yield ChatDelta("text", text=self.reply)
        yield ChatDelta("finish", finish_reason="stop")


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    cfg = Config()
    cfg.memory_path.mkdir(parents=True, exist_ok=True)
    cfg.vault_path.mkdir(parents=True, exist_ok=True)
    return cfg


def _patch_router(config, monkeypatch, reply):
    def fake_router(cfg):
        class R:
            def resolve(self, role):
                return ReplyClient(reply), "fake"
        return R()
    monkeypatch.setattr(planning, "ModelRouter", fake_router)


REPLY = """TITLE: Migrate the media stack
STEPS:
1. Snapshot the current config — copy compose files and env
2. Stand up the new containers — bring them up on a test port
3. Cut over — stop old, point DNS at new
RISKS:
- Downtime during cutover
- Volume permissions may differ
"""


def test_parse_plan_structure():
    p = _parse_plan(REPLY)
    assert p["title"] == "Migrate the media stack"
    assert len(p["steps"]) == 3
    assert p["steps"][0]["step"] == "Snapshot the current config"
    assert "copy compose files" in p["steps"][0]["detail"]
    assert len(p["risks"]) == 2


def test_parse_plan_no_steps_is_none():
    assert _parse_plan("TITLE: nothing\nRISKS:\n- x") is None


def test_generate_plan_saves(config, monkeypatch):
    _patch_router(config, monkeypatch, REPLY)
    plan = generate_plan({"goal": "Migrate the media stack"}, config)
    assert plan["title"] == "Migrate the media stack"
    assert len(plan["steps"]) == 3
    saved = list((config.base_path / "plans").glob("*.json"))
    assert len(saved) == 1
    on_disk = json.loads(saved[0].read_text())
    assert on_disk["goal"] == "Migrate the media stack"


def test_generate_plan_unparseable_errors(config, monkeypatch):
    _patch_router(config, monkeypatch, "I cannot make a plan for that.")
    assert "error" in generate_plan({"goal": "x"}, config)


def test_plan_tool_not_gated(config):
    assert planning.DEFINITIONS[0].approval_required is False
