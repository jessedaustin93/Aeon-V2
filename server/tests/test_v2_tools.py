import pytest

from aeon.core.config import Config
from aeon.tools import all_handlers
from aeon.tools import fs as fs_mod
from aeon.tools import memory as memory_mod
from aeon.tools import mesh as mesh_mod
from aeon.tools import vault as vault_mod
from aeon.tools import web as web_mod


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path / "data"))
    cfg = Config()
    cfg.memory_path.mkdir(parents=True, exist_ok=True)
    cfg.vault_path.mkdir(parents=True, exist_ok=True)
    return cfg


# ------------------------------------------------------------------ registry

def test_all_handlers_names_match_definitions(config):
    handlers, definitions = all_handlers(config)
    assert set(handlers) == {d.name for d in definitions}
    assert "shell_run" in handlers


def test_only_shell_requires_approval(config):
    _, definitions = all_handlers(config)
    gated = {d.name for d in definitions if d.approval_required}
    assert gated == {"shell_run"}


# ------------------------------------------------------------------------ fs

def test_fs_read_inside_data_root(config):
    target = config.base_path / "note.txt"
    target.write_text("hello aeon", encoding="utf-8")
    result = fs_mod.fs_read({"path": str(target)}, config)
    assert result["text"] == "hello aeon"


def test_fs_read_refuses_outside_roots(config, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(PermissionError):
        fs_mod.fs_read({"path": str(outside)}, config)


def test_fs_extra_roots_env(config, tmp_path, monkeypatch):
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "ok.txt").write_text("fine", encoding="utf-8")
    monkeypatch.setenv("AEON_TOOLS_FS_ROOTS", str(extra))
    result = fs_mod.fs_read({"path": str(extra / "ok.txt")}, config)
    assert result["text"] == "fine"


def test_fs_list(config):
    (config.base_path / "sub").mkdir()
    (config.base_path / "a.txt").write_text("x", encoding="utf-8")
    result = fs_mod.fs_list({"path": str(config.base_path)}, config)
    names = {e["name"]: e["type"] for e in result["entries"]}
    assert names["a.txt"] == "file"
    assert names["sub"] == "dir"


# ----------------------------------------------------------------------- web

FIXTURE_PAGE = """
<html><head><title>Test Page</title><style>body{}</style></head>
<body><script>var x=1;</script><h1>Header</h1><p>Body text here.</p></body></html>
"""

FIXTURE_SEARCH = """
<div class="result">
<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fsdr">SDR Guide</a>
<a class="result__snippet" href="#">All about <b>SDR</b> radios</a>
</div>
"""


def test_web_fetch_extracts_text(config, monkeypatch):
    monkeypatch.setattr(web_mod, "_http_get", lambda url, timeout=20.0: FIXTURE_PAGE)
    result = web_mod.web_fetch({"url": "http://x"}, config)
    assert result["title"] == "Test Page"
    assert "Body text here." in result["text"]
    assert "var x=1" not in result["text"]


def test_web_fetch_refuses_file_scheme(config):
    with pytest.raises(PermissionError):
        web_mod.web_fetch({"url": "file:///etc/passwd"}, config)


def test_web_fetch_refuses_loopback_and_metadata(config):
    for url in ("http://localhost:1234/v1", "http://127.0.0.1:8787/",
                "http://169.254.169.254/latest/meta-data/"):
        with pytest.raises(PermissionError):
            web_mod.web_fetch({"url": url}, config)


def test_web_fetch_local_override(config, monkeypatch):
    monkeypatch.setenv("AEON_TOOLS_WEB_ALLOW_LOCAL", "1")
    monkeypatch.setattr(web_mod, "_http_get_transport", None, raising=False)
    monkeypatch.setattr(
        web_mod.urllib.request, "urlopen",
        lambda req, timeout=0: (_ for _ in ()).throw(OSError("net disabled")),
    )
    with pytest.raises(OSError):  # passes the URL check, fails only at network
        web_mod.web_fetch({"url": "http://127.0.0.1:9/"}, config)


def test_web_search_parses_results(config, monkeypatch):
    monkeypatch.setattr(web_mod, "_http_get",
                        lambda url, timeout=20.0, data=None: FIXTURE_SEARCH)
    result = web_mod.web_search({"query": "sdr"}, config)
    assert result["results"][0]["title"] == "SDR Guide"
    assert result["results"][0]["url"] == "https://example.com/sdr"


def test_web_search_uses_post_body(config, monkeypatch):
    seen = {}

    def spy(url, timeout=20.0, data=None):
        seen["url"] = url
        seen["data"] = data
        return FIXTURE_SEARCH

    monkeypatch.setattr(web_mod, "_http_get", spy)
    web_mod.web_search({"query": "sdr radios"}, config)
    assert seen["url"] == "https://html.duckduckgo.com/html/"
    assert seen["data"] is not None
    assert b"sdr" in seen["data"]


# -------------------------------------------------------------------- memory

def test_memory_save_and_search_roundtrip(config):
    saved = memory_mod.memory_save(
        {"text": "The GTX 1080 FE lives in the T5810 tower.", "source": "test"}, config
    )
    assert saved["raw_id"]
    found = memory_mod.memory_search({"query": "GTX 1080"}, config)
    assert any("GTX 1080" in r["text"] for r in found["results"])


# --------------------------------------------------------------------- vault

# ---------------------------------------------------------------------- mesh

def test_mesh_post_unconfigured(config, monkeypatch):
    monkeypatch.delenv("AEON_MESH_HUB", raising=False)
    monkeypatch.delenv("AEON_MESH_TOKEN", raising=False)
    result = mesh_mod.mesh_post({"recipient": "claude@x1", "content": "hi"}, config)
    assert "error" in result


def test_mesh_post_configured(config, monkeypatch):
    monkeypatch.setenv("AEON_MESH_HUB", "http://hub:8787")
    monkeypatch.setenv("AEON_MESH_TOKEN", "tok")
    posted = {}

    class FakeClient:
        configured = True

        def __init__(self, cfg):
            pass

        def post_message(self, thread_id, recipient, content, kind="reply"):
            posted.update(dict(thread_id=thread_id, recipient=recipient, content=content))
            return {"id": 99}

    monkeypatch.setattr(mesh_mod, "MeshClient", FakeClient)
    result = mesh_mod.mesh_post(
        {"recipient": "claude@x1", "content": "status?", "thread_id": "t1"}, config
    )
    assert result == {"posted": True, "message_id": 99}
    assert posted["recipient"] == "claude@x1"


def test_vault_unconfigured_returns_error(config):
    config.master_vault_path = None
    result = vault_mod.vault_search({"query": "anything"}, config)
    assert "error" in result


def test_vault_read_refuses_escape(config, tmp_path):
    mv = tmp_path / "mv"
    mv.mkdir()
    (mv / "note.md").write_text("# hi", encoding="utf-8")
    config.master_vault_path = mv
    config.master_vault_enabled = True
    result = vault_mod.vault_read({"path": "note.md"}, config)
    assert result["text"] == "# hi"
    with pytest.raises(PermissionError):
        vault_mod.vault_read({"path": "../escape.md"}, config)
