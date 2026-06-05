# Roadmap

This roadmap separates decision support from execution. The public repository
starts read-only and should stay safe to run without wallet signing material.

## Phase 0 - Public read-only sentinel

Status: current baseline.

- Read Project X LP positions with `eth_call`.
- Read recent pool swaps with `eth_getLogs`.
- Format Telegram-friendly cards.
- Keep live wallet config and local state out of Git.
- Provide privacy guidance, CI, and scanner checks for public use.

## Phase 1 - Chinin-style alert quality

Goal: make alerts more useful before adding new risk.

- Improve action-first Japanese and English alert copy.
- Reduce alert fatigue with better cooldown, materiality, and deduplication.
- Track manual outcomes: ignored, reviewed, rebalanced, exited, widened, narrowed.
- Measure precision and recall against manually labeled outcomes.
- Add fixtures for edge cases: dust positions, stale prices, zero-liquidity NFTs,
  out-of-range positions, missing swap logs, and inconsistent RPC responses.

Exit criteria:

- Alerts explain the next manual decision in one glance.
- False-positive and false-negative rates are measured on historical runs.
- No automated execution path exists.

## Phase 2 - Volatility-aware range decisioning

Goal: recommend ranges and early-exit review points using market context.

Inputs to evaluate:

- HYPE realized daily and intraday ranges.
- BTC and ETH DVOL as crypto implied-vol proxies.
- Traditional-market volatility regime.
- Pool swap-rate deviation and liquidity depth.
- Time in range, distance to lower/upper edge, and fee velocity.

Outputs:

- p50/p75/p90 expected HYPE movement bands.
- Range fit labels: narrow, adequate, wide, edge-risk, stale range.
- Early-exit review signals before a deterministic range exit.
- Recommended manual actions: hold, inspect, widen, narrow, exit, or wait.

Exit criteria:

- Backtests compare forecast labels against next-window range exits.
- Forecast output remains clearly labeled as decision support.
- No wallet signing or transaction submission exists.

## Phase 3 - Paper LP operator

Goal: simulate LP entries, exits, and range updates before any live execution.

- Add a paper-only state machine for virtual LP actions.
- Estimate fees, slippage, gas, IL, and opportunity cost.
- Compare candidate ranges under different volatility regimes.
- Rank actions by expected APR after IL and costs.
- Produce operator packets explaining why a simulated action would have been taken.

Exit criteria:

- Paper recommendations can be replayed deterministically.
- No live funds move.
- Paper/live readiness flags are explicit and default false.
- APR optimization is evaluated after costs, not just fee APR.

## Phase 4 - Human-approved execution adapter design

Goal: design, not enable by default, an execution adapter for users who explicitly
want live operations.

Required gates before any implementation:

- Separate execution module from the public read-only monitor.
- Contract allowlist and method allowlist.
- Per-action human approval by default.
- Maximum notional, daily loss, slippage, gas, and drawdown limits.
- Kill switch and cooldowns.
- Full simulation parity tests.
- External audit or independent review before live use.
- Sensitive operational values stored outside Git.

Exit criteria:

- The public monitor remains safe without the adapter.
- Live execution cannot happen accidentally from default config.
- Every live action has a signed approval record and rollback/containment plan.

## Phase 5 - Guarded automation research

Goal: explore whether limited automation is justified after the previous phases.

Potential capabilities:

- Auto-enter or auto-exit only within strict notional and risk limits.
- Auto-range selection using realized-vol, DVOL/VIX context, fee velocity, and IL risk.
- APR optimization that penalizes churn, gas, slippage, and tail-risk exposure.
- Degradation mode: alert-only when data quality is low.

Required standard:

- Automation must beat the read-only baseline in paper mode before any live
  mode is considered.
- Any live mode should be opt-in, separately packaged, heavily tested, and easy
  to disable.
