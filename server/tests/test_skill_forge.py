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
