from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.services.alert_rules import (
    evaluate_rules,
    format_rule,
    is_recently_fired,
    mark_fired,
    parse_rule,
)


class ParseRuleTests(unittest.TestCase):
    def test_price_below(self) -> None:
        rule = parse_rule("AAPL < 300")
        self.assertIsNotNone(rule)
        self.assertEqual(rule["ticker"], "AAPL")
        self.assertEqual(rule["kind"], "price_below")
        self.assertEqual(rule["value"], 300.0)

    def test_price_above(self) -> None:
        rule = parse_rule("MSFT > 450.5")
        self.assertIsNotNone(rule)
        self.assertEqual(rule["kind"], "price_above")
        self.assertEqual(rule["value"], 450.5)

    def test_pct_move(self) -> None:
        rule = parse_rule("NVDA move 5")
        self.assertIsNotNone(rule)
        self.assertEqual(rule["kind"], "pct_move")
        self.assertEqual(rule["value"], 5.0)

    def test_recommendation_sell(self) -> None:
        rule = parse_rule("TSLA sell")
        self.assertIsNotNone(rule)
        self.assertEqual(rule["kind"], "recommendation")
        self.assertEqual(rule["value"], "SELL")

    def test_recommendation_buy_case_insensitive(self) -> None:
        rule = parse_rule("AMD BUY")
        self.assertIsNotNone(rule)
        self.assertEqual(rule["value"], "BUY")

    def test_invalid_returns_none(self) -> None:
        self.assertIsNone(parse_rule("just some text"))
        self.assertIsNone(parse_rule("AAPL"))
        self.assertIsNone(parse_rule(""))

    def test_last_fired_at_initialized_to_none(self) -> None:
        rule = parse_rule("AAPL < 300")
        self.assertIsNone(rule["last_fired_at"])


class EvaluateRulesTests(unittest.TestCase):
    def _rule(self, kind: str, value, ticker: str = "AAPL") -> dict:
        return {"ticker": ticker, "kind": kind, "value": value, "last_fired_at": None}

    def test_price_below_fires(self) -> None:
        fired = evaluate_rules(
            [self._rule("price_below", 300)],
            ticker="AAPL", price=295.0, prev_close=300.0, recommendation=None,
        )
        self.assertEqual(len(fired), 1)
        self.assertIn("295", fired[0]["reason"])

    def test_price_below_does_not_fire_when_above(self) -> None:
        fired = evaluate_rules(
            [self._rule("price_below", 300)],
            ticker="AAPL", price=310.0, prev_close=300.0, recommendation=None,
        )
        self.assertEqual(len(fired), 0)

    def test_price_above_fires(self) -> None:
        fired = evaluate_rules(
            [self._rule("price_above", 400)],
            ticker="AAPL", price=405.0, prev_close=390.0, recommendation=None,
        )
        self.assertEqual(len(fired), 1)

    def test_pct_move_positive_fires(self) -> None:
        fired = evaluate_rules(
            [self._rule("pct_move", 5)],
            ticker="AAPL", price=315.0, prev_close=300.0, recommendation=None,
        )
        self.assertEqual(len(fired), 1)
        self.assertIn("вырос", fired[0]["reason"])

    def test_pct_move_negative_fires(self) -> None:
        fired = evaluate_rules(
            [self._rule("pct_move", 5)],
            ticker="AAPL", price=283.5, prev_close=300.0, recommendation=None,
        )
        self.assertEqual(len(fired), 1)
        self.assertIn("упал", fired[0]["reason"])

    def test_pct_move_below_threshold_does_not_fire(self) -> None:
        fired = evaluate_rules(
            [self._rule("pct_move", 10)],
            ticker="AAPL", price=304.0, prev_close=300.0, recommendation=None,
        )
        self.assertEqual(len(fired), 0)

    def test_pct_move_no_prev_close_does_not_fire(self) -> None:
        fired = evaluate_rules(
            [self._rule("pct_move", 5)],
            ticker="AAPL", price=315.0, prev_close=None, recommendation=None,
        )
        self.assertEqual(len(fired), 0)

    def test_recommendation_fires(self) -> None:
        fired = evaluate_rules(
            [self._rule("recommendation", "SELL")],
            ticker="AAPL", price=290.0, prev_close=None, recommendation="SELL",
        )
        self.assertEqual(len(fired), 1)

    def test_recommendation_no_match(self) -> None:
        fired = evaluate_rules(
            [self._rule("recommendation", "SELL")],
            ticker="AAPL", price=290.0, prev_close=None, recommendation="NEUTRAL",
        )
        self.assertEqual(len(fired), 0)

    def test_different_ticker_not_evaluated(self) -> None:
        fired = evaluate_rules(
            [self._rule("price_below", 300, ticker="MSFT")],
            ticker="AAPL", price=295.0, prev_close=None, recommendation=None,
        )
        self.assertEqual(len(fired), 0)

    def test_multiple_rules_multiple_fires(self) -> None:
        rules = [
            self._rule("price_below", 300),
            self._rule("recommendation", "SELL"),
        ]
        fired = evaluate_rules(
            rules, ticker="AAPL", price=295.0, prev_close=None, recommendation="SELL",
        )
        self.assertEqual(len(fired), 2)


class CooldownTests(unittest.TestCase):
    def test_not_recently_fired_when_none(self) -> None:
        rule = {"last_fired_at": None}
        self.assertFalse(is_recently_fired(rule))

    def test_recently_fired_within_window(self) -> None:
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.assertTrue(is_recently_fired({"last_fired_at": recent}, cooldown_hours=4))

    def test_not_recently_fired_after_window(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        self.assertFalse(is_recently_fired({"last_fired_at": old}, cooldown_hours=4))

    def test_mark_fired_sets_timestamp(self) -> None:
        rule = {"ticker": "AAPL", "kind": "price_below", "value": 300, "last_fired_at": None}
        fired = mark_fired(rule)
        self.assertIsNotNone(fired["last_fired_at"])
        self.assertIsNone(rule["last_fired_at"])  # original unchanged


class FormatRuleTests(unittest.TestCase):
    def test_price_below(self) -> None:
        self.assertEqual(format_rule({"ticker": "AAPL", "kind": "price_below", "value": 300}), "AAPL < 300")

    def test_price_above(self) -> None:
        self.assertEqual(format_rule({"ticker": "MSFT", "kind": "price_above", "value": 450}), "MSFT > 450")

    def test_pct_move(self) -> None:
        self.assertIn("±5%", format_rule({"ticker": "NVDA", "kind": "pct_move", "value": 5}))

    def test_recommendation(self) -> None:
        self.assertIn("SELL", format_rule({"ticker": "TSLA", "kind": "recommendation", "value": "SELL"}))


if __name__ == "__main__":
    unittest.main()
