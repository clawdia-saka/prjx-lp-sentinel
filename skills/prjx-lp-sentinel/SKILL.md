---
name: prjx-lp-sentinel
description: Use when monitoring Project X / PRJX concentrated liquidity positions on HyperEVM for range exits, impermanent-loss estimates, rebalance signals, ROI summaries, and Telegram alerts through Hermes.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [defi, hyperevm, projectx, prjx, liquidity, alerts, telegram]
    related_skills: [cron-scheduler]
---

# PRJX LP Sentinel

## Overview

This skill monitors Project X / PRJX concentrated liquidity positions on
HyperEVM. It is designed for a wallet that provides liquidity through the
Project X Nonfungible Position Manager. The companion script reads position NFT
IDs, token ranges, current pool ticks, rough token balances, impermanent-loss
estimates, ROI, and rebalance flags.

The skill is intentionally read-only. It can alert through `hermes send` to
Telegram, but it never signs transactions, never rebalances automatically, and
never stores private keys.

## When to Use

- A user asks to watch PRJX / Project X LP positions.
- A user wants Telegram alerts when price leaves an LP range.
- A user wants "rebalance needed" signals for concentrated liquidity.
- A user wants a readable ROI / fees / rewards summary for LP positions.
- A user wants observed-baseline profit %, daily average %, or APR for LP positions.
- A user wants Hermes cron to run a DeFi watchdog script.

Do not use for:

- Executing swaps, mints, burns, collects, or rebalances.
- Private-key handling.
- Tax reporting or audited PnL accounting.
- Protocols other than Project X unless the config is explicitly adapted.

When the user proposes volatility, BitVol/DVOL, VIX, or "our knowledge" as a way
to predict ranges, treat it as a **read-only forecast overlay** first: validate
correlation, generate empirical p75/p90 HYPE range bands, and label outputs as
manual rebalance review only. Do not jump directly to automated rebalancing.

## Data Sources

Default position source:

- HyperEVM mainnet RPC: `https://rpc.hyperliquid.xyz/evm`
- Chain ID: `999`
- Project X Nonfungible Position Manager:
  `0xead19ae861c29bbb2101e834922b2feee69b9091`

The script also supports a snapshot JSON source for dry runs and for cases where
an indexer or PRJX API is preferred.

Optional volatility/range forecast sources:

- Hyperliquid public `candleSnapshot` daily candles for `HYPE`, `BTC`, `ETH`, and `SOL`.
- Deribit public BTC/ETH DVOL endpoints as an accessible BitVol-like crypto implied-vol proxy.
- Yahoo `^VIX` daily close as broader risk context.

See `references/vol-range-forecast-overlay.md` before adding or modifying range-forecast logic.
API/source for BitVol-style and related market-regime data.

The script also supports a snapshot JSON source for dry runs and for cases where
an indexer or PRJX API is preferred.

## Files

- `scripts/prjx_lp_monitor.py` - read-only monitor and Telegram notifier.
- `config/prjx_lp_monitor.json` - local config for this wallet.
- `examples/prjx_lp_positions.sample.json` - offline sample input.

## One-Shot Run

From the project directory:

```bash
python3 scripts/prjx_lp_monitor.py --config config/prjx_lp_monitor.json --no-send
```

Expected behavior:

- Prints a compact wallet summary.
- Prints one line per active position.
- Sends nothing while `--no-send` is present.
- Exits non-zero only for operational failures, not for normal alerts.

## Telegram Delivery

The script uses Hermes' existing delivery layer:

```bash
hermes send --to telegram "test from PRJX LP monitor"
```

If that works, enable sending in `config/prjx_lp_monitor.json`:

```json
{
  "language": "ja",
  "send": {
    "enabled": true,
    "target": "telegram",
    "cooldown_minutes": 60
  }
}
```

Use `language: "ja"` for Japanese Telegram/report text.

For a specific Telegram chat, use a target like:

```text
telegram:-1001234567890
```

## Cron Recipe

Install the script into Hermes' script directory, then create a no-agent cron
job. Keep Telegram delivery inside the script so normal "all good" runs stay
quiet.

```bash
mkdir -p ~/.hermes/scripts
cp scripts/prjx_lp_monitor.py ~/.hermes/scripts/prjx_lp_monitor.py
hermes cron create "3-53/10 * * * *" \
  --name prjx-lp-sentinel \
  --script prjx_lp_monitor.py \
  --no-agent \
  --workdir "$(pwd)"
```

Run one tick immediately:

```bash
hermes cron run prjx-lp-sentinel
```

## Alert Logic

The monitor emits alert events for:

- `OUT_OF_RANGE`: current pool tick is below `tickLower` or above `tickUpper`.
- `NEAR_RANGE_EDGE`: price is still in range but close to either boundary.
- `IL_LIMIT`: estimated impermanent loss is worse than the configured threshold.
- `ROI_LIMIT`: ROI is worse than the configured threshold.
- `MISSING_PRICE`: a position was found but current pool price could not be read.

Use `thresholds.min_alert_value_usd` to mute alert events for dust positions while
still showing them in the snapshot line with `alert muted`. For near-edge alerts,
include which side is closest (`lower` / `upper`) and whether price is above the
lower edge or below the upper edge.

If adding a volatility/range forecast overlay, keep it separate from core alert
truth: forecast context may raise/lower manual review priority, but `OUT_OF_RANGE`
and `NEAR_RANGE_EDGE` remain deterministic on-chain/range facts. Forecast output
must be labeled read-only and `auto_rebalance_enabled=false`.

Rebalance is recommended when a position is out of range or near the configured
edge threshold. The message should say "review / rebalance" instead of "execute"
because this skill does not trade.

## Performance Metrics

For missing cost basis, prefer an observed-baseline mode over pretending to know
the historical deposit cost. With `performance.enabled=true` and
`performance.auto_baseline=true`, the script stores the first observed
`value + collectable fees + rewards` per token ID in `.state/` and reports:

- `観測原価` / observed basis
- `実利` / profit amount and percent since observation
- `日次平均` / average daily percent after `performance.min_apr_days`
- `APR` / annualized daily average after `performance.min_apr_days`

Format Telegram output as readable cards, not pipe-dense one-liners: portfolio
summary first, then one card per LP NFT, separated by blank lines for Telegram
readability. Use emojis for fast scanning (🟢 normal, 🟡 manual review,
🔴 out-of-range), and make the action line explicit near the top (`🧭 判断:
手動リバランス確認` or `🧭 判断: 監視継続`). Alert messages should start with an
action-first / "チンインコピー" style block: `🎯 先に結論` + `👉 今やること`, and
must state that there is no automatic execution. Keep price, recent Swap, range,
forecast fit, PnL, APR, IL, and token composition on separate lines. When
`vol_forecast.enabled=true`, include the read-only VIX/BitVol-context forecast
section (HYPE p75/p90 bands, DVOL/VIX context, `自動リバランスなし`) in the
portfolio card.

The collectable fee estimate uses read-only `eth_call` simulation of the NFPM
`collect` method with no transaction submission or signing. Label this as an
estimate and keep true accounting caveats when reporting it.

For market sanity checks, enable `pricing.swap_rate_overlay`. It reads recent pool
`Swap` events via read-only `eth_getLogs` (the same event stream visible on
HyperEVMScan), derives an average execution rate from `amount1 / amount0`, and
shows it as `直近Swap` / `recent swap` with deviation from current slot0 price.
HyperEVM public RPC rejects log ranges over 1000 blocks, so keep
`max_block_range <= 1000`; use short lookbacks for 10-minute cron jobs to avoid
rate limits. The script throttles RPC calls to 0.25s apart by default; override
`PRJX_LP_RPC_MIN_INTERVAL_SECONDS` only if operational testing shows it is safe.
If the official `https://rpc.hyperliquid.xyz/evm` endpoint rate-limits repeated
onchain smokes or `eth_getLogs`, `https://rpc.hypurrscan.io` is a working chain
999 alternative observed on tetsu's Mac.

## ROI and IL Notes

ROI is only as good as the cost basis in config. If no `cost_basis_usd` override
exists for a token ID, the script reports `ROI n/a`.

Impermanent loss is an estimate based on entry price versus current price:

```text
IL = 2 * sqrt(current_price / entry_price) / (1 + current_price / entry_price) - 1
```

For concentrated liquidity, this is a quick risk signal, not exact realized PnL.
Fees, rewards, and manual deposits/withdrawals should be added as overrides when
precision matters.

## Common Pitfalls

1. **No token IDs found.** Confirm the wallet owns Project X position NFTs on the
   configured Position Manager. Some closed positions may have zero liquidity or
   may have been transferred.

2. **ROI is missing.** Add `cost_basis_usd`, `fees_usd`, and `rewards_usd` under
   `position_overrides` for the token ID.

3. **Too many Telegram messages.** Increase `send.cooldown_minutes`, set
   `thresholds.min_alert_value_usd` to mute dust positions, or set `send.enabled`
   to false while tuning thresholds.

4. **Wrong range display.** Token order matters. Prices are shown as
   `token1 per token0`, adjusted for decimals.

5. **RPC failures.** Switch `onchain.rpc_url` to another HyperEVM RPC provider
   and run with `--no-send` before re-enabling alerts.

## Verification Checklist

- [ ] `python3 scripts/prjx_lp_monitor.py --config config/prjx_lp_monitor.json --no-send` runs.
- [ ] The wallet address is correct.
- [ ] Position Manager address is correct for Project X.
- [ ] Active token IDs match Project X / PRJX portfolio UI.
- [ ] Range status matches PRJX UI for at least one position.
- [ ] Cost-basis overrides are populated for ROI-critical positions.
- [ ] `thresholds.min_alert_value_usd` is high enough to avoid dust-position spam without hiding material positions.
- [ ] `hermes send --to telegram "test"` works.
- [ ] Cron is scheduled no more often than needed and alert cooldown is enabled.
