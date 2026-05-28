# Stock AI Assistant Plan

## Purpose

This file preserves the full project context and implementation plan discussed so far.
`AGENTS.md` is intentionally short and points here for the durable plan.

The goal is a complete local MVP for stock research: API, CLI, persistence, clear docs, tests, and operational checks. The app is not an investment advisory service and must not place orders.

## Previously Discussed Decisions

- Always inspect current files and git state before continuing.
- Keep durable project context in tracked markdown, not only in chat.
- `AGENTS.md` is required repo-level agent context.
- Use `PLAN.md` for detailed planning so `AGENTS.md` stays readable.
- The app must work without `OPENAI_API_KEY`; OpenAI is optional explanation only.
- Offline tests are necessary but not a substitute for live external smoke checks.
- When asked to continue implementation, make concrete progress, verify it, and commit.
- Market data should come from all practical open sources, not just API feeds: include news sites and browser-based collection where useful, with Playwright MCP as the browser tooling path.
- The app should account for exchange trading sessions, market open/close regimes, and publication timestamps for economic and political news when judging freshness and relevance.
- The product surface is Telegram-first and should not depend on a web UI. Every important workflow must be usable through Telegram commands, buttons, scheduled digests, and concise source-backed messages.

## Current Implementation

Implemented:

- FastAPI app with `/`, `/health`, `/analyze/{ticker}`, `/scan`, and `/analyses/recent`.
- Deterministic technical indicators and scoring.
- Market data retrieval through `yfinance`.
- Optional OpenAI explanation with rule-based fallback.
- SQLite snapshot persistence.
- Telegram bot service and entrypoint.
- CLI scanner with default watchlist, custom tickers, and JSON output.
- live smoke script for real market data checks without OpenAI or Telegram.
- readiness endpoint with a database probe.
- Smoke tests for API routes, persistence, scanner behavior, and CLI scripts.
- SQLite path resolution relative to the project root.

## Commit History Baseline Before This Split

- `26a72d6` adds initial MVP files, smoke tests, and docs.
- `3512f61` stabilizes SQLite path resolution.
- `e20ed4f` adds API route smoke tests.
- `42cf49c` adds SQLite persistence smoke coverage.
- `2e83df0` polishes CLI behavior and runtime logging.
- `8089801` adds tracked agent instructions.
- `c5a7665` expands the first project plan in `AGENTS.md`.

## Latest Verification

- 2026-05-28: offline test suite passed with 15 tests.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests`.
- 2026-05-28: live `yfinance` smoke passed with `scripts/live_smoke.py --ticker AAPL --scan AAPL`.

## Known Limits

- OpenAI and Telegram live checks are not fully automated yet.
- The sandbox previously blocked binding `uvicorn` to `127.0.0.1:8000`; API behavior has been validated with `TestClient`.
- Real HTTP startup through `uvicorn` still needs to be verified in an environment where socket binding is allowed.
- Dependencies are broad ranges in `requirements.txt`; no lockfile or constraints file exists.
- There is no CI workflow.
- SQLite schema creation uses `Base.metadata.create_all`; there are no migrations.
- Network-heavy operations still need bounded retry/backoff policy.
- Config validation is partial; startup diagnostics should make invalid env settings obvious.
- Secrets hygiene is implicit through `.gitignore`, but there is no explicit security checklist yet.
- Local runtime notes for Telegram bot operation are not defined yet.
- No user-facing UI exists yet; API, CLI, and Telegram flows are the current product surface.
- Source coverage is still narrow: the app currently depends on `yfinance` for market data and does not yet ingest news or other open web sources through Playwright MCP.
- Session awareness is missing: the app does not yet model exchange open/close hours or news freshness windows for economy and politics.
- Telegram UX is still basic: it lacks per-chat watchlists, alert preferences, source-backed signal explanations, quiet hours, and guided decision flows.
- Risk controls are incomplete: the app does not yet separate short-term trading context from long-term research, does not flag stale/low-confidence data prominently, and does not show source coverage gaps in every Telegram answer.

## Expert Recommendations For Telegram-Only MVP

These are required product and market-structure improvements before treating the bot as a practical securities research assistant. They are not trading advice and must not turn the app into an order-placement system.

### Data Sources And Provenance

1. Build a provider registry so `yfinance` is only one market-data provider, not the core assumption of the app.
2. Add source provenance to every fact: provider name, source URL when available, observed timestamp, published timestamp, fetched timestamp, and confidence level.
3. Use official and open sources first for high-impact facts: exchange calendars, SEC EDGAR filings, Federal Reserve/FRED data, BLS releases, BEA releases, issuer investor-relations pages, and reputable market/news sites.
4. Use Playwright MCP for pages that do not expose clean APIs or RSS, while keeping scraper rules explicit, rate-limited, cached, and respectful of robots/terms.
5. Add source disagreement handling: when price, market cap, earnings date, or news timestamp differs across sources, Telegram must show that the signal is degraded instead of silently choosing one value.

### Exchange Sessions And Freshness

1. Model exchange calendars by exchange, timezone, holiday, early close, regular session, pre-market, after-hours, and closed state.
2. Attach session state to every analysis: `regular_open`, `pre_market`, `after_hours`, `closed`, `holiday`, `early_close`, or `unknown`.
3. Add stale-data rules per session. Example: a daily candle after market close is acceptable for end-of-day research, but should be labelled stale during pre-market if fresh news appeared overnight.
4. Add per-symbol exchange metadata so U.S., international, ETF, ADR, and crypto-like instruments are not treated as if they share the same session.
5. Telegram answers should always include a short freshness line: latest price timestamp, market session state, newest relevant news timestamp, and whether the signal is live, delayed, or stale.

### Economic, Political, And Corporate Event Layer

1. Track scheduled macro events: CPI, PPI, jobs report, GDP, PCE, retail sales, FOMC decisions/minutes, Treasury auctions, and central-bank speeches.
2. Track company events: earnings dates, ex-dividend dates, SEC 8-K/10-Q/10-K filings, guidance changes, buybacks, insider transactions, major litigation, rating changes, and investor-day presentations.
3. Track political/regulatory catalysts: sanctions, tariffs, antitrust decisions, export restrictions, budget/debt-ceiling events, sector regulation, and election-policy headlines.
4. Give every event a time window: before release, just released, active market reaction, cooling period, and stale/archive.
5. Separate scheduled events from breaking news. Scheduled events can be planned in Telegram digests; breaking news should produce alerts only when it is source-confirmed and relevant to a subscribed ticker or sector.

### Scoring And Risk Model Improvements

1. Split the current single `final_score` into at least three views: technical momentum, fundamental quality/value, and event/news risk.
2. Add market regime context: broad index trend, volatility regime, rate/yield backdrop, sector rotation, and risk-on/risk-off state.
3. Add liquidity and tradability checks: average volume, dollar volume, bid/ask or proxy spread when available, market cap bucket, and abnormal volume.
4. Add gap-risk and event-risk penalties around earnings, FOMC, CPI/jobs releases, geopolitical shocks, and major filings.
5. Show confidence separately from recommendation. A high score with weak source coverage should produce a lower-confidence Telegram message.
6. Keep the app non-advisory: Telegram text should say "research signal", avoid imperative buy/sell language, and preserve the no-order-placement boundary.

### Telegram Workflows

1. Replace generic `/scan` behavior with per-chat watchlists: `/watchlist`, `/add AAPL`, `/remove AAPL`, `/scan mine`, and `/scan tech`.
2. Add alert preferences: session-aware digests, quiet hours, max alerts per day, minimum confidence, market-hours-only mode, and breaking-news-only mode.
3. Add source-backed detail commands: `/why AAPL`, `/sources AAPL`, `/events AAPL`, `/freshness AAPL`, `/calendar today`, `/risk AAPL`.
4. Add digest modes: pre-market brief, market-open brief, midday check, close summary, after-hours news summary, and weekly watchlist review.
5. Add Telegram buttons for natural follow-up actions after every analysis: sources, events, rescan, add/remove watchlist, mute ticker, and explain risk.
6. Store per-chat timezone and preferred market so timestamps are readable without requiring a web UI.

### Persistence And Audit Trail

1. Persist raw source snapshots separately from normalized analysis outputs.
2. Store source URLs, timestamps, extraction method, parser version, and content hashes so later Telegram answers can explain where a signal came from.
3. Add retention policies by data type: price snapshots, filings, macro releases, news excerpts, and Telegram alerts should not all share one cleanup rule.
4. Add deduplication for repeated headlines and syndicated stories.
5. Add an audit command for the user: `/audit AAPL` should show recent analyses, key source changes, and why the latest score moved.

### Reliability And Compliance Guardrails

1. Add rate limits and backoff per provider and scraper target.
2. Add explicit handling for paywalled, blocked, or legally restricted pages; do not bypass access controls.
3. Add a source allowlist and blocklist with clear reasons.
4. Add a Telegram-visible disclaimer only where it matters: first use, major alerts, and high-risk events, not spammed on every short status line.
5. Add monitoring for stale jobs: if a scheduled digest cannot refresh sources, send a degraded digest rather than pretending it is current.

## Phase 1: Finish MVP Hardening

Status: in progress.

1. Done: add a live smoke script for real `yfinance` analyze and scan paths without requiring OpenAI or Telegram.
2. Done: add readiness behavior for database availability.
3. Done: improve market-data error handling with timeouts, bounded retries, and clearer user-facing errors.
4. Done: add basic structured logging setup for API, scanner, persistence, and Telegram background loops.
5. Done: add OpenAI live smoke guarded by `OPENAI_API_KEY`, without making OpenAI required for normal operation.
6. Add Telegram live check that verifies token/config safely without sending accidental spam.
7. Verify real `uvicorn` HTTP startup in an environment where socket binding is allowed.
8. Add config validation and startup diagnostics for env settings.
9. Add multi-source market ingestion from open sources and news sites, with Playwright MCP-backed collection where appropriate.
10. Add session-aware freshness logic for exchange hours and news timestamps, especially for economic and political publications.
11. Keep README, AGENTS, and this plan synchronized.

## Phase 2: Make Builds Reproducible

1. Pin or constrain Python dependencies.
2. Document the supported Python version.
3. Add CI for tests and compile checks.
4. Add a one-command local verification entrypoint, such as `make test` or `scripts/check.sh`.
5. Add a secrets and security checklist covering `.env`, API keys, Telegram token, logs, and git status.
6. Add local runtime notes for Telegram bot operation, logs, restart, env setup, and database location.

## Phase 3: Improve Data and Persistence

1. Introduce migrations if the SQLite schema changes beyond the current tables.
2. Add endpoints for full saved analysis payloads.
3. Add retention or cleanup rules for old snapshots.
4. Improve reporting around partial scan failures.

## Phase 4: Productize User Workflows

1. Add watchlist configuration.
2. Add a richer CLI report mode for recent analyses.
3. Improve Telegram commands for custom ticker scans and status visibility.
4. Add user-visible error summaries for failed market data, OpenAI, and Telegram operations.
5. Add per-chat Telegram watchlists, alert preferences, quiet hours, timezone, and preferred market/exchange.
6. Add Telegram-only source-backed workflows: `/why`, `/sources`, `/events`, `/freshness`, `/calendar`, `/risk`, and `/audit`.
7. Add scheduled Telegram digests for pre-market, market open, close, after-hours, and weekly review.
8. Do not add a web UI unless the user explicitly changes direction; Telegram is the primary user interface.

## Phase 5: Market Intelligence Layer

1. Build a provider registry and normalized source model for prices, fundamentals, SEC filings, macro data, news, and exchange calendars.
2. Integrate official open sources for filings and macro releases: SEC EDGAR, Federal Reserve/FRED, BLS, BEA, FOMC calendar, and exchange calendars.
3. Add Playwright MCP-backed collectors for open web pages and news sites that lack stable APIs, with caching, rate limits, provenance, and extraction tests.
4. Add source freshness, source disagreement, and confidence scoring to every analysis.
5. Add exchange-session modeling by symbol and exchange, including regular, pre-market, after-hours, holiday, and early-close states.
6. Add event-aware scoring for earnings, filings, macro releases, central-bank events, political/regulatory news, sanctions, tariffs, and sector-specific catalysts.
7. Persist raw source snapshots, normalized events, source URLs, timestamps, extraction method, parser version, and content hashes.
8. Add Telegram alerts for source-confirmed breaking events only when they affect subscribed tickers, sectors, or macro watchlists.

## Final MVP Acceptance Checklist

Before calling the MVP complete, verify all of the following:

1. API starts with `uvicorn` and real HTTP checks pass for `/health`, `/ready`, `/docs`, `/analyze/{ticker}`, `/scan`, and `/analyses/recent`.
2. CLI scanner works with default tickers, custom tickers, and `--json`.
3. Live `yfinance` smoke passes.
4. App still works without `OPENAI_API_KEY`.
5. OpenAI live smoke passes when `OPENAI_API_KEY` is configured.
6. Telegram token/config live check passes when Telegram settings are configured.
7. SQLite persists analyses and recent-analysis reads work after process restart.
8. Partial scan failures are visible without failing the entire scan.
9. Tests and compile checks pass.
10. Dependencies are pinned or constrained enough for repeatable setup.
11. Secrets are not committed and are not printed in logs.
12. README, AGENTS, and PLAN match the actual commands and behavior.
13. Local runtime notes exist for Telegram bot operation, logs, restart, env setup, and database location.
14. Telegram supports per-chat watchlists, alert preferences, timezone, preferred market, source-backed explanations, event calendar, and freshness checks.
15. Every Telegram analysis includes source provenance, latest data timestamp, market session state, news freshness, and confidence.
16. Market intelligence uses more than `yfinance`, including official open sources and Playwright MCP-backed open web/news collection where appropriate.
17. Scoring separates technical, fundamental, event/news risk, confidence, and market-regime context.
18. Final git status is clean after the completion commit.

## Definition of Done

A change is complete when:

- behavior is implemented;
- relevant tests are added or updated;
- verification commands pass, or the reason they could not run is reported;
- docs are updated when setup, operation, or direction changes;
- work is committed when the user asked for ongoing committed progress.
