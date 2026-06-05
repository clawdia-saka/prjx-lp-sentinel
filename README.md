# PRJX LP Sentinel

Read-only standard-library Python watchdog for Project X / PRJX concentrated
liquidity on HyperEVM.

It monitors a configured Project X LP wallet for:

- LP range exits
- near-range-edge manual rebalance review signals
- value-aware alert muting for dust positions via `thresholds.min_alert_value_usd`
- collectable fee estimates via read-only `eth_call` simulation
- recent Swap-rate overlay from pool `Swap` logs (`eth_getLogs`, the same event stream shown by HyperEVMScan)
- Telegram-friendly card formatting with emoji, blank-line cards, and action-first copy
- observed-baseline profit %, daily average %, and APR estimates
- read-only VIX / DVOL context HYPE range bands and LP forecast-fit labels
- impermanent-loss estimates
- ROI summaries when cost basis is configured
- optional Telegram alerts through `hermes send`

The current project is a monitor and decision-support tool. It does **not** sign
transactions, submit transactions, auto-rebalance, mint, burn, swap, or move
funds.

## Privacy and safety

Do not commit your live wallet configuration.

- The tracked example config uses the zero address as a placeholder.
- Copy `config/prjx_lp_monitor.example.json` to `config/prjx_lp_monitor.json` for local use.
- `config/prjx_lp_monitor.json`, `config/*.local.json`, and `.state/` are gitignored.
- Keep wallet-specific cost basis, alert targets, and observed baseline state local.
- Store any sensitive operational credentials outside the repository.

This repository is not financial advice. Any range changes, exits, entries, or
rebalances should be reviewed manually unless you have built and audited a
separate execution layer with explicit approvals and risk limits.

## Quick check

Run offline with the bundled sample:

```bash
python3 scripts/prjx_lp_monitor.py --config config/prjx_lp_monitor.example.json --source snapshot --no-send
```

Create a local config for live monitoring:

```bash
cp config/prjx_lp_monitor.example.json config/prjx_lp_monitor.json
```

Edit the local-only config:

```json
"wallet": "YOUR_WALLET_ADDRESS_HERE"
```

Run live on HyperEVM without sending alerts:

```bash
python3 scripts/prjx_lp_monitor.py --config config/prjx_lp_monitor.json --no-send
```

The script uses only Python's standard library.

## Optional Telegram alerts

First confirm Hermes can send:

```bash
hermes send --to telegram "PRJX LP monitor test"
```

Set `send.target` and `send.enabled` in `config/prjx_lp_monitor.json` after
`hermes send --to telegram "PRJX LP monitor test"` works.

Use `language: "ja"` for Japanese Telegram/report text. For a specific Telegram
chat, use a local-only target such as:

```text
telegram:<chat_id>
```

## Performance metrics

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

## Swap-rate overlay

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

The overlay reads recent pool `Swap` events with read-only `eth_getLogs`. HyperEVM
public RPC providers can cap log queries, so keep `max_block_range` at or below
1000 and avoid large lookbacks on short cron intervals. The script throttles RPC
calls to 0.25s apart by default; override with
`PRJX_LP_RPC_MIN_INTERVAL_SECONDS` only if needed.

## Volatility forecast overlay

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

## Hermes cron

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

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the staged plan: better Chinin-style alert
quality, volatility-aware range decisioning, paper LP operations, APR/IL/fee
optimization, and strictly gated future execution adapters.

## License

MIT. See [LICENSE](LICENSE).
