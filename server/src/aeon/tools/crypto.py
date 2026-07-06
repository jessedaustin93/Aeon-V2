"""Crypto market data via Crypto.com's public REST API (no keys, read-only).

Groundwork for later trading, but this only reads public ticker data.
"""
import json
import urllib.parse
import urllib.request
from typing import Dict

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition

_BASE = "https://api.crypto.com/exchange/v1/public/get-tickers"


def _normalize(symbol: str) -> str:
    s = symbol.strip().upper()
    return s if "_" in s else f"{s}_USD"


def _http_get(url: str, timeout: float = 15.0) -> Dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Aeon-V2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ticker(symbol: str) -> Dict:
    instrument = _normalize(symbol)
    url = f"{_BASE}?instrument_name={urllib.parse.quote(instrument)}"
    data = _http_get(url)
    rows = (data.get("result") or {}).get("data") or []
    if not rows:
        raise ValueError(f"no ticker for '{instrument}'")
    return rows[0]


def _num(row: Dict, key: str):
    val = row.get(key)
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def crypto_price(arguments: Dict, config: Config) -> Dict:
    row = _ticker(arguments["symbol"])
    change = _num(row, "c")
    return {
        "symbol": row.get("i"),
        "price": _num(row, "a"),
        "change_24h_pct": round(change * 100, 4) if change is not None else None,
        "high_24h": _num(row, "h"),
        "low_24h": _num(row, "l"),
    }


def crypto_market(arguments: Dict, config: Config) -> Dict:
    row = _ticker(arguments["symbol"])
    change = _num(row, "c")
    return {
        "symbol": row.get("i"),
        "price": _num(row, "a"),
        "bid": _num(row, "b"),
        "ask": _num(row, "k"),
        "high_24h": _num(row, "h"),
        "low_24h": _num(row, "l"),
        "volume_24h": _num(row, "v"),
        "change_24h_pct": round(change * 100, 4) if change is not None else None,
    }


DEFINITIONS = [
    ToolDefinition(
        name="crypto_price",
        description="Get the current price and 24h move for a crypto symbol (e.g. BTC, ETH_USDT).",
        parameters={"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]},
        tags=["crypto"],
        approval_required=False,
    ),
    ToolDefinition(
        name="crypto_market",
        description="Get fuller market data (bid/ask/high/low/volume) for a crypto symbol.",
        parameters={"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]},
        tags=["crypto"],
        approval_required=False,
    ),
]

HANDLERS = {"crypto_price": crypto_price, "crypto_market": crypto_market}
