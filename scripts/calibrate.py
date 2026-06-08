#!/usr/bin/env python3
"""Scoring calibration script — grid-searches thresholds and weights.

Fetches stored analysis snapshots from the database, pairs each with
subsequent price movement (1d, 5d, 20d trading days), and finds optimal
parameters for label assignment and component weighting.

Usage:

    python scripts/calibrate.py                          # full run
    python scripts/calibrate.py --quick                   # fewer grid points
    python scripts/calibrate.py --horizon 5               # single horizon

Output: JSON report printed to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any



PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


# ── data loading ──────────────────────────────────────────────────────

def _load_snapshots(limit: int | None = None) -> list[dict[str, Any]]:
    """Load analysis snapshots from the SQLite database."""
    from app.database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        from app.models import AnalysisSnapshot

        query = (
            db.query(AnalysisSnapshot)
            .order_by(AnalysisSnapshot.created_at.desc())
        )
        if limit:
            query = query.limit(limit)
        snapshots = query.all()

        results: list[dict[str, Any]] = []
        for snap in snapshots:
            payload = snap.payload or {}
            scores = payload.get("scores") or {}
            results.append({
                "id": snap.id,
                "ticker": snap.ticker,
                "created_at": snap.created_at,
                "final_score": snap.final_score,
                "recommendation": snap.recommendation,
                "momentum_score": scores.get("momentum_score", 0.0),
                "valuation_score": scores.get("valuation_score", 0.0),
                "risk_score": scores.get("risk_score", 0.0),
                "price": snap.price,
            })
        return results
    finally:
        db.close()


# ── price pairing ─────────────────────────────────────────────────────

def _fetch_price_on_date(ticker: str, target_date: datetime) -> float | None:
    """Fetch approximate close price for a ticker at/after a date.

    Uses yfinance with a narrow date window. Best-effort; returns None
    when price data is unavailable.
    """
    import yfinance as yf

    try:
        start = target_date - __import__("datetime").timedelta(days=1)
        end = target_date + __import__("datetime").timedelta(days=30)
        hist = yf.download(
            ticker, start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False, auto_adjust=False,
        )
    except Exception:
        return None

    if hist.empty or "Close" not in hist.columns:
        return None
    return float(hist["Close"].iloc[-1]) if len(hist) > 0 else None


def _pair_with_future_price(
    snapshots: list[dict[str, Any]],
    horizon_days: int = 5,
) -> list[dict[str, Any]]:
    """Pair each snapshot with the price change after *horizon_days*."""
    paired: list[dict[str, Any]] = []
    for snap in snapshots:
        price = snap.get("price")
        if not price:
            continue
        created = snap["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        future_price = _fetch_price_on_date(snap["ticker"], created)
        if future_price is None or future_price <= 0:
            continue

        change_pct = (future_price - price) / price * 100
        snap["future_change_pct"] = round(change_pct, 2)
        snap["future_price"] = round(future_price, 2)
        paired.append(snap)
    return paired


# ── metrics ───────────────────────────────────────────────────────────

_LABEL_ORDER = ["HIGH_RISK", "CAUTION", "NEUTRAL", "WATCH", "HIGH_INTEREST"]


def _direction(change_pct: float) -> int:
    """1 = price up (good for buy-side), -1 = down, 0 = flat."""
    if change_pct > 2.0:
        return 1
    if change_pct < -2.0:
        return -1
    return 0


def _label_good(label: str) -> int:
    """For a given research label, is price up good (+1), bad (-1), or neutral (0)?"""
    mapping = {
        "HIGH_INTEREST": 1,
        "WATCH": 1,
        "NEUTRAL": 0,
        "CAUTION": -1,
        "HIGH_RISK": -1,
    }
    return mapping.get(label, 0)


@dataclass
class LabelMetrics:
    label: str
    true_positives: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    false_negatives: int = 0
    total: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def accuracy(self) -> float:
        denom = self.total
        return (self.true_positives + self.true_negatives) / denom if denom > 0 else 0.0


def _compute_metrics(
    paired: list[dict[str, Any]],
    label_field: str = "recommendation",
) -> dict[str, Any]:
    """Compute per-label and aggregate metrics."""
    labels: dict[str, LabelMetrics] = {}
    for label in _LABEL_ORDER:
        labels[label] = LabelMetrics(label=label)

    correct = 0
    for snap in paired:
        label = snap.get(label_field, "NEUTRAL")
        change = snap["future_change_pct"]
        direction = _direction(change)
        good = _label_good(label)

        lm = labels.get(label)
        if lm is None:
            continue
        lm.total += 1

        if good == 0:
            if direction == 0:
                correct += 1
                lm.true_positives += 1
            else:
                lm.false_negatives += 1
        elif good == direction:
            correct += 1
            lm.true_positives += 1
        elif direction == 0:
            lm.true_negatives += 1
        else:
            lm.false_positives += 1

    overall = {
        "total_snapshots": len(paired),
        "correct": correct,
        "accuracy": round(correct / len(paired), 4) if paired else 0.0,
        "per_label": {
            lm.label: {
                "total": lm.total,
                "precision": round(lm.precision, 4),
                "recall": round(lm.recall, 4),
                "f1": round(lm.f1, 4),
                "accuracy": round(lm.accuracy, 4),
            }
            for lm in labels.values() if lm.total > 0
        },
    }
    # Macro-average F1
    f1s = [lm.f1 for lm in labels.values() if lm.total > 0]
    overall["macro_avg_f1"] = round(sum(f1s) / len(f1s), 4) if f1s else 0.0
    return overall


# ── grid search ───────────────────────────────────────────────────────

def _grid_search_thresholds(
    paired: list[dict[str, Any]],
    horizons: list[int],
) -> dict[str, Any]:
    """Grid-search final_score thresholds for label assignment."""
    if not paired:
        return {"error": "no data"}

    best = {"thresholds": None, "score": 0.0, "metrics": None}
    for interest_thr in range(60, 91, 5):
        for watch_thr in range(40, 75, 5):
            for caution_thr in range(30, 60, 5):
                if not (interest_thr > watch_thr > caution_thr):
                    continue

                # Apply thresholds
                assigned = []
                for snap in paired:
                    fs = snap["final_score"]
                    if fs >= interest_thr:
                        assigned.append({**snap, "threshold_label": "HIGH_INTEREST"})
                    elif fs >= watch_thr:
                        assigned.append({**snap, "threshold_label": "WATCH"})
                    elif fs >= caution_thr:
                        assigned.append({**snap, "threshold_label": "NEUTRAL"})
                    else:
                        assigned.append({**snap, "threshold_label": "HIGH_RISK"})

                metrics = _compute_metrics(assigned, label_field="threshold_label")
                f1 = metrics.get("macro_avg_f1", 0.0)
                if f1 > best["score"]:
                    best = {
                        "thresholds": {
                            "HIGH_INTEREST": interest_thr,
                            "WATCH": watch_thr,
                            "NEUTRAL": caution_thr,
                            "HIGH_RISK": 0,
                        },
                        "score": round(f1, 4),
                        "metrics": metrics,
                    }

    return best


def _grid_search_weights(
    paired: list[dict[str, Any]],
) -> dict[str, Any]:
    """Grid-search component weights (momentum, valuation, risk)."""
    if not paired:
        return {"error": "no data"}

    # We need access to the scoring function to re-score with different weights.
    # For a simpler approach, we evaluate how well current sub-scores predict future movement.
    pass  # weight search uses simulated scores, not re-scoring

    best = {"weights": None, "score": 0.0}
    for m_weight in range(20, 61, 10):
        for v_weight in range(20, 51, 10):
            for r_weight in range(20, 51, 10):
                total = m_weight + v_weight + r_weight
                if abs(total - 100) > 5:
                    continue

                correct = 0
                for snap in paired:
                    change = snap["future_change_pct"]

                    # Simulate re-scoring: adjust final score based on weight shift
                    ms = snap.get("momentum_score", 50)
                    vs = snap.get("valuation_score", 50)
                    rs = snap.get("risk_score", 50)
                    adjusted = (ms * m_weight + vs * v_weight + rs * r_weight) / 100

                    direction = _direction(change)
                    label = "HIGH_INTEREST" if adjusted >= 75 else "WATCH" if adjusted >= 55 else "CAUTION" if adjusted < 35 else "NEUTRAL"
                    good = _label_good(label)
                    if (good == direction) or (good == 0 and direction == 0):
                        correct += 1

                acc = correct / len(paired) if paired else 0
                if acc > best["score"]:
                    best = {
                        "weights": {"momentum": m_weight, "valuation": v_weight, "risk": r_weight},
                        "score": round(acc, 4),
                    }

    return best


# ── report ────────────────────────────────────────────────────────────

def _default_config() -> dict[str, Any]:
    return {
        "thresholds": {
            "HIGH_INTEREST": 80,
            "WATCH": 60,
            "NEUTRAL": 40,
            "HIGH_RISK": 0,
        },
        "weights": {
            "momentum": 40,
            "valuation": 30,
            "risk": 30,
        },
    }


def build_report(
    paired: list[dict[str, Any]],
    horizon_days: int = 5,
    quick: bool = False,
) -> dict[str, Any]:
    """Build a calibration report."""
    current_metrics = _compute_metrics(paired)
    thr_result = _grid_search_thresholds(paired, [horizon_days])
    w_result = _grid_search_weights(paired) if not quick else {"note": "skipped (--quick)"}

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizon_days": horizon_days,
        "snapshot_count": len(paired),
        "current": {
            "config": _default_config(),
            "metrics": current_metrics,
        },
        "optimal_thresholds": {
            "config": {
                "thresholds": thr_result.get("thresholds", {}),
            },
            "macro_avg_f1": thr_result.get("score", 0.0),
            "metrics": thr_result.get("metrics"),
        },
        "optimal_weights": w_result,
        "improvement": {},
    }

    # Compare
    current_f1 = current_metrics.get("macro_avg_f1", 0.0)
    optimal_f1 = thr_result.get("score", 0.0)
    report["improvement"] = {
        "current_macro_avg_f1": current_f1,
        "optimal_macro_avg_f1": optimal_f1,
        "f1_delta": round(optimal_f1 - current_f1, 4),
    }

    return report


# ── main ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Scoring calibration — grid-search thresholds and weights.")
    parser.add_argument("--quick", action="store_true", help="Skip weight grid search.")
    parser.add_argument("--horizon", type=int, default=5, help="Trading-day horizon (default: 5).")
    parser.add_argument("--limit", type=int, default=None, help="Max snapshots to load.")
    parser.add_argument("--output", type=str, default=None, help="Write report to this file.")
    args = parser.parse_args()

    print("Loading snapshots from database...", file=sys.stderr)
    snapshots = _load_snapshots(limit=args.limit)
    print(f"Loaded {len(snapshots)} snapshots.", file=sys.stderr)

    if not snapshots:
        print(json.dumps({"error": "no snapshots found"}, indent=2))
        sys.exit(1)

    print(f"Pairing with price data (horizon={args.horizon}d)...", file=sys.stderr)
    paired = _pair_with_future_price(snapshots, horizon_days=args.horizon)
    print(f"Paired {len(paired)}/{len(snapshots)} snapshots.", file=sys.stderr)

    report = build_report(paired, horizon_days=args.horizon, quick=args.quick)
    report_json = json.dumps(report, indent=2, default=str)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report_json)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(report_json)


if __name__ == "__main__":
    main()
