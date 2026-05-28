from __future__ import annotations

import io
import json
from argparse import Namespace
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import unittest

import scripts.run_api as run_api
import scripts.run_telegram_bot as run_telegram_bot
import scripts.openai_smoke as openai_smoke
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
                    recommendation="NEUTRAL",
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


class RunApiScriptTests(unittest.TestCase):
    def tearDown(self) -> None:
        run_api.get_settings.cache_clear()

    def test_main_starts_uvicorn_with_local_host(self) -> None:
        fake_settings = SimpleNamespace(
            api_host="127.0.0.1",
            api_port=8000,
            allow_remote_api=False,
        )

        with (
            patch.object(run_api, "parse_args", return_value=Namespace(reload=True)),
            patch.object(run_api, "get_settings", return_value=fake_settings),
            patch.object(run_api, "enforce_local_api_policy") as policy_mock,
            patch.object(run_api, "build_startup_diagnostics", return_value=SimpleNamespace(warnings=())),
            patch.object(run_api.uvicorn, "run") as uvicorn_run,
        ):
            exit_code = run_api.main()

        self.assertEqual(exit_code, 0)
        policy_mock.assert_called_once_with(fake_settings)
        uvicorn_run.assert_called_once_with(
            "app.main:app",
            host="127.0.0.1",
            port=8000,
            reload=True,
        )

    def test_main_rejects_remote_host_without_policy(self) -> None:
        fake_settings = SimpleNamespace(
            api_host="0.0.0.0",
            api_port=8000,
            allow_remote_api=False,
        )

        stderr = io.StringIO()

        with (
            patch.object(run_api, "parse_args", return_value=Namespace(reload=False)),
            patch.object(run_api, "get_settings", return_value=fake_settings),
            patch.object(run_api, "enforce_local_api_policy", side_effect=RuntimeError("blocked")),
            patch.object(run_api, "build_startup_diagnostics", return_value=SimpleNamespace(warnings=())),
            patch.object(run_api.uvicorn, "run") as uvicorn_run,
            redirect_stderr(stderr),
        ):
            with self.assertRaises(RuntimeError):
                run_api.main()

        uvicorn_run.assert_not_called()


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


class OpenAISmokeScriptTests(unittest.TestCase):
    def test_main_requires_openai_key(self) -> None:
        stderr = io.StringIO()

        with (
            patch.object(openai_smoke, "parse_args", return_value=Namespace(ticker="aapl")),
            patch.object(openai_smoke, "get_settings", return_value=SimpleNamespace(openai_api_key=None, openai_model="gpt-4.1-mini")),
            redirect_stderr(stderr),
        ):
            exit_code = openai_smoke.main()

        self.assertEqual(exit_code, 2)
        self.assertIn("requires OPENAI_API_KEY", stderr.getvalue())

    def test_main_runs_openai_explanation_path(self) -> None:
        fake_db = SimpleNamespace(close=MagicMock())
        fake_analysis = SimpleNamespace(
            ticker="AAPL",
            price=189.12,
            scores=SimpleNamespace(final_score=77.7),
            recommendation="NEUTRAL",
            explanation="LLM explanation",
        )

        with (
            patch.object(openai_smoke, "parse_args", return_value=Namespace(ticker="aapl")),
            patch.object(openai_smoke, "get_settings", return_value=SimpleNamespace(openai_api_key="sk-test", openai_model="gpt-4.1-mini")),
            patch.object(openai_smoke, "init_db"),
            patch.object(openai_smoke, "SessionLocal", return_value=fake_db),
            patch.object(openai_smoke, "analyze_ticker", return_value=fake_analysis) as analyze_mock,
            patch("builtins.print") as print_mock,
        ):
            exit_code = openai_smoke.main()

        self.assertEqual(exit_code, 0)
        analyze_mock.assert_called_once_with("AAPL", db=fake_db, use_ai_explanation=True)
        self.assertTrue(fake_db.close.called)
        payload = json.loads(print_mock.call_args.args[0])
        self.assertEqual(payload["analysis"]["explanation"], "LLM explanation")


class LiveSmokeScriptTests(unittest.TestCase):
    def test_main_runs_analyze_and_scan_without_openai(self) -> None:
        fake_db = SimpleNamespace(close=MagicMock())
        fake_analysis = SimpleNamespace(
            ticker="AAPL",
            price=189.12,
            scores=SimpleNamespace(final_score=77.7),
            recommendation="NEUTRAL",
        )
        fake_scan = SimpleNamespace(
            results=[
                SimpleNamespace(
                    ticker="MSFT",
                    final_score=80.0,
                    recommendation="NEUTRAL",
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
