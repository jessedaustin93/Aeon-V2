import pytest

from aeon.core.config import Config
from aeon.models.client import ChatDelta
from aeon.models.router import ModelRouter
from aeon.skills import SkillStore
from aeon.skills.learn import propose_from_transcript


class FakeClient:
    def __init__(self, reply):
        self.reply = reply
        self.base_url = "http://fake/v1"

    def chat(self, model, messages, tools=None, stream=False, temperature=None):
        yield ChatDelta("text", text=self.reply)
        yield ChatDelta("finish", finish_reason="stop")


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    return Config()


def _router(config, reply):
    router = ModelRouter(config)
    router.roles["chat"] = "fake"
    fake = FakeClient(reply)
    router.resolve = lambda role: (fake, "fake")  # type: ignore
    return router


TRANSCRIPT = [
    {"role": "user", "content": "how do I check mesh health?"},
    {"role": "assistant", "content": "ping the hub, then read peer status"},
]


def test_proposes_skill_from_delimited(config):
    reply = "NAME: mesh-health\nDESCRIPTION: Check mesh\nBODY:\n1. ping hub\n2. read peer status"
    skill = propose_from_transcript(TRANSCRIPT, config, _router(config, reply))
    assert skill is not None
    assert skill.name == "mesh-health"
    assert "read peer status" in skill.body
    assert SkillStore(config).list_proposals()[0].name == "mesh-health"


def test_no_skill_sentinel_returns_none(config):
    skill = propose_from_transcript(TRANSCRIPT, config, _router(config, "NO_SKILL"))
    assert skill is None
    assert SkillStore(config).list_proposals() == []


def test_skill_embedded_in_prose(config):
    reply = "Sure! Here is a skill:\nNAME: x-skill\nDESCRIPTION: d\nBODY:\n1. b\nHope that helps."
    skill = propose_from_transcript(TRANSCRIPT, config, _router(config, reply))
    assert skill is not None and skill.name == "x-skill"


def test_invalid_name_declined(config):
    reply = "NAME: Bad Name!\nDESCRIPTION: d\nBODY:\n1. b"
    assert propose_from_transcript(TRANSCRIPT, config, _router(config, reply)) is None


def test_missing_fields_declined(config):
    reply = "NAME: x\nDESCRIPTION:"
    assert propose_from_transcript(TRANSCRIPT, config, _router(config, reply)) is None
