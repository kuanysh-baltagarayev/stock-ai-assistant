from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, TextIO


_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())
_SENSITIVE_KEYWORDS = ("token", "secret", "password", "api_key", "apikey", "authorization")
_TELEGRAM_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")


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
            payload[key] = _sanitize_field(key, value)
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


def _sanitize_field(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return "[REDACTED]"

    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {
            item_key: _sanitize_field(str(item_key), item_value)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_field(key, item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_field(key, item) for item in value)
    if isinstance(value, set):
        return [_sanitize_field(key, item) for item in sorted(value, key=str)]
    return _json_safe(value)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(keyword in normalized for keyword in _SENSITIVE_KEYWORDS)


def _redact_text(value: str) -> str:
    redacted = _TELEGRAM_TOKEN_RE.sub("[REDACTED]", value)
    redacted = _OPENAI_KEY_RE.sub("[REDACTED]", redacted)
    return redacted


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
