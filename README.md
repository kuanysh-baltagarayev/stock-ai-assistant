# Stock AI Assistant

Personal AI research assistant for stock monitoring. The app downloads market data with `yfinance`, calculates indicators with normal Python code, scores stocks with deterministic rules, and optionally uses an LLM only to explain already calculated results.

This is an MVP for private research. It is not a public investment advisory service and it does not place real buy/sell orders.

## Features

- `GET /health` app health check.
- `GET /ready` readiness check with database probe.
- `GET /` quick service index with links.
- `GET /analyze/{ticker}` analyzes one ticker.
- `POST /scan` scans a list of tickers and sorts candidates by `final_score`.
- `GET /analyses/recent` returns the latest stored analyses from SQLite.
- CLI scanner for a default watchlist.
- Telegram bot with `/analyze`, `/scan`, and scheduled digests.
- SQLite snapshot storage for completed analyses.
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

Install dependencies:

```bash
pip install -r requirements.txt
```

Create local env file:

```bash
cp .env.example .env
```

Optional OpenAI setup:

```bash
# Edit .env and set:
OPENAI_API_KEY=your_key_here
```

If `OPENAI_API_KEY` is empty, the app still works and returns a rule-based explanation.

Telegram bot settings:

```bash
TELEGRAM_ENABLED=1
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_DEFAULT_TICKERS=AAPL,MSFT,NVDA
TELEGRAM_DIGEST_INTERVAL_MINUTES=1440
```

The bot stores subscriptions and alert timestamps in SQLite. If `TELEGRAM_ENABLED=1` and `TELEGRAM_BOT_TOKEN` are set, it starts automatically when the app runs.

The default SQLite database path is resolved relative to the project root, so the file stays in this repository even if you launch `uvicorn` from another directory.

## Run API

```bash
uvicorn app.main:app --reload
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

## Run Telegram Bot

```bash
python scripts/run_telegram_bot.py
```

If Telegram is disabled or the token is missing, the script exits with a clear error message.

Available commands:

- `/start` or `/subscribe` to activate the chat.
- `/unsubscribe` to stop alerts.
- `/status` to see subscription state and last digest time.
- `/analyze AAPL` to analyze one ticker.
- `/scan AAPL MSFT NVDA` to scan a list of tickers.

Scheduled digests use `TELEGRAM_DEFAULT_TICKERS` and send the strongest candidates from that list.

## Scoring Model

The score is deterministic and calculated by code:

- `momentum_score`: trend, MA50/MA200 position, 1-month/6-month change, RSI.
- `valuation_score`: trailing P/E, forward P/E, revenue growth, margins, debt/equity.
- `risk_score`: volatility, max drawdown, overbought RSI, unusually large daily move.
- `final_score`: weighted combination of momentum, valuation, and inverse risk.

Recommendation categories:

- `STRONG_BUY_CANDIDATE`
- `BUY_WATCHLIST`
- `HOLD`
- `WAIT`
- `REDUCE`
- `AVOID`

These are analytical signals for research workflow, not guaranteed recommendations.

## Disclaimer

This project is not financial advice. Market data can be delayed, incomplete, or wrong. The scoring rules are intentionally simple for MVP purposes and must be reviewed before any real-world use.
