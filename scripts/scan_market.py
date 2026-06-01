from argparse import ArgumentParser, Namespace
from collections import Counter
from pathlib import Path
import json
import logging
from statistics import mean
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.logging_config import configure_logging  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.services.history import list_recent_snapshots  # noqa: E402
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
        "--recent",
        action="store_true",
        help="Print recent saved analyses from SQLite instead of running a fresh scan.",
    )
    parser.add_argument(
        "--recent-limit",
        type=int,
        default=10,
        help="Maximum number of saved analyses to show in recent mode.",
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
    requested_tickers = [ticker.strip().upper() for ticker in args.tickers if ticker.strip()]
    tickers = requested_tickers or DEFAULT_TICKERS
    ticker_count = len(requested_tickers) if args.recent else len(tickers)
    logger.info("scan_script_started", extra={"component": "cli", "ticker_count": ticker_count})
    init_db()
    db = SessionLocal()
    response = None
    recent_snapshots = None
    try:
        if args.recent:
            recent_snapshots = _load_recent_snapshots(db, requested_tickers, args.recent_limit)
        else:
            response = scan_tickers(tickers, db=db)
    finally:
        db.close()

    if args.recent:
        if args.json:
            print(
                json.dumps(
                    {
                        "mode": "recent",
                        "snapshots": [_serialize_recent_snapshot(row) for row in recent_snapshots or []],
                        "summary": _recent_snapshot_summary(recent_snapshots or []),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print_recent_report(recent_snapshots or [])
    else:
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
            if getattr(response.summary, "notes", None):
                print("\nNotes:")
                for note in response.summary.notes:
                    print(f"- {note}")
            if response.errors:
                print("\nErrors:")
                for item in response.errors:
                    print(f"- {item.ticker}: {item.error}")
    logger.info(
        "scan_script_finished",
        extra={
            "component": "cli",
            "ticker_count": ticker_count,
            "mode": "recent" if args.recent else "scan",
            "result_count": len(recent_snapshots or []) if args.recent else len(response.results),
            "error_count": 0 if args.recent else len(response.errors),
            "partial_failure": False if args.recent else response.summary.partial_failure,
        },
    )
    if args.recent:
        return 0 if recent_snapshots else 1
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


def print_recent_report(rows) -> None:
    print(f"Recent analyses ({len(rows)}):")
    if not rows:
        print("No saved analyses found.")
        return

    summary = _recent_snapshot_summary(rows)
    print(
        "Summary: "
        f"latest={summary['latest_created_at']} "
        f"avg_score={summary['average_final_score']} "
        f"tickers={summary['unique_tickers']} "
        f"warnings={summary['warning_count']}"
    )
    if summary["recommendation_counts"]:
        rec_counts = ", ".join(
            f"{label}={count}" for label, count in sorted(summary["recommendation_counts"].items())
        )
        print(f"Recommendations: {rec_counts}")
    if summary["source_providers"]:
        print(f"Providers: {', '.join(summary['source_providers'])}")

    for row in rows:
        report = _recent_snapshot_report(row)
        print(f"- #{report['id']} {report['ticker']} {report['created_at']}")
        print(
            "  "
            f"price={report['price']} "
            f"score={report['final_score']} "
            f"recommendation={report['recommendation']}"
        )
        print(
            "  "
            f"session={report['session_status']} "
            f"freshness={report['freshness_state']} "
            f"quality={report['data_quality_summary']}"
        )
        print(f"  source={report['source_provider']} confidence={report['confidence']}")
        print(f"  reason={report['short_reason']}")
        if report["operation_notes"]:
            print(f"  notes={' | '.join(report['operation_notes'])}")


def _format_row(values: list[str], widths: list[int]) -> str:
    return " ".join(str(value).ljust(width) for value, width in zip(values, widths))


def _load_recent_snapshots(db, tickers: list[str], limit: int) -> list:
    limit = max(1, min(limit, 100))
    filters = [ticker for ticker in tickers if ticker]
    if len(filters) == 1:
        return list_recent_snapshots(db, limit=limit, ticker=filters[0])
    if not filters:
        return list_recent_snapshots(db, limit=limit, ticker=None)

    snapshots = list_recent_snapshots(db, limit=100, ticker=None)
    if filters:
        allowed = set(filters)
        snapshots = [snapshot for snapshot in snapshots if snapshot.ticker in allowed]
    return snapshots[:limit]


def _recent_snapshot_report(snapshot) -> dict[str, str | list[str] | float | int | None]:
    payload = snapshot.payload if isinstance(snapshot.payload, dict) else {}
    provenance = payload.get("source_provenance") if isinstance(payload.get("source_provenance"), dict) else {}
    data_quality = payload.get("data_quality") if isinstance(payload.get("data_quality"), dict) else {}
    market_session = payload.get("market_session") if isinstance(payload.get("market_session"), dict) else {}
    operation_notes = payload.get("operation_notes")
    if not isinstance(operation_notes, list):
        operation_notes = []

    return {
        "id": snapshot.id,
        "ticker": snapshot.ticker,
        "created_at": snapshot.created_at.isoformat(),
        "price": f"{snapshot.price:.2f}" if snapshot.price is not None else "n/a",
        "final_score": f"{snapshot.final_score:.2f}",
        "recommendation": snapshot.recommendation,
        "session_status": _first_present(market_session.get("status"), "n/a"),
        "freshness_state": _first_present(market_session.get("freshness_state"), "n/a"),
        "data_quality_summary": _first_present(data_quality.get("summary"), "n/a"),
        "source_provider": _first_present(provenance.get("provider_name"), "n/a"),
        "confidence": _first_present(data_quality.get("confidence"), provenance.get("confidence"), "n/a"),
        "short_reason": _first_present(payload.get("short_reason"), "n/a"),
        "operation_notes": operation_notes,
    }


def _serialize(item) -> dict:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if hasattr(item, "__dict__"):
        return {key: value for key, value in vars(item).items() if not key.startswith("_")}
    return {"value": str(item)}


def _serialize_recent_snapshot(snapshot) -> dict:
    report = _recent_snapshot_report(snapshot)
    payload = snapshot.payload if isinstance(snapshot.payload, dict) else {}
    return {
        **report,
        "payload": payload,
    }


def _recent_snapshot_summary(rows) -> dict[str, object]:
    if not rows:
        return {
            "count": 0,
            "unique_tickers": 0,
            "latest_created_at": None,
            "average_final_score": None,
            "recommendation_counts": {},
            "source_providers": [],
            "warning_count": 0,
        }

    reports = [_recent_snapshot_report(row) for row in rows]
    recommendation_counts = Counter(report["recommendation"] for report in reports)
    source_providers = sorted({report["source_provider"] for report in reports if report["source_provider"] != "n/a"})
    warning_count = sum(1 for row in rows if _recent_data_quality_summary(row) not in {"fresh", "ok", "n/a"})

    return {
        "count": len(rows),
        "unique_tickers": len({report["ticker"] for report in reports}),
        "latest_created_at": max(report["created_at"] for report in reports),
        "average_final_score": f"{mean(float(report["final_score"]) for report in reports):.2f}",
        "recommendation_counts": dict(sorted(recommendation_counts.items())),
        "source_providers": source_providers,
        "warning_count": warning_count,
    }


def _recent_data_quality_summary(snapshot) -> str:
    payload = snapshot.payload if isinstance(snapshot.payload, dict) else {}
    data_quality = payload.get("data_quality") if isinstance(payload.get("data_quality"), dict) else {}
    summary = data_quality.get("summary")
    return summary if isinstance(summary, str) else "n/a"


def _first_present(*values):
    for value in values:
        if value not in (None, ""):
            return value
    return "n/a"


if __name__ == "__main__":
    raise SystemExit(main())
