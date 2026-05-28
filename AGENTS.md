# AGENTS.md

## Purpose

This file is the durable working context for agents continuing `stock-ai-assistant`.
Keep it current when project direction, setup, verification, or implementation priorities change.

The user expects the repository to move toward a complete working MVP, not a discussion-only plan.
When implementation details are open, inspect the real repo state first, make a conservative engineering choice, implement it, verify it, and commit finished work.

## Conversation Summary

What has already been established in this project thread:

- The first step for any continuation is to check the current file and git state.
- `AGENTS.md` is required repo-level context and should be tracked in git.
- A working MVP is expected to include API, CLI, persistence, clear setup, tests, and practical next-step documentation.
- README alone is not enough for agent continuity; planning and workflow guidance belong in durable markdown.
- The project should keep working without `OPENAI_API_KEY`; LLM output is optional explanation only.
- Live external validation is still separate from offline smoke tests.

## Current Implementation

The app currently includes:

- FastAPI routes: `/`, `/health`, `/analyze/{ticker}`, `/scan`, `/analyses/recent`
- deterministic indicator and scoring services under `app/services/`
- market data loading via `yfinance`
- optional OpenAI explanation fallback to rule-based text
- SQLite storage for analysis snapshots
- Telegram bot service and script entrypoint
- CLI scanner with default watchlist, custom tickers, and `--json`
- `unittest` smoke coverage for API routes, persistence, scanner behavior, and CLI scripts

Recent project commits:

- `26a72d6` adds the initial MVP files, smoke tests, and docs
- `3512f61` stabilizes SQLite path resolution relative to the project root
- `e20ed4f` adds API route smoke tests
- `42cf49c` adds SQLite persistence smoke coverage
- `2e83df0` polishes CLI behavior and runtime logging
- `8089801` adds the first tracked `AGENTS.md`

## Known Limits

These items are not fully closed yet:

- No live smoke check has been completed against real `yfinance`, OpenAI, or Telegram services.
- The sandbox blocked binding `uvicorn` to `127.0.0.1:8000`; API behavior was validated with `TestClient`.
- Dependencies are declared with broad ranges in `requirements.txt`; no lockfile or constraints file exists.
- There is no CI workflow yet.
- SQLite schema creation uses `Base.metadata.create_all`; there are no migrations.
- Network-heavy operations do not yet have structured retry/backoff policy.
- No separate `PLAN.md` exists yet; this file currently carries the actionable development plan.

## Working Rules

- Start with `git status --short` and inspect relevant files before changing code.
- Preserve user changes. Do not revert unrelated edits.
- Use `apply_patch` for manual file edits.
- Prefer non-interactive git commands.
- Keep changes scoped and commit complete, verified slices.
- If the user asks to commit, actually commit.
- If the user asks to continue implementation, do not stop at a plan.
- Update `AGENTS.md` when durable workflow or project direction changes.

## Verification

Before calling implementation work complete, run:

```bash
.venv/bin/python -m unittest discover -v
.venv/bin/python -m compileall app scripts tests
```

If dependencies changed, also verify installation from a clean virtualenv when feasible.
If CLI behavior changed, add or update tests under `tests/`.
If API behavior changed, add or update `TestClient` coverage.

## Launch Commands

API:

```bash
uvicorn app.main:app --reload
```

CLI scan:

```bash
python scripts/scan_market.py
python scripts/scan_market.py AAPL MSFT NVDA --json
```

Telegram bot:

```bash
python scripts/run_telegram_bot.py
```

## Config Notes

- `DATABASE_URL` defaults to SQLite and is resolved relative to the project root for local paths.
- The app must run without `OPENAI_API_KEY`.
- If `TELEGRAM_ENABLED=1` is set without `TELEGRAM_BOT_TOKEN`, the Telegram script should fail with a clear error.
- `.env`, `.venv/`, SQLite database files, Python caches, and local OS files are ignored by git.

## Development Plan

### Phase 1: Finish MVP Hardening

1. Add a live smoke script that can check real `yfinance` analysis and scan paths without requiring OpenAI or Telegram.
2. Add clear operational health/readiness behavior for database availability.
3. Improve market-data error handling with timeouts, bounded retries, and user-facing messages.
4. Add basic structured logging setup for API, scanner, persistence, and Telegram background loops.
5. Create `PLAN.md` if planning grows beyond this file.

### Phase 2: Make Builds Reproducible

1. Pin or constrain Python dependencies.
2. Document the supported Python version.
3. Add CI for tests and compile checks.
4. Add a one-command local verification entrypoint, such as `make test` or `scripts/check.sh`.

### Phase 3: Improve Data and Persistence

1. Introduce migrations if the SQLite schema changes beyond the current tables.
2. Add richer history endpoints for saved analysis payloads.
3. Add retention or cleanup rules for old snapshots.
4. Add safer handling for partial scan failures.

### Phase 4: Productize User Workflows

1. Add a simple watchlist configuration workflow.
2. Add a richer CLI report mode for recent analyses.
3. Improve Telegram commands for custom ticker scans and status visibility.
4. Consider a minimal local UI only after API, CLI, and bot flows are stable.

## Definition of Done

A change is done when:

- the requested behavior is implemented
- relevant tests are added or updated
- verification commands pass, or any inability to run them is explicitly reported
- docs or `AGENTS.md` are updated if the change affects setup, operation, or project direction
- the working tree is clean after commit when the user asked for committed work
