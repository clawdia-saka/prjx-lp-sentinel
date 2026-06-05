# PRJX LP Sentinel

Read-only Hermes skill and watchdog script for Project X / PRJX concentrated
liquidity on HyperEVM.

It monitors a configured Project X LP wallet for:

- LP range exits
- near-range-edge rebalance signals
- value-aware alert muting for dust positions via `thresholds.min_alert_value_usd`
- collectable fee estimates via read-only `eth_call` simulation
- recent Swap-rate overlay from pool `Swap` logs (`eth_getLogs`, same event data shown by HyperEVMScan)
- Telegram-friendly card formatting with emoji, blank-line cards, and action-first copy
- observed-baseline profit %, daily average %, and APR estimates
- read-only VIX / BitVol-context HYPE range bands and LP forecast-fit labels
- impermanent-loss estimates
- ROI summaries when cost basis is configured
- Telegram alerts through `hermes send`

## Quick Check

Run offline with the bundled sample:

```bash
python3 scripts/prjx_lp_monitor.py --config config/prjx_lp_monitor.example.json --source snapshot --no-send
```

Create a local config for live monitoring:

```bash
cp config/prjx_lp_monitor.example.json config/prjx_lp_monitor.json
```

Run live on HyperEVM:

```bash
python3 scripts/prjx_lp_monitor.py --config config/prjx_lp_monitor.json --no-send
```

## Enable Telegram Alerts

First confirm Hermes can send:

```bash
hermes send --to telegram "PRJX LP monitor test"
```

Set `send.target` and `send.enabled` in `config/prjx_lp_monitor.json` after
`hermes send --to telegram "PRJX LP monitor test"` works.

Set `language` to `ja` for Japanese Telegram/report text.

Enable observed performance metrics with:

```json
"performance": {
  "enabled": true,
  "auto_baseline": true,
  "min_apr_days": 1.0
}
```

`auto_baseline` stores the first observed equity in `.state/` and reports
profit/APR from that observation point. It is not historical deposit cost basis.

Optional Swap overlay:

```json
"pricing": {
  "swap_rate_overlay": {
    "enabled": true,
    "lookback_blocks": 1000,
    "max_block_range": 1000,
    "deviation_warn_pct": 2.0
  }
}
```

The overlay reads recent pool `Swap` events with read-only `eth_getLogs`, which is
the same on-chain event stream exposed by HyperEVMScan. HyperEVM public RPC caps
log queries at 1000 blocks, so keep `max_block_range` at or below 1000 and avoid
large lookbacks on short cron intervals. The local live config uses
`https://rpc.hypurrscan.io` because the official `rpc.hyperliquid.xyz/evm`
endpoint rate-limited repeated onchain smoke tests. The script throttles RPC
calls to 0.25s apart by default; override with
`PRJX_LP_RPC_MIN_INTERVAL_SECONDS` only if needed.

Optional volatility forecast overlay:

```json
"vol_forecast": {
  "enabled": true,
  "days": 120,
  "timeout_seconds": 6
}
```

This is read-only guidance. It uses HYPE realized daily ranges for p75/p90 bands
and shows BTC/ETH DVOL plus VIX as context. It never auto-rebalances.

Telegram output is formatted as cards:

- portfolio summary card first
- blank line between cards for Telegram readability
- one card per LP NFT
- emoji status: 🟢 normal / 🟡 review / 🔴 out-of-range
- action-first alert copy: `🎯 先に結論` + `👉 今やること`
- action-first line in each position: `🧭 判断: ...`
- separate price, Swap, range, forecast fit, PnL, APR, IL, and token composition lines

## Hermes Cron

```bash
mkdir -p ~/.hermes/scripts
cp scripts/prjx_lp_monitor.py ~/.hermes/scripts/prjx_lp_monitor.py
hermes cron create "3-53/10 * * * *" \
  --name prjx-lp-sentinel \
  --script prjx_lp_monitor.py \
  --no-agent \
  --workdir "$(pwd)"
```

Keep the cron job no-agent. The script sends Telegram only when alert events are
new after cooldown, so normal runs stay quiet.

If `hermes cron list` says the gateway is not running, start it with:

```bash
hermes gateway install
```
