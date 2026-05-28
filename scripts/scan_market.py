from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal, init_db  # noqa: E402
from app.services.scanner import scan_tickers  # noqa: E402


DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "AMZN", "GOOGL", "META"]


def main() -> int:
    init_db()
    db = SessionLocal()
    try:
        response = scan_tickers(DEFAULT_TICKERS, db=db)
    finally:
        db.close()

    print_table(response.results)
    if response.errors:
        print("\nErrors:")
        for item in response.errors:
            print(f"- {item.ticker}: {item.error}")
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


if __name__ == "__main__":
    raise SystemExit(main())
