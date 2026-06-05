# Polymarket Source Reliability

This proposal treats Polymarket as a read-only information source, not as an
execution engine. The goal is to test whether prediction-market prices contain
useful, measurable signal for PRJX LP monitoring and later range decisioning.

## Scope

Initial focus:

- Short-interval BTC Up/Down markets.
- 5-minute markets when active and discoverable through the public Gamma API.
- Adjacent short-interval BTC markets, such as 15-minute markets, when those are
  the active product available at collection time.
- Other high-volume crypto or macro markets only after the BTC pipeline is stable.

Out of scope:

- Placing Polymarket orders.
- Treating a market price as a direct trading instruction.
- Using unresolved market outcomes as if they are known.
- Moving LP funds automatically.

## Read-only data sources

Use public endpoints only:

- Gamma API for market discovery, close state, and settled outcome fields.
- CLOB API for current buy/sell prices, spread, and order-book depth.
- Data API for recent trade context when useful.

No private credentials are required for this research lane.

## Collection protocol

For each candidate market, record immutable observations:

- `market_id`
- `event_slug` / `market_slug`
- question text
- market family, e.g. `btc_short_interval`
- interval length when inferable from title/slug
- close time / end time
- observation timestamp
- yes/no prices from Gamma when available
- executable buy/sell quotes from CLOB when available
- spread, liquidity, volume, and top-of-book depth
- whether the market is active, closed, or settled

For short-interval markets, sample at multiple points before close when possible:

- early window
- midpoint
- final minute
- post-close pending state
- post-settlement final state

## Settlement join

Only join outcome labels after the market is closed and the result is final.

Required post-settlement fields:

- final outcome: yes/no or equivalent resolved result
- settlement timestamp observed by the collector
- final Gamma prices if available
- any ambiguity notes: missing result, conflicting metadata, abandoned market,
  or delayed settlement

If the market is not clearly settled, keep it out of reliability scoring and mark
it as `pending_settlement`.

## Scoring

Score each market observation as a forecast made at that observation time.

Core metrics:

- Brier score: `(probability - outcome)^2`
- bucket calibration: average outcome rate for probability buckets
- log-loss when probabilities are safely clipped away from 0 and 1
- directional hit rate above simple thresholds, e.g. 60/40 and 70/30
- signal lead time: how long before close the signal was useful
- market-quality filters: minimum volume, liquidity, spread, and depth

Do not rank a source family from tiny samples. Require a minimum sample count per
market family and time bucket before assigning a stable grade.

## Source-quality ranks

Rank market families, not single markets, so one lucky or noisy market does not
look authoritative.

- A: large sample, liquid, tight spreads, clear settlement, well-calibrated.
- B: useful but limited by sample size, spread, or settlement delay.
- C: weak signal; useful only as context with other indicators.
- D: noisy or unreliable; ignore for decisions.
- Pending: insufficient settled samples.

A rank is informational only. It should influence alert context after validation,
but it should not trigger LP entry, exit, or rebalance by itself.

## Applying to PRJX LP monitoring

Allowed uses after validation:

- Add a context line such as `Prediction-market context: positive / neutral / negative`.
- Raise or lower manual-review priority when Polymarket signal agrees with realized
  volatility, range-edge distance, and pool swap-rate evidence.
- Identify times when crowd-implied short-term BTC direction is noisy and should be
  ignored.

Not allowed:

- Auto-exit LP range solely from Polymarket price.
- Auto-enter or auto-rebalance from Polymarket price.
- Present Polymarket as the settlement source for HYPE or PRJX pool state.

## Initial verification notes

A read-only smoke on 2026-06-05 confirmed:

- `public-search?q=Bitcoin Up or Down 5m` returns settled historical BTC 5-minute
  markets with final prices.
- Active top-volume Gamma markets included a short-interval BTC Up/Down product,
  observed as a 15-minute market at the time of the smoke.

This means the first implementation should support `btc_short_interval` rather
than hard-coding only one interval length.

## Completion criteria for the first research pass

- Collect at least one day of read-only observations.
- Join only settled outcomes.
- Produce a reliability report with sample counts, Brier score, calibration, and
  source-quality rank.
- Keep all LP automation flags false.
- Document limitations before using the signal in live alert copy.
