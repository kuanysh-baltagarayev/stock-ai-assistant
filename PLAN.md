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
- Market data should come from practical open sources, not just API feeds: prefer official APIs, RSS feeds, downloadable files, and static HTML parsers before considering heavier browser automation.
- The app should account for exchange trading sessions, market open/close regimes, and publication timestamps for economic and political news when judging freshness and relevance.
- The product surface is Telegram-first and should not depend on a web UI. Every important workflow must be usable through Telegram commands, buttons, scheduled digests, and concise source-backed messages.
- Market and source expansion must be tiered and explicit. The project should prefer high-signal, legally accessible, testable sources over broad but unreliable scraping.
- The system should identify instruments by more than a display ticker before expanding beyond the first U.S.-centric MVP.
- Scoring labels must remain non-advisory and should migrate away from imperative buy/sell wording.

## Current Implementation

Implemented:

- FastAPI app with `/`, `/health`, `/analyze/{ticker}`, `/scan`, and `/analyses/recent`.
- FastAPI coverage matrix endpoint at `/coverage`.
- Deterministic technical indicators and scoring.
- Market data retrieval through `yfinance`, with Finnhub real-time quote preference for the latest current price when `FINNHUB_API_KEY` is configured.
- Optional OpenAI explanation with rule-based fallback.
- SQLite snapshot persistence.
- SQLite raw source snapshot persistence with provenance metadata and content hashes.
- SQLite instrument registry for symbol, exchange, currency, and related metadata.
- SQLite provider registry for source tier, capability list, legal note, retry policy, and health timestamps.
- SQLite runtime budget counters for provider, OpenAI, and Telegram limits.
- Normalized market-data provider contract plus offline fixture loader for future collectors.
- Session-aware market analysis with exchange-hours freshness notes for U.S. equities.
- Telegram bot service and entrypoint.
- CLI scanner with default watchlist, custom tickers, and JSON output.
- live smoke script for real market data checks without OpenAI or Telegram.
- Per-chat Telegram watchlists with `/watchlist`, `/add`, `/remove`, and `/scan mine`.
- Telegram access control via `TELEGRAM_ALLOWED_CHAT_IDS` allowlist.
- Telegram alert preferences with quiet hours, daily caps, and market-hours-only digests.
- Telegram threshold/move/signal alerts with deduplication, confidence gating, and push delivery for high-impact updates.
- Telegram portfolio holdings and P&L tracking through `/buy`, `/sell`, and `/holdings`.
- Telegram `/chart` image generation for quick price and moving-average context.
- Ticker, market, macro, and political news collection with lightweight sentiment scoring and Telegram `/news` views.
- Telegram source-backed detail commands for saved analysis and source snapshots, including audit comparisons across saved snapshots.
- Telegram analysis follow-up buttons for sources, freshness, risk, rescan, and watchlist actions.
- Telegram `/coverage` command that exposes the supported coverage matrix and known gaps.
- Telegram company event calendar summaries derived from yfinance profile fields, including earnings and dividend hints.
- Telegram main keyboard grouped into clearer analysis, news, alert, and portfolio sections.
- Deterministic scan/digest briefing builder for Telegram that groups results
  into key signals, watch items, and risk/data-quality items with confidence
  and degradation flags, without OpenAI.
- `analyze_ticker` now threads recent SEC EDGAR filing summaries into the main
  analysis payload, operation notes, and Telegram risk/detail views.
- Recent SEC filing types and recency now feed into scoring as explicit
  event-risk inputs, lowering `final_score` when fresh 8-K/10-Q/10-K activity
  raises near-term uncertainty.
- Session-aware scheduled digests for pre-market, market-open, midday, close, after-hours, and weekly review.
- Telegram market-hours gating, digest timing, and session baseline views now use
  the NYSE holiday and early-close calendar instead of simple weekday checks.
- Response-level operation notes for OpenAI fallback, data-quality warnings, partial scan failures, and Telegram budget status.
- readiness endpoint with a database probe.
- Smoke tests for API routes, persistence, scanner behavior, and CLI scripts.
- SQLite path resolution relative to the project root.
- In-memory market-data TTL cache to avoid repeated provider downloads for the
  same ticker inside one running process.
- Enforced per-process runtime budgets for provider calls, OpenAI explanations,
  and Telegram sends.
- Development requirements file for lint and coverage tooling.
- `ruff` and coverage configuration in `pyproject.toml`.
- One-command local verification script at `scripts/check.sh`.
- Local-only API runner at `scripts/run_api.py` with config validation and startup diagnostics.
- Baseline SQLite migrations with a recorded `schema_migrations` table.

## Commit History Baseline Before This Split

- `26a72d6` adds initial MVP files, smoke tests, and docs.
- `3512f61` stabilizes SQLite path resolution.
- `e20ed4f` adds API route smoke tests.
- `42cf49c` adds SQLite persistence smoke coverage.
- `2e83df0` polishes CLI behavior and runtime logging.
- `8089801` adds tracked agent instructions.
- `c5a7665` expands the first project plan in `AGENTS.md`.

## Latest Verification

- 2026-06-08: `scripts/test_fast.sh` passed after adding deterministic
  Telegram scan/digest briefing groups and focused briefing tests, with 97
  tests passing.
- 2026-06-02: `scripts/check.sh` passed after propagating sector-aware catalyst
  context into API/Telegram risk text and rule-based explanations, with targeted
  app/Telegram/scoring coverage plus the full repo verification script.
- 2026-06-02: `scripts/check.sh` passed after making macro and earnings
  event-risk sector-sensitive, with targeted scoring coverage plus the full repo
  verification script.
- 2026-06-02: `scripts/test_fast.sh` passed on the current branch while syncing
  `PLAN.md` with the latest Finnhub/news/alert/chart/portfolio feature set.
- 2026-06-01: `scripts/check.sh` passed after making event-risk scoring
  cluster-aware across earnings dates, recent SEC filings, and high-impact macro
  events, with `ruff`, 274 coverage-wrapped tests, coverage report, and compile
  check.
- 2026-06-01: `scripts/check.sh` passed after making recent SEC filing types and
  recency explicit scoring inputs, wiring filing-driven risk into
  `AnalyzeResponse`, and aligning risk-overlay notes with the actual computed
  risk score, with `ruff`, 269 coverage-wrapped tests, coverage report, and
  compile check.
- 2026-06-01: `scripts/check.sh` passed after threading SEC EDGAR filing context
  into `AnalyzeResponse`, Telegram analysis/risk views, and raw source snapshot
  payloads, with `ruff`, 269 coverage-wrapped tests, coverage report, and
  compile check.
- 2026-06-01: `scripts/check.sh` passed after aligning Telegram market-hours and
  digest session handling with the exchange calendar, fixing early-close market
  open logic, and making EDGAR snapshot persistence tests deterministic, with
  `ruff`, 268 coverage-wrapped tests, coverage report, and compile check.
- 2026-06-01: `scripts/check.sh` passed after adding SEC EDGAR filing collector,
  exchange calendar service, and Telegram `/filings` command, with `ruff`, 142
  coverage-wrapped tests, coverage report, and compile check.
- 2026-06-01: `scripts/check.sh` passed after adding unsubscribe cleanup for
  per-chat Telegram data, with `ruff`, 98 coverage-wrapped tests, coverage
  report, and compile check.
- 2026-06-01: `scripts/check.sh` passed after adding user-visible operation
  error summaries to CLI and Telegram scan/digest output, with `ruff`, 97
  coverage-wrapped tests, coverage report, and compile check.
- 2026-06-01: `scripts/check.sh` passed after adding aggregate summaries to
  the CLI recent-analysis report mode, with `ruff`, 95 coverage-wrapped
  tests, coverage report, and compile check.
- 2026-06-01: `scripts/check.sh` passed after improving Telegram custom scan
  commands and status visibility, with `ruff`, 94 coverage-wrapped tests,
  coverage report, and compile check.
- 2026-06-01: `scripts/check.sh` passed after adding the coverage matrix
  endpoint and Telegram `/coverage` command, with `ruff`, 93 coverage-wrapped
  tests, coverage report, and compile check.
- 2026-06-01: `scripts/check.sh` passed after adding `scripts/run_api.py
  --smoke` local HTTP startup verification, with `ruff`, 91 coverage-wrapped
  tests, coverage report, and compile check.
- 2026-06-01: `scripts/check.sh` passed after Telegram data-quality warnings
  were surfaced in analysis, freshness, sources, and risk views, with `ruff`,
  90 coverage-wrapped tests, coverage report, and compile check.
- 2026-06-01: `scripts/check.sh` passed after persistent runtime budgets were
  introduced, with `ruff`, 89 coverage-wrapped tests, coverage report, and
  compile check.
- 2026-06-01: `scripts/test_fast.sh` passed after Telegram event calendar
  summaries were introduced, with `ruff` and 69 focused tests.
- 2026-06-01: `scripts/check.sh` passed after Telegram event calendar
  summaries were introduced, with `ruff`, 88 coverage-wrapped tests, coverage
  report, and compile check.
- 2026-06-01: `scripts/test_fast.sh` passed after source-disagreement audit
  view was introduced, with `ruff` and 65 focused tests.
- 2026-06-01: `scripts/check.sh` passed after source-disagreement audit view
  was introduced, with `ruff`, 84 coverage-wrapped tests, coverage report, and
  compile check.
- 2026-06-01: `scripts/test_fast.sh` passed after richer CLI recent-analysis
  report mode was introduced, with `ruff` and 65 focused tests.
- 2026-06-01: `scripts/check.sh` passed after richer CLI recent-analysis report
  mode was introduced, with `ruff`, 84 coverage-wrapped tests, coverage
  report, and compile check.
- 2026-06-01: `scripts/test_fast.sh` passed after Telegram alert preferences
  were introduced, with `ruff` and 59 focused tests.
- 2026-06-01: `scripts/check.sh` passed after Telegram alert preferences were
  introduced, with `ruff`, 78 coverage-wrapped tests, coverage report, and
  compile check.
- 2026-05-31: `scripts/test_fast.sh` passed after Telegram access control was
  introduced, with `ruff` and 49 focused tests.
- 2026-05-31: `scripts/check.sh` passed after Telegram access control was
  introduced, with `ruff`, 68 coverage-wrapped tests, coverage report, and
  compile check.
- 2026-06-01: `scripts/test_fast.sh` passed after session-aware scheduled
  Telegram digests were introduced, with `ruff` and 63 focused tests.
- 2026-06-01: `scripts/check.sh` passed after session-aware scheduled Telegram
  digests were introduced, with `ruff`, 82 coverage-wrapped tests, coverage
  report, and compile check.
- 2026-06-01: `scripts/test_fast.sh` passed after Telegram source-backed detail
  commands were introduced, with `ruff` and 61 focused tests.
- 2026-06-01: `scripts/check.sh` passed after Telegram source-backed detail
  commands were introduced, with `ruff`, 80 coverage-wrapped tests, coverage
  report, and compile check.
- 2026-05-31: `scripts/test_fast.sh` passed after user-visible operation
  summaries were introduced, with `ruff` and 51 focused tests.
- 2026-05-31: `scripts/check.sh` passed after user-visible operation summaries
  were introduced, with `ruff`, 70 coverage-wrapped tests, coverage report,
  and compile check.
- 2026-05-31: `scripts/test_fast.sh` passed after source provider abstraction
  updates, with `ruff` and 54 focused tests.
- 2026-05-31: `scripts/check.sh` passed after source provider abstraction
  updates, with `ruff`, 73 coverage-wrapped tests, coverage report, and
  compile check.
- 2026-06-01: `scripts/test_fast.sh` passed after session/freshness foundation
  updates, with `ruff` and 55 focused tests.
- 2026-06-01: `scripts/check.sh` passed after session/freshness foundation
  updates, with `ruff`, 74 coverage-wrapped tests, coverage report, and
  compile check.
- 2026-05-31: `scripts/test_fast.sh` passed after per-chat Telegram watchlist
  support was introduced, with `ruff` and 44 focused tests.
- 2026-05-31: `scripts/check.sh` passed after per-chat Telegram watchlist
  support was introduced, with `ruff`, 63 coverage-wrapped tests, coverage
  report, and compile check.
- 2026-05-31: `scripts/test_fast.sh` passed after development economy workflow
  updates, with `ruff` and 40 focused tests.
- 2026-05-31: `scripts/check.sh` passed after development economy workflow
  updates, with `ruff`, 59 coverage-wrapped tests, coverage report, and compile
  check.
- 2026-05-31: `scripts/check.sh` passed after market-data TTL cache and runtime
  budget enforcement were introduced, with `ruff`, 59 coverage-wrapped tests,
  coverage report, and compile check.
- 2026-05-28: offline test suite passed with 55 tests after raw source snapshot, data-quality, and FX metadata support was introduced.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after raw source snapshot, data-quality, and FX metadata support was introduced.
- 2026-05-28: `scripts/check.sh` passed after raw source snapshot, data-quality, and FX metadata support was introduced, with `ruff`, 55 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 54 tests after provider registry support was introduced.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after provider registry support was introduced.
- 2026-05-28: `scripts/check.sh` passed after provider registry support was introduced, with `ruff`, 54 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 50 tests after instrument registry support was introduced.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after instrument registry support was introduced.
- 2026-05-28: `scripts/check.sh` passed after instrument registry support was introduced, with `ruff`, 50 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 49 tests after partial scan failure reporting was introduced.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after partial scan failure reporting was introduced.
- 2026-05-28: `scripts/check.sh` passed after partial scan failure reporting was introduced, with `ruff`, 49 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 49 tests after snapshot retention and cleanup rules were introduced.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after snapshot retention and cleanup rules were introduced.
- 2026-05-28: `scripts/check.sh` passed after snapshot retention and cleanup rules were introduced, with `ruff`, 49 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 48 tests after snapshot retention and cleanup rules were introduced.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after snapshot retention and cleanup rules were introduced.
- 2026-05-28: `scripts/check.sh` passed after snapshot retention and cleanup rules were introduced, with `ruff`, 48 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 46 tests after full analysis payload endpoint support was introduced.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after full analysis payload endpoint support was introduced.
- 2026-05-28: `scripts/check.sh` passed after full analysis payload endpoint support was introduced, with `ruff`, 46 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 44 tests after baseline migrations were introduced.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after baseline migrations were introduced.
- 2026-05-28: `scripts/check.sh` passed after baseline migrations were introduced, with `ruff`, 44 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 40 tests after runtime budget updates.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after runtime budget updates.
- 2026-05-28: `scripts/check.sh` passed after runtime budget updates, with `ruff`, 40 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 40 tests after live network guard updates.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after live network guard updates.
- 2026-05-28: `scripts/check.sh` passed after live network guard updates, with `ruff`, 40 coverage-wrapped tests, coverage report, and compile check.
- 2026-05-28: offline test suite passed with 39 tests after CI workflow addition.
- 2026-05-28: compile check passed for `app`, `scripts`, and `tests` after CI workflow addition.
- 2026-05-28: `scripts/check.sh` passed after CI workflow addition, with `ruff`, 39 coverage-wrapped tests, coverage report, and compile check.
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
- Dependencies are pinned in `requirements.txt` and `requirements-dev.txt`, but there is still no separate lockfile or constraints file for transitive dependencies.
- Supported Python version is documented in `README.md`.
- SQLite schema changes now run through the internal migration runner, but richer
  schema/versioning tooling is still not in place.
- Network-heavy operations still need bounded retry/backoff policy.
- Secrets hygiene is implicit through `.gitignore`, but there is no explicit security checklist yet.
- Local runtime notes for Telegram bot operation are not defined yet.
- No user-facing UI exists yet; API, CLI, and Telegram flows are the current product surface.
- Source coverage is still narrow: the app now combines `yfinance`, Finnhub, SEC
  EDGAR, Alpha Vantage, and GDELT in a U.S.-centric setup, but it still lacks
  broader official macro feeds, deeper multi-market coverage, and richer
  cross-provider reconciliation.
- Session awareness is present for U.S. equities in the core analysis path, but
  broader exchange calendars and timezone-complete freshness windows for global
  markets are still not modeled.
- Telegram UX is materially broader now, but digest scheduling and preference
  control are still basic compared with the target job model.
- Risk controls are incomplete: the app does not yet separate short-term trading context from long-term research, and it still does not show source coverage gaps in every Telegram answer.
- Instrument identity exists for the U.S.-centric MVP, but cross-listing mapping, provider aliases, and global identifier coverage remain incomplete.
- Corporate actions are currently represented as a raw-close policy with no auto-adjustment, and broader adjusted-price handling is still limited.
- OpenAI explanations do not yet have a dedicated prompt-injection and source-grounding safety layer for future web/news ingestion.
- Telegram access control is allowlist-based and intentionally narrow for the current MVP; broader onboarding flows are still not implemented.
- Scheduler behavior is still basic and not yet idempotent or timezone-aware, even though per-chat quiet hours and daily caps are now enforced.
- The current recommendation labels include buy/sell-like language and should be replaced with neutral research labels before wider practical use.
- FX normalization metadata is stored, but no live FX conversion provider is wired in yet.
- Browser automation collectors are not part of the current MVP configuration.

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
3. Tier 3: open web collection for pages that lack clean APIs or RSS. Prefer static HTML parsing; use browser automation only when explicitly justified, allowed, rate-limited, cached, and covered by extraction tests.
4. Blocked: paywalled, login-only, legally restricted, or technically blocked pages where access would require bypass behavior.

Provider records must include:

1. Provider name and source URL.
2. Source tier and data category.
3. Observed timestamp, published timestamp, fetched timestamp, and parser version.
4. Extraction method: API, RSS, file download, HTML parser, or explicitly approved browser automation.
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

## Deployment And Validation Posture

Current product-validation stance:

1. Do not prioritize production deployment yet; the app is still too early for a broader launch.
2. When deployment becomes useful, prefer the existing Hetzner server that already hosts `avtoqyzmet.kz` instead of paying for a second idle server.
3. The first deployment target should be Telegram-first validation for U.S. market research, not a public HTTP API.
4. Keep the API bound to localhost unless there is a concrete reason to expose it publicly.
5. Use Telegram access controls during the early validation phase so product-quality testing is not confused by public abuse, random traffic, or premature growth experiments.
6. Treat public onboarding, open discovery, and broader demand testing as later phases after the bot is stable and personally useful.

OpenAI stance for deployment and product validation:

1. OpenAI is worth adding only as an optional explanation and summarization layer on top of deterministic facts.
2. The core score, market facts, and risk signals must stay usable without OpenAI.
3. Do not let the LLM become the primary market-analysis engine or the authority for prices, events, or recommendations.
4. The first value from OpenAI should be better Telegram briefings, clearer summaries, and cleaner "what changed" explanations rather than more complex autonomous reasoning.

## No-OpenAI Utility Roadmap

This section is the detailed implementation queue for making the app useful
before adding OpenAI. The goal is to reduce future planning cost: each slice
names the intended product behavior, likely files, tests, acceptance criteria,
and known constraints.

Guiding principles:

1. OpenAI must remain optional. Every workflow below must work with
   `OPENAI_API_KEY` unset.
2. Prioritize Telegram usefulness over public API expansion. The primary
   user-facing loop is watchlist -> briefing -> detail -> audit -> refinement.
3. Prefer source-backed deterministic summaries over generated prose.
4. Keep each implementation slice small enough to verify with
   `scripts/test_fast.sh`; run `scripts/check.sh` before committing.
5. Use offline fixtures for provider and scoring tests. Live network checks stay
   explicit through `ALLOW_LIVE_NETWORK=1`.
6. Avoid public launch work until the bot is personally useful and stable.

### Priority 1: Telegram Daily Briefing

Product goal:

1. Make `/scan mine` and scheduled digests answer the practical question:
   "What should I look at today and why?"
2. The answer should group results by actionability, not only by score.
3. The message should be useful without tapping follow-up buttons.

Current state:

1. Telegram has watchlists, scans, digests, confidence thresholds, source-backed
   detail commands, and scheduled session modes.
2. Done: `app/services/briefing.py` now builds deterministic scan briefings and
   Telegram scan/digest output groups results by key signals, watch items, and
   risk/data-quality items.
3. Remaining: briefing items still need score deltas, latest news timestamps,
   richer freshness/source-gap flags, and reuse in CLI recent reports.

Implementation plan:

1. Add a deterministic briefing builder, preferably
   `app/services/briefing.py`, rather than burying logic in Telegram formatting.
2. Define a `BriefingItem`/`BriefingSummary` internal dataclass with:
   ticker, label, final_score, score_delta, confidence, freshness_state,
   latest_news_time, risk_flags, catalyst_flags, source_gap_flags, and
   short_reason.
3. Build the summary from existing `AnalyzeResponse`, saved
   `AnalysisSnapshot`, `data_quality`, `market_session`, `news`, `sec_filings`,
   and `operation_notes`.
4. Use it in `TelegramBotService._scan_text`, scheduled digest formatting, and
   optionally CLI `--recent`.
5. Keep the first message under Telegram's practical reading limit:
   top 5 tickers, one line per ticker, then short "market context" and
   "degraded data" sections.

Suggested files:

1. `app/services/briefing.py`
2. `app/services/telegram/_formatting.py`
3. `app/services/telegram_bot.py`
4. `tests/test_briefing.py`
5. `tests/test_telegram_digests.py`
6. `tests/test_telegram_disclaimers.py`

Acceptance criteria:

1. `/scan mine` shows a grouped briefing with confidence and freshness visible.
2. Scheduled digests use the same deterministic summary structure.
3. Low-confidence and stale-source results are not hidden silently; they are
   either filtered by user threshold or shown under a degraded-data note.
4. Tests cover empty watchlist, partial scan failure, low confidence, stale
   data, source disagreement, and one high-risk catalyst.

### Priority 2: Mandatory Freshness And Confidence In Telegram

Product goal:

1. Every important Telegram answer should show whether the signal is fresh,
   delayed, stale, or degraded.
2. Users should see confidence and source coverage before trusting a score.

Current state:

1. `AnalyzeResponse` already carries `data_quality`, `market_session`,
   `source_provenance`, and operation notes.
2. `/sources`, `/freshness`, and `/risk` expose much of this detail.
3. The first `/analyze` and scan/digest messages still need a compact,
   consistent freshness line.

Implementation plan:

1. Add a shared formatter helper for a compact freshness line:
   session status, latest price timestamp, provider, confidence, and flags.
2. Use it in `_analysis_text`, `_scan_text`, digest text, `_why_text`,
   `_risk_text`, and audit output when available.
3. Treat missing timestamp or unknown provider as a visible degradation, not as
   a normal state.
4. Keep the language non-advisory: "research signal", "confidence",
   "data quality", "source gap".

Suggested files:

1. `app/services/telegram/_formatting.py`
2. `app/services/coverage.py`
3. `app/schemas.py`
4. `tests/test_telegram_disclaimers.py`
5. `tests/test_telegram_details.py`

Acceptance criteria:

1. `/analyze AAPL` includes one compact source/freshness/confidence line.
2. `/scan mine` includes confidence and degraded-data counts.
3. `/risk AAPL` includes data confidence and source gaps near the top.
4. Tests assert the first answer does not require `/sources` to discover stale
   or low-confidence data.

### Priority 3: Thread FRED Macro Data Into Core Analysis

Product goal:

1. Use official FRED data to improve market context without OpenAI.
2. Let macro conditions influence risk, weighting, and Telegram explanations
   when `FRED_API_KEY` is configured.
3. Keep graceful fallback when no FRED key exists.

Current state:

1. `app/services/fred_collector.py` exists and has tests.
2. `scanner._save_macro_indicators()` persists FRED source snapshots when a DB
   session and `FRED_API_KEY` are available.
3. `analyze_ticker()` currently calls `build_macro_context(generated_at,
   news_context=news_context)` without passing `fred_latest`, so persisted FRED
   data does not reliably affect the main score.

Implementation plan:

1. Add a helper in `scanner.py` or a new macro service:
   fetch FRED once per analysis when enabled, convert latest observations into
   `{series_id: value}`.
2. Pass the resulting `fred_latest` into `build_macro_context(...)`.
3. Persist the same FRED collection as a `SourceSnapshot` when `db` is present.
4. Add operation notes when FRED is unavailable, stale, or partially failed.
5. Avoid repeated FRED calls during multi-ticker scans; introduce a scan-level
   macro context or short TTL cache before using this in `scan_tickers`.
6. Update `macro_context_summary()` text so Fed rate, unemployment, and CPI
   context is explicit and not overstated.

Suggested files:

1. `app/services/scanner.py`
2. `app/services/macro_context.py`
3. `app/services/fred_collector.py`
4. `tests/test_macro_context.py`
5. `tests/test_app.py`
6. `tests/test_fred_collector.py`

Acceptance criteria:

1. With mocked FRED data, `analyze_ticker()` passes `fred_latest` into scoring.
2. FRED snapshot persistence remains optional and does not break analysis.
3. Without `FRED_API_KEY`, analysis still passes and adds a clear non-fatal
   operation note only when user-facing context needs it.
4. Scans do not make one FRED network call per ticker.
5. Tests cover FRED success, missing key, partial error, and scan reuse.

### Priority 4: Market Regime Context

Product goal:

1. Stop analyzing a ticker in isolation.
2. Add broad U.S. market context: index trend, volatility regime, rates/yields
   backdrop, sector rotation, and risk-on/risk-off state.

Current state:

1. `MacroContext` has volatility/rate/inflation fields and upcoming events.
2. Scoring already adapts weights when macro context exists.
3. There is no dedicated market-regime collector or normalized regime snapshot.

Implementation plan:

1. Add `app/services/market_regime.py`.
2. Start with a narrow, testable U.S. regime model:
   SPY trend, QQQ trend, VIX proxy if available through yfinance, 10Y yield
   proxy where available, and sector ETF relative strength for a small fixed
   set.
3. Represent regime as deterministic fields:
   `index_trend`, `volatility_regime`, `rates_backdrop`, `sector_rotation`,
   `risk_appetite`, `confidence`, and `source_provenance`.
4. Feed regime into scoring as context, not as a dominant signal.
5. Surface one short Telegram line: "Market regime: risk-on/risk-off/mixed,
   confidence X, source Y".

Suggested files:

1. `app/services/market_regime.py`
2. `app/services/scoring.py`
3. `app/services/scanner.py`
4. `app/services/telegram/_formatting.py`
5. `tests/test_market_regime.py`
6. `tests/test_macro_aware_scoring.py`

Acceptance criteria:

1. Regime builder works from offline price fixtures.
2. Missing VIX/yield data degrades confidence instead of failing analysis.
3. Telegram analysis includes a short regime line when available.
4. Scoring tests prove regime affects risk/weights within capped bounds.

### Priority 5: Score Decomposition In User Output

Product goal:

1. Make the deterministic score understandable without LLM prose.
2. Show users whether a signal comes from momentum, valuation, event risk, or
   weak data.

Current state:

1. `Scores` already has `momentum_score`, `valuation_score`, `risk_score`, and
   `final_score`.
2. Telegram currently prints the numeric scores but needs better grouping and
   short deterministic labels.

Implementation plan:

1. Add a score-explanation helper that maps score ranges and reasons into
   stable labels:
   technical setup, valuation setup, event/news risk, data confidence.
2. Avoid buy/sell phrasing. Use `HIGH_INTEREST`, `WATCH`, `NEUTRAL`,
   `CAUTION`, `HIGH_RISK` and Russian translations.
3. Add missing-data reasons so a high final score with poor source coverage is
   visibly low-confidence.
4. Use the same helper in API payload, Telegram analysis, digest, and CLI
   recent report.

Suggested files:

1. `app/services/scoring_explain.py` or existing `ai_explainer.py` rule-based
   section if kept cleanly separated from OpenAI.
2. `app/services/telegram/_formatting.py`
3. `scripts/scan_market.py`
4. `tests/test_research_labels.py`
5. `tests/test_telegram_disclaimers.py`

Acceptance criteria:

1. Telegram shows the top deterministic reasons grouped by technical,
   valuation, risk, and data quality.
2. The same payload works without OpenAI.
3. Tests prove no buy/sell-like wording returns in user-facing text.

### Priority 6: Historical Replay And Backtest Quality Review

Product goal:

1. Validate whether the deterministic score is useful over time.
2. Keep this as quality review, not a performance promise.
3. Make `/backtest TICKER` honest and actionable.

Current state:

1. `app/services/backtesting.py` and tests exist.
2. Telegram recognizes `/backtest TICKER`.
3. `TelegramBotService._backtest_ticker()` currently returns a placeholder when
   there are snapshots but no historical-price comparison.

Implementation plan:

1. Finish `_backtest_ticker()` by pairing saved `AnalysisSnapshot.created_at`
   with later price data over fixed horizons: 1d, 5d, 20d.
2. Use adjusted or raw price policy explicitly and show which one was used.
3. Add a CLI path, for example `scripts/scan_market.py --backtest AAPL`, only
   if it stays small; Telegram first is enough for the first slice.
4. Report hit rate by label, average forward return, false positives, false
   negatives, sample size, and data-quality caveats.
5. Add a "not enough data" path that tells the user how many saved analyses are
   needed.

Suggested files:

1. `app/services/backtesting.py`
2. `app/services/telegram_bot.py`
3. `app/services/market_data.py`
4. `tests/test_backtesting.py`
5. `tests/test_telegram_details.py` or a new `tests/test_telegram_backtest.py`

Acceptance criteria:

1. `/backtest AAPL` compares historical snapshots to later prices when enough
   data exists.
2. The report includes sample size and explicit "not investment performance"
   wording.
3. Offline tests cover correct/incorrect signal classification, insufficient
   data, missing price data, and neutral labels.

### Priority 7: Better "Why Changed" Audit

Product goal:

1. Make `/audit TICKER` the explanation engine without OpenAI.
2. Show why a score moved since the last snapshot.

Current state:

1. Raw source snapshots and analysis snapshots are persisted.
2. `/audit` shows recent score/provenance changes.
3. It can be expanded into a compact delta report.

Implementation plan:

1. Add a deterministic delta builder:
   price delta, final score delta, sub-score deltas, label change, confidence
   delta, source change, latest filing/news change, market session change.
2. Include "probable drivers" from changed fields, not guessed causal claims.
3. Add a "source changed" warning when provider or confidence changed between
   snapshots.
4. Reuse the same delta in daily briefings.

Suggested files:

1. `app/services/history.py`
2. `app/services/telegram_bot.py`
3. `app/services/briefing.py`
4. `tests/test_history.py`
5. `tests/test_telegram_details.py`

Acceptance criteria:

1. `/audit AAPL` explains score movement without LLM.
2. It distinguishes real signal movement from source/freshness/confidence
   changes.
3. Tests cover score delta, confidence degradation, source disagreement,
   filing/news arrival, and label change.

### Priority 8: Source Gaps And Coverage Warnings

Product goal:

1. Users should know when a signal is narrow because sources are missing.
2. The bot should prefer "degraded but useful" over silent confidence.

Current state:

1. `/coverage` exists.
2. Provider registry and source snapshots exist.
3. Coverage gaps are not shown consistently in every high-level Telegram
   answer.

Implementation plan:

1. Create a per-analysis source coverage summary:
   expected sources, present sources, missing optional sources, missing critical
   sources, source disagreement, stale source count.
2. For U.S. equities, expected sources should initially include market data,
   SEC filings where CIK is known, macro calendar/context, and news context.
3. Add a short source-gap line to analysis, scans, digests, and risk view.
4. Keep `/coverage` as the detailed static matrix and use the per-analysis
   summary for the current ticker.

Suggested files:

1. `app/services/coverage.py`
2. `app/services/scanner.py`
3. `app/services/telegram/_formatting.py`
4. `tests/test_app.py`
5. `tests/test_telegram_disclaimers.py`

Acceptance criteria:

1. A missing SEC/FRED/news source lowers or explains confidence where relevant.
2. The first Telegram answer shows source gaps compactly.
3. Tests cover full coverage, partial coverage, and stale source coverage.

### Priority 9: Corporate Actions And Price Policy Hardening

Product goal:

1. Prevent misleading technical signals around splits, dividends, missing
   candles, and partial sessions.
2. Make price adjustment policy visible and testable.

Current state:

1. Price adjustment policy metadata exists.
2. The plan still requires stronger handling for adjusted prices, splits,
   dividends, missing candles, partial sessions, and delayed quotes.

Implementation plan:

1. Add fixtures for split/dividend/missing-candle scenarios.
2. Add data-quality flags:
   `split_detected`, `dividend_detected`, `missing_candles`,
   `partial_session`, `adjustment_policy_warning`.
3. Ensure technical indicators either use a documented adjusted series or mark
   raw-close limitations.
4. Telegram should show a short warning when corporate-action flags affect
   confidence.

Suggested files:

1. `app/services/market_data.py`
2. `app/services/indicators.py`
3. `app/services/source_snapshots.py`
4. `tests/test_app.py`
5. `tests/test_indicators.py` if created

Acceptance criteria:

1. Split/dividend fixtures produce deterministic data-quality flags.
2. Technical scores do not silently treat broken series as normal.
3. Telegram shows corporate-action warnings when confidence is degraded.

### Priority 10: Scheduler And User Preference Hardening

Product goal:

1. Make digests reliable enough for real personal use.
2. Avoid duplicate, missed, or timezone-confusing alerts.

Current state:

1. Telegram has quiet hours, daily caps, market-hours-only mode, and digest
   deduplication.
2. The scheduler is still basic and not a full persisted job model.

Implementation plan:

1. Add persisted job records with last run, next run, status, failure reason,
   and content fingerprint.
2. Add per-chat timezone support to scheduling and display.
3. Distinguish scheduled digest, breaking event, price move, and weekly review
   job types.
4. On partial provider failure, send a degraded digest if enough data exists;
   do not pretend the refresh was complete.

Suggested files:

1. `app/models.py`
2. `app/migrations.py`
3. `app/services/telegram_bot.py`
4. `app/services/market_hours.py`
5. `tests/test_telegram_digests.py`
6. `tests/test_telegram_preferences.py`

Acceptance criteria:

1. Restarting the bot does not duplicate the latest digest.
2. Quiet hours and market-hours-only mode use the user's timezone.
3. Failure reason is stored and visible in `/status` or preferences output.

### Priority 11: Minimal Product Validation Metrics

Product goal:

1. Learn whether the bot is useful before public launch.
2. Track usage without storing unnecessary personal data.

Current state:

1. Runtime logs exist.
2. Telegram subscriptions and preferences are persisted.
3. There is no explicit product-validation metric layer.

Implementation plan:

1. Track command usage counts by command, day, and chat ID hash or internal
   chat ID according to the privacy policy chosen for the MVP.
2. Track return usage: active chats per day/week, watchlist size, digest opens
   cannot be measured directly in Telegram, but follow-up button usage can.
3. Track quality proxies: number of rescans, `/audit`, `/sources`, `/risk`,
   and `/remove` after alerts.
4. Add an admin-only summary command or CLI report for personal validation.
5. Do not add public growth funnels yet.

Suggested files:

1. `app/models.py`
2. `app/migrations.py`
3. `app/services/telegram_bot.py`
4. `scripts/scan_market.py` or new `scripts/usage_report.py`
5. `tests/test_telegram_preferences.py`

Acceptance criteria:

1. Usage metrics are stored without secrets or message text.
2. Admin report shows daily active chats, command counts, and top workflows.
3. Tests prove unsubscribe cleanup handles personal data consistently.

### Priority 12: Documentation And Runbooks For The Closed Bot

Product goal:

1. Make the future private Telegram deployment repeatable without rediscovery.
2. Keep public API exposure out of scope until explicitly chosen.

Implementation plan:

1. Add a closed-bot runbook only when deployment work begins.
2. Include env variables, systemd service, local-only API policy, Telegram
   long-polling/webhook choice, SQLite backup, logs, restart, and rollback.
3. Document Hetzner shared-server constraints:
   bind API to localhost, use one worker initially, enforce budgets, monitor
   memory/CPU, and consider small swap.
4. Do not deploy as part of this roadmap unless explicitly requested.

Suggested files:

1. `README.md`
2. `docs/deploy-telegram-bot.md` if docs grow beyond README.
3. `PLAN.md`

Acceptance criteria:

1. A future deployment can be performed from documented commands.
2. The docs make clear that public API exposure is not part of the first bot
   validation phase.

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

## Development Economy Rules

These rules keep future implementation work cheap in tokens, live-provider
quota, and review time.

1. Work in one vertical slice at a time: schema, service behavior, tests, docs,
   and verification for a narrow workflow.
2. Prefer offline fixtures and deterministic tests before any live provider
   smoke. Use `ALLOW_LIVE_NETWORK=1` only for deliberate final checks.
3. Use `scripts/test_fast.sh` while iterating and reserve `scripts/check.sh` for
   completion checks before commit.
4. Keep normal development on rule-based explanations; run OpenAI smoke only
   when changing LLM behavior.
5. Keep development watchlists to one to three tickers unless testing scan-scale
   behavior.
6. When asking an agent to continue, name the next slice and expected files when
   possible. This avoids re-reading unrelated project areas.
7. Update this plan at the end of each slice so future turns can resume from
   tracked context instead of rediscovering decisions.
8. Commit completed, verified slices so future agents can inspect `git log` and
   `git show` instead of relying on chat history.

## Next Implementation Slices

Suggested order for low-waste progress:

1. Done: Live SEC EDGAR filing summaries and official exchange calendar feeds with
   source-backed Telegram hooks.
   - `app/services/edgar_collector.py`: fetches recent 8-K/10-Q/10-K filings via
     EDGAR public API (Tier 1, no auth); registered in provider registry.
   - `app/services/exchange_calendar.py`: NYSE holiday/early-close calendar for
     2025-2026; `get_session_state`, `is_trading_day`, `next_trading_day`.
   - Telegram `/filings TICKER` command and "Подачи SEC" inline button.
   - 42 new offline tests in `test_edgar_collector.py` and `test_exchange_calendar.py`.

2. Done: persist EDGAR filing metadata as a `SourceSnapshot` alongside the
   market-data snapshot during `analyze_ticker`.
   - `app/services/scanner.py` saves the `edgar` source snapshot when filings are
     available and logs collector failures without breaking analysis.
   - Offline persistence coverage now mocks EDGAR fetches so the repo check does
     not depend on external network availability.

3. Done: route Telegram market-hours gating and scheduled digest timing through
   `exchange_calendar.py` so holidays and early closes are handled consistently.
   - `app/services/market_hours.py` now treats only `regular_open` as open and
     computes next open via `next_trading_day(...)`.
   - `app/services/telegram_bot.py` now uses exchange-calendar session states for
     market-hours-only skips, digest mode selection, and the calendar baseline view.

4. Done: surface stored EDGAR filing summaries directly in analysis payloads,
   operation notes, and risk/event interpretation so filing context affects the
   main `/analyze` output instead of only the separate `/filings` view.
   - `AnalyzeResponse.sec_filings` now carries recent forms, dates, and SEC URLs.
   - Telegram `/analyze` and `/risk` render recent filing context from the saved
     analysis payload.
   - `SourceSnapshot.payload` now preserves collector-specific `payload_extra`,
     so EDGAR filing lists are retained in raw snapshot storage.

5. Done: use recent SEC filing types and recency as explicit event-risk inputs
   in scoring, so fresh 8-K/10-Q/10-K activity influences risk and `final_score`
   instead of remaining display-only context.
   - `app/services/scoring.py` now applies filing-age/type penalties to
     `risk_score`, capped to avoid overpowering the rest of the model.
   - `app/services/scanner.py` passes the built SEC filing context into scoring
     and uses the actual computed risk score when generating risk-overlay notes.

6. Done: calibrate event-risk integration across earnings calendar, SEC filings,
   and macro events so the score can distinguish "routine fresh disclosure" from
   "material catalyst cluster" instead of stacking each source independently.
   - `app/services/scoring.py` now builds a single catalyst-aware event-risk
     adjustment with diminishing weights and a cluster bonus across macro,
     earnings, and filing signals instead of naively stacking every source.
   - `app/services/scanner.py` passes company event calendars into scoring, so
     scheduled earnings materially affect risk in the main analysis path.
   - Focused tests now cover routine filing risk, distant earnings, and
     multi-signal catalyst clusters.

7. Done: feed sector sensitivity into the same event-risk layer so macro and
   earnings catalysts hit sectors asymmetrically instead of treating all
   tickers as equally exposed to the same calendar.
   - `app/services/scoring.py` now uses sector sensitivity profiles to amplify
     or dampen macro-event and earnings catalyst severity based on sector rate,
     inflation, and growth exposure.
   - `tests/test_macro_aware_scoring.py` now proves that rising-rate macro risk
     hits Technology harder than Financials, and that earnings risk hits
     growth-sensitive sectors harder than defensive ones.

8. Done: propagate sector-aware catalyst context into user-facing explanation
   layers so Telegram/API risk text distinguishes generic event risk from
   sector-specific macro and earnings exposure.
   - `app/services/scanner.py` now emits explicit sector-adjusted catalyst notes
     into `operation_notes` when macro or earnings catalysts should hit a sector
     harder or softer than average.
   - `app/services/telegram/_formatting.py` now surfaces those notes in the
     stored `/risk` view under a dedicated risk-drivers block.
   - `app/services/ai_explainer.py` now translates the newer macro/earnings
     catalyst reasons so rule-based explanations remain readable in Russian.

9. Done: sector-tagged news and sector-aware digest routing so breaking-event
   alerts reach subscribers based on their watchlist sectors instead of being
   generic pushes for all subscribers.
   - `app/services/news_collector.py`: `_SECTOR_KEYWORDS` map, `_tag_sectors()`
     keyword-tagger, `news_relevant_for_sectors()` filter function, and
     `affected_sectors` field on every `NewsItem`.
   - `app/services/telegram_bot.py`: `_watchlist_sectors()` derives subscriber
     sectors from the instrument registry; digest routing filters `high_impact_news`
     output through `news_relevant_for_sectors()` before building each digest.
   - 11 new tests (7 in `test_news_collector`, 2 in `test_telegram_digests`).

10. Done: enrich event-aware scoring with political/regulatory catalysts derived
    from breaking news so tariff, sanction, antitrust, and regulatory headlines
    materially raise the risk score for affected sectors.
    - `app/services/news_collector.py`: `_POLITICAL_KEYWORDS` set,
      `political_risk_level_from_news()` detects "elevated" or "high" risk
      from macro news items filtered by source reliability and sentiment strength.
    - `app/services/macro_context.py`: `political_risk_level` field on
      `MacroContext`; `build_macro_context()` now accepts optional `news_context`
      and surfaces political risk in `macro_context_summary()` notes.
    - `app/services/scoring.py`: `_political_regulatory_catalyst()` maps risk
      level to an `EventCatalyst` with sector-specific amplification
      (Industrials/Materials for tariffs, Technology for antitrust/export,
      Financials for banking regulation, Energy for sanctions).
    - `app/services/scanner.py`: news is now collected before `build_macro_context`
      so political risk feeds into scoring; `_build_news` refactored into
      `_collect_news_context` + `_build_news_payload`.
    - 13 new tests across `test_macro_aware_scoring` and `test_news_collector`.

## Operations, Budgets, And Runtime Boundaries

The MVP should stay runnable on a local machine. Heavy provider calls, Telegram
sends, and LLM usage need explicit limits.

Operational requirements:

1. Define API exposure: local-only by default; if exposed beyond localhost, add authentication, rate limits, CORS policy, and security headers.
2. Add cost and runtime budgets for OpenAI calls, provider requests, and Telegram sends. Add collector-specific budgets only when those collectors exist.
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
4. Prefer official APIs, RSS, downloadable files, and static HTML parsers for pages that expose stable open data; consider browser automation only as a later, justified exception with explicit rules, rate limits, caching, and respect for robots/terms.
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
3. Done: add CI for tests and compile checks.
4. Done: add a one-command local verification entrypoint at `scripts/check.sh`.
5. Done: add a fast development verification entrypoint at `scripts/test_fast.sh`.
6. Done: add a secrets and security checklist covering `.env`, API keys, Telegram token, logs, and git status.
7. Done: add local runtime notes for Telegram bot operation, logs, restart, env setup, and database location.
8. Done: add clear live-smoke environment flags so offline tests never depend on network access.
9. Done: add provider-call, OpenAI-call, and Telegram-send runtime budgets; provider, OpenAI, and Telegram-send budgets are enforced per process.
10. Done: add backup/restore notes for the local SQLite database.

## Phase 3: Improve Data and Persistence

1. Done: introduce migrations before the SQLite schema changes beyond the current tables.
2. Done: add endpoints for full saved analysis payloads.
3. Done: add retention or cleanup rules for old snapshots.
4. Done: improve reporting around partial scan failures.
5. Done: add an instrument registry for symbol, exchange, MIC, country, timezone, currency, asset type, provider aliases, and stable identifiers.
6. Done: add a provider registry with source tier, capability list, legal/terms note, cache TTL, retry policy, and failure taxonomy.
7. Done: persist raw source snapshots separately from normalized analysis outputs.
8. Done: persist source URLs, timestamps, extraction method, parser version, confidence, and content hashes.
9. Done: add provider health and last-success records.
10. Done: add corporate-action and adjusted-price policy before using expanded historical analysis.
11. Done: add stale, delayed, estimated, missing, and source-disagreed data-quality flags.
12. Done: add FX normalization fields before supporting non-USD instruments.

## Phase 4: Productize User Workflows

1. Done: add watchlist configuration with per-chat Telegram watchlists and list commands.
2. Done: add a richer CLI report mode for recent analyses.
3. Done: improve Telegram commands for custom ticker scans and status visibility.
4. Done: add user-visible error summaries for failed market data, OpenAI, and Telegram operations.
5. Done: add per-chat Telegram watchlists and alert preferences with quiet hours, daily caps, and market-hours-only mode.
6. Done: add Telegram-only source-backed workflows: `/why`, `/sources`, `/events`, `/freshness`, `/calendar`, `/risk`, and `/audit` against saved analysis and source snapshots.
7. Done: add scheduled Telegram digests for pre-market, market open, close, after-hours, and weekly review.
8. Done: add Telegram chat allowlist via `TELEGRAM_ALLOWED_CHAT_IDS`.
9. Done: add per-chat data deletion or cleanup behavior.
10. Done: add alert deduplication and confidence thresholds.
   Telegram scan and digest flows now enforce minimum confidence thresholds, and scheduled digests skip duplicate payloads until content changes.
11. Done: replace buy/sell-like labels with neutral research labels in API, CLI, Telegram, docs, and tests.
12. Done: add contextual disclaimer behavior for first use, high-risk events, and major alerts.
13. Done: add Telegram `/news` views for ticker-specific and market/macro context with concise sentiment summaries.
14. Done: add Telegram threshold/move/signal alerts plus push delivery for high-impact news and price moves.
15. Done: add Telegram portfolio holdings and P&L tracking with `/buy`, `/sell`, and `/holdings`.
16. Done: add Telegram `/chart` image generation for quick visual price review.
17. Done: reorganize the Telegram main keyboard into clearer workflow sections.
18. Do not add a web UI unless the user explicitly changes direction; Telegram is the primary user interface.

## Phase 5: Market Intelligence Layer

Detailed no-OpenAI implementation guidance lives in `No-OpenAI Utility Roadmap`
above. Keep this phase list short and status-oriented.

1. Partly done: normalized source models exist for prices, SEC filings, exchange
   calendars, FRED macro observations, and news context; broader fundamentals,
   BLS, BEA, Treasury, FOMC calendars, and issuer-event normalization remain
   incomplete.
2. Partly done: official open sources are integrated for SEC EDGAR, NYSE
   calendar logic, and FRED collection; FRED data still needs to be threaded into
   the main `analyze_ticker` macro context and scan-level reuse.
3. Partly done: market-session modeling exists for U.S. equities; per-symbol
   exchange/timezone expansion and non-U.S. session handling remain pending.
4. Partly done: source freshness, source disagreement, and confidence fields
   exist; every high-level Telegram answer still needs a mandatory compact
   freshness/confidence/source-gap line.
5. Pending: strengthen data-quality handling for adjusted prices, splits,
   dividends, missing candles, partial sessions, and delayed quotes.
6. Pending: add open web collectors for news sites that lack stable APIs only
   when legally accessible and useful, with caching, rate limits, provenance,
   extraction fixtures, and source allow/block rules.
7. Deferred: add LLM source-grounding and prompt-injection protections before
   using OpenAI for web/news summarization; this is not required for no-OpenAI
   usefulness.
8. Partly done: event-aware scoring already uses earnings, SEC filings, macro
   events, sector sensitivity, sector-tagged news, and political/regulatory
   catalysts; richer official macro-release feeds and issuer-event sources
   remain pending.
9. Pending: add market-regime context: SPY/QQQ trend, volatility regime,
   rate/yield backdrop, sector rotation, and risk-on/risk-off state.
10. Partly done: `backtesting.py` and tests exist, and Telegram parses
   `/backtest`; complete historical price pairing and user-facing quality
   report remain pending.
11. Partly done: Telegram alerts cover confidence thresholds, duplicate
   suppression, threshold rules, high-impact news push, and sector-routed
   digests; macro-watchlist-specific breaking-event routing remains pending.
12. Partly done: deterministic briefing builder exists for `/scan mine` and
   scheduled digests; next step is enriching it with score deltas, freshness,
   latest news timestamps, and per-analysis source gaps.
13. Pending: upgrade `/audit` into a deterministic "why changed" report that
   separates real signal movement from source, freshness, and confidence drift.
14. Pending: add minimal product-validation metrics for private testing:
   command counts, active chats, follow-up usage, and workflow retention without
   storing unnecessary message text.

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
16. Market intelligence uses more than `yfinance`, including official open sources, stable feeds, downloadable files, and tested open web collection where appropriate.
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
