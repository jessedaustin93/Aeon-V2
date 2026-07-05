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


def test_proposes_skill_from_json(config):
    reply = '{"name": "mesh-health", "description": "Check mesh", "body": "1. ping hub"}'
    skill = propose_from_transcript(TRANSCRIPT, config, _router(config, reply))
    assert skill is not None
    assert skill.name == "mesh-health"
    assert SkillStore(config).list_proposals()[0].name == "mesh-health"


def test_no_skill_sentinel_returns_none(config):
    skill = propose_from_transcript(TRANSCRIPT, config, _router(config, "NO_SKILL"))
    assert skill is None
    assert SkillStore(config).list_proposals() == []


def test_json_embedded_in_prose(config):
    reply = 'Sure! Here is a skill:\n{"name": "x", "description": "d", "body": "b"}\nHope that helps.'
    skill = propose_from_transcript(TRANSCRIPT, config, _router(config, reply))
    assert skill is not None and skill.name == "x"


def test_invalid_name_declined(config):
    reply = '{"name": "Bad Name!", "description": "d", "body": "b"}'
    assert propose_from_transcript(TRANSCRIPT, config, _router(config, reply)) is None


def test_missing_fields_declined(config):
    reply = '{"name": "x", "description": ""}'
    assert propose_from_transcript(TRANSCRIPT, config, _router(config, reply)) is None
