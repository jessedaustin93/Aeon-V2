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
Reply in EXACTLY this format and nothing else (the body is multi-line markdown):

NAME: kebab-case-name
DESCRIPTION: one line
BODY:
1. first concrete step
2. second concrete step
(more steps as needed)"""

# A skill passes the critique if every rubric score meets this bar. 3 = "decent";
# the A/B functional test is the real proof that it helps. Demanding 4+ here made
# a strict local critic reject everything.
CRITIQUE_MIN_SCORE = 3

_CRITIQUE_PROMPT = """You are a reviewer. Judge whether this SKILL is worth \
keeping. Score 1-5 each: specific (concrete, not vague), grounded (supported by \
the report), actionable (the assistant can follow it). A score of 3 means \
decent; reserve 1-2 for genuinely vague, ungrounded, or unusable content.

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
    # Models often wrap JSON in ```json fences — strip them before matching.
    cleaned = re.sub(r"```(?:json)?", "", text)
    match = _JSON_RE.search(cleaned)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _parse_draft(text: str) -> Optional[Dict]:
    """Parse the delimiter-based draft format (tolerates a multi-line body)."""
    name_m = re.search(r"(?im)^\s*NAME:\s*(.+?)\s*$", text)
    desc_m = re.search(r"(?im)^\s*DESCRIPTION:\s*(.+?)\s*$", text)
    body_m = re.search(r"(?is)\bBODY:\s*\n?(.*)$", text)
    if not (name_m and desc_m and body_m):
        return None
    name = name_m.group(1).strip().strip("`").strip()
    description = desc_m.group(1).strip()
    body = body_m.group(1).strip().strip("`").strip()
    if not (name and description and body) or not _NAME_RE.match(name):
        return None
    return {"name": name, "description": description, "body": body}


def draft_skill(topic: str, report: str, client, model, feedback: str = "") -> Optional[Dict]:
    fb = f"\nFix these problems from the last attempt:\n{feedback}\n" if feedback else ""
    return _parse_draft(
        _complete(client, model, _DRAFT_PROMPT.format(topic=topic, report=report, feedback=fb))
    )


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
    if not data:
        return {"passed": False, "scores": {}, "issues": ["unparseable critique"]}
    scores = data.get("scores", {}) or {}
    # Compute the verdict from the scores against a fixed bar rather than
    # trusting the model's self-reported "passed" — more honest and stable.
    numeric = []
    for v in scores.values():
        try:
            numeric.append(int(v))
        except (TypeError, ValueError):
            numeric.append(0)
    passed = bool(numeric) and all(n >= CRITIQUE_MIN_SCORE for n in numeric)
    return {
        "passed": passed,
        "scores": scores,
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
    # Task-gen and judging want fast, clean JSON — the instruct (chat) model,
    # not the slow thinking (deep) model that research uses.
    client, model = router.resolve("chat")
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
    # Bound the research pass: report synthesis on a local model gets slow with
    # many sources, and the skill only needs enough grounding to be correct.
    if research is None:
        research = lambda t, c, r: run_research(
            t, c, r, max_sources=3, max_queries=2, role="chat")

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

    # Draft/critique run on the fast instruct model; research (above) used deep.
    client, model = router.resolve("chat")
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
