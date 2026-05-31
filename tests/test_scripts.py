from __future__ import annotations

import io
import json
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import unittest

import scripts.run_api as run_api
import scripts.check_telegram as check_telegram
import scripts.live_http_smoke as live_http_smoke
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
            summary=SimpleNamespace(
                requested_count=2,
                success_count=1,
                error_count=0,
                partial_failure=False,
                message="Scan completed successfully for 1 tickers.",
                failed_tickers=[],
                notes=["Example note."],
            ),
        )

        with (
            patch.object(
                scan_market,
                "parse_args",
                return_value=Namespace(tickers=["aapl", "msft"], json=True, recent=False, recent_limit=10),
            ),
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
        self.assertEqual(payload["summary"]["success_count"], 1)
        self.assertEqual(payload["summary"]["notes"], ["Example note."])

    def test_main_renders_recent_analysis_report(self) -> None:
        fake_db = SimpleNamespace(close=MagicMock())
        recent_rows = [
            SimpleNamespace(
                id=7,
                ticker="AAPL",
                price=189.12,
                final_score=77.7,
                recommendation="NEUTRAL",
                created_at=SimpleNamespace(isoformat=MagicMock(return_value="2026-06-01T10:00:00+00:00")),
                payload={
                    "short_reason": "AAPL short reason",
                    "data_quality": {"summary": "fresh", "confidence": 0.91},
                    "market_session": {"status": "open", "freshness_state": "fresh"},
                    "source_provenance": {"provider_name": "yfinance"},
                    "operation_notes": ["Market is open."],
                },
            )
        ]
        stdout = io.StringIO()

        with (
            patch.object(
                scan_market,
                "parse_args",
                return_value=Namespace(tickers=["aapl"], json=False, recent=True, recent_limit=5),
            ),
            patch.object(scan_market, "init_db"),
            patch.object(scan_market, "SessionLocal", return_value=fake_db),
            patch.object(scan_market, "list_recent_snapshots", return_value=recent_rows) as recent_mock,
            redirect_stdout(stdout),
        ):
            exit_code = scan_market.main()

        self.assertEqual(exit_code, 0)
        recent_mock.assert_called_once_with(fake_db, limit=5, ticker="AAPL")
        self.assertTrue(fake_db.close.called)
        output = stdout.getvalue()
        self.assertIn("Recent analyses (1):", output)
        self.assertIn("#7 AAPL 2026-06-01T10:00:00+00:00", output)
        self.assertIn("session=open freshness=fresh quality=fresh", output)
        self.assertIn("source=yfinance confidence=0.91", output)
        self.assertIn("reason=AAPL short reason", output)
        self.assertIn("notes=Market is open.", output)

    def test_main_recent_mode_without_tickers_reads_all_recent_snapshots(self) -> None:
        fake_db = SimpleNamespace(close=MagicMock())
        stdout = io.StringIO()

        with (
            patch.object(
                scan_market,
                "parse_args",
                return_value=Namespace(tickers=[], json=False, recent=True, recent_limit=3),
            ),
            patch.object(scan_market, "init_db"),
            patch.object(scan_market, "SessionLocal", return_value=fake_db),
            patch.object(scan_market, "list_recent_snapshots", return_value=[]) as recent_mock,
            redirect_stdout(stdout),
        ):
            exit_code = scan_market.main()

        self.assertEqual(exit_code, 1)
        recent_mock.assert_called_once_with(fake_db, limit=3, ticker=None)
        self.assertTrue(fake_db.close.called)
        self.assertIn("No saved analyses found.", stdout.getvalue())


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


class CheckTelegramScriptTests(unittest.TestCase):
    def tearDown(self) -> None:
        check_telegram.get_settings.cache_clear()

    def test_main_reports_missing_token(self) -> None:
        stderr = io.StringIO()

        with (
            patch.dict("os.environ", {"ALLOW_LIVE_NETWORK": "1"}, clear=False),
            patch.object(check_telegram, "get_settings", return_value=SimpleNamespace(telegram_bot_token=None, telegram_enabled=True)),
            redirect_stderr(stderr),
        ):
            exit_code = check_telegram.main()

        self.assertEqual(exit_code, 2)
        self.assertIn("requires TELEGRAM_BOT_TOKEN", stderr.getvalue())

    def test_main_runs_safe_live_check(self) -> None:
        fake_settings = SimpleNamespace(telegram_bot_token="123456:abcdefghijklmnopqrstuvwxyzABCDEF", telegram_enabled=True)
        fake_service = SimpleNamespace(live_check=MagicMock(return_value={"status": "ok", "username": "stock_bot"}))
        stdout = io.StringIO()

        with (
            patch.dict("os.environ", {"ALLOW_LIVE_NETWORK": "1"}, clear=False),
            patch.object(check_telegram, "get_settings", return_value=fake_settings),
            patch.object(check_telegram, "TelegramBotService", return_value=fake_service) as service_ctor,
            patch("sys.stdout", stdout),
        ):
            exit_code = check_telegram.main()

        self.assertEqual(exit_code, 0)
        service_ctor.assert_called_once_with(settings=fake_settings)
        fake_service.live_check.assert_called_once()
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["username"], "stock_bot")


class LiveHttpSmokeScriptTests(unittest.TestCase):
    def test_main_requires_live_network_flag(self) -> None:
        stderr = io.StringIO()

        with (
            patch.object(live_http_smoke, "parse_args", return_value=Namespace(ticker="AAPL", scan=["MSFT"])),
            redirect_stderr(stderr),
        ):
            exit_code = live_http_smoke.main()

        self.assertEqual(exit_code, 2)
        self.assertIn("requires ALLOW_LIVE_NETWORK=1", stderr.getvalue())

    def test_main_requires_ticker_and_scan_list(self) -> None:
        stderr = io.StringIO()

        with (
            patch.dict("os.environ", {"ALLOW_LIVE_NETWORK": "1"}, clear=False),
            patch.object(live_http_smoke, "parse_args", return_value=Namespace(ticker=" ", scan=[])),
            redirect_stderr(stderr),
        ):
            exit_code = live_http_smoke.main()

        self.assertEqual(exit_code, 2)
        self.assertIn("requires a ticker", stderr.getvalue())

    def test_main_runs_real_http_smoke_flow(self) -> None:
        fake_process = SimpleNamespace()
        stdout = io.StringIO()

        def fake_get_json(url: str) -> object:
            if url.endswith("/health"):
                return {"status": "ok"}
            if url.endswith("/ready"):
                return {"status": "ready"}
            if "/analyze/" in url:
                return {
                    "ticker": "AAPL",
                    "scores": {"final_score": 77.7},
                    "recommendation": "NEUTRAL",
                }
            if url.endswith("/scan"):
                return {"results": [{"ticker": "AAPL"}], "errors": []}
            if url.endswith("/analyses/recent?limit=5"):
                return [{"ticker": "AAPL"}]
            raise AssertionError(f"Unexpected URL: {url}")

        with (
            patch.dict("os.environ", {"ALLOW_LIVE_NETWORK": "1"}, clear=False),
            patch.object(
                live_http_smoke,
                "parse_args",
                return_value=Namespace(host="127.0.0.1", port=18080, timeout=5, ticker="aapl", scan=["msft"]),
            ),
            patch.object(live_http_smoke, "_find_free_port", return_value=18080),
            patch.object(live_http_smoke, "_launch_server", return_value=fake_process) as launch_mock,
            patch.object(live_http_smoke, "_wait_for_health") as wait_mock,
            patch.object(live_http_smoke, "_get_json", side_effect=fake_get_json) as get_json_mock,
            patch.object(live_http_smoke, "_get_text", return_value="<html>swagger</html>"),
            patch.object(live_http_smoke, "_post_json", return_value={"results": [{"ticker": "AAPL"}], "errors": []}) as post_mock,
            patch.object(live_http_smoke, "_stop_process") as stop_mock,
            patch("sys.stdout", stdout),
        ):
            exit_code = live_http_smoke.main()

        self.assertEqual(exit_code, 0)
        launch_mock.assert_called_once()
        wait_mock.assert_called_once_with("http://127.0.0.1:18080", timeout_seconds=5)
        get_json_mock.assert_any_call("http://127.0.0.1:18080/health")
        get_json_mock.assert_any_call("http://127.0.0.1:18080/ready")
        get_json_mock.assert_any_call("http://127.0.0.1:18080/analyze/AAPL")
        get_json_mock.assert_any_call("http://127.0.0.1:18080/analyses/recent?limit=5")
        post_mock.assert_called_once_with(
            "http://127.0.0.1:18080/scan",
            {"tickers": ["MSFT"]},
        )
        stop_mock.assert_called_once_with(fake_process)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["analysis"]["ticker"], "AAPL")


class OpenAISmokeScriptTests(unittest.TestCase):
    def test_main_requires_openai_key(self) -> None:
        stderr = io.StringIO()

        with (
            patch.dict("os.environ", {"ALLOW_LIVE_NETWORK": "1"}, clear=False),
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
            patch.dict("os.environ", {"ALLOW_LIVE_NETWORK": "1"}, clear=False),
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
            summary=SimpleNamespace(
                requested_count=1,
                success_count=1,
                error_count=0,
                partial_failure=False,
                message="Scan completed successfully for 1 tickers.",
                failed_tickers=[],
            ),
        )

        with (
            patch.dict("os.environ", {"ALLOW_LIVE_NETWORK": "1"}, clear=False),
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
        self.assertEqual(payload["scan"]["summary"]["success_count"], 1)

    def test_main_rejects_empty_input(self) -> None:
        stderr = io.StringIO()

        with (
            patch.dict("os.environ", {"ALLOW_LIVE_NETWORK": "1"}, clear=False),
            patch.object(live_smoke, "parse_args", return_value=Namespace(ticker="", scan=[])),
            redirect_stderr(stderr),
        ):
            exit_code = live_smoke.main()

        self.assertEqual(exit_code, 2)
        self.assertIn("requires a ticker", stderr.getvalue())
