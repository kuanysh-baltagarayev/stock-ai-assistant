import asyncio
from pathlib import Path
import sys
import traceback


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.logging_config import configure_logging  # noqa: E402
from app.services.telegram_bot import run_telegram_bot  # noqa: E402


def main() -> int:
    configure_logging(force=True)
    try:
        asyncio.run(run_telegram_bot())
    except RuntimeError as exc:
        print(f"Telegram bot could not start: {exc}", file=sys.stderr)
        return 1
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
