from __future__ import annotations

import json
from pathlib import Path
import sys
import traceback


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.logging_config import configure_logging  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.services.telegram_bot import TelegramBotService  # noqa: E402
from scripts.live_guard import require_live_network  # noqa: E402


def main() -> int:
    configure_logging(force=True)
    if not require_live_network("Telegram live check"):
        return 2
    settings = get_settings()
    service = TelegramBotService(settings=settings)

    if not settings.telegram_bot_token:
        print("Telegram live check requires TELEGRAM_BOT_TOKEN.", file=sys.stderr)
        return 2
    if not settings.telegram_enabled:
        print("Telegram live check requires TELEGRAM_ENABLED=1.", file=sys.stderr)
        return 2

    try:
        result = service.live_check()
    except Exception as exc:
        print(f"Telegram live check failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
