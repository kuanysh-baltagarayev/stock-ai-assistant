from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
import sys


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
    return parser.parse_args()


def main() -> int:
    configure_logging(force=True)
    args = parse_args()
    settings = get_settings()
    enforce_local_api_policy(settings)
    diagnostics = build_startup_diagnostics(settings)

    for warning in diagnostics.warnings:
        print(f"Startup warning: {warning}", file=sys.stderr)

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
