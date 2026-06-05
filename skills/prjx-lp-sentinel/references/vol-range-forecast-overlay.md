# PRJX LP Sentinel: Vol / Range Forecast Overlay

Session-derived pattern for extending the read-only PRJX LP sentinel with range-forecast context before any rebalance automation.

## Goal

Add a **read-only risk overlay** that helps decide whether an LP range is too narrow, too close to one edge, or wide enough for the current volatility regime. This is not an execution signal and must not auto-rebalance.

## Data sources that worked

- Hyperliquid public `candleSnapshot` API:
  - daily candles for `HYPE`, `BTC`, `ETH`, `SOL`
  - useful fields: daily realized range `% = (high - low) / close * 100`, absolute return `%`
- Deribit public volatility index API:
  - `public/get_volatility_index_data?currency=BTC|ETH&resolution=1D`
  - usable as an accessible BitVol-like crypto implied-vol proxy when direct BitVol/T3 APIs are unavailable or unstable
- Yahoo chart endpoint:
  - `^VIX` daily close, useful as context but not a primary driver

## Initial empirical finding

On a 120-day quick spike for HYPE daily range:

- Major-coin realized range correlated better than VIX/DVOL as raw features.
- Same-day correlations were strongest, but are not directly forecastable:
  - SOL range same-day: about `r=0.50`
  - BTC range same-day: about `r=0.49`
  - ETH range same-day: about `r=0.46`
- Previous-day realized range was weaker but usable for conservative regime labeling:
  - SOL/BTC/ETH range prev-day: roughly `r=0.25-0.28`
- BTC/ETH DVOL and VIX alone were weak as direct predictors; treat them as regime/context features, not rebalance drivers.

## Recommended implementation shape

Add an opt-in `vol_forecast` section or CLI flag such as `--enable-vol-forecast`.

Compute:

- `range_regime`: `calm`, `normal`, `wide`, `extreme`
- empirical HYPE bands from recent realized range:
  - p75 band: base daily range guide
  - p90 band: conservative wide-range guide
- LP fit diagnostics for each material position:
  - `inside_forecast_band`
  - `lower_edge_too_close`
  - `upper_edge_too_close`
  - `wide_enough_for_p90`
- human action label:
  - `hold_range`
  - `monitor_lower_edge`
  - `monitor_upper_edge`
  - `manual_rebalance_review_lower`
  - `manual_rebalance_review_upper`
  - `range_too_narrow_for_regime`

Always include explicit safety fields in machine-readable artifacts and human output:

```text
forecast_read_only=true
auto_rebalance_enabled=false
```

## Telegram/report example

```text
Vol forecast: WIDE
HYPE p75 band: 60.27-66.21
HYPE p90 band: 59.71-66.78
LP fit: lower edge close, upper wide enough
Action: monitor lower edge / manual rebalance review only
```

## Pitfalls

- Do not call VIX/DVOL a precise daily range predictor. Use them as context/regime features.
- Do not rely on same-day realized range for forward-looking signals except as live intraday context clearly labeled as such.
- Do not convert forecast output into automatic swaps, mints, burns, collects, or rebalances.
- Keep dust-position muting (`thresholds.min_alert_value_usd`) active so forecast context does not reintroduce notification spam.
- Label BitVol/T3 availability carefully; if direct endpoints are unreliable, use Deribit DVOL as a proxy rather than claiming BitVol is unavailable forever.

## Verification recipe

Before enabling in cron:

1. Run a no-send one-shot with forecast enabled.
2. Confirm Hyperliquid, Deribit, and Yahoo fetch failures degrade gracefully.
3. Confirm the forecast section appears in stdout and Telegram text only as read-only guidance.
4. Confirm existing range/edge alerts still fire and dust-position alerts remain muted.
5. Add tests for p75/p90 band calculation, edge-fit classification, and fetch-failure fallback.
