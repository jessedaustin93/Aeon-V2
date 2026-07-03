"""Memory index agent — responds to LLM query_memory tool calls.

This is the bridge between the LLM tool-call loop and the memory store.
When the message bus is built, replace direct search() calls with bus messages.
"""
import json
import re
from typing import Dict, List, Optional

from .config import Config
from .search import search

_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "about", "is", "are", "was", "were", "be",
    "been", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "regarding", "related",
    "relevant", "memories", "memory", "information", "high", "importance",
    "important", "all", "any", "some", "most", "patterns", "concepts",
}

# Content fields tried in order when formatting a memory for LLM consumption.
_CONTENT_FIELDS = ("summary", "description", "concept", "content", "text", "title")


def _extract_keywords(query: str) -> List[str]:
    """Split a natural-language query into searchable keywords."""
    words = re.split(r"[\s,;:\.]+", query.lower())
    keywords = [w for w in words if len(w) > 2 and w not in _STOP_WORDS]
    return keywords[:5] if keywords else [query]


class MemoryIndexAgent:
    """Executes memory queries on behalf of the LLM tool-calling loop."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()

    def query(
        self,
        query: str,
        memory_types: Optional[List[str]] = None,
        limit: int = 5,
    ) -> List[Dict]:
        """Search memory and return results formatted for LLM consumption.

        Splits the query into keywords, searches each, deduplicates by ID,
        and sorts by importance descending. Defaults to episodic + semantic
        (raw entries are verbatim inputs, not useful for reflection).
        """
        if memory_types is None:
            memory_types = ["episodic", "semantic", "reflections"]

        seen_ids: set = set()
        all_results: List[Dict] = []

        for keyword in _extract_keywords(query):
            for r in search(keyword, memory_types=memory_types, config=self.config):
                mem = r.get("memory", {})
                mem_id = mem.get("id", "")
                if mem_id and mem_id not in seen_ids:
                    seen_ids.add(mem_id)
                    all_results.append(r)

        # Sort by importance descending so the LLM sees the best memories first.
        all_results.sort(
            key=lambda r: float(r.get("memory", {}).get("importance", 0) or 0),
            reverse=True,
        )

        formatted: List[Dict] = []
        for r in all_results[:limit]:
            mem = r.get("memory", {})
            entry: Dict = {
                "id":         mem.get("id", ""),
                "type":       mem.get("type", r.get("match_type", "")),
                "importance": float(mem.get("importance", 0) or 0),
            }
            for field in _CONTENT_FIELDS:
                val = mem.get(field)
                if val and str(val).strip():
                    entry["content"] = str(val)[:200]
                    break
            if entry.get("content"):
                formatted.append(entry)

        return formatted

    def handle_tool_call(self, name: str, arguments: str) -> str:
        """Dispatch a tool call by name and return JSON string result."""
        if name != "query_memory":
            return json.dumps({"error": f"Unknown tool: {name}"})
        try:
            args = json.loads(arguments)
        except Exception:
            return json.dumps({"error": "Invalid arguments JSON"})
        results = self.query(
            query=args.get("query", ""),
            memory_types=args.get("memory_types"),
        )
        return json.dumps(results, ensure_ascii=False)

    def _handle_bus_query(self, message: Dict) -> str:
        """Bus entry point — called via bus.request("memory.query", msg).

        Registered transiently by generate_with_memory() around each LLM call.
        Returns the JSON string result expected by the LLM tool-call loop.
        """
        payload = message.get("payload", {})
        return self.handle_tool_call(
            payload.get("name", ""),
            payload.get("arguments", "{}"),
        )
