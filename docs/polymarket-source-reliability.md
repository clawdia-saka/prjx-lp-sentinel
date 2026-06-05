# Polymarket and Topic Source Reliability

This proposal treats Polymarket, CB Terminal topics, and public news feeds as
read-only information sources, not as execution engines. The goal is to test
whether topic momentum and prediction-market prices contain useful, measurable
signal for PRJX LP monitoring and later decision-support context for LP review.
The default lane uses public endpoints only and requires no private credentials.

## Scope

Initial focus:

- Short-interval BTC Up/Down markets.
- 5-minute markets when active and discoverable through the public Gamma API.
- Adjacent short-interval BTC markets, such as 15-minute markets, when those are
  the active product available at collection time.
- CB Terminal topics from `https://cb-terminal.dev/api/topics` as the first
  trend/topic feed.
- Other public news sources as corroboration, especially crypto, macro,
  regulation, ETF/flow, DeFi/on-chain risk, and AI-infrastructure stories.
- User-relevant topic families beyond BTC once the BTC pipeline is stable.

Out of scope:

- Placing Polymarket orders.
- Treating a market price as a direct trading instruction.
- Using unresolved market outcomes as if they are known.
- Moving LP funds automatically.
- Treating CB Terminal, X/Twitter, Telegram, RSS, or a single news site as a
  settlement oracle.

## Read-only data sources

Use public endpoints and public pages only unless a later private-source adapter
is explicitly approved.

### CB Terminal topics

Primary endpoint:

- `https://cb-terminal.dev/api/topics`

Observed response shape from the 2026-06-05 smoke:

- Top-level fields: `data`, `has_more`, `next_cursor`.
- Topic fields: `id`, `importance_score`, `type`, `status`, `created_at`,
  `updated_at`, `title`, `summary`, `content`, `metadata`, `sources`,
  `summary_items`.
- Source fields include `source_type`, `url`, `author`, `published_at`, and
  `quote_text`.
- Common observed topic types: `macro`, `alert`, `crypto`, `politics`,
  `summary`, `listings`.
- Pagination uses `?cursor=<next_cursor>`; `?limit=<n>` is accepted.

Collector notes:

- Store the raw topic and raw sources before scoring relevance.
- Preserve `importance_score`, `type`, source count, source URLs, and timestamps.
- Deduplicate by `id`; when a topic updates, append a new observation row rather
  than overwriting the old one.
- Treat social-derived sources as leads, not confirmed facts, until corroborated.

### Polymarket

Use public endpoints only:

- Gamma API for market discovery, close state, and settled outcome fields.
- CLOB API for current buy/sell prices, spread, and order-book depth.
- Data API for recent trade context when useful.

Polymarket remains a read-only probability source in this lane. It should be
cross-referenced against topic feeds, not used as a stand-alone trading trigger.

### Other public news sources

Use adapters that can be disabled independently:

- Crypto and market news RSS/Atom feeds.
- Official project, exchange, protocol, ETF issuer, and regulator posts.
- Economic-calendar and central-bank public releases.
- On-chain/security researcher public posts when they include source URLs.
- Japan/WebX/crypto-regulation sources when relevant to the user's public work.

Each external source should be tagged as one of:

- `primary`: official announcement, filing, regulator, project/team post.
- `aggregator`: CB Terminal, RSS/news aggregator, calendar feed.
- `social_lead`: X/Twitter, Telegram, or researcher post that still needs
  corroboration.
- `market_implied`: Polymarket probability or price movement.

## User-relevant topic families

Do not restrict the research lane to BTC once the short-interval collector works.
Expand candidate topics using these families:

- `btc_short_interval`: BTC 5-minute or adjacent short-interval Up/Down markets.
- `crypto_market_regime`: BTC/ETH/SOL/HYPE moves, ETF flows, stablecoin stress,
  exchange outages, large liquidations, funding/volatility regime shifts.
- `defi_lp_onchain_risk`: DEX/AMM/liquidity-pool events, hacks, bridge incidents,
  oracle issues, token unlocks, airdrops, and pool-specific manipulation risk.
- `prediction_market_industry`: Polymarket, Kalshi, regulation, regional access,
  market integrity, prediction-market volumes, and settlement disputes.
- `macro_rates_fx_geopolitics`: Fed, CPI, rates, USD/JPY, treasury/liquidity,
  election/geopolitical shocks that can move crypto risk.
- `ai_gpu_infra_equities`: Nvidia/GPU/datacenter/AI model news that can affect
  tech equities or crypto-AI narratives.
- `japan_webx_crypto_policy`: Japan crypto regulation, WebX-relevant events,
  exchanges, SBI/Monex/FSA themes, JPY volatility.
- `project_x_prjx_hyperliquid`: Project X / PRJX, Hyperliquid/HYPE ecosystem,
  DEX volume and LP conditions.

A topic can map to multiple families. Store the family assignments and the terms
that caused the match so filters can be audited later.

## Relevance scoring

For each topic, compute a transparent relevance score before it reaches alert
copy:

- Recency: newer topics score higher, with decay by family.
- Importance: CB Terminal `importance_score` or source-specific priority.
- Domain match: keyword/entity match to the topic families above.
- Source support: independent source count and source type quality.
- Market support: existence of a related Polymarket market with meaningful
  volume, liquidity, tight enough spread, or fast probability movement.
- PRJX/LP link: direct connection to HYPE/PRJX, DeFi liquidity, volatility, or
  crypto risk regime.

Suggested labels:

- `high_relevance`: likely useful for the user or PRJX LP monitoring.
- `watch`: possibly useful; include in digest but not urgent alerts.
- `background`: track for trend memory, not alert-worthy.
- `ignore`: low relevance or weak source quality.

## Topic-to-market linking

For each high or watch topic:

1. Extract entities, tickers, protocols, countries, events, and time windows from
   the topic title/summary/content.
2. Generate Polymarket search queries from those entities.
3. Search Gamma for related active and recently closed markets.
4. Link only when the market question is semantically tied to the topic.
5. Store the link with a confidence label:
   - `direct`: market question asks about the same event.
   - `adjacent`: market is related but not a direct settlement target.
   - `regime`: broad macro/crypto-risk proxy.
   - `weak`: keep for exploration only; exclude from decision context.

Never treat a linked Polymarket outcome as the truth source for the underlying
news topic unless the market's own settled condition is exactly the event being
scored.

## Collection protocol

For each candidate Polymarket market, record immutable observations:

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
- linked topic IDs and link confidence
- whether the market is active, closed, or settled

For each topic observation, record:

- `topic_id`
- title, summary, type, status, created/updated timestamps
- `importance_score`
- source URLs/authors/source types/published timestamps
- assigned topic families and relevance label
- generated Polymarket queries
- linked market IDs, if any
- corroboration status: `uncorroborated`, `multi_source`, `official`, or
  `conflicted`

For short-interval markets, sample at multiple points before close when possible:

- early window
- midpoint
- final minute
- post-close pending state
- post-settlement final state

## Settlement and outcome joins

Only join outcome labels after the market or topic is final.

For Polymarket:

- Join only after the market is closed and the result is final.
- Required post-settlement fields: final yes/no result, settlement timestamp,
  final Gamma prices if available, and ambiguity notes.
- If the market is not clearly settled, mark `pending_settlement` and exclude it
  from reliability scoring.

For topic/news sources:

- Score only questions that can later be checked against a concrete outcome:
  official announcement, regulatory action, filing, market close, ETF flow, hack
  confirmation, exchange status, or similar observable result.
- If a topic is narrative-only and cannot be settled, score it for timeliness,
  corroboration, and usefulness, not true/false accuracy.
- Preserve the difference between `topic_relevance`, `source_reliability`, and
  `market_probability_accuracy`.

## Scoring

Score each market observation as a forecast made at that observation time.

Core Polymarket metrics:

- Brier score: `(probability - outcome)^2`.
- Bucket calibration: average outcome rate for probability buckets.
- Log-loss when probabilities are safely clipped away from 0 and 1.
- Directional hit rate above simple thresholds, e.g. 60/40 and 70/30.
- Signal lead time: how long before close the signal was useful.
- Market-quality filters: minimum volume, liquidity, spread, and depth.

Core topic/news metrics:

- Time-to-first-alert versus official confirmation. Market reaction may be used
  only as a timeliness/usefulness proxy, not as a truth source.
- Corroboration count and source-type quality.
- False-positive or materially misleading rate.
- Duplicate/noise rate.
- Relevance precision: how often a surfaced topic was actually useful for the
  user's domains.

Do not rank a source family from tiny samples. Require a minimum sample count per
market family, topic family, and time bucket before assigning a stable grade.

## Source-quality ranks

Rank source families, not single stories or single markets, so one lucky or noisy
item does not look authoritative.

- A: large sample, liquid/timely, clear settlement or confirmation,
  well-calibrated or consistently useful.
- B: useful but limited by sample size, spread, source type, or confirmation
  delay.
- C: weak signal; useful only as context with other indicators.
- D: noisy or unreliable; ignore for decisions.
- Pending: insufficient settled/confirmed samples.

A rank is informational only. It should influence alert context after validation,
but it should not trigger LP entry, exit, or rebalance by itself.

## Applying to PRJX LP monitoring

Allowed uses after validation:

- Add context lines such as:
  - `Topic context: high relevance / watch / background`
  - `Prediction-market context: positive / neutral / negative`
  - `Source quality: CB Terminal crypto topics = B/Pending`
- Raise or lower manual-review priority when topic momentum, Polymarket signal,
  realized volatility, range-edge distance, and pool swap-rate evidence agree.
- Identify times when crowd-implied short-term BTC direction is noisy and should
  be ignored.
- Surface user-relevant trend digests separate from urgent LP alerts.

Not allowed:

- Auto-exit LP range solely from a topic or Polymarket price.
- Auto-enter or auto-rebalance from a topic or Polymarket price.
- Present Polymarket, CB Terminal, X/Twitter, Telegram, or RSS as the settlement
  source for HYPE or PRJX pool state.

## Initial verification notes

Read-only smoke checks on 2026-06-05 confirmed:

- `public-search?q=Bitcoin Up or Down 5m` returns settled historical BTC 5-minute
  markets with final prices.
- Active top-volume Gamma markets included a short-interval BTC Up/Down product,
  observed as a 15-minute market at the time of the smoke.
- `https://cb-terminal.dev/api/topics` returns a paginated JSON feed with 50
  topics per default page, `has_more`, `next_cursor`, and topic/source metadata.
- The CB Terminal topic feed included crypto, macro, politics, alerts, listings,
  and summary topic types during the smoke.

This means the first implementation should support `btc_short_interval` rather
than hard-coding only one interval length, and should support broad topic-family
routing rather than hard-coding only BTC.

## Completion criteria for the first research pass

- Collect at least one day of read-only Polymarket observations.
- Collect at least one day of CB Terminal topic snapshots.
- Join only settled Polymarket outcomes and externally confirmable topic outcomes.
- Produce a reliability report with sample counts, Brier score, calibration,
  topic-source quality, relevance precision, and source-quality rank.
- Keep all LP automation flags false.
- Document limitations before using the signal in live alert copy.
