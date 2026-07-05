import json

from aeon.core.config import Config
from aeon.models.router import ModelRouter, Worker, discover_workers


def _write_models_json(root, data):
    root.mkdir(parents=True, exist_ok=True)
    (root / "models.json").write_text(json.dumps(data), encoding="utf-8")


def test_env_fallback_single_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AEON_LLM_BASE_URL", "http://gpu:1234/v1")
    monkeypatch.setenv("AEON_LLM_CHAT_MODEL", "qwen-chat")
    router = ModelRouter(Config())
    assert len(router.workers) == 1
    assert router.workers[0].base_url == "http://gpu:1234/v1"
    client, model = router.resolve("chat")
    assert model == "qwen-chat"
    assert client.base_url == "http://gpu:1234/v1"


def test_v1_env_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    for var in ("AEON_LLM_BASE_URL", "AEON_LLM_CHAT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AEON_V1_LLM_BASE_URL", "http://old:1234/v1")
    monkeypatch.setenv("AEON_V1_LLM_MODEL", "old-chat")
    router = ModelRouter(Config())
    client, model = router.resolve("chat")
    assert client.base_url == "http://old:1234/v1"
    assert model == "old-chat"


def test_models_json_roles_and_priority(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    _write_models_json(tmp_path, {
        "roles": {"chat": "big-model"},
        "workers": [
            {"name": "slow", "base_url": "http://slow/v1", "models": ["big-model"], "priority": 1},
            {"name": "fast", "base_url": "http://fast/v1", "models": ["big-model"], "priority": 9},
            {"name": "other", "base_url": "http://other/v1", "models": ["tiny"], "priority": 99},
        ],
    })
    router = ModelRouter(Config())
    client, model = router.resolve("chat")
    assert model == "big-model"
    assert client.base_url == "http://fast/v1"


def test_unhealthy_worker_skipped(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    _write_models_json(tmp_path, {
        "roles": {"chat": "m"},
        "workers": [
            {"name": "a", "base_url": "http://a/v1", "models": ["*"], "priority": 9},
            {"name": "b", "base_url": "http://b/v1", "models": ["*"], "priority": 1},
        ],
    })
    router = ModelRouter(Config())
    router.workers[0].healthy = False
    client, _ = router.resolve("chat")
    assert client.base_url == "http://b/v1"


def test_resolve_unknown_role_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    router = ModelRouter(Config())
    try:
        router.resolve("nope")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_discover_workers_skips_unreachable():
    def probe(base_url):
        if "down" in base_url:
            raise OSError("unreachable")
        return ["model-a"]

    workers = discover_workers(
        ["http://up:1234/v1", "http://down:1234/v1"], http_probe=probe
    )
    assert [w.base_url for w in workers] == ["http://up:1234/v1"]
    assert workers[0].name == "up"
    assert workers[0].models == ["*"]


def test_add_workers_dedupes(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AEON_LLM_BASE_URL", "http://local:1234/v1")
    router = ModelRouter(Config())
    router.add_workers([Worker(name="a", base_url="http://a/v1")])
    router.add_workers([Worker(name="a-again", base_url="http://a/v1")])  # dupe
    urls = [w.base_url for w in router.workers]
    assert urls.count("http://a/v1") == 1


def test_mesh_llm_workers_env_discovery(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AEON_LLM_BASE_URL", "http://local:1234/v1")
    monkeypatch.setenv("AEON_MESH_LLM_WORKERS", "http://t3610:1234/v1,http://t5810b:1234/v1")
    monkeypatch.setattr(
        "aeon.models.router.ChatClient.list_models",
        lambda self: ["m"],  # all reachable
    )
    router = ModelRouter(Config())
    urls = [w.base_url for w in router.workers]
    assert "http://t3610:1234/v1" in urls
    assert "http://t5810b:1234/v1" in urls


def test_health_check_updates(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    _write_models_json(tmp_path, {
        "roles": {"chat": "m"},
        "workers": [{"name": "a", "base_url": "http://a/v1", "models": ["*"], "priority": 1}],
    })
    router = ModelRouter(Config())

    def boom(self):
        raise OSError("down")

    monkeypatch.setattr("aeon.models.client.ChatClient.list_models", boom)
    status = router.health_check()
    assert status == {"a": False}
    assert router.workers[0].healthy is False
