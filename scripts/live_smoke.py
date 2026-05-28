from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
import json
import logging
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.logging_config import configure_logging  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.services.scanner import analyze_ticker, scan_tickers  # noqa: E402
from scripts.live_guard import require_live_network  # noqa: E402


DEFAULT_TICKER = "AAPL"
DEFAULT_SCAN_TICKERS = ["AAPL", "MSFT", "NVDA"]
logger = logging.getLogger(__name__)


def parse_args() -> Namespace:
    parser = ArgumentParser(
        description="Run a live smoke check against real market data providers."
    )
    parser.add_argument(
        "--ticker",
        default=DEFAULT_TICKER,
        help="Ticker for the single analyze smoke check.",
    )
    parser.add_argument(
        "--scan",
        nargs="*",
        default=DEFAULT_SCAN_TICKERS,
        help="Tickers for the scan smoke check.",
    )
    return parser.parse_args()


def main() -> int:
    configure_logging(force=True)
    if not require_live_network("Live smoke"):
        return 2
    args = parse_args()
    ticker = args.ticker.strip().upper()
    scan_ticker_list = [item.strip().upper() for item in args.scan if item.strip()]
    if not ticker or not scan_ticker_list:
        print("Live smoke requires a ticker and at least one scan ticker.", file=sys.stderr)
        return 2

    logger.info(
        "live_smoke_started",
        extra={
            "component": "cli",
            "ticker": ticker,
            "scan_ticker_count": len(scan_ticker_list),
        },
    )
    init_db()
    db = SessionLocal()
    try:
        analysis = analyze_ticker(ticker, db=db, use_ai_explanation=False)
        scan = scan_tickers(scan_ticker_list, db=db)
    except Exception as exc:
        print(f"Live smoke failed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    payload = {
        "status": "ok" if scan.results else "degraded",
        "analysis": {
            "ticker": analysis.ticker,
            "price": analysis.price,
            "final_score": analysis.scores.final_score,
            "recommendation": analysis.recommendation,
        },
        "scan": {
            "result_count": len(scan.results),
            "error_count": len(scan.errors),
            "top": [
                {
                    "ticker": item.ticker,
                    "final_score": item.final_score,
                    "recommendation": item.recommendation,
                }
                for item in scan.results[:3]
            ],
            "errors": [item.model_dump() for item in scan.errors],
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    logger.info(
        "live_smoke_finished",
        extra={
            "component": "cli",
            "ticker": ticker,
            "scan_ticker_count": len(scan_ticker_list),
            "result_count": len(scan.results),
            "error_count": len(scan.errors),
        },
    )
    return 0 if scan.results else 1


if __name__ == "__main__":
    raise SystemExit(main())
