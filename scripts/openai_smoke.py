from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
import json
import logging
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.services.scanner import analyze_ticker  # noqa: E402


DEFAULT_TICKER = "AAPL"
logger = logging.getLogger(__name__)


def parse_args() -> Namespace:
    parser = ArgumentParser(description="Run an OpenAI explanation smoke check.")
    parser.add_argument(
        "--ticker",
        default=DEFAULT_TICKER,
        help="Ticker to analyze with the OpenAI-backed explanation path.",
    )
    return parser.parse_args()


def main() -> int:
    configure_logging(force=True)
    args = parse_args()
    ticker = args.ticker.strip().upper()
    if not ticker:
        print("OpenAI smoke requires a ticker.", file=sys.stderr)
        return 2

    settings = get_settings()
    if not settings.openai_api_key:
        print("OpenAI smoke requires OPENAI_API_KEY to be set.", file=sys.stderr)
        return 2

    logger.info(
        "openai_smoke_started",
        extra={"component": "cli", "ticker": ticker, "model": settings.openai_model},
    )
    init_db()
    db = SessionLocal()
    try:
        analysis = analyze_ticker(ticker, db=db, use_ai_explanation=True)
    except Exception as exc:
        print(f"OpenAI smoke failed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    payload = {
        "status": "ok",
        "analysis": {
            "ticker": analysis.ticker,
            "price": analysis.price,
            "final_score": analysis.scores.final_score,
            "recommendation": analysis.recommendation,
            "explanation": analysis.explanation,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    logger.info(
        "openai_smoke_finished",
        extra={
            "component": "cli",
            "ticker": ticker,
            "final_score": analysis.scores.final_score,
            "recommendation": analysis.recommendation,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
