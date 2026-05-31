# Stock AI Assistant

Personal AI research assistant for stock monitoring. The app downloads market data with `yfinance`, calculates indicators with normal Python code, scores stocks with deterministic rules, and optionally uses an LLM only to explain already calculated results.

This is an MVP for private research. It is not a public investment advisory service and it does not place real buy/sell orders.

## Features

- `GET /health` app health check.
- `GET /ready` readiness check with database probe.
- `GET /` quick service index with links.
- `GET /analyze/{ticker}` analyzes one ticker.
- `POST /scan` scans a list of tickers, sorts candidates by `final_score`, and returns a summary when some tickers fail.
- `GET /analyses/recent` returns the latest stored analyses from SQLite.
- `GET /analyses/{analysis_id}` returns a saved analysis with its full payload.
- `GET /instruments/{symbol}` returns the saved instrument registry entry for a symbol.
- `GET /providers` and `GET /providers/{name}` expose provider registry entries and health.
- CLI scanner for a default watchlist.
- Telegram bot with `/analyze`, `/scan`, watchlists, preferences, source-backed detail commands, and scheduled digests.
- SQLite snapshot storage for completed analyses.
- SQLite raw source snapshot storage with provenance metadata and content hashes.
- SQLite instrument registry for symbol, exchange, currency, and related metadata.
- SQLite provider registry for source tier, capability list, legal note, retry policy, and health timestamps.
- Normalized market-data provider contract with offline fixture support for future collectors.
- Works without `OPENAI_API_KEY`; falls back to rule-based explanations.

## Stack

- Python
- FastAPI
- SQLite
- SQLAlchemy
- Pydantic
- yfinance
- pandas / numpy
- python-dotenv
- uvicorn
- Optional OpenAI API

## Setup

Create and activate a virtual environment:

```bash
cd ~/Desktop/stock-ai-assistant
python3 -m venv .venv
source .venv/bin/activate
```

Supported Python: 3.11+.

Install dependencies:

```bash
pip install -r requirements.txt
```

For development checks, install the development tools too:

```bash
pip install -r requirements-dev.txt
```

The dependency files are pinned so repeated installs resolve to the same package versions across machines.

## Live Network Checks

Live smoke scripts are opt-in. Set this flag when you want to contact external services on purpose:

```bash
ALLOW_LIVE_NETWORK=1
```

Examples:

```bash
ALLOW_LIVE_NETWORK=1 python scripts/live_smoke.py
ALLOW_LIVE_NETWORK=1 python scripts/live_http_smoke.py
ALLOW_LIVE_NETWORK=1 python scripts/openai_smoke.py
ALLOW_LIVE_NETWORK=1 python scripts/check_telegram.py
```

Create local env file:

```bash
cp .env.example .env
```

The API runs locally by default. Keep `APP_HOST=127.0.0.1` unless you have
added the public-facing controls called out in `PLAN.md`.

Optional OpenAI setup:

```bash
# Edit .env and set:
OPENAI_API_KEY=your_key_here
```

If `OPENAI_API_KEY` is empty, the app still works and returns a rule-based explanation.

Market-data resilience settings:

```bash
MARKET_DATA_TIMEOUT_SECONDS=20
MARKET_DATA_MAX_ATTEMPTS=3
MARKET_DATA_RETRY_BACKOFF_SECONDS=1.5
MARKET_DATA_CACHE_TTL_SECONDS=3600
```

`MARKET_DATA_CACHE_TTL_SECONDS` keeps repeated ticker analyses inside the same
running process from re-downloading provider data. Set it to `0` to disable the
in-memory cache.

Runtime budgets:

```bash
PROVIDER_CALL_BUDGET=1000
OPENAI_CALL_BUDGET=50
PLAYWRIGHT_PAGE_BUDGET=20
TELEGRAM_SEND_BUDGET=200
```

Runtime budgets are enforced per process. Provider calls, OpenAI explanations,
and Telegram `sendMessage` calls stop when their configured limit is exhausted;
restart the process to reset counters.

Snapshot retention:

```bash
ANALYSIS_SNAPSHOT_RETENTION_COUNT=50
ANALYSIS_SNAPSHOT_RETENTION_DAYS=365
```

Runtime logs are emitted as JSON lines to stderr from the API, CLI, persistence, and Telegram loops.

Telegram bot settings:

```bash
TELEGRAM_ENABLED=1
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_DEFAULT_TICKERS=AAPL,MSFT,NVDA
TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321
TELEGRAM_DIGEST_INTERVAL_MINUTES=1440
```

Set `TELEGRAM_ALLOWED_CHAT_IDS` to a comma-separated list of chat IDs to restrict the bot to approved chats. Leave it empty to allow any chat that can reach the bot.

The bot stores subscriptions, watchlists, and alert preferences in SQLite. If `TELEGRAM_ENABLED=1` and `TELEGRAM_BOT_TOKEN` are set, it starts automatically when the app runs.

The default SQLite database path is resolved relative to the project root, so the file stays in this repository even if you launch `uvicorn` from another directory.

## Operational Notes

- Telegram bot output and API logs are JSON lines on stderr.
- Restart the API or bot by rerunning the relevant script; there is no daemon manager in the repo.
- The SQLite database lives at `stock_ai_assistant.db` in the repository root unless `DATABASE_URL` points elsewhere.
- Back up the database by copying that file while the app is stopped.
- Restore by replacing the file and restarting the app.
- Schema migrations run automatically at startup and are recorded in the `schema_migrations` table.
- Analysis snapshots are cleaned up automatically to keep the latest per-ticker history within the configured retention policy.
- Raw provider snapshots are stored separately from normalized analyses with source URLs, timestamps, parser version, confidence, and content hashes.
- Provider health is stored in `provider_registry` and updated when market data requests succeed or fail.
- Analysis responses include explicit data-quality flags, market session state, operation notes, and FX assumption metadata. Non-USD FX conversion is not applied yet, so values remain in the reported trading currency.
- If `TELEGRAM_ALLOWED_CHAT_IDS` is set, only those chats can use the bot and receive digests.

## Security Checklist

- Keep `.env` out of git.
- Verify `git status` before committing.
- Do not log API keys or Telegram tokens.
- Use the live network flag only for intentional smoke checks.
- Rotate tokens if a secret ever appears in shell history, logs, or screenshots.

## Run API

```bash
python scripts/run_api.py --reload
```

Real HTTP smoke:

```bash
python scripts/live_http_smoke.py
```

OpenAPI docs:

```text
http://127.0.0.1:8000/docs
```

Quick app index:

```text
http://127.0.0.1:8000/
```

## Run Tests

```bash
python -m unittest discover -v
```

Fast development loop:

```bash
scripts/test_fast.sh
scripts/test_fast.sh tests.test_app.AppSmokeTests
```

Full local verification:

```bash
scripts/check.sh
```

`scripts/test_fast.sh` runs `ruff` and a focused unittest set without coverage
for quick iteration. `scripts/check.sh` runs `ruff`, coverage-wrapped unit
tests, a coverage report, and `compileall`; use it before considering a change
complete.

## Check Health

```bash
curl http://127.0.0.1:8000/health
```

Expected shape:

```json
{
  "status": "ok",
  "app": "Stock AI Assistant",
  "generated_at": "2026-05-28T00:00:00Z",
  "database": "sqlite:////absolute/path/to/stock-ai-assistant/stock_ai_assistant.db"
}
```

Readiness check:

```bash
curl http://127.0.0.1:8000/ready
```

Expected ready response:

```json
{
  "status": "ready",
  "app": "Stock AI Assistant",
  "generated_at": "2026-05-28T00:00:00Z",
  "database": "sqlite:////absolute/path/to/stock-ai-assistant/stock_ai_assistant.db",
  "checks": {
    "database": "ok"
  }
}
```

## Analyze One Ticker

```bash
curl http://127.0.0.1:8000/analyze/NVDA
```

The response includes:

- current price;
- company name, sector, market cap, P/E, growth, margins, debt/equity when available;
- 1-day, 1-month, and 6-month changes;
- MA50 and MA200;
- RSI;
- annualized volatility;
- max drawdown;
- momentum, valuation, risk, and final score;
- analytical signal;
- explanation.

## Scan Tickers

```bash
curl -X POST http://127.0.0.1:8000/scan \
  -H "Content-Type: application/json" \
  -d '{"tickers":["AAPL","MSFT","NVDA","TSLA","AMD"]}'
```

The response is sorted by `final_score`, with stronger candidates at the top and weaker or riskier names lower.

## Recent Analyses

```bash
curl "http://127.0.0.1:8000/analyses/recent?limit=5"
```

This returns the most recent saved analyses from SQLite so you can inspect prior runs without re-downloading market data.

## Run CLI Scanner

```bash
python scripts/scan_market.py
```

Default tickers:

```text
AAPL, MSFT, NVDA, TSLA, AMD, AMZN, GOOGL, META
```

You can also pass custom tickers and get JSON output:

```bash
python scripts/scan_market.py AAPL MSFT NVDA --json
```

The script prints:

```text
ticker, price, final_score, recommendation, short_reason
```

## Run Live Smoke Check

This command uses real market data and does not require OpenAI or Telegram:

```bash
python scripts/live_smoke.py
python scripts/live_smoke.py --ticker AAPL --scan AAPL MSFT NVDA
```

OpenAI explanation smoke:

```bash
python scripts/openai_smoke.py
python scripts/openai_smoke.py --ticker AAPL
```

This command requires `OPENAI_API_KEY`.

## Run Telegram Bot

```bash
python scripts/run_telegram_bot.py
```

If Telegram is disabled or the token is missing, the script exits with a clear error message.

Telegram config smoke:

```bash
python scripts/check_telegram.py
```

Available commands:

- `/start` or `/subscribe` to activate the chat.
- `/unsubscribe` to stop alerts.
- `/status` to see subscription state and last digest time.
- `/watchlist` to view the personal ticker list.
- `/add AAPL MSFT` to add tickers to the personal list.
- `/remove AAPL` to remove tickers from the personal list.
- `/prefs` to review alert preferences.
- `/quiet 22:00-07:00` or `/quiet off` to set quiet hours.
- `/cap 3` or `/cap off` to set or clear the daily alert cap.
- `/markethours on` or `/markethours off` to restrict scheduled digests to U.S. market hours.
- `/why AAPL`, `/sources AAPL`, `/events AAPL`, `/freshness AAPL`, `/calendar today`, `/risk AAPL`, and `/audit AAPL` for source-backed detail views from saved snapshots.
- `/analyze AAPL` to analyze one ticker.
- `/scan AAPL MSFT NVDA` to scan a list of tickers.
- `/scan mine` to scan the personal watchlist.

Scheduled digests use the personal watchlist when it exists and fall back to `TELEGRAM_DEFAULT_TICKERS` when it does not.
On first use, and for major or high-risk alerts, Telegram includes a short contextual disclaimer instead of repeating the same warning on every line.
Per-chat alert preferences are stored in SQLite and currently cover quiet hours, daily caps, and market-hours-only digests.
Scheduled digests respect those preferences before sending anything.
The detail commands read from saved analysis and source snapshots, so they reflect the latest stored provenance and freshness context even when a live event calendar feed is not available yet.

## Scoring Model

The score is deterministic and calculated by code:

- `momentum_score`: trend, MA50/MA200 position, 1-month/6-month change, RSI.
- `valuation_score`: trailing P/E, forward P/E, revenue growth, margins, debt/equity.
- `risk_score`: volatility, max drawdown, overbought RSI, unusually large daily move.
- `final_score`: weighted combination of momentum, valuation, and inverse risk.

Research labels:

- `HIGH_INTEREST`
- `WATCH`
- `NEUTRAL`
- `CAUTION`
- `HIGH_RISK`

These are neutral research labels for workflow triage, not financial advice or guaranteed recommendations.

## Disclaimer

This project is not financial advice. Market data can be delayed, incomplete, or wrong. The scoring rules are intentionally simple for MVP purposes and must be reviewed before any real-world use.
