"""Skill Forge: research a topic and forge a validated skill from it.

A forged skill must clear a rubric critique AND a live A/B functional test
before it is offered as a proposal — never a hollow label.
"""
import json
import re
from typing import Dict, Optional

from aeon.core.config import Config
from aeon.agent.loop import AgentEvent, AgentLoop
from aeon.models.router import ModelRouter
from aeon.skills.store import SkillStore, _NAME_RE

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
    data = _parse_json(
        _complete(client, model, _DRAFT_PROMPT.format(topic=topic, report=report, feedback=fb))
    )
    if not data:
        return None
    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    body = str(data.get("body", "")).strip()
    if not (name and description and body) or not _NAME_RE.match(name):
        return None
    return {"name": name, "description": description, "body": body}


def critique_skill(draft: Dict, report: str, client, model) -> Dict:
    data = _parse_json(
        _complete(
            client,
            model,
            _CRITIQUE_PROMPT.format(
                report=report,
                name=draft["name"],
                description=draft["description"],
                body=draft["body"],
            ),
        )
    )
    if not data or "passed" not in data:
        return {"passed": False, "scores": {}, "issues": ["unparseable critique"]}
    return {
        "passed": bool(data["passed"]),
        "scores": data.get("scores", {}),
        "issues": list(data.get("issues", [])),
    }


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
    """Run the skill on a representative task with vs without it, and judge."""
    client, model = router.resolve("deep")
    task = _complete(
        client, model,
        _TASK_PROMPT.format(name=draft["name"], description=draft["description"]),
    ).strip()
    if not task:
        task = draft["description"]
    if loop_factory is None:
        loop_factory = lambda cfg, enable_tools=False: AgentLoop(config=cfg, enable_tools=enable_tools)
    with_skill = _run_once(
        loop_factory(config, enable_tools=False), task,
        preamble=f"Use this skill:\n{draft['body']}",
    )
    without = _run_once(loop_factory(config, enable_tools=False), task)
    verdict = _parse_json(
        _complete(client, model, _JUDGE_PROMPT.format(
            task=task, with_skill=with_skill, without_skill=without))
    )
    with_better = bool(verdict.get("with_better")) if verdict else False
    reason = verdict.get("reason", "") if verdict else "judge output unparseable"
    return {"with_better": with_better, "reason": reason, "task": task}


def forge_skill(topic, config=None, router=None, max_attempts=3,
                research=None, loop_factory=None):
    """Research a topic and forge a validated skill from it.

    Streams AgentEvents. Ends in `done` (with the proposal + evidence) only if
    the draft clears the critique gate AND beats the baseline in the A/B test;
    otherwise ends in `error` with the reason — never a hollow proposal.
    """
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
