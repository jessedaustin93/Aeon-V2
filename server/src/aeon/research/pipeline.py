"""Deep research pipeline.

Reuses the AgentEvent shape for streaming progress. Uses the `deep` model
role for planning and synthesis, and the existing web_search / web_fetch
tool handlers for gathering. Reports are markdown with a Sources section
and are saved under <data>/research/ plus summarized into memory.
"""
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from aeon.core.config import Config
from aeon.core.time_utils import utc_now_iso
from aeon.agent.loop import AgentEvent
from aeon.models.router import ModelRouter
from aeon.tools.web import web_fetch, web_search

_PLAN_PROMPT = """You are planning web research for this question:

{question}

Reply with ONLY a JSON array of 2-4 focused search queries, e.g.
["query one", "query two"]."""

_REPORT_PROMPT = """Write a thorough, well-structured markdown research report \
answering the question below, using ONLY the provided sources. Cite sources \
inline as [n] and end with a "## Sources" section listing each numbered URL. \
Be honest about gaps.

Question: {question}

Sources:
{sources}
"""

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:50] or "untitled"


@dataclass
class ResearchRun:
    id: str
    question: str
    status: str  # "running" | "complete" | "error"
    report_path: str = ""
    sources: List[Dict] = field(default_factory=list)
    created_at: str = ""


class ResearchStore:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.dir = self.config.base_path / "research"
        self.dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> List[Dict]:
        runs = []
        for path in sorted(self.dir.glob("*.md"), reverse=True):
            meta = self.dir / f"{path.stem}.json"
            if meta.exists():
                try:
                    runs.append(json.loads(meta.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue
        return runs

    def get(self, run_id: str) -> Optional[Dict]:
        for meta in self.dir.glob("*.json"):
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("id") == run_id:
                report = self.dir / Path(data["report_path"]).name
                data["report"] = report.read_text(encoding="utf-8") if report.exists() else ""
                return data
        return None

    def save(self, run: ResearchRun, report_md: str) -> str:
        stem = f"{run.id}-{_slug(run.question)}"
        report_path = self.dir / f"{stem}.md"
        report_path.write_text(report_md, encoding="utf-8")
        run.report_path = str(report_path)
        (self.dir / f"{stem}.json").write_text(
            json.dumps(asdict(run), indent=2), encoding="utf-8"
        )
        return str(report_path)


def _plan_queries(question: str, client, model) -> List[str]:
    reply = ""
    for delta in client.chat(model, [{"role": "user", "content": _PLAN_PROMPT.format(question=question)}], stream=False):
        if delta.kind == "text":
            reply += delta.text
    match = _JSON_ARRAY_RE.search(reply)
    if match:
        try:
            queries = json.loads(match.group(0))
            if isinstance(queries, list) and queries:
                return [str(q) for q in queries[:4]]
        except json.JSONDecodeError:
            pass
    return [question]


def run_research(
    question: str,
    config: Optional[Config] = None,
    router: Optional[ModelRouter] = None,
    max_sources: int = 6,
    max_queries: int = 4,
) -> Iterator[AgentEvent]:
    config = config or Config()
    router = router or ModelRouter(config)
    store = ResearchStore(config)
    run = ResearchRun(
        id=uuid.uuid4().hex[:12],
        question=question,
        status="running",
        created_at=utc_now_iso(),
    )

    try:
        client, model = router.resolve("deep")
    except ValueError as exc:
        yield AgentEvent("error", {"error": str(exc)})
        return

    yield AgentEvent("text", {"text": "Planning research queries...\n"})
    queries = _plan_queries(question, client, model)[:max_queries]

    seen_urls = set()
    sources: List[Dict] = []
    for query in queries:
        yield AgentEvent("text", {"text": f"Searching: {query}\n"})
        try:
            hits = web_search({"query": query, "limit": 4}, config)["results"]
        except Exception as exc:
            yield AgentEvent("text", {"text": f"  search failed: {exc}\n"})
            continue
        for hit in hits:
            url = hit.get("url", "")
            if not url or url in seen_urls or len(sources) >= max_sources:
                continue
            seen_urls.add(url)
            yield AgentEvent("text", {"text": f"Reading: {url}\n"})
            try:
                page = web_fetch({"url": url}, config)
            except Exception as exc:
                yield AgentEvent("text", {"text": f"  fetch failed: {exc}\n"})
                continue
            sources.append(
                {"url": url, "title": page.get("title") or hit.get("title", ""),
                 "text": page.get("text", "")[:4000]}
            )

    if not sources:
        run.status = "error"
        yield AgentEvent("error", {"error": "no sources could be gathered"})
        return

    yield AgentEvent("text", {"text": "Writing report...\n"})
    sources_block = "\n\n".join(
        f"[{i + 1}] {s['title']} — {s['url']}\n{s['text']}"
        for i, s in enumerate(sources)
    )
    report_md = ""
    prompt = _REPORT_PROMPT.format(question=question, sources=sources_block)
    for delta in client.chat(model, [{"role": "user", "content": prompt}], stream=False):
        if delta.kind == "text":
            report_md += delta.text

    if "## Sources" not in report_md:
        report_md += "\n\n## Sources\n" + "\n".join(
            f"{i + 1}. {s['url']}" for i, s in enumerate(sources)
        )

    run.sources = [{"url": s["url"], "title": s["title"]} for s in sources]
    run.status = "complete"
    report_path = store.save(run, f"# {question}\n\n{report_md}\n")

    # Summarize into memory (best-effort; never breaks the run).
    try:
        from aeon.core.ingest import ingest
        ingest(f"Research report on: {question}\nSaved at {report_path}", source="research", config=config)
    except Exception:
        pass

    yield AgentEvent("done", {"run_id": run.id, "report_path": report_path,
                              "sources": run.sources})
