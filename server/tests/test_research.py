import pytest

from aeon.core.config import Config
from aeon.models.client import ChatDelta
from aeon.models.router import ModelRouter
from aeon.research import ResearchStore, run_research
from aeon.research import pipeline as pl


class ScriptedClient:
    """First call returns the plan, second returns the report."""

    def __init__(self, plan_reply, report_reply):
        self.replies = [plan_reply, report_reply]
        self.base_url = "http://fake/v1"

    def chat(self, model, messages, tools=None, stream=False, temperature=None):
        reply = self.replies.pop(0)
        yield ChatDelta("text", text=reply)
        yield ChatDelta("finish", finish_reason="stop")


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    cfg = Config()
    cfg.memory_path.mkdir(parents=True, exist_ok=True)
    cfg.vault_path.mkdir(parents=True, exist_ok=True)
    return cfg


def _router(config, client):
    router = ModelRouter(config)
    router.roles["deep"] = "fake-deep"
    router.resolve = lambda role: (client, "fake-deep")  # type: ignore
    return router


def _stub_web(monkeypatch, pages):
    monkeypatch.setattr(pl, "web_search",
                        lambda args, cfg: {"results": [{"url": u, "title": t}
                                                        for u, t in pages]})
    monkeypatch.setattr(pl, "web_fetch",
                        lambda args, cfg: {"title": "T", "text": f"content of {args['url']}"})


def test_full_research_run(config, monkeypatch):
    client = ScriptedClient('["query one", "query two"]',
                            "Findings [1].\n\n## Sources\n1. http://a.com")
    _stub_web(monkeypatch, [("http://a.com", "A"), ("http://b.com", "B")])
    events = list(run_research("what is SDR?", config, _router(config, client)))
    done = events[-1]
    assert done.kind == "done"
    assert len(done.data["sources"]) == 2
    report = ResearchStore(config).get(done.data["run_id"])
    assert "what is SDR?" in report["report"]
    assert "## Sources" in report["report"]


def test_research_honors_role(config, monkeypatch):
    client = ScriptedClient('["q"]', "report\n## Sources\n1. http://a.com")
    seen = {}
    router = _router(config, client)
    orig = router.resolve
    router.resolve = lambda role: (seen.__setitem__("role", role), orig(role))[1]
    _stub_web(monkeypatch, [("http://a.com", "A")])
    list(run_research("q?", config, router, role="chat"))
    assert seen["role"] == "chat"


def test_report_without_sources_section_gets_one(config, monkeypatch):
    client = ScriptedClient('["q"]', "Just a bare answer with no sources heading.")
    _stub_web(monkeypatch, [("http://a.com", "A")])
    events = list(run_research("q?", config, _router(config, client)))
    report = ResearchStore(config).get(events[-1].data["run_id"])["report"]
    assert "## Sources" in report
    assert "http://a.com" in report


def test_plan_fallback_to_question(config, monkeypatch):
    client = ScriptedClient("not json at all", "report [1]\n## Sources\n1. http://a.com")
    _stub_web(monkeypatch, [("http://a.com", "A")])
    events = list(run_research("fallback question", config, _router(config, client)))
    assert events[-1].kind == "done"


def test_no_sources_is_error(config, monkeypatch):
    client = ScriptedClient('["q"]', "unused")
    monkeypatch.setattr(pl, "web_search", lambda args, cfg: {"results": []})
    events = list(run_research("q?", config, _router(config, client)))
    assert events[-1].kind == "error"


def test_fetch_failure_skipped(config, monkeypatch):
    client = ScriptedClient('["q"]', "report\n## Sources\n1. http://b.com")
    monkeypatch.setattr(pl, "web_search",
                        lambda args, cfg: {"results": [{"url": "http://a.com", "title": "A"},
                                                       {"url": "http://b.com", "title": "B"}]})

    def flaky_fetch(args, cfg):
        if args["url"] == "http://a.com":
            raise OSError("boom")
        return {"title": "B", "text": "good content"}

    monkeypatch.setattr(pl, "web_fetch", flaky_fetch)
    events = list(run_research("q?", config, _router(config, client)))
    done = events[-1]
    assert done.kind == "done"
    assert [s["url"] for s in done.data["sources"]] == ["http://b.com"]
