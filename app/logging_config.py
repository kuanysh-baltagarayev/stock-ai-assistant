from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any, TextIO


_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat().replace(
                "+00:00", "Z"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            payload[key] = _json_safe(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=_json_default)


def configure_logging(
    *,
    level: int = logging.INFO,
    stream: TextIO | None = None,
    force: bool = False,
) -> None:
    root = logging.getLogger()
    if force:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()
    elif root.handlers:
        root.setLevel(level)
        return

    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredFormatter())
    root.addHandler(handler)
    root.setLevel(level)


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, default=_json_default)
    except TypeError:
        return str(value)
    return value


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
