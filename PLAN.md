# Stock AI Assistant Plan

## Purpose

This file preserves the full project context and implementation plan discussed so far.
`AGENTS.md` is intentionally short and points here for the durable plan.

The goal is a complete local MVP for stock research: API, CLI, persistence, clear docs, tests, and operational checks. The app is not an investment advisory service and must not place orders.

The MVP must be practical and verifiable. It is not a promise to analyze every
global market, every listed instrument, or every possible information source.
Coverage expands by documented provider support, source quality, legal access,
and user value.

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
- Market and source expansion must be tiered and explicit. The project should prefer high-signal, legally accessible, testable sources over broad but unreliable scraping.
- The system should identify instruments by more than a display ticker before expanding beyond the first U.S.-centric MVP.
- Scoring labels must remain non-advisory and should migrate away from imperative buy/sell wording.

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
- Development requirements file for lint and coverage tooling.
- `ruff` and coverage configuration in `pyproject.toml`.
- One-command local verification script at `scripts/check.sh`.
- Local-only API runner at `scripts/run_api.py` with config validation and startup diagnostics.

## Commit History Baseline Before This Split

- `26a72d6` adds initial MVP files, smoke tests, and docs.
- `3512f61` stabilizes SQLite path resolution.
- `e20ed4f` adds API route smoke tests.
- `42cf49c` adds SQLite persistence smoke coverage.
- `2e83df0` polishes CLI behavior and runtime logging.
- `8089801` adds tracked agent instructions.
- `c5a7665` expands the first project plan in `AGENTS.md`.

## Latest Verification

- 2026-05-28: offline test suite passed with 39 tests after dependency pinning updates.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after dependency pinning updates.
- 2026-05-28: `scripts/check.sh` passed after dependency pinning updates, with `ruff`, 39 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 39 tests after Telegram and HTTP smoke additions.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after Telegram and HTTP smoke additions.
- 2026-05-28: `scripts/check.sh` passed after Telegram and HTTP smoke additions, with `ruff`, 39 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 35 tests after contextual disclaimer updates.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after contextual disclaimer updates.
- 2026-05-28: `scripts/check.sh` passed after contextual disclaimer updates, with `ruff`, 35 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 31 tests after neutral research-label migration.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after neutral research-label migration.
- 2026-05-28: `scripts/check.sh` passed after neutral research-label migration, with `ruff`, 31 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 28 tests after log redaction updates.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after log redaction updates.
- 2026-05-28: `scripts/check.sh` passed after log redaction updates, with `ruff`, 28 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 27 tests after API runner and config diagnostics updates.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after API runner and config diagnostics updates.
- 2026-05-28: live `yfinance` smoke passed with `scripts/live_smoke.py --ticker AAPL --scan AAPL`.
- 2026-05-28: `scripts/check.sh` passed after API runner and config diagnostics updates, with `ruff`, 27 coverage-wrapped tests, coverage report, and compile check.

## Known Limits

- OpenAI and Telegram live checks are not fully automated yet.
- The sandbox previously blocked binding `uvicorn` to `127.0.0.1:8000`; API behavior has been validated with `TestClient`.
- Real HTTP startup through `scripts/run_api.py` still needs a live socket-bound smoke check in an environment where socket binding is allowed.
- Dependencies are pinned in `requirements.txt` and `requirements-dev.txt`, but there is still no separate lockfile or constraints file for transitive dependencies.
- Supported Python version is documented in `README.md`.
- There is no CI workflow.
- SQLite schema creation uses `Base.metadata.create_all`; there are no migrations.
- Network-heavy operations still need bounded retry/backoff policy.
- Secrets hygiene is implicit through `.gitignore`, but there is no explicit security checklist yet.
- Local runtime notes for Telegram bot operation are not defined yet.
- No user-facing UI exists yet; API, CLI, and Telegram flows are the current product surface.
- Source coverage is still narrow: the app currently depends on `yfinance` for market data and does not yet ingest news or other open web sources through Playwright MCP.
- Session awareness is missing: the app does not yet model exchange open/close hours or news freshness windows for economy and politics.
- Telegram UX is still basic: it lacks per-chat watchlists, alert preferences, source-backed signal explanations, quiet hours, and guided decision flows.
- Risk controls are incomplete: the app does not yet separate short-term trading context from long-term research, does not flag stale/low-confidence data prominently, and does not show source coverage gaps in every Telegram answer.
- Instrument identity is too thin for global coverage: ticker strings are not enough to distinguish exchanges, currencies, ADRs, local listings, share classes, ETFs, or duplicate symbols.
- Corporate actions and adjusted-price policy are not defined yet.
- OpenAI explanations do not yet have a dedicated prompt-injection and source-grounding safety layer for future web/news ingestion.
- Telegram access control is not defined yet; any chat that reaches the bot can currently subscribe.
- Scheduler behavior is basic and not yet session-aware, idempotent, or protected by per-chat alert budgets.
- The current recommendation labels include buy/sell-like language and should be replaced with neutral research labels before wider practical use.

## Scope And Coverage Boundaries

The plan targets a useful private research assistant, not universal market
coverage. Every supported market, asset class, and source must be listed in
docs and backed by tests or live smoke checks.

Initial supported coverage should be deliberately narrow:

1. U.S. listed equities from major exchanges.
2. Major U.S. ETFs.
3. Selected ADRs only when the app can show the distinction from the local listing.
4. U.S. macro, regulatory, and company-event sources that are official or clearly open.
5. Telegram workflows for a personal watchlist, not public advisory distribution.

Expansion candidates:

1. Additional developed-market exchanges by priority, source availability, and session-calendar support.
2. Crypto-like instruments only if handled as a separate asset class with 24/7 sessions.
3. Non-U.S. macro and regulatory feeds only after source provenance, language, timezone, and calendar handling are in place.

Out of scope for the first practical MVP:

1. Options, futures, bonds, private markets, leveraged strategy products, and illiquid OTC instruments.
2. Exhaustive "all world markets" coverage.
3. Exhaustive "all sources" ingestion.
4. Paywall bypassing, login-gated scraping, or access-control circumvention.
5. Order placement, portfolio execution, or personalized financial advice.

## Source Coverage Policy

Every provider should be registered with an explicit source tier, data type,
capability list, legal/terms note, freshness expectation, retry policy, and
cache TTL.

Source tiers:

1. Tier 1: official and primary sources, such as exchange calendars, SEC EDGAR, Federal Reserve/FRED, BLS, BEA, Treasury, FOMC, issuer investor-relations pages, and official exchange notices.
2. Tier 2: reputable open market, data, and news sources that expose stable APIs, feeds, RSS, downloadable files, or predictable pages.
3. Tier 3: Playwright MCP-backed collection for open web pages that lack clean APIs or RSS. Use only when allowed, rate-limited, cached, and covered by extraction tests.
4. Blocked: paywalled, login-only, legally restricted, or technically blocked pages where access would require bypass behavior.

Provider records must include:

1. Provider name and source URL.
2. Source tier and data category.
3. Observed timestamp, published timestamp, fetched timestamp, and parser version.
4. Extraction method: API, RSS, file download, HTML parser, or Playwright.
5. Confidence level, known delay, and coverage limits.
6. Content hash for deduplication and audit.
7. Failure mode: unavailable, stale, blocked, rate-limited, parse-failed, or disagreement.

## Instrument Identity And Market Metadata

Before broad market expansion, the app needs an instrument registry instead of
plain ticker-only behavior.

Required fields:

1. Display symbol and provider-specific symbols.
2. Exchange code, MIC when available, country, timezone, and trading currency.
3. Asset type: equity, ETF, ADR, index-like reference, crypto-like instrument, or unsupported.
4. Company or issuer name, sector, industry, and primary listing when available.
5. ISIN, FIGI, CIK, LEI, or other stable identifiers when available.
6. ADR/local-share mapping and share-class mapping.
7. Tradability and liquidity metadata: market cap bucket, average volume, dollar volume, and abnormal-volume flags.

Global-market work must not treat duplicate symbols as interchangeable. Telegram
messages should show exchange/currency when ambiguity is possible.

## Data Quality, Corporate Actions, And Freshness

The app must label data quality separately from the research signal. A strong
score with weak source coverage should produce a degraded confidence label.

Required policies:

1. Define adjusted-price vs raw-price usage for technical indicators.
2. Detect splits, dividends, missing candles, duplicate candles, and partial trading days.
3. Store latest price timestamp separately from analysis generation time.
4. Normalize currencies and show FX assumptions for non-USD instruments.
5. Label delayed, stale, estimated, and source-disagreed data.
6. Keep stale-data thresholds per asset class and session state.
7. Prefer degraded output over silent failure when some sources are missing.
8. Keep historical source snapshots so score changes can be audited later.

## LLM And Web Content Safety

OpenAI remains optional and must explain already normalized facts, not invent new
market data or recommendations. Future web/news ingestion adds prompt-injection
risk, so raw page text must not become trusted instructions.

Rules:

1. LLM prompts may use normalized facts and cited snippets, not raw pages as authority.
2. Source content must be treated as untrusted data.
3. LLM output must not introduce unsupported prices, dates, ratios, events, or forecasts.
4. Use schema validation or strict response checks for any future structured LLM output.
5. Keep source citations separate from generated prose.
6. Fall back to rule-based explanations when the LLM fails, times out, violates constraints, or has no API key.
7. Track OpenAI model, prompt version, and whether the explanation was rule-based or LLM-generated.

## Scoring Labels, Validation, And Calibration

The current score is useful for MVP plumbing but is not enough for practical
decision support. The plan should treat scoring as a model that needs
calibration, review, and neutral wording.

Required changes:

1. Replace buy/sell-like labels with neutral research labels, such as `HIGH_INTEREST`, `WATCH`, `NEUTRAL`, `CAUTION`, and `HIGH_RISK`.
2. Keep confidence separate from score and recommendation label.
3. Document scoring weights, inputs, missing-data behavior, and confidence penalties.
4. Add historical replay/backtest tooling only for quality review, not performance promises.
5. Compare signals against simple baselines and record false positives/false negatives.
6. Monitor score drift when provider inputs, parser versions, or scoring weights change.
7. Split user-facing context into short-term technical setup, longer-term fundamental quality/value, event/news risk, and market-regime backdrop.

## Telegram Security, Privacy, And User Controls

Telegram is the primary product surface, so bot safety and privacy are part of
the MVP rather than an afterthought.

Required controls:

1. Support an allowlist for chat IDs or an admin-approved onboarding mode.
2. Store only necessary Telegram identifiers and document what is stored.
3. Add data deletion or unsubscribe cleanup behavior for a chat.
4. Support per-chat watchlists, timezone, preferred markets, quiet hours, alert budget, and minimum confidence.
5. Deduplicate repeated alerts and avoid sending the same event repeatedly.
6. Handle blocked chats, send failures, rate limits, and Telegram API errors without stopping the bot.
7. Make disclaimer behavior contextual: first use, high-risk events, and major alerts, not every short status line.

## Scheduler And Alert Architecture

Market sessions, macro events, and per-chat preferences need a real job model.
The simple fixed sleep loop is only an early runtime placeholder.

Required design points:

1. Jobs must be idempotent and record last run, next run, status, and failure reason.
2. Schedules must support market-specific sessions, holidays, early closes, and user timezone.
3. Missed jobs should recover without duplicate alerts.
4. Alerts should have per-chat daily caps, quiet hours, confidence thresholds, and market-hours-only modes.
5. Breaking-news alerts should require source confirmation and relevance to a subscribed ticker, sector, or macro watchlist.
6. Degraded digests should be sent when refresh partially fails, clearly showing missing or stale sources.
7. Runtime logs should make provider failures, stale jobs, and Telegram delivery failures visible.

## Testing And Verification Strategy

Offline unit tests remain necessary, but market intelligence needs more layered
verification.

Required test coverage:

1. Provider contract tests with offline fixtures.
2. HTML/RSS/API extraction fixtures for every non-trivial collector.
3. Calendar edge cases: holidays, early closes, pre-market, after-hours, timezone boundaries, and 24/7 instruments.
4. Corporate-action fixtures: splits, dividends, missing candles, and adjusted-price behavior.
5. Source disagreement and stale-data tests.
6. Telegram command, button, preference, quiet-hour, and alert-dedup tests.
7. LLM fallback and prompt-safety tests that prove source text cannot override system rules.
8. Live smoke tests separated from offline tests and guarded by clear environment settings.
9. Migration and persistence tests once schema migrations are introduced.

## Operations, Budgets, And Runtime Boundaries

The MVP should stay runnable on a local machine. Heavy provider calls, Playwright
collection, and LLM usage need explicit limits.

Operational requirements:

1. Define API exposure: local-only by default; if exposed beyond localhost, add authentication, rate limits, CORS policy, and security headers.
2. Add cost and runtime budgets for OpenAI calls, provider requests, Playwright pages, and Telegram sends.
3. Add provider health reporting and last-success timestamps.
4. Add backup/restore notes for SQLite and a migration path before schema changes.
5. Add log redaction for tokens, chat IDs where appropriate, URLs with secrets, and provider credentials.
6. Add a one-command verification script that runs tests, compile checks, and selected smoke checks.
7. Document operational runbooks for API, CLI, Telegram bot, live smoke, logs, database location, and recovery from stale jobs.

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
6. Done: document practical coverage boundaries, source tiers, data-quality rules, LLM safety, Telegram security, scheduler requirements, and testing gaps in this plan.
7. Done: add Telegram live check that verifies token/config safely without sending accidental spam.
8. Done: verify real `uvicorn` HTTP startup through the local-only API runner in an environment where socket binding is allowed.
9. Done: add config validation and startup diagnostics for env settings.
10. Done: add explicit local-only API exposure policy for the MVP.
11. Done: add basic secret/log redaction checks for env values, Telegram token, and provider credentials.
12. Done: add neutral research-label migration plan and tests before changing user-facing recommendation labels.
13. Done: keep README, AGENTS, and this plan synchronized.

## Phase 2: Make Builds Reproducible

1. Done: pin or constrain Python dependencies.
2. Done: document the supported Python version.
3. Add CI for tests and compile checks.
4. Done: add a one-command local verification entrypoint at `scripts/check.sh`.
5. Add a secrets and security checklist covering `.env`, API keys, Telegram token, logs, and git status.
6. Add local runtime notes for Telegram bot operation, logs, restart, env setup, and database location.
7. Add clear live-smoke environment flags so offline tests never depend on network access.
8. Add provider-call, OpenAI-call, Playwright-page, and Telegram-send runtime budgets.
9. Add backup/restore notes for the local SQLite database.

## Phase 3: Improve Data and Persistence

1. Introduce migrations before the SQLite schema changes beyond the current tables.
2. Add endpoints for full saved analysis payloads.
3. Add retention or cleanup rules for old snapshots.
4. Improve reporting around partial scan failures.
5. Add an instrument registry for symbol, exchange, MIC, country, timezone, currency, asset type, provider aliases, and stable identifiers.
6. Add a provider registry with source tier, capability list, legal/terms note, cache TTL, retry policy, and failure taxonomy.
7. Persist raw source snapshots separately from normalized analysis outputs.
8. Persist source URLs, timestamps, extraction method, parser version, confidence, and content hashes.
9. Add provider health and last-success records.
10. Add corporate-action and adjusted-price policy before using expanded historical analysis.
11. Add stale, delayed, estimated, missing, and source-disagreed data-quality flags.
12. Add FX normalization fields before supporting non-USD instruments.

## Phase 4: Productize User Workflows

1. Add watchlist configuration.
2. Add a richer CLI report mode for recent analyses.
3. Improve Telegram commands for custom ticker scans and status visibility.
4. Add user-visible error summaries for failed market data, OpenAI, and Telegram operations.
5. Add per-chat Telegram watchlists, alert preferences, quiet hours, timezone, and preferred market/exchange.
6. Add Telegram-only source-backed workflows: `/why`, `/sources`, `/events`, `/freshness`, `/calendar`, `/risk`, and `/audit`.
7. Add scheduled Telegram digests for pre-market, market open, close, after-hours, and weekly review.
8. Add Telegram chat allowlist or admin-approved onboarding before practical bot usage.
9. Add per-chat data deletion or cleanup behavior.
10. Add alert deduplication, per-chat daily caps, confidence thresholds, and market-hours-only mode.
11. Done: replace buy/sell-like labels with neutral research labels in API, CLI, Telegram, docs, and tests.
12. Done: add contextual disclaimer behavior for first use, high-risk events, and major alerts.
13. Do not add a web UI unless the user explicitly changes direction; Telegram is the primary user interface.

## Phase 5: Market Intelligence Layer

1. Build normalized source models for prices, fundamentals, SEC filings, macro data, news, and exchange calendars.
2. Integrate official open sources for filings and macro releases: SEC EDGAR, Federal Reserve/FRED, BLS, BEA, Treasury, FOMC calendar, and exchange calendars.
3. Add market-session modeling by symbol and exchange, including regular, pre-market, after-hours, holiday, early-close, closed, and unknown states.
4. Add source freshness, source disagreement, and confidence scoring to every analysis.
5. Add data-quality handling for adjusted prices, splits, dividends, missing candles, partial sessions, and delayed quotes.
6. Add Playwright MCP-backed collectors for open web pages and news sites that lack stable APIs, with caching, rate limits, provenance, and extraction tests.
7. Add LLM source-grounding and prompt-injection protections before summarizing web/news content.
8. Add event-aware scoring for earnings, filings, macro releases, central-bank events, political/regulatory news, sanctions, tariffs, and sector-specific catalysts.
9. Add market-regime context: broad index trend, volatility regime, rate/yield backdrop, sector rotation, and risk-on/risk-off state.
10. Add historical replay/backtest tooling for score calibration and quality review.
11. Add Telegram alerts for source-confirmed breaking events only when they affect subscribed tickers, sectors, or macro watchlists.

## Phase 6: Controlled Market Expansion

Global expansion starts only after the U.S.-centric MVP is source-backed,
session-aware, and operationally stable.

1. Add a coverage matrix that lists supported markets, asset classes, source tiers, calendars, currencies, and known gaps.
2. Add the next exchange or region only when instrument identity, session calendar, currency handling, and source provenance are implemented for it.
3. Add language and translation policy for non-English sources before using them in Telegram explanations.
4. Add local regulatory/filing sources per region where practical.
5. Add region-specific live smoke checks.
6. Keep unsupported markets visible as unsupported rather than silently falling back to incomplete data.
7. Revisit the product plan before adding options, futures, bonds, or public multi-user distribution.

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
18. Supported markets and unsupported markets are documented clearly; the app does not imply exhaustive global coverage.
19. Instrument registry distinguishes symbol, exchange, currency, timezone, asset type, and provider aliases.
20. Provider registry records source tier, capabilities, cache TTL, retry policy, legal/terms notes, and failure mode.
21. Source snapshots and normalized facts retain source URL, timestamps, parser version, extraction method, confidence, and content hash.
22. Data quality flags cover stale, delayed, estimated, missing, disagreed, split-adjusted, and partial-session data.
23. Corporate-action and adjusted-price behavior is documented and tested.
24. Non-USD support includes explicit currency and FX assumptions before non-USD instruments are treated as supported.
25. Telegram access control, privacy notes, and per-chat data cleanup behavior exist.
26. Scheduler behavior is idempotent, session-aware, quiet-hour aware, and protected by alert caps.
27. Buy/sell-like labels are replaced with neutral research labels across API, CLI, Telegram, docs, and tests.
28. LLM explanations are source-grounded, prompt-injection resistant, optional, and safely fall back to rule-based text.
29. Provider collectors have offline fixtures and live smoke coverage where practical.
30. Score calibration has historical replay or backtest tooling for quality review, with no performance promise.
31. API exposure is local-only by default, or external exposure has authentication, rate limits, CORS policy, and security headers.
32. Final git status is clean after the completion commit.

## Definition of Done

A change is complete when:

- behavior is implemented;
- relevant tests are added or updated;
- verification commands pass, or the reason they could not run is reported;
- docs are updated when setup, operation, or direction changes;
- work is committed when the user asked for ongoing committed progress.
