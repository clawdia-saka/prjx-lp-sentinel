#!/usr/bin/env python3
"""Spike: test whether vol proxies help forecast HYPE daily LP range risk.

Read-only, stdlib-only. Pulls public daily data from:
- Hyperliquid candleSnapshot: HYPE/BTC/ETH/SOL realized ranges
- Deribit DVOL public API: BTC/ETH implied vol index
- Yahoo chart endpoint: VIX close
"""

from __future__ import annotations

import json
import math
import statistics
import time
import urllib.request
from datetime import datetime, timezone
from collections.abc import Sequence
from typing import Any

DAYS = 120


def utc_day(ms_or_s: int) -> str:
    if ms_or_s > 10_000_000_000:
        ms_or_s //= 1000
    return datetime.fromtimestamp(ms_or_s, timezone.utc).date().isoformat()


def http_json(url: str, *, data: bytes | None = None, timeout: int = 30) -> Any:
    headers = {"User-Agent": "prjx-vol-range-spike/0.1", "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def hyperliquid_candles(coin: str, start_ms: int, end_ms: int) -> dict[str, dict[str, float]]:
    payload = {
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": "1d", "startTime": start_ms, "endTime": end_ms},
    }
    rows = http_json("https://api.hyperliquid.xyz/info", data=json.dumps(payload).encode())
    out = {}
    for row in rows:
        day = utc_day(int(row["t"]))
        open_ = float(row["o"])
        high = float(row["h"])
        low = float(row["l"])
        close = float(row["c"])
        out[day] = {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "range_pct": (high - low) / close * 100 if close else math.nan,
            "abs_ret_pct": abs(close - open_) / open_ * 100 if open_ else math.nan,
        }
    return out


def deribit_dvol(currency: str, start_ms: int, end_ms: int) -> dict[str, dict[str, float]]:
    url = (
        "https://www.deribit.com/api/v2/public/get_volatility_index_data"
        f"?currency={currency}&start_timestamp={start_ms}&end_timestamp={end_ms}&resolution=1D"
    )
    rows = http_json(url)["result"]["data"]
    return {
        utc_day(int(row[0])): {"open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4])}
        for row in rows
    }


def yahoo_daily(symbol: str, days: int) -> dict[str, dict[str, float]]:
    period2 = int(time.time())
    period1 = period2 - days * 24 * 3600
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={period1}&period2={period2}&interval=1d"
    result = http_json(url)["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    out = {}
    for ts, open_, high, low, close in zip(
        result["timestamp"], quote["open"], quote["high"], quote["low"], quote["close"]
    ):
        if close is None:
            continue
        out[utc_day(int(ts))] = {
            "open": float(open_) if open_ is not None else math.nan,
            "high": float(high) if high is not None else math.nan,
            "low": float(low) if low is not None else math.nan,
            "close": float(close),
        }
    return out


def corr(xs: Sequence[float | None], ys: Sequence[float | None]) -> tuple[float | None, int]:
    pairs = [
        (x, y)
        for x, y in zip(xs, ys)
        if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)
    ]
    if len(pairs) < 3:
        return None, len(pairs)
    xvals = [p[0] for p in pairs]
    yvals = [p[1] for p in pairs]
    mx = sum(xvals) / len(xvals)
    my = sum(yvals) / len(yvals)
    vx = sum((x - mx) ** 2 for x in xvals)
    vy = sum((y - my) ** 2 for y in yvals)
    if vx == 0 or vy == 0:
        return None, len(pairs)
    return sum((x - mx) * (y - my) for x, y in pairs) / math.sqrt(vx * vy), len(pairs)


def previous(days: list[str], source: dict[str, dict[str, float]], field: str) -> list[float | None]:
    values = []
    for i, _day in enumerate(days):
        if i == 0:
            values.append(None)
            continue
        values.append(source.get(days[i - 1], {}).get(field))
    return values


def quantile(values: list[float], q: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[idx]


def main() -> int:
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - DAYS * 24 * 3600 * 1000

    hype = hyperliquid_candles("HYPE", start_ms, now_ms)
    btc = hyperliquid_candles("BTC", start_ms, now_ms)
    eth = hyperliquid_candles("ETH", start_ms, now_ms)
    sol = hyperliquid_candles("SOL", start_ms, now_ms)
    btc_dvol = deribit_dvol("BTC", start_ms, now_ms)
    eth_dvol = deribit_dvol("ETH", start_ms, now_ms)
    vix = yahoo_daily("%5EVIX", DAYS)

    days = sorted(set(hype) & set(btc) & set(eth) & set(sol))
    y = [hype[day]["range_pct"] for day in days]

    features = {
        "BTC range same-day": [btc.get(day, {}).get("range_pct") for day in days],
        "BTC abs return same-day": [btc.get(day, {}).get("abs_ret_pct") for day in days],
        "ETH range same-day": [eth.get(day, {}).get("range_pct") for day in days],
        "SOL range same-day": [sol.get(day, {}).get("range_pct") for day in days],
        "BTC range prev-day": previous(days, btc, "range_pct"),
        "BTC abs return prev-day": previous(days, btc, "abs_ret_pct"),
        "ETH range prev-day": previous(days, eth, "range_pct"),
        "SOL range prev-day": previous(days, sol, "range_pct"),
        "BTC DVOL close same-day": [btc_dvol.get(day, {}).get("close") for day in days],
        "ETH DVOL close same-day": [eth_dvol.get(day, {}).get("close") for day in days],
        "BTC DVOL close prev-day": previous(days, btc_dvol, "close"),
        "ETH DVOL close prev-day": previous(days, eth_dvol, "close"),
        "VIX close same-day": [vix.get(day, {}).get("close") for day in days],
        "VIX close prev-day": previous(days, vix, "close"),
    }

    rows = []
    for name, xs in features.items():
        r, n = corr(xs, y)
        rows.append((abs(r) if r is not None else -1.0, r, n, name))
    rows.sort(reverse=True)

    print(f"sample_days={len(days)} from={days[0]} to={days[-1]}")
    print(
        "hype_range_pct "
        f"median={statistics.median(y):.2f} p75={quantile(y, 0.75):.2f} p90={quantile(y, 0.90):.2f} last={y[-1]:.2f}"
    )
    print("correlations_vs_hype_daily_range_pct:")
    for _abs_r, r, n, name in rows:
        if r is None:
            print(f"- {name}: r=n/a n={n}")
        else:
            print(f"- {name}: r={r:.3f} n={n}")

    # Simple read-only range suggestion from realized distribution. This is NOT a trade instruction.
    latest_close = hype[days[-1]]["close"]
    base_range_pct = quantile(y[-60:], 0.75) if len(y) >= 60 else quantile(y, 0.75)
    conservative_range_pct = quantile(y[-60:], 0.90) if len(y) >= 60 else quantile(y, 0.90)
    print("range_suggestion_read_only:")
    for label, pct in [("base_p75", base_range_pct), ("wide_p90", conservative_range_pct)]:
        half = pct / 2 / 100
        print(f"- {label}: ±{pct/2:.2f}% around HYPE {latest_close:.4f} => {latest_close*(1-half):.4f}-{latest_close*(1+half):.4f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
