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
- Packaging and deployment are not defined yet.
- No user-facing UI exists yet; API, CLI, and Telegram flows are the current product surface.

## Phase 1: Finish MVP Hardening

Status: in progress.

1. Done: add a live smoke script for real `yfinance` analyze and scan paths without requiring OpenAI or Telegram.
2. Done: add readiness behavior for database availability.
3. Improve market-data error handling with timeouts, bounded retries, and clearer user-facing errors.
4. Add basic structured logging setup for API, scanner, persistence, and Telegram background loops.
5. Add OpenAI live smoke guarded by `OPENAI_API_KEY`, without making OpenAI required for normal operation.
6. Add Telegram live check that verifies token/config safely without sending accidental spam.
7. Verify real `uvicorn` HTTP startup in an environment where socket binding is allowed.
8. Add config validation and startup diagnostics for env settings.
9. Keep README, AGENTS, and this plan synchronized.

## Phase 2: Make Builds Reproducible

1. Pin or constrain Python dependencies.
2. Document the supported Python version.
3. Add CI for tests and compile checks.
4. Add a one-command local verification entrypoint, such as `make test` or `scripts/check.sh`.
5. Add a secrets and security checklist covering `.env`, API keys, Telegram token, logs, and git status.
6. Add packaging or deployment notes, including production run command and environment checklist.

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
5. Consider a minimal local UI only after API, CLI, and bot flows are stable.

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
13. Deployment or production-run notes exist.
14. Final git status is clean after the completion commit.

## Definition of Done

A change is complete when:

- behavior is implemented;
- relevant tests are added or updated;
- verification commands pass, or the reason they could not run is reported;
- docs are updated when setup, operation, or direction changes;
- work is committed when the user asked for ongoing committed progress.
