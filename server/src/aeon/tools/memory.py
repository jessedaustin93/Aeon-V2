"""Memory tools — wrap aeon.core search/ingest. Writes go through the
core write_guard, so governance is unchanged."""
from typing import Dict

from aeon.core.config import Config
from aeon.core.ingest import ingest
from aeon.core.search import search
from aeon.core.tools import ToolDefinition


def memory_search(arguments: Dict, config: Config) -> Dict:
    results = search(arguments["query"], config=config)
    limit = int(arguments.get("limit", 5))
    trimmed = []
    for r in results[:limit]:
        mem = r.get("memory") or {}
        trimmed.append(
            {
                "id": mem.get("id"),
                "type": mem.get("type") or mem.get("memory_type"),
                "text": (mem.get("text") or mem.get("summary") or "")[:500],
                "score": r.get("score"),
            }
        )
    return {"query": arguments["query"], "results": trimmed}


def memory_save(arguments: Dict, config: Config) -> Dict:
    result = ingest(
        arguments["text"],
        source=arguments.get("source", "agent"),
        config=config,
    )
    return {
        "raw_id": result["raw"]["id"],
        "episodic": bool(result.get("episodic")),
        "semantic": bool(result.get("semantic")),
    }


DEFINITIONS = [
    ToolDefinition(
        name="memory_search",
        description="Search Aeon's local memory store (raw/episodic/semantic/reflections).",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "description": "Max results, default 5"},
            },
            "required": ["query"],
        },
        tags=["memory"],
        approval_required=False,
    ),
    ToolDefinition(
        name="memory_save",
        description="Save a fact or observation into Aeon's local memory.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "source": {"type": "string", "description": "Where this came from"},
            },
            "required": ["text"],
        },
        tags=["memory"],
        approval_required=False,
    ),
]

HANDLERS = {"memory_search": memory_search, "memory_save": memory_save}
