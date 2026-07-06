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

def test_draft_parses_delimited():
    c = ReplyClient("NAME: mesh-health\nDESCRIPTION: check the mesh\nBODY:\n1. ping hub")
    d = forge.draft_skill("mesh", "REPORT", c, "m")
    assert d["name"] == "mesh-health"
    assert d["body"] == "1. ping hub"


def test_draft_keeps_multiline_body():
    # The whole reason for the delimiter format: bodies span many lines.
    reply = ("NAME: v4-fix\nDESCRIPTION: fix V4 drivers\nBODY:\n"
             "1. blacklist dvb_usb_rtl28xxu\n2. reload udev\n3. test with rtl_test")
    d = forge.draft_skill("t", "R", ReplyClient(reply), "m")
    assert d["name"] == "v4-fix"
    assert "blacklist dvb_usb_rtl28xxu" in d["body"]
    assert "rtl_test" in d["body"]
    assert d["body"].count("\n") == 2


def test_draft_rejects_bad_name():
    c = ReplyClient("NAME: Bad Name\nDESCRIPTION: d\nBODY:\nstep")
    assert forge.draft_skill("t", "R", c, "m") is None


def test_draft_rejects_incomplete():
    c = ReplyClient("NAME: x\nDESCRIPTION:")
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


# --------------------------------------------------------------- orchestration

from aeon.skills.store import SkillStore
from aeon.research import ResearchStore, ResearchRun


def _fake_research(report_text, sources):
    def research(topic, config, router):
        run = ResearchRun(id="r1", question=topic, status="complete",
                          created_at="now", sources=sources)
        ResearchStore(config).save(run, report_text)
        yield AgentEvent("text", {"text": "researching\n"})
        yield AgentEvent("done", {"run_id": "r1", "report_path": "x", "sources": sources})
    return research


def test_forge_success_lands_proposal(config):
    client = ReplyClient(
        "NAME: v4-triage\nDESCRIPTION: triage RTL-SDR V4 issues\nBODY:\n1. check driver",
        '{"passed": true, "scores":{"specific":5,"grounded":5,"actionable":5}, "issues":[]}',
        "How do I fix V4 drivers?",
        '{"with_better": true, "reason": "grounded in sources"}',
    )
    router = _router(config, client)
    loops = [StubLoop("good"), StubLoop("meh")]
    events = list(forge.forge_skill(
        "RTL-SDR V4", config, router,
        research=_fake_research("REPORT about V4 drivers", [{"url": "http://a", "title": "A"}]),
        loop_factory=lambda cfg, enable_tools=False: loops.pop(0),
    ))
    done = events[-1]
    assert done.kind == "done"
    assert done.data["skill"]["name"] == "v4-triage"
    assert done.data["evidence"]["ab"]["with_better"] is True
    assert SkillStore(config).list_proposals()[0].name == "v4-triage"


def test_forge_rejected_on_critique(config):
    client = ReplyClient(
        "NAME: junk\nDESCRIPTION: d\nBODY:\nvague",
        '{"passed": false, "scores":{"specific":1}, "issues":["too vague"]}',
        "NAME: junk\nDESCRIPTION: d\nBODY:\nstill vague",
        '{"passed": false, "scores":{"specific":1}, "issues":["still vague"]}',
        "NAME: junk\nDESCRIPTION: d\nBODY:\nvague again",
        '{"passed": false, "scores":{"specific":1}, "issues":["nope"]}',
    )
    events = list(forge.forge_skill(
        "topic", config, _router(config, client), max_attempts=3,
        research=_fake_research("REPORT", [{"url": "http://a", "title": "A"}]),
    ))
    assert events[-1].kind == "error"
    assert "critique" in events[-1].data["error"]
    assert SkillStore(config).list_proposals() == []


def test_forge_rejected_when_ab_not_better(config):
    client = ReplyClient(
        "NAME: okskill\nDESCRIPTION: d\nBODY:\n1. do the thing",
        '{"passed": true, "scores":{"specific":4,"grounded":4,"actionable":4}, "issues":[]}',
        "test task?",
        '{"with_better": false, "reason": "no improvement"}',
    )
    loops = [StubLoop("a"), StubLoop("b")]
    events = list(forge.forge_skill(
        "topic", config, _router(config, client),
        research=_fake_research("REPORT", [{"url": "http://a", "title": "A"}]),
        loop_factory=lambda cfg, enable_tools=False: loops.pop(0),
    ))
    assert events[-1].kind == "error"
    assert "baseline" in events[-1].data["error"]
    assert SkillStore(config).list_proposals() == []


def test_forge_error_when_no_report(config):
    def empty_research(topic, config, router):
        yield AgentEvent("error", {"error": "no sources"})
    events = list(forge.forge_skill("topic", config, _router(config, ReplyClient()),
                                    research=empty_research))
    assert events[-1].kind == "error"
