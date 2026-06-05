#!/usr/bin/env python3
"""Read-only Project X / PRJX LP monitor for Hermes cron.

The script intentionally uses only Python's standard library so it can run from
Hermes cron without a project virtualenv.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BALANCE_OF = "70a08231"
OWNER_INDEX_SELECTOR = "2f745c59"
POSITIONS = "99fbab88"
COLLECT = "fc6f7865"
FACTORY = "c45a0155"
GET_POOL = "1698ee82"
SLOT0 = "3850c7bd"
SYMBOL = "95d89b41"
DECIMALS = "313ce567"
SWAP_TOPIC0 = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
RPC_LAST_REQUEST_TS = 0.0


@dataclass
class TokenMeta:
    address: str
    symbol: str
    decimals: int


@dataclass
class Position:
    position_id: str
    pool: str
    token0: TokenMeta
    token1: TokenMeta
    tick: int | None
    tick_lower: int
    tick_upper: int
    price: float | None
    lower_price: float | None
    upper_price: float | None
    amount0: float | None
    amount1: float | None
    fee_amount0: float | None
    fee_amount1: float | None
    liquidity: int | None
    pool_address: str | None
    value_usd: float | None
    cost_basis_usd: float | None
    fees_usd: float
    rewards_usd: float
    entry_price: float | None
    swap_price: float | None = None
    swap_age_blocks: int | None = None
    swap_price_source: str | None = None


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(2)


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        die(f"config not found: {path}")
    except json.JSONDecodeError as exc:
        die(f"invalid JSON in {path}: {exc}")


def rpc_min_interval_seconds() -> float:
    try:
        return max(float(os.environ.get("PRJX_LP_RPC_MIN_INTERVAL_SECONDS", "0.25") or 0), 0.0)
    except ValueError:
        return 0.25


def wait_for_rpc_slot() -> None:
    global RPC_LAST_REQUEST_TS
    min_interval = rpc_min_interval_seconds()
    if min_interval <= 0:
        return
    now = time.time()
    delay = RPC_LAST_REQUEST_TS + min_interval - now
    if delay > 0:
        time.sleep(delay)
    RPC_LAST_REQUEST_TS = time.time()


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def rpc_call(rpc_url: str, method: str, params: list[Any]) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        rpc_url,
        data=body,
        headers={"content-type": "application/json", "user-agent": "prjx-lp-sentinel/1.0"},
        method="POST",
    )
    for attempt in range(3):
        try:
            wait_for_rpc_slot()
            with urllib.request.urlopen(req, timeout=20) as res:
                payload = json.loads(res.read().decode())
        except urllib.error.URLError as exc:
            if attempt < 2:
                time.sleep(1.0 + attempt)
                continue
            raise RuntimeError(f"RPC request failed: {exc}") from exc
        if payload.get("error"):
            message = str(payload["error"].get("message", payload["error"])) if isinstance(payload["error"], dict) else str(payload["error"])
            if "rate limit" in message.lower() and attempt < 2:
                time.sleep(1.5 + attempt * 1.5)
                continue
            raise RuntimeError(f"RPC error: {payload['error']}")
        return payload.get("result")
    raise RuntimeError("RPC request failed after retries")


def eth_call(rpc_url: str, to: str, data: str, from_address: str | None = None) -> str:
    call = {"to": to, "data": data}
    if from_address:
        call["from"] = clean_address(from_address)
    result = rpc_call(rpc_url, "eth_call", [call, "latest"])
    if not isinstance(result, str) or not result.startswith("0x"):
        raise RuntimeError(f"bad eth_call result for {to}: {result!r}")
    return result


def clean_address(address: str) -> str:
    address = address.strip()
    if not address.startswith("0x") or len(address) != 42:
        die(f"bad address: {address}")
    return "0x" + address[2:].lower()


def pad_word(hex_value: str) -> str:
    value = hex_value[2:] if hex_value.startswith("0x") else hex_value
    return value.rjust(64, "0")


def encode_address(address: str) -> str:
    return pad_word(clean_address(address)[2:])


def encode_uint(value: int) -> str:
    if value < 0:
        raise ValueError("uint cannot be negative")
    return hex(value)[2:].rjust(64, "0")


def words(result: str) -> list[str]:
    data = result[2:] if result.startswith("0x") else result
    return [data[i : i + 64] for i in range(0, len(data), 64) if data[i : i + 64]]


def decode_uint(word: str) -> int:
    return int(word, 16)


def decode_int(word: str) -> int:
    value = int(word, 16)
    if value >= 1 << 255:
        value -= 1 << 256
    return value


def decode_address(word: str) -> str:
    return "0x" + word[-40:].lower()


def decode_string_or_bytes32(result: str) -> str | None:
    ws = words(result)
    if not ws:
        return None
    if len(ws) == 1:
        raw = bytes.fromhex(ws[0]).rstrip(b"\x00")
        try:
            text = raw.decode("utf-8").strip()
            return text or None
        except UnicodeDecodeError:
            return None
    try:
        offset = decode_uint(ws[0]) // 32
        size = decode_uint(ws[offset])
        data_words = ws[offset + 1 :]
        raw = bytes.fromhex("".join(data_words))[:size]
        return raw.decode("utf-8").strip() or None
    except Exception:
        return None


def safe_eth_call(rpc_url: str, to: str, data: str) -> str | None:
    try:
        return eth_call(rpc_url, to, data)
    except Exception:
        return None


def get_token_meta(rpc_url: str, address: str, cache: dict[str, TokenMeta]) -> TokenMeta:
    address = clean_address(address)
    if address in cache:
        return cache[address]

    symbol = None
    raw_symbol = safe_eth_call(rpc_url, address, "0x" + SYMBOL)
    if raw_symbol:
        symbol = decode_string_or_bytes32(raw_symbol)
    raw_decimals = safe_eth_call(rpc_url, address, "0x" + DECIMALS)
    decimals = 18
    if raw_decimals:
        try:
            decimals = decode_uint(words(raw_decimals)[0])
        except Exception:
            decimals = 18
    meta = TokenMeta(address=address, symbol=symbol or address[:8], decimals=decimals)
    cache[address] = meta
    return meta


def tick_to_price(tick: int, token0_decimals: int, token1_decimals: int) -> float:
    return (1.0001 ** tick) * (10 ** token0_decimals) / (10 ** token1_decimals)


def amounts_from_liquidity(
    liquidity: int,
    tick: int,
    tick_lower: int,
    tick_upper: int,
    token0_decimals: int,
    token1_decimals: int,
) -> tuple[float, float]:
    sqrt_p = math.sqrt(1.0001 ** tick)
    sqrt_l = math.sqrt(1.0001 ** tick_lower)
    sqrt_u = math.sqrt(1.0001 ** tick_upper)

    if tick <= tick_lower:
        amount0_raw = liquidity * (sqrt_u - sqrt_l) / (sqrt_l * sqrt_u)
        amount1_raw = 0.0
    elif tick >= tick_upper:
        amount0_raw = 0.0
        amount1_raw = liquidity * (sqrt_u - sqrt_l)
    else:
        amount0_raw = liquidity * (sqrt_u - sqrt_p) / (sqrt_p * sqrt_u)
        amount1_raw = liquidity * (sqrt_p - sqrt_l)

    return amount0_raw / (10 ** token0_decimals), amount1_raw / (10 ** token1_decimals)


def price_from_sqrt_price_x96(sqrt_price_x96: int, token0_decimals: int, token1_decimals: int) -> float | None:
    if sqrt_price_x96 <= 0:
        return None
    ratio = sqrt_price_x96 / (1 << 96)
    price = ratio * ratio * (10 ** token0_decimals) / (10 ** token1_decimals)
    return price if price > 0 and math.isfinite(price) else None


def block_number(rpc_url: str) -> int:
    raw = rpc_call(rpc_url, "eth_blockNumber", [])
    if not isinstance(raw, str) or not raw.startswith("0x"):
        raise RuntimeError(f"bad eth_blockNumber result: {raw!r}")
    return int(raw, 16)


def decode_swap_log_price(log: dict[str, Any], token0: TokenMeta, token1: TokenMeta) -> dict[str, Any] | None:
    data_words = words(str(log.get("data", "0x")))
    if len(data_words) < 5:
        return None
    amount0_raw = decode_int(data_words[0])
    amount1_raw = decode_int(data_words[1])
    sqrt_price_x96 = decode_uint(data_words[2])
    amount0 = abs(amount0_raw) / (10 ** token0.decimals)
    amount1 = abs(amount1_raw) / (10 ** token1.decimals)
    amount_price = amount1 / amount0 if amount0 > 0 and amount1 > 0 else None
    sqrt_price = price_from_sqrt_price_x96(sqrt_price_x96, token0.decimals, token1.decimals)
    price = amount_price if amount_price and math.isfinite(amount_price) else sqrt_price
    if price is None or price <= 0 or not math.isfinite(price):
        return None
    block_raw = str(log.get("blockNumber", "0x0"))
    return {
        "price": price,
        "block": int(block_raw, 16) if block_raw.startswith("0x") else int(block_raw),
        "source": "swap_amounts" if amount_price else "swap_sqrt_price",
    }


def recent_swap_rate(
    rpc_url: str,
    pool_address: str,
    token0: TokenMeta,
    token1: TokenMeta,
    latest_block: int,
    lookback_blocks: int,
    max_block_range: int = 1000,
) -> dict[str, Any] | None:
    earliest_block = max(latest_block - max(lookback_blocks, 1) + 1, 0)

    def log_sort_key(log: dict[str, Any]) -> tuple[int, int, int]:
        def parse_hexish(value: Any) -> int:
            text = str(value or "0x0")
            return int(text, 16) if text.startswith("0x") else int(text)

        return (
            parse_hexish(log.get("blockNumber")),
            parse_hexish(log.get("transactionIndex")),
            parse_hexish(log.get("logIndex")),
        )

    to_block = latest_block
    while to_block >= earliest_block:
        chunk_size = max(1, min(max_block_range, to_block - earliest_block + 1))
        from_block = to_block - chunk_size + 1
        logs = rpc_call(
            rpc_url,
            "eth_getLogs",
            [
                {
                    "address": clean_address(pool_address),
                    "fromBlock": hex(from_block),
                    "toBlock": hex(to_block),
                    "topics": [SWAP_TOPIC0],
                }
            ],
        )
        if isinstance(logs, list) and logs:
            for log in sorted(logs, key=log_sort_key, reverse=True):
                decoded = decode_swap_log_price(log, token0, token1)
                if decoded:
                    return decoded
        to_block = from_block - 1
    return None


def safe_recent_swap_rate(
    rpc_url: str,
    pool_address: str,
    token0: TokenMeta,
    token1: TokenMeta,
    latest_block: int,
    lookback_blocks: int,
    max_block_range: int = 1000,
) -> dict[str, Any] | None:
    try:
        return recent_swap_rate(rpc_url, pool_address, token0, token1, latest_block, lookback_blocks, max_block_range)
    except Exception:
        return None


def token_usd_prices(token0: TokenMeta, token1: TokenMeta, pair_price: float | None, cfg: dict[str, Any]) -> tuple[float | None, float | None]:
    if pair_price is None or pair_price <= 0:
        return None, None
    pricing = cfg.get("pricing", {})
    stable_symbols = {str(s).upper() for s in pricing.get("stable_symbols", [])}
    usd_prices = pricing.get("usd_prices", {})

    token0_symbol = token0.symbol.upper()
    token1_symbol = token1.symbol.upper()
    token0_addr = token0.address.lower()
    token1_addr = token1.address.lower()

    price0 = None
    price1 = None

    if token0_symbol in stable_symbols or token0_addr in usd_prices:
        price0 = float(usd_prices.get(token0_addr, usd_prices.get(token0.symbol, 1)) or 1)
        price1 = price0 / pair_price
    elif token1_symbol in stable_symbols or token1_addr in usd_prices:
        price1 = float(usd_prices.get(token1_addr, usd_prices.get(token1.symbol, 1)) or 1)
        price0 = price1 * pair_price
    else:
        p0 = usd_prices.get(token0_addr, usd_prices.get(token0.symbol))
        p1 = usd_prices.get(token1_addr, usd_prices.get(token1.symbol))
        price0 = float(p0) if p0 else None
        price1 = float(p1) if p1 else None

    return price0, price1


def amounts_usd_value(
    token0: TokenMeta,
    amount0: float | None,
    token1: TokenMeta,
    amount1: float | None,
    pair_price: float | None,
    cfg: dict[str, Any],
) -> float | None:
    if amount0 is None or amount1 is None:
        return None
    price0, price1 = token_usd_prices(token0, token1, pair_price, cfg)
    if price0 is None or price1 is None:
        return None
    return amount0 * price0 + amount1 * price1


def infer_usd_value(position: Position, cfg: dict[str, Any]) -> float | None:
    if position.value_usd is not None:
        return position.value_usd
    return amounts_usd_value(position.token0, position.amount0, position.token1, position.amount1, position.price, cfg)


def enrich_usd_prices_from_stable_pairs(positions: list[Position], cfg: dict[str, Any]) -> None:
    pricing = cfg.setdefault("pricing", {})
    usd_prices = pricing.setdefault("usd_prices", {})
    stable_symbols = {str(s).upper() for s in pricing.get("stable_symbols", [])}

    derived: dict[str, list[float]] = {}

    def add_price(token: TokenMeta, value: float) -> None:
        if value <= 0 or not math.isfinite(value):
            return
        derived.setdefault(token.address.lower(), []).append(value)
        derived.setdefault(token.symbol, []).append(value)

    def commit_derived() -> None:
        for key, values in derived.items():
            if key not in usd_prices and values:
                usd_prices[key] = sum(values) / len(values)

    def known_price(token: TokenMeta) -> float | None:
        value = usd_prices.get(token.address.lower(), usd_prices.get(token.symbol))
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    for pos in positions:
        if not pos.price or pos.price <= 0:
            continue
        token0_stable = pos.token0.symbol.upper() in stable_symbols
        token1_stable = pos.token1.symbol.upper() in stable_symbols
        if token1_stable and not token0_stable:
            add_price(pos.token1, 1.0)
            add_price(pos.token0, pos.price)
        elif token0_stable and not token1_stable:
            add_price(pos.token0, 1.0)
            add_price(pos.token1, 1.0 / pos.price)
    commit_derived()

    changed = True
    while changed:
        changed = False
        for pos in positions:
            if not pos.price or pos.price <= 0:
                continue
            p0 = known_price(pos.token0)
            p1 = known_price(pos.token1)
            before = len(usd_prices)
            if p0 is not None and p1 is None:
                add_price(pos.token1, p0 / pos.price)
                commit_derived()
            elif p1 is not None and p0 is None:
                add_price(pos.token0, p1 * pos.price)
                commit_derived()
            if len(usd_prices) > before:
                changed = True


def http_json(url: str, *, data: bytes | None = None, timeout: float = 8.0) -> Any:
    headers = {"User-Agent": "prjx-lp-sentinel/1.0", "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode())


def utc_day(ms_or_s: int) -> str:
    if ms_or_s > 10_000_000_000:
        ms_or_s //= 1000
    return time.strftime("%Y-%m-%d", time.gmtime(ms_or_s))


def finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def quantile(values: list[float], q: float) -> float | None:
    clean = sorted(v for v in values if math.isfinite(v))
    if not clean:
        return None
    idx = min(len(clean) - 1, max(0, round((len(clean) - 1) * q)))
    return clean[idx]


def hyperliquid_daily_candles(coin: str, start_ms: int, end_ms: int, timeout: float) -> dict[str, dict[str, float]]:
    payload = {
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": "1d", "startTime": start_ms, "endTime": end_ms},
    }
    rows = http_json("https://api.hyperliquid.xyz/info", data=json.dumps(payload).encode(), timeout=timeout)
    out: dict[str, dict[str, float]] = {}
    for row in rows or []:
        close = finite_float(row.get("c"))
        high = finite_float(row.get("h"))
        low = finite_float(row.get("l"))
        open_ = finite_float(row.get("o"))
        ts = row.get("t")
        if close is None or high is None or low is None or ts is None or close <= 0:
            continue
        out[utc_day(int(ts))] = {
            "open": open_ if open_ is not None else close,
            "high": high,
            "low": low,
            "close": close,
            "range_pct": (high - low) / close * 100,
            "abs_ret_pct": abs(close - (open_ if open_ is not None else close)) / (open_ if open_ else close) * 100,
        }
    return out


def deribit_dvol(currency: str, start_ms: int, end_ms: int, timeout: float) -> dict[str, dict[str, float]]:
    url = (
        "https://www.deribit.com/api/v2/public/get_volatility_index_data"
        f"?currency={currency}&start_timestamp={start_ms}&end_timestamp={end_ms}&resolution=1D"
    )
    rows = http_json(url, timeout=timeout).get("result", {}).get("data", [])
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        if len(row) < 5:
            continue
        close = finite_float(row[4])
        if close is None:
            continue
        out[utc_day(int(row[0]))] = {"close": close}
    return out


def yahoo_daily(symbol: str, days: int, timeout: float) -> dict[str, dict[str, float]]:
    period2 = int(time.time())
    period1 = period2 - days * 24 * 3600
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={period1}&period2={period2}&interval=1d"
    chart = http_json(url, timeout=timeout).get("chart", {}).get("result", [])
    if not chart:
        return {}
    result = chart[0]
    quote = result.get("indicators", {}).get("quote", [{}])[0]
    out: dict[str, dict[str, float]] = {}
    for ts, close in zip(result.get("timestamp", []), quote.get("close", [])):
        close_f = finite_float(close)
        if close_f is not None:
            out[utc_day(int(ts))] = {"close": close_f}
    return out


def current_hype_usd_price(positions: list[Position], cfg: dict[str, Any]) -> float | None:
    pricing = cfg.get("pricing", {})
    stable_symbols = {str(s).upper() for s in pricing.get("stable_symbols", [])}
    hype_symbols = {"HYPE", "WHYPE"}
    for pos in positions:
        if not pos.price or pos.price <= 0:
            continue
        token0 = pos.token0.symbol.upper()
        token1 = pos.token1.symbol.upper()
        if token0 in hype_symbols and token1 in stable_symbols:
            return pos.price
        if token1 in hype_symbols and token0 in stable_symbols:
            return 1.0 / pos.price
    usd_prices = pricing.get("usd_prices", {})
    for key in ("WHYPE", "HYPE"):
        value = finite_float(usd_prices.get(key))
        if value and value > 0:
            return value
    return None


def latest_close(source: dict[str, dict[str, float]], field: str = "close") -> float | None:
    if not source:
        return None
    for day in reversed(sorted(source)):
        value = finite_float(source.get(day, {}).get(field))
        if value is not None:
            return value
    return None


def build_vol_forecast(positions: list[Position], cfg: dict[str, Any]) -> dict[str, Any] | None:
    vol_cfg = cfg.get("vol_forecast", {})
    if not bool(vol_cfg.get("enabled", False)):
        return None

    days = int(vol_cfg.get("days", 120) or 120)
    timeout = float(vol_cfg.get("timeout_seconds", 6.0) or 6.0)
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - days * 24 * 3600 * 1000
    errors: list[str] = []

    try:
        hype = hyperliquid_daily_candles("HYPE", start_ms, now_ms, timeout)
    except Exception as exc:
        hype = {}
        errors.append(f"HYPE candles: {type(exc).__name__}")

    context: dict[str, float | None] = {"btc_dvol": None, "eth_dvol": None, "vix": None}
    for label, fetch in (
        ("BTC DVOL", lambda: deribit_dvol("BTC", start_ms, now_ms, timeout)),
        ("ETH DVOL", lambda: deribit_dvol("ETH", start_ms, now_ms, timeout)),
        ("VIX", lambda: yahoo_daily("%5EVIX", days, timeout)),
    ):
        try:
            data = fetch()
            key = "vix" if label == "VIX" else label.lower().replace(" ", "_")
            context[key] = latest_close(data)
        except Exception as exc:
            errors.append(f"{label}: {type(exc).__name__}")

    price = current_hype_usd_price(positions, cfg)
    ranges = [row["range_pct"] for row in hype.values() if finite_float(row.get("range_pct")) is not None]
    median_pct = quantile(ranges, 0.50)
    p75_pct = quantile(ranges, 0.75)
    p90_pct = quantile(ranges, 0.90)
    last_range_pct = latest_close(hype, "range_pct")
    if price is None or p75_pct is None or p90_pct is None:
        return {
            "enabled": True,
            "error": "HYPE価格またはHYPE daily rangeを取得できません",
            "errors": errors,
            "forecast_read_only": True,
            "auto_rebalance_enabled": False,
        }

    def band(range_pct: float) -> tuple[float, float]:
        half = range_pct / 200.0
        return price * (1 - half), price * (1 + half)

    p75_lower, p75_upper = band(p75_pct)
    p90_lower, p90_upper = band(p90_pct)
    regime = "calm"
    if last_range_pct is not None and median_pct is not None:
        if last_range_pct >= p90_pct:
            regime = "extreme"
        elif last_range_pct >= p75_pct:
            regime = "wide"
        elif last_range_pct >= median_pct:
            regime = "normal"

    return {
        "enabled": True,
        "regime": regime,
        "sample_days": len(ranges),
        "current_price": price,
        "median_pct": median_pct,
        "p75_pct": p75_pct,
        "p90_pct": p90_pct,
        "last_range_pct": last_range_pct,
        "p75_lower": p75_lower,
        "p75_upper": p75_upper,
        "p90_lower": p90_lower,
        "p90_upper": p90_upper,
        "btc_dvol": context.get("btc_dvol"),
        "eth_dvol": context.get("eth_dvol"),
        "vix": context.get("vix"),
        "errors": errors,
        "forecast_read_only": True,
        "auto_rebalance_enabled": False,
    }


def regime_label(regime: str | None, ja: bool = False) -> str:
    labels_ja = {"calm": "落ち着き", "normal": "通常", "wide": "広め", "extreme": "極端"}
    return labels_ja.get(str(regime), str(regime or "n/a")) if ja else str(regime or "n/a")


def format_vol_forecast(forecast: dict[str, Any] | None, ja: bool = False) -> list[str]:
    if not forecast or not forecast.get("enabled"):
        return []
    if forecast.get("error"):
        errors = ", ".join(forecast.get("errors") or [])
        if ja:
            suffix = f" ({errors})" if errors else ""
            return [f"🌦 予測レンジ(VIX/BitVol文脈): n/a{suffix}"]
        suffix = f" ({errors})" if errors else ""
        return [f"🌦 forecast range(VIX/BitVol context): n/a{suffix}"]

    if ja:
        lines = [
            f"🌦 予測レンジ(VIX/BitVol文脈): {regime_label(forecast.get('regime'), ja=True)} / HYPE ${number(forecast.get('current_price'))}",
            f"📊 p75目安 {number(forecast.get('p75_lower'))} - {number(forecast.get('p75_upper'))} (±{number((forecast.get('p75_pct') or 0) / 2)}%)",
            f"🛡 p90広め {number(forecast.get('p90_lower'))} - {number(forecast.get('p90_upper'))} (±{number((forecast.get('p90_pct') or 0) / 2)}%)",
            f"🧩 文脈: HYPE直近日中レンジ {number(forecast.get('last_range_pct'))}% / BTC DVOL {number(forecast.get('btc_dvol'))} / ETH DVOL {number(forecast.get('eth_dvol'))} / VIX {number(forecast.get('vix'))}",
            "🔒 読み取り専用: 自動リバランスなし",
        ]
    else:
        lines = [
            f"🌦 forecast range(VIX/BitVol context): {regime_label(forecast.get('regime'))} / HYPE ${number(forecast.get('current_price'))}",
            f"📊 p75 guide {number(forecast.get('p75_lower'))} - {number(forecast.get('p75_upper'))} (±{number((forecast.get('p75_pct') or 0) / 2)}%)",
            f"🛡 p90 wide {number(forecast.get('p90_lower'))} - {number(forecast.get('p90_upper'))} (±{number((forecast.get('p90_pct') or 0) / 2)}%)",
            f"🧩 context: HYPE last daily range {number(forecast.get('last_range_pct'))}% / BTC DVOL {number(forecast.get('btc_dvol'))} / ETH DVOL {number(forecast.get('eth_dvol'))} / VIX {number(forecast.get('vix'))}",
            "🔒 read-only: auto_rebalance_enabled=false",
        ]
    if forecast.get("errors"):
        lines.append(("⚠️ 一部データ取得失敗: " if ja else "⚠️ partial fetch failures: ") + ", ".join(forecast.get("errors") or []))
    return lines


def is_hype_stable_position(pos: Position, cfg: dict[str, Any]) -> bool:
    stable_symbols = {str(s).upper() for s in cfg.get("pricing", {}).get("stable_symbols", [])}
    hype_symbols = {"HYPE", "WHYPE"}
    token0 = pos.token0.symbol.upper()
    token1 = pos.token1.symbol.upper()
    return (token0 in hype_symbols and token1 in stable_symbols) or (token1 in hype_symbols and token0 in stable_symbols)


def vol_fit_text(pos: Position, forecast: dict[str, Any] | None, ja: bool = False, cfg: dict[str, Any] | None = None) -> str | None:
    if not forecast or forecast.get("error"):
        return None
    cfg = cfg or {"pricing": {"stable_symbols": ["USDC", "USDT", "USDT0", "USD0", "USDe"]}}
    if not is_hype_stable_position(pos, cfg):
        return None
    if pos.lower_price is None or pos.upper_price is None:
        return None
    p75_lower = finite_float(forecast.get("p75_lower"))
    p75_upper = finite_float(forecast.get("p75_upper"))
    p90_lower = finite_float(forecast.get("p90_lower"))
    p90_upper = finite_float(forecast.get("p90_upper"))
    if p75_lower is None or p75_upper is None or p90_lower is None or p90_upper is None:
        return None
    covers_p75 = pos.lower_price <= p75_lower and pos.upper_price >= p75_upper
    covers_p90 = pos.lower_price <= p90_lower and pos.upper_price >= p90_upper
    if covers_p90:
        label = "p90帯までOK" if ja else "covers p90 band"
    elif covers_p75:
        label = "p75帯OK / p90は注意" if ja else "covers p75 / watch p90"
    elif pos.lower_price > p75_lower:
        label = "下限割れ注意" if ja else "lower-break watch"
    elif pos.upper_price < p75_upper:
        label = "上限抜け注意" if ja else "upper-break watch"
    else:
        label = "予測帯fit要確認" if ja else "forecast fit review"
    return f"🌦 予測fit: {label}"


def get_factory(rpc_url: str, position_manager: str, configured: str | None) -> str:
    if configured:
        return clean_address(configured)
    raw = eth_call(rpc_url, position_manager, "0x" + FACTORY)
    return decode_address(words(raw)[0])


def collectable_fee_amounts(
    rpc_url: str,
    position_manager: str,
    wallet: str,
    position_id: int,
    token0: TokenMeta,
    token1: TokenMeta,
    fallback_amount0_raw: int,
    fallback_amount1_raw: int,
) -> tuple[float | None, float | None]:
    """Read collectable fees via eth_call simulation; never signs or submits a tx."""
    amount0_raw = fallback_amount0_raw
    amount1_raw = fallback_amount1_raw
    max_uint128 = (1 << 128) - 1
    try:
        raw = eth_call(
            rpc_url,
            position_manager,
            "0x" + COLLECT + encode_uint(position_id) + encode_address(wallet) + encode_uint(max_uint128) + encode_uint(max_uint128),
            from_address=wallet,
        )
        result_words = words(raw)
        if len(result_words) >= 2:
            amount0_raw = decode_uint(result_words[0])
            amount1_raw = decode_uint(result_words[1])
    except Exception:
        pass
    return amount0_raw / (10 ** token0.decimals), amount1_raw / (10 ** token1.decimals)


def read_onchain_positions(cfg: dict[str, Any]) -> list[Position]:
    wallet = clean_address(cfg["wallet"])
    onchain = cfg.get("onchain", {})
    rpc_url = str(onchain.get("rpc_url") or die("onchain.rpc_url is required"))
    pm = clean_address(onchain.get("position_manager") or die("onchain.position_manager is required"))
    max_positions = int(onchain.get("max_positions", 80))
    include_zero = bool(onchain.get("include_zero_liquidity", False))
    position_ids_filter = {str(x) for x in onchain.get("position_ids", [])}
    meta_cache: dict[str, TokenMeta] = {}
    pricing_cfg = cfg.get("pricing", {})
    swap_cfg = pricing_cfg.get("swap_rate_overlay", {})
    swap_enabled = bool(swap_cfg.get("enabled", False))
    swap_lookback_blocks = int(swap_cfg.get("lookback_blocks", 1200) or 1200)
    swap_max_block_range = int(swap_cfg.get("max_block_range", 1000) or 1000)
    swap_latest_block = None
    swap_cache: dict[str, dict[str, Any] | None] = {}

    factory = get_factory(rpc_url, pm, onchain.get("factory") or None)
    if swap_enabled:
        try:
            swap_latest_block = block_number(rpc_url)
        except Exception:
            swap_enabled = False

    balance_raw = eth_call(rpc_url, pm, "0x" + BALANCE_OF + encode_address(wallet))
    balance = decode_uint(words(balance_raw)[0])
    limit = min(balance, max_positions)
    positions: list[Position] = []

    for idx in range(limit):
        position_id_raw = eth_call(
            rpc_url,
            pm,
            "0x" + OWNER_INDEX_SELECTOR + encode_address(wallet) + encode_uint(idx),
        )
        position_id = decode_uint(words(position_id_raw)[0])
        if position_ids_filter and str(position_id) not in position_ids_filter:
            continue

        pos_raw = eth_call(rpc_url, pm, "0x" + POSITIONS + encode_uint(position_id))
        fields = words(pos_raw)
        if len(fields) < 12:
            continue
        token0_addr = decode_address(fields[2])
        token1_addr = decode_address(fields[3])
        fee = decode_uint(fields[4])
        tick_lower = decode_int(fields[5])
        tick_upper = decode_int(fields[6])
        liquidity = decode_uint(fields[7])
        tokens_owed0_raw = decode_uint(fields[10]) if len(fields) > 10 else 0
        tokens_owed1_raw = decode_uint(fields[11]) if len(fields) > 11 else 0
        if liquidity == 0 and not include_zero:
            continue

        token0 = get_token_meta(rpc_url, token0_addr, meta_cache)
        token1 = get_token_meta(rpc_url, token1_addr, meta_cache)
        pool = f"{token0.symbol}/{token1.symbol} {fee / 10000:.2f}%"

        pool_address = None
        tick = None
        price = None
        lower_price = tick_to_price(tick_lower, token0.decimals, token1.decimals)
        upper_price = tick_to_price(tick_upper, token0.decimals, token1.decimals)
        amount0 = None
        amount1 = None
        swap_price = None
        swap_age_blocks = None
        swap_price_source = None
        fee_amount0, fee_amount1 = collectable_fee_amounts(
            rpc_url,
            pm,
            wallet,
            position_id,
            token0,
            token1,
            tokens_owed0_raw,
            tokens_owed1_raw,
        )

        try:
            pool_raw = eth_call(
                rpc_url,
                factory,
                "0x" + GET_POOL + encode_address(token0_addr) + encode_address(token1_addr) + encode_uint(fee),
            )
            pool_address = decode_address(words(pool_raw)[0])
            if int(pool_address, 16) != 0:
                slot0_raw = eth_call(rpc_url, pool_address, "0x" + SLOT0)
                slot0_words = words(slot0_raw)
                tick = decode_int(slot0_words[1])
                price = tick_to_price(tick, token0.decimals, token1.decimals)
                amount0, amount1 = amounts_from_liquidity(
                    liquidity, tick, tick_lower, tick_upper, token0.decimals, token1.decimals
                )
                if swap_enabled and swap_latest_block is not None:
                    cache_key = pool_address.lower()
                    if cache_key not in swap_cache:
                        swap_cache[cache_key] = safe_recent_swap_rate(
                            rpc_url,
                            pool_address,
                            token0,
                            token1,
                            swap_latest_block,
                            swap_lookback_blocks,
                            swap_max_block_range,
                        )
                    swap_info = swap_cache.get(cache_key)
                    if swap_info:
                        swap_price = float(swap_info["price"])
                        swap_block = int(swap_info["block"])
                        swap_age_blocks = max(swap_latest_block - swap_block, 0)
                        swap_price_source = str(swap_info.get("source") or "swap")
        except Exception:
            pass

        positions.append(
            Position(
                position_id=str(position_id),
                pool=pool,
                token0=token0,
                token1=token1,
                tick=tick,
                tick_lower=tick_lower,
                tick_upper=tick_upper,
                price=price,
                lower_price=lower_price,
                upper_price=upper_price,
                amount0=amount0,
                amount1=amount1,
                fee_amount0=fee_amount0,
                fee_amount1=fee_amount1,
                liquidity=liquidity,
                pool_address=pool_address,
                value_usd=None,
                cost_basis_usd=None,
                fees_usd=0.0,
                rewards_usd=0.0,
                entry_price=None,
                swap_price=swap_price,
                swap_age_blocks=swap_age_blocks,
                swap_price_source=swap_price_source,
            )
        )
    return apply_overrides(positions, cfg)


def read_snapshot_positions(cfg: dict[str, Any], base_dir: Path) -> list[Position]:
    snapshot_path = Path(cfg.get("snapshot", {}).get("path", "examples/prjx_lp_positions.sample.json"))
    if not snapshot_path.is_absolute():
        snapshot_path = base_dir / snapshot_path
    data = load_json(snapshot_path)
    positions = []
    for row in data.get("positions", []):
        token0 = TokenMeta(row.get("token0", ""), row.get("token0_symbol", "token0"), int(row.get("token0_decimals", 18)))
        token1 = TokenMeta(row.get("token1", ""), row.get("token1_symbol", "token1"), int(row.get("token1_decimals", 18)))
        positions.append(
            Position(
                position_id=str(row.get("position_id", row.get("id", "unknown"))),
                pool=str(row.get("pool", f"{token0.symbol}/{token1.symbol}")),
                token0=token0,
                token1=token1,
                tick=int(row["tick"]) if row.get("tick") is not None else None,
                tick_lower=int(row["tick_lower"]),
                tick_upper=int(row["tick_upper"]),
                price=float(row["price"]) if row.get("price") is not None else None,
                lower_price=float(row["lower_price"]) if row.get("lower_price") is not None else None,
                upper_price=float(row["upper_price"]) if row.get("upper_price") is not None else None,
                amount0=float(row["amount0"]) if row.get("amount0") is not None else None,
                amount1=float(row["amount1"]) if row.get("amount1") is not None else None,
                fee_amount0=float(row["fee_amount0"]) if row.get("fee_amount0") is not None else None,
                fee_amount1=float(row["fee_amount1"]) if row.get("fee_amount1") is not None else None,
                liquidity=int(row["liquidity"]) if row.get("liquidity") is not None else None,
                pool_address=row.get("pool_address"),
                value_usd=float(row["value_usd"]) if row.get("value_usd") is not None else None,
                cost_basis_usd=float(row["cost_basis_usd"]) if row.get("cost_basis_usd") is not None else None,
                fees_usd=float(row.get("fees_usd", 0) or 0),
                rewards_usd=float(row.get("rewards_usd", 0) or 0),
                entry_price=float(row["entry_price"]) if row.get("entry_price") is not None else None,
                swap_price=float(row["swap_price"]) if row.get("swap_price") is not None else None,
                swap_age_blocks=int(row["swap_age_blocks"]) if row.get("swap_age_blocks") is not None else None,
                swap_price_source=row.get("swap_price_source"),
            )
        )
    return apply_overrides(positions, cfg)


def apply_overrides(positions: list[Position], cfg: dict[str, Any]) -> list[Position]:
    overrides = cfg.get("position_overrides", {})
    for pos in positions:
        ov = overrides.get(pos.position_id, {})
        if "label" in ov:
            pos.pool = str(ov["label"])
        if "cost_basis_usd" in ov:
            pos.cost_basis_usd = float(ov["cost_basis_usd"])
        if "fees_usd" in ov:
            pos.fees_usd = float(ov["fees_usd"])
        if "rewards_usd" in ov:
            pos.rewards_usd = float(ov["rewards_usd"])
        if "entry_price" in ov:
            pos.entry_price = float(ov["entry_price"])
        if "value_usd" in ov:
            pos.value_usd = float(ov["value_usd"])
    return positions


def percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%"


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.2f}"


def number(value: float | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 1000:
        return f"{value:,.4f}"
    if abs(value) >= 1:
        return f"{value:.6g}"
    return f"{value:.8g}"


def japanese_enabled(cfg: dict[str, Any]) -> bool:
    language = str(cfg.get("language") or cfg.get("locale") or "").lower()
    return language.startswith("ja") or language in {"jp", "japanese", "日本語"}


def status_label(status: str, *, ja: bool) -> str:
    if not ja:
        return status
    return {
        "IN_RANGE": "範囲内",
        "OUT_OF_RANGE": "範囲外",
        "MISSING_PRICE": "価格取得不可",
    }.get(status, status)


def severity_label(severity: str, *, ja: bool) -> str:
    if not ja:
        return severity.upper()
    return {
        "warn": "警告",
        "critical": "重要",
        "info": "情報",
    }.get(severity.lower(), severity.upper())


def kind_label(kind: str, *, ja: bool) -> str:
    if not ja:
        return kind
    return {
        "OUT_OF_RANGE": "レンジ外",
        "NEAR_RANGE_EDGE": "レンジ端接近",
        "IL_LIMIT": "IL上限超過",
        "ROI_LIMIT": "ROI下限割れ",
        "MISSING_PRICE": "価格取得不可",
        "SWAP_RATE_DEVIATION": "Swap実勢乖離",
    }.get(kind, kind)


def edge_label(edge_name: str | None, *, ja: bool) -> str:
    if edge_name == "lower":
        return "下限" if ja else "lower"
    if edge_name == "upper":
        return "上限" if ja else "upper"
    return "レンジ端" if ja else "nearest"


def direction_label(direction: str | None, *, ja: bool) -> str | None:
    if not direction or not ja:
        return direction
    return {
        "below lower edge": "下限割れ",
        "above upper edge": "上限超え",
        "above lower edge": "下限より上",
        "below upper edge": "上限より下",
    }.get(direction, direction)


def swap_deviation_pct(pos: Position) -> float | None:
    if pos.swap_price is None or pos.price is None or pos.price <= 0:
        return None
    return (pos.swap_price - pos.price) / pos.price * 100


def swap_rate_text(pos: Position, *, ja: bool) -> str:
    if pos.swap_price is None:
        return ""
    deviation = swap_deviation_pct(pos)
    parts = []
    if deviation is not None:
        parts.append(("乖離 " if ja else "deviation ") + percent(deviation))
    if pos.swap_age_blocks is not None:
        parts.append(f"{pos.swap_age_blocks}blk前" if ja else f"{pos.swap_age_blocks} blocks ago")
    context = f"({', '.join(parts)})" if parts else ""
    label = "🔁 直近Swap" if ja else "🔁 recent swap"
    return f"{label} {number(pos.swap_price)}{context}"


def status_emoji(status: str, rebalance: bool) -> str:
    if status == "OUT_OF_RANGE":
        return "🔴"
    if status == "MISSING_PRICE":
        return "⚪"
    if rebalance:
        return "🟡"
    return "🟢"


def severity_emoji(severity: str) -> str:
    return {
        "critical": "🚨",
        "warn": "⚠️",
        "info": "ℹ️",
    }.get(severity.lower(), "•")


def range_status(pos: Position) -> tuple[str, float | None, str | None, str | None]:
    if pos.tick is None:
        return "MISSING_PRICE", None, None, None
    if pos.tick < pos.tick_lower or pos.tick > pos.tick_upper:
        edge_name = "lower" if pos.tick < pos.tick_lower else "upper"
        direction = "below lower edge" if pos.tick < pos.tick_lower else "above upper edge"
        return "OUT_OF_RANGE", None, edge_name, direction
    if pos.price is None or pos.lower_price is None or pos.upper_price is None:
        return "IN_RANGE", None, None, None
    if pos.price <= 0:
        return "IN_RANGE", None, None, None
    lower_distance_pct = abs(pos.price - pos.lower_price) / pos.price * 100
    upper_distance_pct = abs(pos.upper_price - pos.price) / pos.price * 100
    if lower_distance_pct <= upper_distance_pct:
        return "IN_RANGE", lower_distance_pct, "lower", "above lower edge"
    return "IN_RANGE", upper_distance_pct, "upper", "below upper edge"


def il_estimate_pct(pos: Position) -> float | None:
    if not pos.entry_price or not pos.price or pos.entry_price <= 0 or pos.price <= 0:
        return None
    ratio = pos.price / pos.entry_price
    return (2 * math.sqrt(ratio) / (1 + ratio) - 1) * 100


def roi_pct(pos: Position, value_usd: float | None) -> float | None:
    if value_usd is None or pos.cost_basis_usd is None or pos.cost_basis_usd <= 0:
        return None
    return ((value_usd + pos.fees_usd + pos.rewards_usd - pos.cost_basis_usd) / pos.cost_basis_usd) * 100


def performance_enabled(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("performance", {}).get("enabled", False))


def performance_baseline(
    pos: Position,
    equity_usd: float | None,
    cfg: dict[str, Any],
    state: dict[str, Any] | None,
    now_ts: int,
) -> tuple[float | None, int | None]:
    if pos.cost_basis_usd is not None and pos.cost_basis_usd > 0:
        override = cfg.get("position_overrides", {}).get(pos.position_id, {})
        started_at = override.get("baseline_ts") or override.get("baseline_started_at")
        return pos.cost_basis_usd, int(started_at) if isinstance(started_at, int) else None
    if not performance_enabled(cfg) or state is None or equity_usd is None or equity_usd <= 0:
        return None, None

    perf_cfg = cfg.get("performance", {})
    perf_state = state.setdefault("performance", {})
    baselines = perf_state.setdefault("baselines", {})
    baseline = baselines.get(pos.position_id)
    if not baseline and bool(perf_cfg.get("auto_baseline", True)):
        baseline = {
            "ts": now_ts,
            "equity_usd": equity_usd,
            "pool": pos.pool,
            "note": "observed_baseline_not_original_cost_basis",
        }
        baselines[pos.position_id] = baseline
    if not baseline:
        return None, None
    try:
        basis = float(baseline.get("equity_usd", 0) or 0)
        ts = int(baseline.get("ts", 0) or 0)
    except (TypeError, ValueError):
        return None, None
    if basis <= 0:
        return None, None
    return basis, ts or None


def profit_metrics(equity_usd: float | None, basis_usd: float | None, baseline_ts: int | None, now_ts: int, min_days: float) -> dict[str, float | None]:
    if equity_usd is None or basis_usd is None or basis_usd <= 0:
        return {"profit_usd": None, "profit_pct": None, "days": None, "daily_pct": None, "apr_pct": None}
    profit_usd = equity_usd - basis_usd
    profit_pct = profit_usd / basis_usd * 100
    days = None
    daily_pct = None
    apr_pct = None
    if baseline_ts:
        days = max((now_ts - baseline_ts) / 86400, 0)
        if days >= min_days and days > 0:
            daily_pct = profit_pct / days
            apr_pct = daily_pct * 365
    return {"profit_usd": profit_usd, "profit_pct": profit_pct, "days": days, "daily_pct": daily_pct, "apr_pct": apr_pct}


def metric_percent(value: float | None, *, wait_days: float | None = None, ja: bool = False) -> str:
    if value is not None:
        return percent(value)
    if wait_days is not None and wait_days < 1:
        return "n/a(1日未満)" if ja else "n/a(<1d)"
    return "n/a"


def evaluate(positions: list[Position], cfg: dict[str, Any], state: dict[str, Any] | None = None, now_ts: int | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    enrich_usd_prices_from_stable_pairs(positions, cfg)
    vol_forecast = build_vol_forecast(positions, cfg)
    ja = japanese_enabled(cfg)
    now_ts = int(now_ts or time.time())
    thresholds = cfg.get("thresholds", {})
    near_pct = float(thresholds.get("near_range_edge_pct", 5.0))
    il_limit = float(thresholds.get("impermanent_loss_pct", -3.0))
    roi_limit = float(thresholds.get("roi_pct", -5.0))
    min_alert_value_usd = float(thresholds.get("min_alert_value_usd", 0) or 0)
    min_apr_days = float(cfg.get("performance", {}).get("min_apr_days", 1.0) or 1.0)
    swap_overlay_cfg = cfg.get("pricing", {}).get("swap_rate_overlay", {})
    swap_deviation_warn_pct = float(swap_overlay_cfg.get("deviation_warn_pct", 0) or 0)

    lines = []
    events = []
    total_value = 0.0
    total_cost = 0.0
    total_fees = 0.0
    total_rewards = 0.0
    total_equity = 0.0
    total_basis = 0.0
    weighted_daily_pct = 0.0
    weighted_apr_pct = 0.0
    weighted_perf_basis = 0.0
    valued_count = 0

    for pos in positions:
        value_usd = infer_usd_value(pos, cfg)
        pos.value_usd = value_usd
        collectable_fees_usd = amounts_usd_value(pos.token0, pos.fee_amount0, pos.token1, pos.fee_amount1, pos.price, cfg) or 0.0
        fees_usd_total = pos.fees_usd + collectable_fees_usd
        equity_usd = value_usd + fees_usd_total + pos.rewards_usd if value_usd is not None else None
        basis_usd, baseline_ts = performance_baseline(pos, equity_usd, cfg, state, now_ts)
        metrics = profit_metrics(equity_usd, basis_usd, baseline_ts, now_ts, min_apr_days)
        il_pct = il_estimate_pct(pos)
        roi = metrics["profit_pct"] if metrics["profit_pct"] is not None else roi_pct(pos, value_usd)
        status, edge_distance, edge_name, edge_direction = range_status(pos)
        rebalance = status == "OUT_OF_RANGE" or (edge_distance is not None and edge_distance <= near_pct)
        alert_value_muted = value_usd is not None and value_usd < min_alert_value_usd

        if value_usd is not None:
            total_value += value_usd
            valued_count += 1
        if pos.cost_basis_usd is not None:
            total_cost += pos.cost_basis_usd
        if basis_usd is not None:
            total_basis += basis_usd
        if equity_usd is not None:
            total_equity += equity_usd
        if metrics["daily_pct"] is not None and metrics["apr_pct"] is not None and basis_usd is not None:
            weighted_daily_pct += metrics["daily_pct"] * basis_usd
            weighted_apr_pct += metrics["apr_pct"] * basis_usd
            weighted_perf_basis += basis_usd
        total_fees += fees_usd_total
        total_rewards += pos.rewards_usd

        if edge_distance is not None:
            edge_text = f"{edge_label(edge_name, ja=ja)}まで {edge_distance:.2f}%" if ja else f"edge {edge_label(edge_name, ja=ja)} {edge_distance:.2f}%"
        else:
            edge_text = "レンジ端 n/a" if ja else "edge n/a"
        amount_text = None
        if pos.amount0 is not None and pos.amount1 is not None:
            amount_text = f"{number(pos.amount0)} {pos.token0.symbol} + {number(pos.amount1)} {pos.token1.symbol}"
        swap_text = swap_rate_text(pos, ja=ja)
        fit_text = vol_fit_text(pos, vol_forecast, ja=ja, cfg=cfg)
        if ja:
            card_lines = [
                f"{status_emoji(status, rebalance)} {pos.pool} #{pos.position_id}",
                f"🧭 判断: {'手動リバランス確認' if rebalance else '監視継続'}",
                f"📍 状態: {status_label(status, ja=ja)} / {edge_text}",
                f"💱 現在価格 {number(pos.price)}",
            ]
            if swap_text:
                card_lines.append(swap_text)
            card_lines.extend(
                [
                    f"📏 レンジ {number(pos.lower_price)} - {number(pos.upper_price)}",
                ]
            )
            if fit_text:
                card_lines.append(fit_text)
            card_lines.extend(
                [
                    f"💰 評価額 {money(value_usd)} / 🧾 観測原価 {money(basis_usd)}",
                    f"💸 未回収手数料 {money(fees_usd_total)} / 🎁 報酬 {money(pos.rewards_usd)}",
                    f"📈 実利 {money(metrics['profit_usd'])}({percent(metrics['profit_pct'])})",
                    f"⏱ 日次平均 {metric_percent(metrics['daily_pct'], wait_days=metrics['days'], ja=ja)} / 🚀 APR {metric_percent(metrics['apr_pct'], wait_days=metrics['days'], ja=ja)}",
                    f"🧪 IL概算 {percent(il_pct)}",
                ]
            )
            if amount_text:
                card_lines.append(f"🪙 構成: {amount_text}")
            if alert_value_muted and rebalance:
                card_lines.append(f"🔕 通知抑制: 評価額 < {money(min_alert_value_usd)}")
            line = "\n".join(card_lines)
        else:
            card_lines = [
                f"{status_emoji(status, rebalance)} {pos.pool} #{pos.position_id}",
                f"🧭 decision: {'rebalance review' if rebalance else 'monitor'}",
                f"📍 status: {status} / {edge_text}",
                f"💱 price {number(pos.price)}",
            ]
            if swap_text:
                card_lines.append(swap_text)
            card_lines.extend(
                [
                    f"📏 range {number(pos.lower_price)} - {number(pos.upper_price)}",
                ]
            )
            if fit_text:
                card_lines.append(fit_text)
            card_lines.extend(
                [
                    f"💰 value {money(value_usd)} / 🧾 observed basis {money(basis_usd)}",
                    f"💸 fees {money(fees_usd_total)} / 🎁 rewards {money(pos.rewards_usd)}",
                    f"📈 profit {money(metrics['profit_usd'])}({percent(metrics['profit_pct'])})",
                    f"⏱ daily avg {metric_percent(metrics['daily_pct'], wait_days=metrics['days'])} / 🚀 APR {metric_percent(metrics['apr_pct'], wait_days=metrics['days'])}",
                    f"🧪 IL est {percent(il_pct)}",
                ]
            )
            if amount_text:
                card_lines.append(f"🪙 composition: {amount_text}")
            if alert_value_muted and rebalance:
                card_lines.append(f"🔕 alert muted: value < {money(min_alert_value_usd)}")
            line = "\n".join(card_lines)
        lines.append(line)

        def add_event(kind: str, severity: str, detail: str) -> None:
            if alert_value_muted:
                return
            events.append(
                {
                    "kind": kind,
                    "severity": severity,
                    "position_id": pos.position_id,
                    "pool": pos.pool,
                    "detail": detail,
                    "price": pos.price,
                    "edge_distance_pct": edge_distance,
                    "edge_name": edge_name,
                    "status": status,
                }
            )

        if status == "MISSING_PRICE":
            add_event("MISSING_PRICE", "warn", "現在プール価格を取得できません" if ja else "could not read current pool price")
        if status == "OUT_OF_RANGE":
            out_detail = (
                f"現在価格 {number(pos.price)} がレンジ {number(pos.lower_price)}-{number(pos.upper_price)} の外側"
                if ja
                else f"price {number(pos.price)} outside {number(pos.lower_price)}-{number(pos.upper_price)}"
            )
            if edge_direction:
                out_detail += f" ({direction_label(edge_direction, ja=ja)})"
            add_event(
                "OUT_OF_RANGE",
                "critical",
                out_detail,
            )
        elif edge_distance is not None and edge_distance <= near_pct:
            detail = (
                f"{edge_label(edge_name, ja=ja)}まで {edge_distance:.2f}%"
                if ja
                else f"{edge_distance:.2f}% from {edge_name or 'nearest'} range edge"
            )
            if edge_direction:
                detail += f" ({direction_label(edge_direction, ja=ja)})"
            add_event("NEAR_RANGE_EDGE", "warn", detail)
        if il_pct is not None and il_pct <= il_limit:
            add_event("IL_LIMIT", "warn", f"IL概算 {il_pct:.2f}% <= {il_limit:.2f}%" if ja else f"IL estimate {il_pct:.2f}% <= {il_limit:.2f}%")
        if roi is not None and roi <= roi_limit:
            add_event("ROI_LIMIT", "warn", f"ROI {roi:.2f}% <= {roi_limit:.2f}%")
        current_swap_deviation = swap_deviation_pct(pos)
        if (
            current_swap_deviation is not None
            and swap_deviation_warn_pct > 0
            and abs(current_swap_deviation) >= swap_deviation_warn_pct
        ):
            detail = (
                f"直近Swap {number(pos.swap_price)} が現在価格 {number(pos.price)} から {percent(current_swap_deviation)} 乖離"
                if ja
                else f"recent swap {number(pos.swap_price)} deviates {percent(current_swap_deviation)} from price {number(pos.price)}"
            )
            add_event("SWAP_RATE_DEVIATION", "warn", detail)

    portfolio_profit_usd = None
    portfolio_profit_pct = None
    portfolio_daily_pct = None
    portfolio_apr_pct = None
    if total_basis > 0:
        portfolio_profit_usd = total_equity - total_basis
        portfolio_profit_pct = portfolio_profit_usd / total_basis * 100
    elif total_cost > 0:
        portfolio_profit_usd = total_value + total_fees + total_rewards - total_cost
        portfolio_profit_pct = portfolio_profit_usd / total_cost * 100
    if weighted_perf_basis > 0:
        portfolio_daily_pct = weighted_daily_pct / weighted_perf_basis
        portfolio_apr_pct = weighted_apr_pct / weighted_perf_basis
    if ja:
        header = "\n".join(
            [
                "📊 PRJX LP Sentinel",
                f"👛 Wallet: {cfg.get('wallet')}",
                f"📦 稼働中ポジション {len(positions)}件",
                f"💰 評価額 {money(total_value if valued_count else None)}",
                f"🧾 観測原価 {money(total_basis if total_basis else None)}",
                f"💸 未回収手数料 {money(total_fees)} / 🎁 報酬 {money(total_rewards)}",
                f"📈 実利 {money(portfolio_profit_usd)}({percent(portfolio_profit_pct)})",
                f"⏱ 日次平均 {metric_percent(portfolio_daily_pct, ja=ja)} / 🚀 APR {metric_percent(portfolio_apr_pct, ja=ja)}",
            ]
        )
    else:
        header = "\n".join(
            [
                "📊 PRJX LP Sentinel",
                f"👛 wallet: {cfg.get('wallet')}",
                f"📦 active positions: {len(positions)}",
                f"💰 value {money(total_value if valued_count else None)}",
                f"🧾 observed basis {money(total_basis if total_basis else None)}",
                f"💸 fees {money(total_fees)} / 🎁 rewards {money(total_rewards)}",
                f"📈 profit {money(portfolio_profit_usd)}({percent(portfolio_profit_pct)})",
                f"⏱ daily avg {metric_percent(portfolio_daily_pct)} / 🚀 APR {metric_percent(portfolio_apr_pct)}",
            ]
        )
    forecast_lines = format_vol_forecast(vol_forecast, ja=ja)
    if forecast_lines:
        header = "\n".join([header, "", *forecast_lines])
    return [header] + lines, events


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sent": {}}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"sent": {}}


def event_signature(event: dict[str, Any]) -> str:
    base = json.dumps(event, sort_keys=True)
    return hashlib.sha256(base.encode()).hexdigest()[:16]


def severity_rank(severity: str | None) -> int:
    return {"info": 0, "warn": 1, "critical": 2}.get(str(severity or "").lower(), 0)


def float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def event_cooldown_record(event: dict[str, Any], sig: str, ts: int) -> dict[str, Any]:
    return {
        "signature": sig,
        "ts": ts,
        "severity": event.get("severity"),
        "price": event.get("price"),
        "edge_distance_pct": event.get("edge_distance_pct"),
        "status": event.get("status"),
    }


def cooldown_bypass_reason(event: dict[str, Any], previous: dict[str, Any], send_cfg: dict[str, Any]) -> str | None:
    """Return why an event should bypass cooldown, or None to suppress.

    Normal near-edge noise is suppressed for the configured cooldown window, but
    the user still wants a ping if the same LP keeps moving materially. Compare
    against the last actually-sent event, not the last observed event.
    """
    if bool(send_cfg.get("cooldown_bypass_on_severity_escalation", True)):
        if severity_rank(event.get("severity")) > severity_rank(previous.get("severity")):
            return "severity_escalation"

    price_threshold = float(send_cfg.get("cooldown_bypass_price_move_pct", 2.0) or 0)
    prev_price = float_or_none(previous.get("price"))
    current_price = float_or_none(event.get("price"))
    if price_threshold > 0 and prev_price and current_price and prev_price > 0:
        price_move_pct = abs(current_price / prev_price - 1.0) * 100.0
        if price_move_pct >= price_threshold:
            return "price_move"

    edge_threshold = float(send_cfg.get("cooldown_bypass_edge_move_pct", 1.0) or 0)
    prev_edge = float_or_none(previous.get("edge_distance_pct"))
    current_edge = float_or_none(event.get("edge_distance_pct"))
    if edge_threshold > 0 and prev_edge is not None and current_edge is not None:
        if abs(current_edge - prev_edge) >= edge_threshold:
            return "edge_move"

    return None


def filter_events_for_cooldown(
    events: list[dict[str, Any]],
    state: dict[str, Any],
    cooldown_minutes: int,
    send_cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    now = int(time.time())
    cooldown = cooldown_minutes * 60
    send_cfg = send_cfg or {}
    sent = state.setdefault("sent", {})
    filtered = []
    for event in events:
        key = f"{event['position_id']}:{event['kind']}"
        sig = event_signature(event)
        previous = sent.get(key, {})
        within_cooldown = cooldown > 0 and now - int(previous.get("ts", 0)) < cooldown
        bypass_reason = cooldown_bypass_reason(event, previous, send_cfg) if previous else None
        if within_cooldown and not bypass_reason:
            continue
        if bypass_reason:
            event["cooldown_override_reason"] = bypass_reason
        filtered.append(event)
        sent[key] = event_cooldown_record(event, sig, now)
    return filtered


def join_cards(lines: list[str]) -> str:
    return "\n\n".join(lines)


def action_first_copy(events: list[dict[str, Any]], ja: bool = False) -> str | None:
    if not events:
        return None
    first = events[0]
    extra = "" if len(events) == 1 else (f" 他{len(events) - 1}件" if ja else f" +{len(events) - 1} more")
    if ja:
        if first.get("kind") == "NEAR_RANGE_EDGE":
            return (
                f"🎯 先に結論: {first['pool']} #{first['position_id']} がレンジ端接近{extra}。\n"
                f"👉 今やること: 下限/上限とリバランス要否を手動確認。自動実行はしない。"
            )
        if first.get("kind") == "OUT_OF_RANGE":
            return (
                f"🎯 先に結論: {first['pool']} #{first['position_id']} がレンジ外{extra}。\n"
                f"👉 今やること: ポジションを手動確認。自動実行はしない。"
            )
        return (
            f"🎯 先に結論: {first['pool']} #{first['position_id']} に確認イベント{extra}。\n"
            f"👉 今やること: 詳細を見て手動判断。自動実行はしない。"
        )
    if first.get("kind") == "NEAR_RANGE_EDGE":
        return (
            f"🎯 Bottom line: {first['pool']} #{first['position_id']} is near a range edge{extra}.\n"
            f"👉 Action: manually review range/rebalance; no auto execution."
        )
    if first.get("kind") == "OUT_OF_RANGE":
        return (
            f"🎯 Bottom line: {first['pool']} #{first['position_id']} is out of range{extra}.\n"
            f"👉 Action: manually review position; no auto execution."
        )
    return (
        f"🎯 Bottom line: {first['pool']} #{first['position_id']} needs review{extra}.\n"
        f"👉 Action: inspect details manually; no auto execution."
    )


def build_alert_message(summary_lines: list[str], events: list[dict[str, Any]], cfg: dict[str, Any]) -> str:
    ja = japanese_enabled(cfg)
    event_header = "🚨 アラート:" if ja else "🚨 Alerts:"
    event_blocks = []
    for event in events:
        if ja:
            event_blocks.append(
                f"{severity_emoji(event['severity'])} {severity_label(event['severity'], ja=ja)} {kind_label(event['kind'], ja=ja)}\n"
                f"🏷 {event['pool']} #{event['position_id']}\n"
                f"📌 {event['detail']}"
            )
        else:
            event_blocks.append(
                f"{severity_emoji(event['severity'])} {severity_label(event['severity'], ja=ja)} {kind_label(event['kind'], ja=ja)}\n"
                f"🏷 {event['pool']} #{event['position_id']}\n"
                f"📌 {event['detail']}"
            )
    snapshot_header = "📸 スナップショット:" if ja else "📸 Snapshot:"
    action_block = action_first_copy(events, ja=ja)
    parts = [event_header]
    if action_block:
        parts.append(action_block)
    parts.extend(event_blocks)
    parts.extend([snapshot_header, join_cards(summary_lines)])
    return "\n\n".join(parts)


def send_telegram(target: str, subject: str, message: str) -> None:
    hermes = shutil.which("hermes")
    if not hermes:
        raise RuntimeError("hermes CLI not found")
    cmd = [hermes, "send", "--to", target, "--subject", subject, message]
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Project X / PRJX LP sentinel")
    parser.add_argument("--config", default="config/prjx_lp_monitor.json")
    parser.add_argument("--no-send", action="store_true", help="do not send Telegram alerts")
    parser.add_argument("--source", choices=["onchain", "snapshot"], help="override config source")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute() and not config_path.exists():
        workdir_config = Path.cwd() / config_path
        script_config = Path(__file__).resolve().parent.parent / config_path
        if workdir_config.exists():
            config_path = workdir_config
        elif script_config.exists():
            config_path = script_config
    config_path = config_path.resolve()
    base_dir = config_path.parent.parent if config_path.parent.name == "config" else Path.cwd()
    cfg = load_json(config_path)
    state_path = Path(cfg.get("state", {}).get("path", ".state/prjx_lp_monitor_state.json"))
    if not state_path.is_absolute():
        state_path = base_dir / state_path
    state = load_state(state_path)
    source = args.source or cfg.get("source", "onchain")

    positions: list[Position]
    if source == "snapshot":
        positions = read_snapshot_positions(cfg, base_dir)
    elif source == "onchain":
        positions = read_onchain_positions(cfg)
    else:
        die(f"unsupported source: {source}")

    summary_lines, events = evaluate(positions, cfg, state=state)
    print(join_cards(summary_lines))

    send_cfg = cfg.get("send", {})
    send_enabled = bool(send_cfg.get("enabled", False)) or os.environ.get("PRJX_LP_SEND") == "1"
    if args.no_send:
        send_enabled = False

    cooldown_minutes = int(send_cfg.get("cooldown_minutes", 60))
    if send_enabled:
        new_events = filter_events_for_cooldown(events, state, cooldown_minutes, send_cfg)
    else:
        new_events = events
    if send_enabled or performance_enabled(cfg):
        save_json(state_path, state)

    if new_events and send_enabled:
        message = build_alert_message(summary_lines, new_events, cfg)
        send_telegram(send_cfg.get("target", "telegram"), send_cfg.get("subject", "[PRJX LP]"), message)
        if japanese_enabled(cfg):
            print(f"📨 {len(new_events)}件のアラートを {send_cfg.get('target', 'telegram')} に送信しました")
        else:
            print(f"📨 sent {len(new_events)} alert(s) to {send_cfg.get('target', 'telegram')}")
    elif events:
        if japanese_enabled(cfg):
            print(f"📣 アラート候補 {len(events)}件 / cooldown後の新規 {len(new_events)}件 / 送信有効={send_enabled}")
        else:
            print(f"📣 {len(events)} alert event(s), {len(new_events)} new after cooldown, send_enabled={send_enabled}")
    else:
        print("✅ アラートなし" if japanese_enabled(cfg) else "✅ no alert events")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
