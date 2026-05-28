from __future__ import annotations

import io
import json
from argparse import Namespace
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import unittest

import scripts.run_telegram_bot as run_telegram_bot
import scripts.live_smoke as live_smoke
import scripts.scan_market as scan_market


class ScanMarketScriptTests(unittest.TestCase):
    def test_main_supports_custom_tickers_and_json_output(self) -> None:
        fake_db = SimpleNamespace(close=MagicMock())
        fake_response = SimpleNamespace(
            results=[
                SimpleNamespace(
                    ticker="AAPL",
                    price=189.12,
                    final_score=77.7,
                    recommendation="HOLD",
                    short_reason="AAPL short reason",
                )
            ],
            errors=[],
        )

        with (
            patch.object(scan_market, "parse_args", return_value=Namespace(tickers=["aapl", "msft"], json=True)),
            patch.object(scan_market, "init_db"),
            patch.object(scan_market, "SessionLocal", return_value=fake_db),
            patch.object(scan_market, "scan_tickers", return_value=fake_response) as scan_mock,
            patch("builtins.print") as print_mock,
        ):
            exit_code = scan_market.main()

        self.assertEqual(exit_code, 0)
        scan_mock.assert_called_once_with(["AAPL", "MSFT"], db=fake_db)
        self.assertTrue(fake_db.close.called)
        payload = json.loads(print_mock.call_args.args[0])
        self.assertEqual(payload["results"][0]["ticker"], "AAPL")


class RunTelegramBotScriptTests(unittest.TestCase):
    def test_main_reports_runtime_errors(self) -> None:
        stderr = io.StringIO()

        with (
            patch.object(run_telegram_bot, "run_telegram_bot", side_effect=RuntimeError("missing token")),
            redirect_stderr(stderr),
        ):
            exit_code = run_telegram_bot.main()

        self.assertEqual(exit_code, 1)
        self.assertIn("missing token", stderr.getvalue())


class LiveSmokeScriptTests(unittest.TestCase):
    def test_main_runs_analyze_and_scan_without_openai(self) -> None:
        fake_db = SimpleNamespace(close=MagicMock())
        fake_analysis = SimpleNamespace(
            ticker="AAPL",
            price=189.12,
            scores=SimpleNamespace(final_score=77.7),
            recommendation="HOLD",
        )
        fake_scan = SimpleNamespace(
            results=[
                SimpleNamespace(
                    ticker="MSFT",
                    final_score=80.0,
                    recommendation="HOLD",
                )
            ],
            errors=[],
        )

        with (
            patch.object(live_smoke, "parse_args", return_value=Namespace(ticker="aapl", scan=["msft"])),
            patch.object(live_smoke, "init_db"),
            patch.object(live_smoke, "SessionLocal", return_value=fake_db),
            patch.object(live_smoke, "analyze_ticker", return_value=fake_analysis) as analyze_mock,
            patch.object(live_smoke, "scan_tickers", return_value=fake_scan) as scan_mock,
            patch("builtins.print") as print_mock,
        ):
            exit_code = live_smoke.main()

        self.assertEqual(exit_code, 0)
        analyze_mock.assert_called_once_with("AAPL", db=fake_db, use_ai_explanation=False)
        scan_mock.assert_called_once_with(["MSFT"], db=fake_db)
        self.assertTrue(fake_db.close.called)
        payload = json.loads(print_mock.call_args.args[0])
        self.assertEqual(payload["status"], "ok")

    def test_main_rejects_empty_input(self) -> None:
        stderr = io.StringIO()

        with (
            patch.object(live_smoke, "parse_args", return_value=Namespace(ticker="", scan=[])),
            redirect_stderr(stderr),
        ):
            exit_code = live_smoke.main()

        self.assertEqual(exit_code, 2)
        self.assertIn("requires a ticker", stderr.getvalue())
