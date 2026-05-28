# AGENTS.md

## Project Context

Stock AI Assistant is a local MVP for stock research. It:

- downloads market data with `yfinance`
- calculates indicators and scores deterministically
- optionally uses OpenAI only for explanation text
- stores analysis snapshots in SQLite
- exposes a FastAPI API
- includes a CLI scanner and a Telegram bot entrypoint

## Current Status

The repository already has:

- FastAPI routes for `/`, `/health`, `/analyze/{ticker}`, `/scan`, and `/analyses/recent`
- SQLite persistence for analysis snapshots
- CLI scan and Telegram bot scripts
- smoke tests for API, persistence, and CLI behavior

Treat the app as an MVP that is usable now, but still suitable for incremental hardening.

## Working Rules

- Prefer direct inspection of the repository before making assumptions.
- Keep changes narrow and practical.
- Do not remove user changes unless explicitly requested.
- Use `apply_patch` for file edits.
- Use non-interactive git commands.
- Prefer tests or code evidence over speculation.

## Verification

Run the following before calling the work done:

```bash
.venv/bin/python -m unittest discover -v
.venv/bin/python -m compileall app scripts tests
```

If you change CLI behavior, also update or add tests under `tests/`.

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

- `DATABASE_URL` is resolved relative to the project root for local SQLite paths.
- If `TELEGRAM_ENABLED=1` is set without a token, the Telegram script should fail clearly.
- The app must still work without `OPENAI_API_KEY`.

## Likely Next Improvements

1. Live smoke checks against external services.
2. Dependency pinning or a lockfile.
3. CI for tests and compile checks.
4. Retry/backoff for network-heavy operations.
5. Packaging and deployment docs.
