# Architecture and delivery plan

Phase 1 uses Next.js App Router, a FastAPI service holding provider credentials and calculations, and PostgreSQL for observation history. An Alpaca adapter supplies daily stock bars and indicative options snapshots for a limited universe; Alpha Vantage remains an optional legacy adapter. Explicit refresh ingests data; scans use saved observations. Missing, stale, throttled, or unentitled data is never replaced with synthetic market data. Scheduling and corporate events remain future work.

## Provider evaluation (17 November 2026)

- [Alpha Vantage](https://www.alphavantage.co/documentation/): historical options since 2008 with IV and Greeks; historical options are premium, and without a date the previous session is returned. [Premium pricing and entitlement](https://www.alphavantage.co/premium/) depend on plan; verify fees and permitted use before purchase. Selected for an end-of-day research adapter, not real-time execution or intraday backtesting.
- [Massive](https://massive.com/docs/rest/options): consolidated US options; listed individual plans include Basic free, Starter $29/month, Developer $79/month and Advanced $199/month. [Snapshot fields depend on entitlement](https://massive.com/options). [Individual plans are for non-professional use](https://massive.com/knowledge-base/categories/options); business use and OPRA redistribution carry separate terms. Validate exact history, quote access and licensing.
- Unofficial Yahoo wrappers are not a dependable licensed options API; access can change. No free source is assumed to provide complete options quotes.

## Schema and API

Phase 1 tables: securities (unique ticker), daily prices (security/date/source unique), option contracts (provider identifier unique), option quotes (contract/date/source unique), and ingestion runs (timestamps/status/message). Phase 2–4 extensions: corporate events, source documents, immutable research reports and assumptions, screening runs/results, scenarios, watchlists, paper trades and valuations. Historical reports must be versioned.

API: GET /health, GET /securities, POST /ingest/{ticker}, GET /securities/{ticker}, GET /securities/{ticker}/options, GET /scan, and POST /payoff. OpenAPI is at /docs. No orders are placed.

## Roadmap

1. Phase 1: end-of-day provider, storage, scanner, chain, realized volatility, expiration payoff, dashboard, tests and Compose.
2. Phase 2: SEC and news retrieval, provenance-first research, validated provider-agnostic AI reports and citations.
3. Phase 3: historical tracking, transparent ranking, editable sensitivity analysis and watchlists.
4. Phase 4: paper portfolio and point-in-time backtesting only after licensed historical quotes and survivorship-aware universes are available. Until then backtesting is incomplete.

## Modeling assumptions and open decisions

Realized volatility is sample standard deviation of 20 daily log returns, annualized by sqrt(252), from unadjusted closes; splits and dividends can distort it. Option IV is the provider figure, not an event probability. Spread is (ask-bid)/mid; invalid or zero-sided markets are excluded from candidates. Expiry payoff uses intrinsic value less ask premium, 100 shares per standard contract, excluding fees and early exercise. Low IV relative to past volatility is only a screening signal, not evidence of positive expected value. Daily data are historical and may be stale. Validate provider fields, corporate actions and license before relying on results.

## Provider update

The current primary adapter uses Alpaca IEX stock bars and indicative option snapshots by default; selected option contracts can be checked explicitly with MarketData.app. Alpha Vantage remains separately selectable. MarketData.app free pricing is historical, not a guaranteed current delayed quote. Timestamped observations live in additive market_bars and market_option_quotes tables alongside the original tables. Alembic migrations manage schema creation and upgrades; a verified baseline adopts matching unversioned databases without replacing their observations. Automatic fallback and broker-connected paper trading are not implemented.

## Phase 1 completion update

Manual refresh is the MVP ingestion policy; no scheduled provider calls are made. Alembic owns schema upgrades, and a verified baseline adopts the previous unversioned schema without replacing historical data. The chain supports filters and pagination, with IV and hypothetical expiration payoff charts. Stale quotes are excluded from the screen unless explicitly requested. Realized volatility remains based on raw unadjusted closes; splits and dividends can inflate it. Alpaca indicative quotes are not executable. MarketData.app live entitlement remains to be verified with a configured token.

## Phase 2 research foundation

SEC submissions and filing excerpts plus Alpaca news headlines and summaries are saved as immutable, content-hashed source documents. An OpenAI-compatible provider adapter returns Pydantic-validated qualitative reports; citation IDs and exact excerpts are checked before saving. Source excerpts may be incomplete, and quote matching is not factual verification. A separate Alembic revision adds source and report tables. Source retrieval is manual and uses a one-hour per-provider cache; SEC requests require an identifying user agent and are spaced below the published limit.

## Phase 3 watchlists and sensitivity

Watchlist contracts are archived rather than deleted; immutable scenario snapshots retain user inputs, results and the then-current primary-provider quote. The scenario model uses expiration intrinsic payoff, per-contract transaction cost, and user-supplied probabilities. The screening priority exposes weighted IV/RV, spread, and completeness factors; evidence, catalyst and expected value are explicitly not assessed. Quote history is limited to locally saved observations, not a historical backtest.

## Phase 3 refinement

Pre-expiration scenarios use user-supplied date, risk-free rate, continuous dividend yield and per-scenario volatility in European Black-Scholes-Merton; expiration scenarios retain intrinsic payoff. American early exercise and discrete dividends are not modeled. Source-linked user judgments and saved scenario expected value contribute to a separate, fully disclosed watchlist priority only when observations and inputs meet completeness and freshness gates. Dated judgment versions are stored separately; quote history is paginated and provider/feed-separated.

## Phase 4 foundation

The local paper ledger stores manual fills, positions, cash and immutable valuation snapshots without a broker connection. Stale, missing, zero-bid, and expired marks are unvalued; indicative quotes are explicitly hypothetical. Backtesting remains gated until licensed, point-in-time data and a survivorship-aware universe are verified and full replay and expiry handling are integrated. An internal, test-only deterministic replay checks timing and executable-feed assumptions; no incomplete run is presented as a historical result.
