import pytest

from aeon.core.config import Config
from aeon.models.client import ChatDelta
from aeon.skills import forge


class ReplyClient:
    """Returns queued replies, one per chat() call."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.base_url = "http://fake/v1"
        self.calls = []

    def chat(self, model, messages, tools=None, stream=False, temperature=None):
        self.calls.append(messages)
        yield ChatDelta("text", text=self.replies.pop(0))
        yield ChatDelta("finish", finish_reason="stop")


# ---------------------------------------------------------------- draft/critique

def test_draft_parses_json():
    c = ReplyClient('{"name":"mesh-health","description":"d","body":"1. ping hub"}')
    d = forge.draft_skill("mesh", "REPORT", c, "m")
    assert d["name"] == "mesh-health"
    assert d["body"] == "1. ping hub"


def test_draft_rejects_bad_name():
    c = ReplyClient('{"name":"Bad Name","description":"d","body":"b"}')
    assert forge.draft_skill("t", "R", c, "m") is None


def test_draft_rejects_incomplete():
    c = ReplyClient('{"name":"x","description":""}')
    assert forge.draft_skill("t", "R", c, "m") is None


def test_critique_pass():
    c = ReplyClient('{"passed": true, "scores": {"specific":5,"grounded":5,"actionable":5}, "issues": []}')
    r = forge.critique_skill({"name": "x", "description": "d", "body": "b"}, "R", c, "m")
    assert r["passed"] is True
    assert r["scores"]["grounded"] == 5


def test_critique_fail_with_issues():
    c = ReplyClient('{"passed": false, "scores": {"specific":2}, "issues": ["too vague"]}')
    r = forge.critique_skill({"name": "x", "description": "d", "body": "b"}, "R", c, "m")
    assert r["passed"] is False
    assert "too vague" in r["issues"]


def test_critique_unparseable_fails_closed():
    c = ReplyClient("the skill looks fine to me")
    r = forge.critique_skill({"name": "x", "description": "d", "body": "b"}, "R", c, "m")
    assert r["passed"] is False


# ------------------------------------------------------------------- A/B test

from aeon.agent.loop import AgentEvent
from aeon.models.router import ModelRouter


class StubLoop:
    def __init__(self, reply):
        self.reply = reply
        self.seen = []

    def run(self, messages, role="chat"):
        self.seen.append(messages)
        yield AgentEvent("text", {"text": self.reply})
        yield AgentEvent("done", {"text": self.reply})


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    cfg = Config()
    cfg.memory_path.mkdir(parents=True, exist_ok=True)
    cfg.vault_path.mkdir(parents=True, exist_ok=True)
    return cfg


def _router(config, client):
    r = ModelRouter(config)
    r.roles["deep"] = "fake"
    r.resolve = lambda role: (client, "fake")
    return r


def test_ab_test_with_better(config):
    client = ReplyClient("What differs in V4?", '{"with_better": true, "reason": "more grounded"}')
    loops = [StubLoop("with-skill answer"), StubLoop("plain answer")]
    factory = lambda cfg, enable_tools=False: loops.pop(0)
    result = forge.ab_test(
        {"name": "x", "description": "d", "body": "steps"},
        config, _router(config, client), loop_factory=factory)
    assert result["with_better"] is True
    assert result["task"] == "What differs in V4?"


def test_ab_test_not_better(config):
    client = ReplyClient("task?", '{"with_better": false, "reason": "no change"}')
    loops = [StubLoop("a"), StubLoop("b")]
    factory = lambda cfg, enable_tools=False: loops.pop(0)
    result = forge.ab_test({"name": "x", "description": "d", "body": "s"},
                           config, _router(config, client), loop_factory=factory)
    assert result["with_better"] is False


def test_ab_test_unparseable_judge_is_false(config):
    client = ReplyClient("task?", "they seem about the same honestly")
    loops = [StubLoop("a"), StubLoop("b")]
    factory = lambda cfg, enable_tools=False: loops.pop(0)
    result = forge.ab_test({"name": "x", "description": "d", "body": "s"},
                           config, _router(config, client), loop_factory=factory)
    assert result["with_better"] is False
