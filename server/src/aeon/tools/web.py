"""Web tools: fetch a page as text, search via DuckDuckGo HTML."""
import html
import html.parser
import os
import re
import urllib.parse
import urllib.request
from typing import Dict, List

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition

MAX_TEXT_CHARS = 100_000
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) Aeon-V2"


def _check_url(url: str) -> None:
    """Refuse non-HTTP schemes (file:// would bypass fs scoping) and
    loopback/link-local targets (SSRF into local services / metadata),
    unless AEON_TOOLS_WEB_ALLOW_LOCAL=1. Private LAN addresses stay
    allowed — fetching docs from mesh machines is a supported use."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise PermissionError(f"URL scheme not allowed: {parsed.scheme or '(none)'}")
    if os.environ.get("AEON_TOOLS_WEB_ALLOW_LOCAL", "").strip() == "1":
        return
    host = (parsed.hostname or "").lower()
    blocked = (
        host in ("localhost", "ip6-localhost")
        or host.startswith("127.")
        or host in ("::1", "0.0.0.0")
        or host.startswith("169.254.")
        or host.startswith("fe80:")
    )
    if blocked:
        raise PermissionError(f"Refusing to fetch local/link-local address: {host}")


def _http_get(url: str, timeout: float = 20.0) -> str:
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


class _TextExtractor(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__()
        self.parts: List[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data.strip()
        elif not self._skip_depth and data.strip():
            self.parts.append(data.strip())


def web_fetch(arguments: Dict, config: Config) -> Dict:
    url = arguments["url"]
    raw = _http_get(url)
    extractor = _TextExtractor()
    extractor.feed(raw)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(extractor.parts))
    return {"url": url, "title": extractor.title, "text": text[:MAX_TEXT_CHARS]}


_RESULT_RE = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'.*?(?:class="[^"]*result__snippet[^"]*"[^>]*>(?P<snippet>.*?)</a>)?',
    re.DOTALL,
)


def _strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _decode_ddg_url(url: str) -> str:
    # DuckDuckGo HTML results wrap targets as //duckduckgo.com/l/?uddg=<encoded>
    parsed = urllib.parse.urlparse(url, scheme="https")
    if parsed.path.startswith("/l/"):
        query = urllib.parse.parse_qs(parsed.query)
        target = query.get("uddg", [""])[0]
        if target:
            return target
    return url


def web_search(arguments: Dict, config: Config) -> Dict:
    query = arguments["query"]
    limit = int(arguments.get("limit", 5))
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    raw = _http_get(url)
    results = []
    for match in _RESULT_RE.finditer(raw):
        results.append(
            {
                "title": _strip_tags(match.group("title")),
                "url": _decode_ddg_url(match.group("url")),
                "snippet": _strip_tags(match.group("snippet") or ""),
            }
        )
        if len(results) >= limit:
            break
    return {"query": query, "results": results}


DEFINITIONS = [
    ToolDefinition(
        name="web_fetch",
        description="Fetch a URL and return its readable text content.",
        parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        tags=["web"],
        approval_required=False,
    ),
    ToolDefinition(
        name="web_search",
        description="Search the web (DuckDuckGo). Returns titles, URLs, and snippets.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "description": "Max results, default 5"},
            },
            "required": ["query"],
        },
        tags=["web"],
        approval_required=False,
    ),
]

HANDLERS = {"web_fetch": web_fetch, "web_search": web_search}
