from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models import TelegramSubscription
from app.services.market_data import InvalidTickerError, normalize_ticker


class ParsingMixin:
    def _detail_ticker(self, args: list[str]) -> str | None:
        if not args:
            return None
        ticker = args[0].strip().upper()
        return ticker or None

    def _format_dt(self, value: Any) -> str:
        if value is None:
            return "n/a"
        if isinstance(value, str):
            return value
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat()
        return str(value)

    def _current_day_key(self, moment: datetime | None = None) -> str:
        return (moment or datetime.now(timezone.utc)).date().isoformat()

    def _format_minutes(self, minutes: int | None) -> str:
        if minutes is None:
            return "off"
        hours, remainder = divmod(minutes, 60)
        return f"{hours:02d}:{remainder:02d}"

    def _format_quiet_hours(self, subscription: TelegramSubscription) -> str:
        start = getattr(subscription, "quiet_hours_start_minute", None)
        end = getattr(subscription, "quiet_hours_end_minute", None)
        if start is None or end is None:
            return "off"
        return f"{self._format_minutes(start)}-{self._format_minutes(end)}"

    def _parse_minutes(self, value: str) -> tuple[int | None, str | None]:
        raw = value.strip()
        if not raw:
            return None, "Укажи время в формате HH:MM или HH."
        parts = raw.split(":")
        if len(parts) == 1:
            try:
                hour = int(parts[0])
            except ValueError:
                return None, "Укажи время в формате HH:MM или HH."
            minute = 0
        elif len(parts) == 2:
            try:
                hour = int(parts[0])
                minute = int(parts[1])
            except ValueError:
                return None, "Укажи время в формате HH:MM или HH."
        else:
            return None, "Укажи время в формате HH:MM или HH."
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None, "Время должно быть в диапазоне 00:00-23:59."
        return hour * 60 + minute, None

    def _parse_quiet_hours(self, value: str) -> tuple[int | None, int | None, str | None]:
        raw = value.strip().lower()
        if not raw or raw in {"off", "none", "clear", "unset"}:
            return None, None, None
        if "-" not in raw:
            return None, None, "Формат quiet hours: /quiet 22:00-07:00 или /quiet off."
        start_raw, end_raw = raw.split("-", maxsplit=1)
        start, start_error = self._parse_minutes(start_raw)
        if start_error:
            return None, None, start_error
        end, end_error = self._parse_minutes(end_raw)
        if end_error:
            return None, None, end_error
        if start == end:
            return None, None, "Quiet hours start and end must be different."
        return start, end, None

    def _parse_daily_cap(self, value: str) -> tuple[int | None, str | None]:
        raw = value.strip().lower()
        if not raw or raw in {"off", "none", "clear", "unset"}:
            return None, None
        try:
            parsed = int(raw)
        except ValueError:
            return None, "Daily cap must be a positive integer or /cap off."
        if parsed < 1:
            return None, "Daily cap must be a positive integer or /cap off."
        return parsed, None

    def _parse_confidence_threshold(self, value: str) -> tuple[float | None, str | None]:
        raw = value.strip().lower()
        if not raw or raw in {"off", "none", "clear", "unset"}:
            return None, None
        try:
            parsed = float(raw)
        except ValueError:
            return None, "Используй /confidence 0.75 или /confidence off."
        if parsed < 0 or parsed > 1:
            return None, "Порог уверенности должен быть от 0 до 1, либо /confidence off."
        return parsed, None

    def _parse_toggle(self, value: str) -> tuple[bool, str | None]:
        raw = value.strip().lower()
        if raw in {"on", "1", "true", "yes"}:
            return True, None
        if raw in {"off", "0", "false", "no"}:
            return False, None
        return False, "Use /markethours on or /markethours off."

    def _parse_tickers(self, args: list[str]) -> list[str]:
        tickers: list[str] = []
        for item in args:
            if not item.startswith("/"):
                tickers.append(item.strip().upper())
        return tickers

    def _normalize_watchlist_symbols(self, tickers: list[str]) -> tuple[list[str], list[str]]:
        normalized: list[str] = []
        invalid: list[str] = []
        seen: set[str] = set()
        for item in tickers:
            raw = item.strip().rstrip(",")
            if not raw:
                continue
            try:
                symbol = normalize_ticker(raw)
            except InvalidTickerError:
                invalid.append(item)
                continue
            if symbol not in seen:
                normalized.append(symbol)
                seen.add(symbol)
        return normalized, invalid

    def _filter_results_by_confidence(self, results: list[Any], min_confidence: float | None) -> list[Any]:
        if min_confidence is None:
            return results
        filtered: list[Any] = []
        for item in results:
            confidence = getattr(item, "confidence", None)
            if not isinstance(confidence, (int, float)):
                quality = getattr(item, "data_quality", None)
                if isinstance(quality, dict):
                    confidence = quality.get("confidence")
                elif quality is not None:
                    confidence = getattr(quality, "confidence", None)
            if isinstance(confidence, (int, float)) and confidence >= min_confidence:
                filtered.append(item)
        return filtered
