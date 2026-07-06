import pytest

from aeon.core.config import Config
from aeon.tools import crypto as c


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    return Config()


TICKER = {
    "result": {"data": [{
        "i": "BTC_USD", "h": "63958.54", "l": "61258.01", "a": "62055.25",
        "v": "5301.75", "vv": "332115193.06", "c": "-0.0113",
        "b": "62059.48", "k": "62059.49", "t": 1783350090505,
    }]}
}


def test_normalize_adds_usd():
    assert c._normalize("btc") == "BTC_USD"
    assert c._normalize("ETH_USDT") == "ETH_USDT"


def test_crypto_price(config, monkeypatch):
    seen = {}
    def fake_get(url, timeout=15.0):
        seen["url"] = url
        return TICKER
    monkeypatch.setattr(c, "_http_get", fake_get)
    r = c.crypto_price({"symbol": "btc"}, config)
    assert r["symbol"] == "BTC_USD"
    assert r["price"] == 62055.25
    assert r["change_24h_pct"] == -1.13
    assert "BTC_USD" in seen["url"]


def test_crypto_market(config, monkeypatch):
    monkeypatch.setattr(c, "_http_get", lambda url, timeout=15.0: TICKER)
    r = c.crypto_market({"symbol": "BTC_USD"}, config)
    assert r["bid"] == 62059.48
    assert r["ask"] == 62059.49
    assert r["volume_24h"] == 5301.75


def test_unknown_symbol_raises(config, monkeypatch):
    monkeypatch.setattr(c, "_http_get", lambda url, timeout=15.0: {"result": {"data": []}})
    with pytest.raises(ValueError):
        c.crypto_price({"symbol": "NOPE"}, config)


def test_crypto_tools_are_not_gated(config):
    assert all(d.approval_required is False for d in c.DEFINITIONS)
