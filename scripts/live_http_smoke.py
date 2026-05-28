from __future__ import annotations

from argparse import ArgumentParser, Namespace
from contextlib import suppress
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from urllib import parse, request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.logging_config import configure_logging  # noqa: E402
from scripts.live_guard import require_live_network  # noqa: E402


DEFAULT_TICKER = "AAPL"
DEFAULT_SCAN_TICKERS = ["AAPL", "MSFT", "NVDA"]


def parse_args() -> Namespace:
    parser = ArgumentParser(
        description="Run a real uvicorn startup smoke check against local HTTP endpoints."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for the temporary uvicorn server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port for the temporary uvicorn server. Use 0 to auto-select a free port.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Maximum number of seconds to wait for the server and checks.",
    )
    parser.add_argument(
        "--ticker",
        default=DEFAULT_TICKER,
        help="Ticker to verify against the analyze endpoint.",
    )
    parser.add_argument(
        "--scan",
        nargs="*",
        default=DEFAULT_SCAN_TICKERS,
        help="Tickers to verify against the scan endpoint.",
    )
    return parser.parse_args()


def main() -> int:
    configure_logging(force=True)
    if not require_live_network("HTTP smoke"):
        return 2
    args = parse_args()
    ticker = args.ticker.strip().upper()
    scan_tickers = [item.strip().upper() for item in args.scan if item.strip()]
    if not ticker or not scan_tickers:
        print("HTTP smoke requires a ticker and at least one scan ticker.", file=sys.stderr)
        return 2

    port = args.port or _find_free_port(args.host)
    with tempfile.TemporaryDirectory() as tmpdir:
        database_path = Path(tmpdir) / "smoke.db"
        env = _build_env(args.host, port, database_path)
        process = _launch_server(env)
        try:
            base_url = f"http://{args.host}:{port}"
            _wait_for_health(base_url, timeout_seconds=args.timeout)
            health = _get_json(f"{base_url}/health")
            ready = _get_json(f"{base_url}/ready")
            docs = _get_text(f"{base_url}/docs")
            analysis = _get_json(f"{base_url}/analyze/{parse.quote(ticker)}")
            scan = _post_json(f"{base_url}/scan", {"tickers": scan_tickers})
            recent = _get_json(f"{base_url}/analyses/recent?limit=5")
        except Exception as exc:
            print(f"HTTP smoke failed: {exc}", file=sys.stderr)
            return 1
        finally:
            _stop_process(process)

    payload = {
        "status": "ok",
        "base_url": f"http://{args.host}:{port}",
        "health": health,
        "ready": ready,
        "docs_status": "ok" if "swagger" in docs.lower() or "<html" in docs.lower() else "unexpected",
        "analysis": {
            "ticker": analysis["ticker"],
            "final_score": analysis["scores"]["final_score"],
            "recommendation": analysis["recommendation"],
        },
        "scan": {
            "result_count": len(scan["results"]),
            "error_count": len(scan["errors"]),
        },
        "recent_count": len(recent),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _build_env(host: str, port: int, database_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["APP_HOST"] = host
    env["APP_PORT"] = str(port)
    env["ALLOW_REMOTE_API"] = "0"
    env["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    env["OPENAI_API_KEY"] = ""
    env["TELEGRAM_ENABLED"] = "0"
    env["TELEGRAM_BOT_TOKEN"] = ""
    return env


def _launch_server(env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app"],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_health(base_url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            _get_json(f"{base_url}/health")
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise TimeoutError(f"Server did not become ready within {timeout_seconds}s: {last_error}")


def _get_json(url: str) -> object:
    text = _get_text(url)
    return json.loads(text)


def _post_json(url: str, payload: dict[str, object]) -> object:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with request.urlopen(req, timeout=30) as response:
        text = response.read().decode("utf-8")
    return json.loads(text)


def _get_text(url: str) -> str:
    with request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=10)
    if process.poll() is None:
        process.kill()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)


def _find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    raise SystemExit(main())
