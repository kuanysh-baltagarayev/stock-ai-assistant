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
from app.services.scanner import scan_tickers  # noqa: E402


DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "AMZN", "GOOGL", "META"]
logger = logging.getLogger(__name__)


def parse_args() -> Namespace:
    parser = ArgumentParser(description="Scan a watchlist of tickers and print the results.")
    parser.add_argument(
        "tickers",
        nargs="*",
        help="Optional list of tickers to scan. Defaults to the built-in watchlist.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the scan response as JSON instead of a table.",
    )
    return parser.parse_args()


def main() -> int:
    configure_logging(force=True)
    args = parse_args()
    tickers = [ticker.strip().upper() for ticker in args.tickers if ticker.strip()] or DEFAULT_TICKERS
    logger.info("scan_script_started", extra={"component": "cli", "ticker_count": len(tickers)})
    init_db()
    db = SessionLocal()
    try:
        response = scan_tickers(tickers, db=db)
    finally:
        db.close()

    if args.json:
        print(
            json.dumps(
                {
                    "results": [_serialize(row) for row in response.results],
                    "errors": [_serialize(row) for row in response.errors],
                    "summary": _serialize(response.summary),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_table(response.results)
        print(
            f"\nSummary: {response.summary.message} "
            f"(success={response.summary.success_count}, errors={response.summary.error_count})"
        )
        if response.errors:
            print("\nErrors:")
            for item in response.errors:
                print(f"- {item.ticker}: {item.error}")
    logger.info(
        "scan_script_finished",
        extra={
            "component": "cli",
            "ticker_count": len(tickers),
            "result_count": len(response.results),
            "error_count": len(response.errors),
            "partial_failure": response.summary.partial_failure,
        },
    )
    return 0 if response.results else 1


def print_table(rows) -> None:
    headers = ["ticker", "price", "final_score", "recommendation", "short_reason"]
    widths = [8, 12, 13, 24, 80]
    print(_format_row(headers, widths))
    print(_format_row(["-" * (width - 1) for width in widths], widths))
    for row in rows:
        print(
            _format_row(
                [
                    row.ticker,
                    f"{row.price:.2f}",
                    f"{row.final_score:.2f}",
                    row.recommendation,
                    row.short_reason[:77] + "..." if len(row.short_reason) > 80 else row.short_reason,
                ],
                widths,
            )
        )


def _format_row(values: list[str], widths: list[int]) -> str:
    return " ".join(str(value).ljust(width) for value, width in zip(values, widths))


def _serialize(item) -> dict:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if hasattr(item, "__dict__"):
        return {key: value for key, value in vars(item).items() if not key.startswith("_")}
    return {"value": str(item)}


if __name__ == "__main__":
    raise SystemExit(main())
