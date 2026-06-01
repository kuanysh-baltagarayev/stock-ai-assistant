from __future__ import annotations

from typing import Any


class UiMixin:
    def _chat_is_allowed(self, chat_id: int) -> bool:
        allowed_chat_ids = getattr(self.settings, "telegram_allowed_chat_ids", []) or []
        return not allowed_chat_ids or chat_id in allowed_chat_ids

    def _access_denied_text(self) -> str:
        allowed_chat_ids = getattr(self.settings, "telegram_allowed_chat_ids", []) or []
        if allowed_chat_ids:
            allowed = ", ".join(str(chat_id) for chat_id in allowed_chat_ids)
            return (
                "Доступ к этому боту ограничен.\n"
                f"Чат не входит в TELEGRAM_ALLOWED_CHAT_IDS: {allowed}.\n"
                "Если доступ нужен, добавь этот chat_id в allowlist и перезапусти бота."
            )
        return "Доступ к этому боту временно ограничен."

    def _button_subscribe(self) -> str:
        return "Подписаться"

    def _button_unsubscribe(self) -> str:
        return "Отписаться"

    def _button_status(self) -> str:
        return "Статус"

    def _button_scan(self) -> str:
        return "Сканировать рынок"

    def _button_help(self) -> str:
        return "Помощь"

    def _button_choose_ticker(self) -> str:
        return "Выбрать тикер"

    def _button_watchlist(self) -> str:
        return "Мой список"

    def _button_preferences(self) -> str:
        return "Настройки"

    def _button_back(self) -> str:
        return "Назад"

    def _ticker_buttons(self) -> list[str]:
        return [f"Анализ {ticker}" for ticker in self._configured_tickers()]

    def _main_keyboard(self) -> dict[str, Any]:
        keyboard: list[list[dict[str, str]]] = [
            [
                {"text": self._button_subscribe()},
                {"text": self._button_unsubscribe()},
                {"text": self._button_status()},
            ],
            [
                {"text": self._button_watchlist()},
                {"text": self._button_preferences()},
                {"text": self._button_choose_ticker()},
                {"text": self._button_scan()},
            ],
            [{"text": self._button_help()}],
        ]
        return {
            "keyboard": keyboard,
            "resize_keyboard": True,
            "is_persistent": True,
        }

    def _ticker_keyboard(self) -> dict[str, Any]:
        ticker_buttons = self._ticker_buttons()
        keyboard: list[list[dict[str, str]]] = []
        for index in range(0, len(ticker_buttons), 3):
            keyboard.append([{"text": button} for button in ticker_buttons[index : index + 3]])
        keyboard.append([{"text": self._button_back()}])
        return {
            "keyboard": keyboard,
            "resize_keyboard": True,
            "is_persistent": True,
        }

    def _analysis_followup_keyboard(self, ticker: str) -> dict[str, Any]:
        ticker = ticker.upper()
        return {
            "inline_keyboard": [
                [
                    {"text": "Почему", "callback_data": self._callback_data("why", ticker)},
                    {"text": "Источники", "callback_data": self._callback_data("sources", ticker)},
                ],
                [
                    {"text": "События", "callback_data": self._callback_data("events", ticker)},
                    {"text": "Подачи SEC", "callback_data": self._callback_data("filings", ticker)},
                ],
                [
                    {"text": "Свежесть", "callback_data": self._callback_data("freshness", ticker)},
                    {"text": "Риск", "callback_data": self._callback_data("risk", ticker)},
                ],
                [
                    {"text": "Аудит", "callback_data": self._callback_data("audit", ticker)},
                    {"text": "Пересканировать", "callback_data": self._callback_data("rescan", ticker)},
                ],
                [
                    {"text": "Добавить в список", "callback_data": self._callback_data("watchlist_add", ticker)},
                    {"text": "Убрать из списка", "callback_data": self._callback_data("watchlist_remove", ticker)},
                ],
                [
                    {"text": "Заглушить", "callback_data": self._callback_data("mute", ticker)},
                ],
            ]
        }

    def _callback_data(self, action: str, ticker: str) -> str:
        return f"{action}:{ticker.upper()}"

    def _parse_callback_data(self, data: str) -> tuple[str | None, str | None]:
        if not data or ":" not in data:
            return None, None
        action, ticker = data.split(":", 1)
        action = action.strip()
        ticker = ticker.strip().upper()
        if not action or not ticker:
            return None, None
        return action, ticker
