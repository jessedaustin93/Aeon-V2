# Aeon-V2 Phase 7: Skill Forge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aeon can research a topic and forge a *validated* skill from it — one that clears a critique gate and a live A/B functional test — landing it as a proposal with evidence, never a hollow label.

**Architecture:** New `aeon.skills.forge` orchestrates: reuse `aeon.research.run_research` for grounding, draft a skill from the report with the `deep` model, run a rubric **critique gate** (regenerate on fail), run a **live A/B test** (agent loop with vs without the skill, judged), and only on double-pass write the proposal plus an `evidence.json` sidecar via an extended `SkillStore`. Streamed through a new SSE endpoint and surfaced in the Skills view.

**Tech Stack:** Python 3.11, stdlib + FastAPI (server); React + TS (web). No new deps.

## Global Constraints

- Model access only via `ModelRouter.resolve`; the pipeline uses the `deep` role for draft/critique/judge and a tool-less `AgentLoop` for the A/B runs.
- A forged skill is offered ONLY if the critique gate passes AND the A/B judge says the with-skill answer is better. Otherwise: rejected, no proposal.
- A passing skill lands as a **proposal** (never auto-activated) with evidence.
- Evidence sidecar is `<data>/skills/_proposals/<name>/evidence.json`.
- All model I/O isolated behind injectable clients so tests use no network.
- Commit after every task; full suite green before each commit.
- Reuse existing shapes: `Skill(name, description, body, path)`,
  `AgentEvent(kind, data)`, `run_research(topic, config, router) -> Iterator[AgentEvent]` (final `done` event carries `run_id`; fetch report via `ResearchStore(config).get(run_id)["report"]`).

## File structure

- `server/src/aeon/skills/forge.py` — the pipeline (draft, critique, A/B, orchestration, `forge_skill` generator).
- `server/src/aeon/skills/store.py` — extend: `propose(..., evidence=None)` writes `evidence.json`; add `evidence(name)`.
- `server/src/aeon/api/app.py` — add `POST /api/skills/forge` (SSE); include evidence in `GET /api/skills` proposals.
- `web/src/api.ts` — `forgeSkill` stream + `Skill.evidence` type.
- `web/src/views/SkillsView.tsx` + `views.css` — forge box + evidence panel.
- Tests: `server/tests/test_skill_forge.py`, extend `test_skills_store.py`, `test_api.py`.

---

### Task 1: SkillStore evidence sidecar

**Files:**
- Modify: `server/src/aeon/skills/store.py`
- Test: `server/tests/test_skills_store.py`

**Interfaces:**
- Produces: `SkillStore.propose(name, description, body, evidence: dict | None = None) -> Skill` — when `evidence` given, also writes `_proposals/<name>/evidence.json`. `SkillStore.evidence(name: str) -> dict | None` reads it (from proposal dir, falling back to active dir). `approve()` moves the whole dir so `evidence.json` travels with the skill.

- [ ] **Step 1: Write the failing tests**

Add to `server/tests/test_skills_store.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ~/Aeon-V2/server && .venv/bin/pytest tests/test_skills_store.py -k evidence -q`
Expected: FAIL — `propose()` takes no `evidence`; `evidence` attr missing.

- [ ] **Step 3: Implement**

In `store.py`, extend `propose` and add `evidence`:

```python
    def propose(self, name: str, description: str, body: str,
                evidence: Optional[dict] = None) -> Skill:
        self._check_name(name)
        skill = Skill(name=name, description=description, body=body)
        target = self.proposals_root / name
        target.mkdir(parents=True, exist_ok=True)
        md = target / "SKILL.md"
        md.write_text(_serialize_skill(skill), encoding="utf-8")
        if evidence is not None:
            (target / "evidence.json").write_text(
                json.dumps(evidence, indent=2), encoding="utf-8"
            )
        skill.path = str(md)
        return skill

    def evidence(self, name: str) -> Optional[dict]:
        for root in (self.proposals_root / name, self.root / name):
            path = root / "evidence.json"
            if path.is_file():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return None
        return None
```

Add `import json` if not present (it is). `approve()` already `shutil.move`s the dir, so `evidence.json` travels automatically.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_skills_store.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd ~/Aeon-V2 && git add -A && git commit -m "feat: skill evidence sidecar in SkillStore"
```

---

### Task 2: Draft + critique gate

**Files:**
- Create: `server/src/aeon/skills/forge.py`
- Test: `server/tests/test_skill_forge.py`

**Interfaces:**
- Produces:
  - `draft_skill(topic: str, report: str, client, model, feedback: str = "") -> dict | None` — returns `{"name","description","body"}` parsed from the model's JSON (reuses the same `\{.*\}` extraction as `skills/learn.py`), or `None` if unparseable/incomplete or the name is invalid (`aeon.skills.store` name rule: `^[a-z0-9][a-z0-9-]{0,63}$`).
  - `critique_skill(draft: dict, report: str, client, model) -> dict` — returns `{"passed": bool, "scores": {"specific": int, "grounded": int, "actionable": int}, "issues": [str]}`. Parse JSON; on unparseable output return `{"passed": False, "scores": {}, "issues": ["unparseable critique"]}`.
- Consumes: a client with `.chat(model, messages, stream=False) -> Iterator[ChatDelta]` (the real `ChatClient`; tests pass a fake).

- [ ] **Step 1: Write the failing tests**

`server/tests/test_skill_forge.py`:

```python
import json
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
    r = forge.critique_skill({"name":"x","description":"d","body":"b"}, "R", c, "m")
    assert r["passed"] is True
    assert r["scores"]["grounded"] == 5


def test_critique_fail_with_issues():
    c = ReplyClient('{"passed": false, "scores": {"specific":2}, "issues": ["too vague"]}')
    r = forge.critique_skill({"name":"x","description":"d","body":"b"}, "R", c, "m")
    assert r["passed"] is False
    assert "too vague" in r["issues"]


def test_critique_unparseable_fails_closed():
    c = ReplyClient("the skill looks fine to me")
    r = forge.critique_skill({"name":"x","description":"d","body":"b"}, "R", c, "m")
    assert r["passed"] is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_skill_forge.py -q`
Expected: FAIL — `No module named 'aeon.skills.forge'`.

- [ ] **Step 3: Implement `forge.py` (draft + critique only for now)**

```python
"""Skill Forge: research a topic and forge a validated skill from it.

A forged skill must clear a rubric critique AND a live A/B functional test
before it is offered as a proposal — never a hollow label.
"""
import json
import re
from typing import Dict, Optional

from aeon.core.config import Config
from aeon.skills.store import _NAME_RE

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_DRAFT_PROMPT = """You are writing a reusable SKILL for an AI assistant, grounded \
ONLY in the research report below. A skill is concrete, actionable guidance for a \
class of tasks — numbered steps the assistant can actually follow, not vague \
advice. Every claim must be supported by the report.

Topic: {topic}

Research report:
{report}
{feedback}
Reply with ONLY a JSON object:
{{"name": "kebab-case-name", "description": "one line", "body": "markdown steps"}}"""

_CRITIQUE_PROMPT = """You are a strict reviewer. Judge whether this SKILL is worth \
keeping. Score 1-5 each: specific (concrete, not vague), grounded (supported by \
the report), actionable (the assistant can follow it). It PASSES only if every \
score is >= 4.

Research report:
{report}

Skill:
name: {name}
description: {description}
body:
{body}

Reply with ONLY a JSON object:
{{"passed": true|false, "scores": {{"specific": n, "grounded": n, "actionable": n}}, "issues": ["..."]}}"""


def _complete(client, model, prompt: str) -> str:
    text = ""
    for delta in client.chat(model, [{"role": "user", "content": prompt}], stream=False):
        if delta.kind == "text":
            text += delta.text
    return text


def _parse_json(text: str) -> Optional[dict]:
    match = _JSON_RE.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def draft_skill(topic: str, report: str, client, model, feedback: str = "") -> Optional[Dict]:
    fb = f"\nFix these problems from the last attempt:\n{feedback}\n" if feedback else ""
    data = _parse_json(_complete(client, model, _DRAFT_PROMPT.format(
        topic=topic, report=report, feedback=fb)))
    if not data:
        return None
    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    body = str(data.get("body", "")).strip()
    if not (name and description and body) or not _NAME_RE.match(name):
        return None
    return {"name": name, "description": description, "body": body}


def critique_skill(draft: Dict, report: str, client, model) -> Dict:
    data = _parse_json(_complete(client, model, _CRITIQUE_PROMPT.format(
        report=report, name=draft["name"],
        description=draft["description"], body=draft["body"])))
    if not data or "passed" not in data:
        return {"passed": False, "scores": {}, "issues": ["unparseable critique"]}
    return {
        "passed": bool(data["passed"]),
        "scores": data.get("scores", {}),
        "issues": list(data.get("issues", [])),
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_skill_forge.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Aeon-V2 && git add -A && git commit -m "feat: skill forge draft + critique gate"
```

---

### Task 3: Live A/B functional test

**Files:**
- Modify: `server/src/aeon/skills/forge.py`
- Test: extend `server/tests/test_skill_forge.py`

**Interfaces:**
- Produces:
  - `ab_test(draft: dict, config, router, loop_factory=None) -> dict` — returns `{"with_better": bool, "reason": str, "task": str}`.
    1. Ask the `deep` model for one representative test task in the skill's domain (`_TASK_PROMPT`); on failure fall back to `draft["description"]`.
    2. Run a **tool-less** `AgentLoop` twice: once with the skill body prepended as a system preamble to the task, once without. Collect each reply's text.
    3. Ask the `deep` model to judge (`_JUDGE_PROMPT`) → JSON `{"with_better": bool, "reason": str}`.
  - `loop_factory(config, enable_tools=False) -> loop` defaults to constructing `AgentLoop`; tests inject a stub. The loop's `.run(messages, role=...) -> Iterator[AgentEvent]` is consumed for `text`/`done`.

- [ ] **Step 1: Write the failing tests**

Append to `test_skill_forge.py`:

```python
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
    # replies: [task question, judge verdict]
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
    result = forge.ab_test({"name":"x","description":"d","body":"s"},
                           config, _router(config, client), loop_factory=factory)
    assert result["with_better"] is False


def test_ab_test_unparseable_judge_is_false(config):
    client = ReplyClient("task?", "they seem about the same honestly")
    loops = [StubLoop("a"), StubLoop("b")]
    factory = lambda cfg, enable_tools=False: loops.pop(0)
    result = forge.ab_test({"name":"x","description":"d","body":"s"},
                           config, _router(config, client), loop_factory=factory)
    assert result["with_better"] is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_skill_forge.py -k ab_test -q`
Expected: FAIL — `module 'aeon.skills.forge' has no attribute 'ab_test'`.

- [ ] **Step 3: Implement `ab_test`**

Add to `forge.py`:

```python
from aeon.agent.loop import AgentLoop
from aeon.models.router import ModelRouter

_TASK_PROMPT = """Give ONE realistic user question that a skill named "{name}" \
({description}) should help answer. Reply with only the question, no preamble."""

_JUDGE_PROMPT = """Two assistant answers to the same question. Answer A used a \
skill; answer B did not. Is A clearly better — more specific, correct, and useful?

Question: {task}

Answer A (with skill):
{with_skill}

Answer B (without skill):
{without_skill}

Reply with ONLY a JSON object: {{"with_better": true|false, "reason": "..."}}"""


def _run_once(loop, task: str, preamble: str = "") -> str:
    messages = []
    if preamble:
        messages.append({"role": "system", "content": preamble})
    messages.append({"role": "user", "content": task})
    reply = ""
    for event in loop.run(messages):
        if event.kind == "text":
            reply += event.data.get("text", "")
        elif event.kind == "done" and not reply:
            reply = event.data.get("text", "")
    return reply.strip()


def ab_test(draft: Dict, config: Config, router: ModelRouter, loop_factory=None) -> Dict:
    client, model = router.resolve("deep")
    task = _complete(client, model, _TASK_PROMPT.format(
        name=draft["name"], description=draft["description"])).strip()
    if not task:
        task = draft["description"]
    if loop_factory is None:
        loop_factory = lambda cfg, enable_tools=False: AgentLoop(config=cfg, enable_tools=enable_tools)
    with_skill = _run_once(loop_factory(config, enable_tools=False), task,
                           preamble=f"Use this skill:\n{draft['body']}")
    without = _run_once(loop_factory(config, enable_tools=False), task)
    verdict = _parse_json(_complete(client, model, _JUDGE_PROMPT.format(
        task=task, with_skill=with_skill, without_skill=without)))
    with_better = bool(verdict.get("with_better")) if verdict else False
    reason = verdict.get("reason", "") if verdict else "judge output unparseable"
    return {"with_better": with_better, "reason": reason, "task": task}
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_skill_forge.py -q`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Aeon-V2 && git add -A && git commit -m "feat: skill forge live A/B functional test"
```

---

### Task 4: `forge_skill` orchestration (streamed)

**Files:**
- Modify: `server/src/aeon/skills/forge.py`
- Test: extend `server/tests/test_skill_forge.py`

**Interfaces:**
- Produces: `forge_skill(topic, config=None, router=None, max_attempts=3, research=None) -> Iterator[AgentEvent]`.
  - `research(topic, config, router)` defaults to `aeon.research.run_research`; injectable for tests. Consume it, echoing its `text` events as progress; capture the final `done` event's `run_id` and read the report via `ResearchStore(config).get(run_id)["report"]`. If research errors or yields no report → yield `AgentEvent("error", {"error": "research produced no report"})` and stop.
  - Loop up to `max_attempts`: `draft_skill` (feedback from prior critique issues) → `critique_skill`. Emit `text` progress each attempt. On pass, break. If never passes → `AgentEvent("error", {"error": "skill failed critique", "issues": [...]})`.
  - `ab_test` the passing draft. If `with_better` is False → `AgentEvent("error", {"error": "skill did not beat baseline", "ab": {...}})` and stop (no proposal).
  - On double-pass: build `evidence = {"topic","sources","scores","issues","ab","report_excerpt"}`, `SkillStore(config).propose(name, description, body, evidence=evidence)`, and yield `AgentEvent("done", {"skill": {...}, "evidence": evidence})`.
- The research `done` event shape is `{"run_id", "report_path", "sources"}` (from `aeon.research.pipeline`).

- [ ] **Step 1: Write the failing tests**

Append to `test_skill_forge.py`:

```python
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


def test_forge_success_lands_proposal(config, monkeypatch):
    # research report, then per attempt: draft, critique; then ab: task, judge
    client = ReplyClient(
        '{"name":"v4-triage","description":"triage RTL-SDR V4 issues","body":"1. check driver"}',  # draft
        '{"passed": true, "scores":{"specific":5,"grounded":5,"actionable":5}, "issues":[]}',        # critique
        "How do I fix V4 drivers?",                                                                  # ab task
        '{"with_better": true, "reason": "grounded in sources"}',                                    # judge
    )
    router = _router(config, client)
    loops = [StubLoop("good"), StubLoop("meh")]
    monkeypatch.setattr(forge, "AgentLoop", None, raising=False)
    events = list(forge.forge_skill(
        "RTL-SDR V4", config, router,
        research=_fake_research("REPORT about V4 drivers", [{"url":"http://a","title":"A"}]),
    ))
    # patch loop_factory indirectly: forge_skill builds ab_test with default factory,
    # so inject via monkeypatching ab_test's loop construction:
    done = events[-1]
    assert done.kind == "done"
    assert done.data["skill"]["name"] == "v4-triage"
    assert done.data["evidence"]["ab"]["with_better"] is True
    assert SkillStore(config).list_proposals()[0].name == "v4-triage"


def test_forge_rejected_on_critique(config):
    client = ReplyClient(
        '{"name":"junk","description":"d","body":"vague"}',
        '{"passed": false, "scores":{"specific":1}, "issues":["too vague"]}',
        '{"name":"junk","description":"d","body":"still vague"}',
        '{"passed": false, "scores":{"specific":1}, "issues":["still vague"]}',
        '{"name":"junk","description":"d","body":"vague again"}',
        '{"passed": false, "scores":{"specific":1}, "issues":["nope"]}',
    )
    events = list(forge.forge_skill(
        "topic", config, _router(config, client), max_attempts=3,
        research=_fake_research("REPORT", [{"url":"http://a","title":"A"}]),
    ))
    assert events[-1].kind == "error"
    assert "critique" in events[-1].data["error"]
    assert SkillStore(config).list_proposals() == []
```

Because `ab_test` builds real `AgentLoop`s by default, the success test must
inject a stub factory. Implement `forge_skill` to accept an optional
`loop_factory` param forwarded to `ab_test`, and update the success test to pass
`loop_factory=lambda cfg, enable_tools=False: loops.pop(0)`.

- [ ] **Step 2: Adjust the success test to pass `loop_factory`**

Replace the `forge.forge_skill(...)` call in `test_forge_success_lands_proposal`:

```python
    loops = [StubLoop("good"), StubLoop("meh")]
    events = list(forge.forge_skill(
        "RTL-SDR V4", config, router,
        research=_fake_research("REPORT about V4 drivers", [{"url":"http://a","title":"A"}]),
        loop_factory=lambda cfg, enable_tools=False: loops.pop(0),
    ))
```

Remove the `monkeypatch.setattr(forge, "AgentLoop", None...)` line.

- [ ] **Step 3: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_skill_forge.py -k forge_ -q`
Expected: FAIL — `forge_skill` not defined.

- [ ] **Step 4: Implement `forge_skill`**

Add to `forge.py`:

```python
from aeon.skills.store import SkillStore


def forge_skill(topic, config=None, router=None, max_attempts=3,
                research=None, loop_factory=None):
    from aeon.research import run_research, ResearchStore
    config = config or Config()
    router = router or ModelRouter(config)
    research = research or run_research

    yield AgentEvent("text", {"text": f"Researching: {topic}\n"})
    run_id = None
    sources = []
    for event in research(topic, config, router):
        if event.kind == "text":
            yield event
        elif event.kind == "done":
            run_id = event.data.get("run_id")
            sources = event.data.get("sources", [])
        elif event.kind == "error":
            yield AgentEvent("error", {"error": f"research failed: {event.data.get('error')}"})
            return
    stored = ResearchStore(config).get(run_id) if run_id else None
    report = (stored or {}).get("report", "")
    if not report:
        yield AgentEvent("error", {"error": "research produced no report"})
        return

    client, model = router.resolve("deep")
    draft = None
    critique = {"issues": []}
    for attempt in range(1, max_attempts + 1):
        yield AgentEvent("text", {"text": f"Drafting skill (attempt {attempt})\n"})
        feedback = "\n".join(critique.get("issues", [])) if attempt > 1 else ""
        draft = draft_skill(topic, report, client, model, feedback=feedback)
        if not draft:
            continue
        yield AgentEvent("text", {"text": "Critiquing draft\n"})
        critique = critique_skill(draft, report, client, model)
        if critique["passed"]:
            break
    if not draft or not critique.get("passed"):
        yield AgentEvent("error", {"error": "skill failed critique",
                                   "issues": critique.get("issues", [])})
        return

    yield AgentEvent("text", {"text": "Running live A/B test\n"})
    ab = ab_test(draft, config, router, loop_factory=loop_factory)
    if not ab["with_better"]:
        yield AgentEvent("error", {"error": "skill did not beat baseline", "ab": ab})
        return

    evidence = {
        "topic": topic,
        "sources": sources,
        "scores": critique.get("scores", {}),
        "ab": ab,
        "report_excerpt": report[:800],
    }
    skill = SkillStore(config).propose(
        draft["name"], draft["description"], draft["body"], evidence=evidence)
    yield AgentEvent("done", {
        "skill": {"name": skill.name, "description": skill.description, "body": skill.body},
        "evidence": evidence,
    })
```

Update `ab_test` signature already takes `loop_factory`; ensure `forge_skill`
forwards it (done above).

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/pytest tests/test_skill_forge.py -q`
Expected: 11 passed.

- [ ] **Step 6: Full suite + commit**

```bash
cd ~/Aeon-V2/server && .venv/bin/pytest -q
cd ~/Aeon-V2 && git add -A && git commit -m "feat: forge_skill orchestration (research -> validated proposal)"
```

---

### Task 5: API — forge endpoint + evidence in listing

**Files:**
- Modify: `server/src/aeon/api/app.py`
- Test: extend `server/tests/test_api.py`

**Interfaces:**
- `POST /api/skills/forge {topic}` → SSE stream of `forge_skill` events (JSON `data:` frames). 422 if `topic` empty.
- `GET /api/skills` proposals each gain an `"evidence"` key (dict or null) from `skill_store.evidence(name)`.

- [ ] **Step 1: Write the failing tests**

Add to `test_api.py`:

```python
def test_skills_listing_includes_evidence(client):
    store = client.app.state.skill_store
    store.propose("forged", "d", "b", evidence={"ab": {"with_better": True}})
    proposals = client.get("/api/skills", headers=AUTH).json()["proposals"]
    forged = [p for p in proposals if p["name"] == "forged"][0]
    assert forged["evidence"]["ab"]["with_better"] is True


def test_forge_endpoint_streams(client, monkeypatch):
    from aeon.agent.loop import AgentEvent
    def fake_forge(topic, config, router, **kwargs):
        yield AgentEvent("text", {"text": "researching\n"})
        yield AgentEvent("done", {"skill": {"name": "x", "description": "d", "body": "b"},
                                  "evidence": {"ab": {"with_better": True}}})
    monkeypatch.setattr("aeon.api.app.forge_skill", fake_forge)
    resp = client.post("/api/skills/forge", headers=AUTH, json={"topic": "SDR"})
    assert resp.status_code == 200
    kinds = [json.loads(l[5:])["kind"] for l in resp.text.splitlines() if l.startswith("data:")]
    assert kinds == ["text", "done"]


def test_forge_requires_topic(client):
    assert client.post("/api/skills/forge", headers=AUTH, json={"topic": ""}).status_code == 422
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_api.py -k "evidence or forge" -q`
Expected: FAIL — no evidence key; `/api/skills/forge` 404.

- [ ] **Step 3: Implement**

In `app.py`, add import near the other skills imports:

```python
from aeon.skills.forge import forge_skill
```

Change the `list_skills` proposals to include evidence:

```python
    @app.get("/api/skills", dependencies=[auth])
    def list_skills() -> Dict:
        return {
            "active": [asdict(s) for s in skill_store.list_active()],
            "proposals": [
                {**asdict(s), "evidence": skill_store.evidence(s.name)}
                for s in skill_store.list_proposals()
            ],
        }
```

Add the forge endpoint next to `propose_skill`:

```python
    @app.post("/api/skills/forge", dependencies=[auth])
    def forge(body: Dict) -> StreamingResponse:
        topic = (body.get("topic") or "").strip()
        if not topic:
            raise HTTPException(status_code=422, detail="topic is required")

        def stream() -> Iterator[str]:
            for event in forge_skill(topic, cfg, router):
                yield f"data: {json.dumps(asdict(event))}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_api.py -q`
Expected: all pass.

- [ ] **Step 5: Full suite + commit**

```bash
cd ~/Aeon-V2/server && .venv/bin/pytest -q
cd ~/Aeon-V2 && git add -A && git commit -m "feat: /api/skills/forge endpoint + evidence in skills listing"
```

---

### Task 6: Web UI — forge box + evidence panel

**Files:**
- Modify: `web/src/api.ts`, `web/src/views/SkillsView.tsx`, `web/src/views/views.css`

**Interfaces:**
- `api.ts`: add `forgeSkill(topic)` via `stream("/api/skills/forge", {topic}, onEvent)`; extend `Skill` with `evidence?: SkillEvidence | null`; add `SkillEvidence` type `{ topic?: string; sources?: {url:string;title:string}[]; scores?: Record<string,number>; ab?: {with_better:boolean; reason:string; task:string}; report_excerpt?: string }`.
- `SkillsView.tsx`: a "Forge from research" input + button that streams progress into a trace box; on `done`, reload skills. Each proposal shows its evidence (A/B verdict chip, rubric scores, sources) in an expander.

- [ ] **Step 1: Add API surface**

In `web/src/api.ts`, extend the `Skill` interface:

```typescript
export interface SkillEvidence {
  topic?: string;
  sources?: { url: string; title: string }[];
  scores?: Record<string, number>;
  ab?: { with_better: boolean; reason: string; task: string };
  report_excerpt?: string;
}
export interface Skill {
  name: string;
  description: string;
  body: string;
  path?: string;
  evidence?: SkillEvidence | null;
}
```

Add to the `api` object (before the closing `}`):

```typescript
  forgeSkill: (topic: string, onEvent: (e: AgentEvent) => void) =>
    stream("/api/skills/forge", { topic }, onEvent),
```

- [ ] **Step 2: Forge box + trace + evidence in `SkillsView.tsx`**

Add state and a forge handler at the top of the component:

```typescript
  const [topic, setTopic] = useState("");
  const [forging, setForging] = useState(false);
  const [trace, setTrace] = useState<string[]>([]);

  async function forge() {
    const t = topic.trim();
    if (!t || forging) return;
    setForging(true);
    setTrace([]);
    await api
      .forgeSkill(t, (e) => {
        if (e.kind === "text") setTrace((x) => [...x, String(e.data.text).trim()].filter(Boolean));
        else if (e.kind === "error") setTrace((x) => [...x, `rejected: ${e.data.error}`]);
        else if (e.kind === "done") setTrace((x) => [...x, `forged: ${(e.data.skill as {name:string}).name}`]);
      })
      .catch(() => setTrace((x) => [...x, "connection lost"]));
    setForging(false);
    setTopic("");
    load();
  }
```

Add the forge box as the first child of `.view-body`:

```tsx
        <div className="panel forge-box">
          <div className="readout">Forge a skill from research</div>
          <div className="forge-row">
            <input value={topic} placeholder="Topic to research and turn into a skill…"
              onChange={(e) => setTopic(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && forge()} />
            <button className="btn-primary" onClick={forge} disabled={forging || !topic.trim()}>
              {forging ? "Forging…" : "Forge"}
            </button>
          </div>
          {trace.length > 0 && (
            <div className="forge-trace">
              {trace.map((t, i) => (
                <div key={i} className="mono trace-line"><span className="trace-mark">›</span> {t}</div>
              ))}
            </div>
          )}
        </div>
```

In the proposal card, after `<p className="skill-desc">`, render evidence when present:

```tsx
                  {s.evidence && (
                    <div className="evidence">
                      {s.evidence.ab && (
                        <span className={`chip ${s.evidence.ab.with_better ? "chip-ok" : "chip-alert"}`}>
                          A/B {s.evidence.ab.with_better ? "passed" : "failed"}
                        </span>
                      )}
                      {s.evidence.scores &&
                        Object.entries(s.evidence.scores).map(([k, v]) => (
                          <span key={k} className="chip">{k} {v}/5</span>
                        ))}
                      {s.evidence.sources && s.evidence.sources.length > 0 && (
                        <span className="readout">{s.evidence.sources.length} sources</span>
                      )}
                    </div>
                  )}
```

- [ ] **Step 3: Styles in `views.css`**

```css
.forge-box { padding: 16px; margin-bottom: 18px; display: flex; flex-direction: column; gap: 10px; }
.forge-row { display: flex; gap: 10px; }
.forge-row input { flex: 1; }
.forge-trace { display: flex; flex-direction: column; gap: 4px; border-top: 1px solid var(--line-soft); padding-top: 10px; }
.evidence { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 4px; }
```

- [ ] **Step 4: Build the web app**

Run: `cd ~/Aeon-V2/web && npm run build`
Expected: build succeeds, no TS errors.

- [ ] **Step 5: Commit**

```bash
cd ~/Aeon-V2 && git add -A && git commit -m "feat: Skills view forge box + evidence panel"
```

---

### Task 7: Live verification + deploy + push

- [ ] **Step 1: Full server suite**

Run: `cd ~/Aeon-V2/server && .venv/bin/pytest -q` — expect all green.

- [ ] **Step 2: Live forge against the T5810** (SSH tunnel to LM Studio as in earlier phases; a real topic like "RTL-SDR V4 vs V3"). Confirm the stream ends in either a `done` with a proposal + evidence, or an honest `error` (critique/AB rejection). Either is a pass — the point is it doesn't fabricate.

- [ ] **Step 3: Push + CI green**

```bash
cd ~/Aeon-V2 && git push && gh run watch --exit-status $(gh run list --limit 1 --json databaseId -q '.[0].databaseId')
```

- [ ] **Step 4: Deploy to the T5810**

```bash
ssh t5810 'cd ~/Aeon-V2 && git pull && server/.venv/bin/pip install -e server/ && cd web && npm install && npm run build && systemctl --user restart aeon-server'
```

## Self-review notes

- **Spec coverage:** research (Task 4 via injected `run_research`), draft (T2),
  critique gate + regenerate (T2/T4), A/B test (T3), proposal-with-evidence only
  on double-pass (T4), evidence sidecar (T1), API (T5), UI (T6), deploy (T7). ✓
- **Type consistency:** `draft` dicts are always `{name, description, body}`;
  `critique` always `{passed, scores, issues}`; `ab` always
  `{with_better, reason, task}`; evidence keys match between T4 (write), T5
  (API), and T6 (UI render). ✓
- **Reused shapes verified against code:** `_NAME_RE` and `SkillStore.propose`
  in `skills/store.py`; `AgentEvent` in `agent/loop.py`; `run_research` /
  `ResearchStore.get(run_id)["report"]` / `ResearchRun` in `research/pipeline.py`.
