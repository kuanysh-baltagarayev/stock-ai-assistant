from __future__ import annotations

from argparse import ArgumentParser, Namespace
from contextlib import suppress
from pathlib import Path
import sys
import json
import os
import socket
import subprocess
import tempfile
import time
from urllib import request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.diagnostics import build_startup_diagnostics, enforce_local_api_policy  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402


def parse_args() -> Namespace:
    parser = ArgumentParser(description="Run the Stock AI Assistant API with local-only policy checks.")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn reload mode for local development.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Start uvicorn temporarily and verify local HTTP startup before exiting.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Override the host used for smoke verification.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port used for smoke verification. Use 0 to auto-select a free port.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Maximum number of seconds to wait for smoke verification.",
    )
    return parser.parse_args()


def main() -> int:
    configure_logging(force=True)
    args = parse_args()
    settings = get_settings()
    enforce_local_api_policy(settings)
    diagnostics = build_startup_diagnostics(settings)

    for warning in diagnostics.warnings:
        print(f"Startup warning: {warning}", file=sys.stderr)

    if args.smoke:
        return _run_smoke_check(args, settings)

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=args.reload,
    )
    return 0


def _run_smoke_check(args: Namespace, settings: object) -> int:
    host = (args.host or settings.api_host).strip() or settings.api_host
    port = args.port or _find_free_port(host)

    with tempfile.TemporaryDirectory() as tmpdir:
        database_path = Path(tmpdir) / "run_api_smoke.db"
        env = _build_env(host, port, database_path)
        process = _launch_server(env)
        try:
            base_url = f"http://{host}:{port}"
            _wait_for_health(base_url, timeout_seconds=args.timeout)
            health = _get_json(f"{base_url}/health")
            ready = _get_json(f"{base_url}/ready")
            docs = _get_text(f"{base_url}/docs")
        except Exception as exc:
            print(f"API smoke failed: {exc}", file=sys.stderr)
            return 1
        finally:
            _stop_process(process)

    payload = {
        "status": "ok",
        "base_url": f"http://{host}:{port}",
        "health": health,
        "ready": ready,
        "docs_status": "ok" if "swagger" in docs.lower() or "<html" in docs.lower() else "unexpected",
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
    with request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


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
