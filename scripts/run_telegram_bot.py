from pathlib import Path
import asyncio
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.telegram_bot import run_telegram_bot  # noqa: E402


def main() -> int:
    asyncio.run(run_telegram_bot())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
