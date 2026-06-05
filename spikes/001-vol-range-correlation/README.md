# Spike 001: Vol proxies → HYPE daily range forecast

## Question

Can BitVol-like crypto implied volatility, VIX, or major-coin realized ranges help the PRJX LP sentinel forecast the next day's HYPE/WHYPE range and produce better read-only rebalance/range guidance?

## Data sources tested

- Hyperliquid public `candleSnapshot` daily candles for `HYPE`, `BTC`, `ETH`, `SOL`.
- Deribit public volatility index data for BTC/ETH DVOL. This is an accessible BitVol-like crypto implied-vol proxy.
- Yahoo chart endpoint for `^VIX`.
- Direct BitVol/T3 API endpoints were not reliable in this environment; use Deribit DVOL first unless a stable BitVol API is found.

## Command

```bash
python3 spikes/001-vol-range-correlation/vol_range_spike.py
```

## Current result

Latest run:

```text
sample_days=121 from=2026-02-05 to=2026-06-05
hype_range_pct median=6.10 p75=8.44 p90=11.53 last=5.69
correlations_vs_hype_daily_range_pct:
- SOL range same-day: r=0.504 n=121
- BTC range same-day: r=0.493 n=121
- ETH range same-day: r=0.461 n=121
- BTC abs return same-day: r=0.400 n=121
- SOL range prev-day: r=0.282 n=120
- BTC range prev-day: r=0.269 n=120
- BTC abs return prev-day: r=0.254 n=120
- ETH range prev-day: r=0.254 n=120
- VIX close prev-day: r=-0.225 n=84
- VIX close same-day: r=-0.141 n=84
- BTC DVOL close prev-day: r=0.129 n=120
- BTC DVOL close same-day: r=0.129 n=121
- ETH DVOL close prev-day: r=-0.037 n=120
- ETH DVOL close same-day: r=-0.013 n=121
range_suggestion_read_only:
- base_p75: ±4.69% around HYPE 63.2410 => 60.2737-66.2083
- wide_p90: ±5.59% around HYPE 63.2410 => 59.7059-66.7761
```

## Interpretation

- Major-coin realized range is more promising than VIX/DVOL as a raw feature.
- Same-day correlation is not directly tradable, but it validates that HYPE range expands with broader crypto realized volatility.
- Previous-day features have weak-to-moderate correlation (~0.25-0.28), enough for a conservative risk regime label but not enough for precise prediction.
- VIX/DVOL alone should not drive rebalance decisions. They can be regime/context features.

## Recommendation for real build

Build a read-only `vol_forecast` section into `prjx_lp_monitor.py`:

1. Fetch HYPE/BTC/ETH/SOL daily ranges plus BTC/ETH DVOL and VIX.
2. Produce a `range_regime`: `calm`, `normal`, `wide`, or `extreme`.
3. Suggest candidate HYPE daily bands using empirical p75/p90 realized range, not a black-box prediction.
4. Compare current LP lower/upper edges against the forecast band:
   - `inside_forecast_band`
   - `lower_edge_too_close`
   - `upper_edge_too_close`
   - `wide_enough_for_p90`
5. Send this as read-only guidance only. Do not auto-rebalance.

## Verdict: PARTIAL

Useful as a read-only risk overlay. VIX/DVOL alone are insufficient; combine realized HYPE range with DVOL/VIX context.
