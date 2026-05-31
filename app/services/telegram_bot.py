from __future__ import annotations

import asyncio
import logging
import json
from datetime import datetime, timezone
from typing import Any
from urllib import error as urlerror
from urllib import parse, request
from zoneinfo import ZoneInfo

from app.config import Settings, get_settings
from app.database import SessionLocal, init_db
from app.models import AnalysisSnapshot, SourceSnapshot, TelegramSubscription
from app.services.market_data import InvalidTickerError, normalize_ticker
from app.services.research_labels import research_label_to_russian
from app.services.history import build_snapshot_audit_entries, list_recent_snapshots
from app.services.runtime_budget import (
    RuntimeBudgetExceeded,
    consume_runtime_budget,
    runtime_budget_snapshot,
)
from app.services.scanner import analyze_ticker, scan_tickers


logger = logging.getLogger(__name__)


class TelegramBotService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._running = False
        self._offset = 0
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def enabled(self) -> bool:
        return bool(self.settings.telegram_enabled and self.settings.telegram_bot_token)

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
                    {"text": "Свежесть", "callback_data": self._callback_data("freshness", ticker)},
                ],
                [
                    {"text": "Риск", "callback_data": self._callback_data("risk", ticker)},
                    {"text": "Аудит", "callback_data": self._callback_data("audit", ticker)},
                ],
                [
                    {"text": "Пересканировать", "callback_data": self._callback_data("rescan", ticker)},
                    {"text": "Добавить в список", "callback_data": self._callback_data("watchlist_add", ticker)},
                ],
                [
                    {"text": "Убрать из списка", "callback_data": self._callback_data("watchlist_remove", ticker)},
                    {"text": "Заглушить", "callback_data": self._callback_data("mute", ticker)},
                ],
            ]
        }

    def _callback_data(self, action: str, ticker: str) -> str:
        return f"{action}:{ticker.upper()}"

    async def start(self) -> None:
        if not self.enabled:
            return

        init_db()
        self._running = True
        self._tasks = [asyncio.create_task(self._poll_loop(), name="telegram-poll-loop")]
        if self.settings.telegram_digest_interval_minutes > 0:
            self._tasks.append(
                asyncio.create_task(self._digest_loop(), name="telegram-digest-loop")
            )
        logger.info(
            "telegram_bot_started",
            extra={
                "component": "telegram",
                "digest_interval_minutes": self.settings.telegram_digest_interval_minutes,
                "poll_timeout_seconds": self.settings.telegram_poll_timeout_seconds,
                "task_count": len(self._tasks),
            },
        )

    async def stop(self) -> None:
        self._running = False
        tasks = list(self._tasks)
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        if tasks:
            logger.info(
                "telegram_bot_stopped",
                extra={"component": "telegram", "task_count": len(tasks)},
            )

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                updates = await asyncio.to_thread(
                    self._get_updates, self._offset, self.settings.telegram_poll_timeout_seconds
                )
                logger.debug(
                    "telegram_updates_received",
                    extra={"component": "telegram", "update_count": len(updates)},
                )
                for update in updates:
                    self._offset = max(self._offset, int(update["update_id"]) + 1)
                    await self._handle_update(update)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - resilience path
                logger.exception("Telegram polling loop failed")
                await asyncio.sleep(5)

    async def _digest_loop(self) -> None:
        interval = max(1, int(self.settings.telegram_digest_interval_minutes)) * 60
        while self._running:
            try:
                await asyncio.sleep(interval)
                await self._send_digest_to_active_subscribers()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - resilience path
                logger.exception("Telegram digest loop failed")

    async def _handle_update(self, update: dict[str, Any]) -> None:
        callback_query = update.get("callback_query")
        if callback_query:
            await self._handle_callback_query(callback_query)
            return

        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return

        text = (message.get("text") or "").strip()
        if not text:
            return

        if not self._chat_is_allowed(int(chat_id)):
            await self._send_message(int(chat_id), self._access_denied_text())
            return

        user = message.get("from") or {}
        username = user.get("username") or user.get("first_name") or user.get("last_name")

        action, args = self._resolve_action(text)

        if action == "start":
            is_first_use = self._subscription_for_chat(int(chat_id)) is None
            await self._send_message(
                int(chat_id),
                self._welcome_text(is_first_use=is_first_use),
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "help":
            await self._send_message(
                int(chat_id),
                self._help_text(),
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "ticker_menu":
            await self._send_message(
                int(chat_id),
                "Выбери тикер из списка ниже.",
                reply_markup=self._ticker_keyboard(),
            )
            return

        if action == "back":
            await self._send_message(
                int(chat_id),
                "Возвращаю главное меню.",
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "watchlist":
            await self._send_message(
                int(chat_id),
                self._watchlist_text(int(chat_id)),
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "preferences":
            await self._send_message(
                int(chat_id),
                self._preferences_text(int(chat_id)),
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "subscribe":
            is_first_use = self._subscription_for_chat(int(chat_id)) is None
            self._upsert_subscription(int(chat_id), username=username, active=True)
            subscribe_text = "Подписка активирована. Я буду отправлять тебе дайджесты и ответы на кнопки."
            if is_first_use:
                subscribe_text = f"{subscribe_text}\n\n{self._first_use_disclaimer()}"
            await self._send_message(
                int(chat_id),
                subscribe_text,
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "add":
            added, invalid = self._update_watchlist(
                int(chat_id),
                username=username,
                tickers=args,
                mode="add",
            )
            await self._send_message(
                int(chat_id),
                self._watchlist_update_text(
                    chat_id=int(chat_id),
                    mode="add",
                    changed_tickers=added,
                    invalid_tickers=invalid,
                ),
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "remove":
            removed, invalid = self._update_watchlist(
                int(chat_id),
                username=username,
                tickers=args,
                mode="remove",
            )
            await self._send_message(
                int(chat_id),
                self._watchlist_update_text(
                    chat_id=int(chat_id),
                    mode="remove",
                    changed_tickers=removed,
                    invalid_tickers=invalid,
                ),
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "unsubscribe":
            self._upsert_subscription(int(chat_id), username=username, active=False)
            await self._send_message(
                int(chat_id),
                "Подписка отключена.",
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "quiet":
            quiet_hours_start_minute, quiet_hours_end_minute, quiet_error = self._parse_quiet_hours(
                args[0] if args else ""
            )
            if quiet_error:
                await self._send_message(
                    int(chat_id),
                    quiet_error,
                    reply_markup=self._main_keyboard(),
                )
                return
            self._upsert_subscription(
                int(chat_id),
                username=username,
                active=True,
                preferences={
                    "quiet_hours_start_minute": quiet_hours_start_minute,
                    "quiet_hours_end_minute": quiet_hours_end_minute,
                },
            )
            await self._send_message(
                int(chat_id),
                self._preferences_text(
                    int(chat_id),
                    notice=(
                        "Quiet hours updated."
                        if quiet_hours_start_minute is not None
                        else "Quiet hours cleared."
                    ),
                ),
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "cap":
            cap_value, cap_error = self._parse_daily_cap(args[0] if args else "")
            if cap_error:
                await self._send_message(
                    int(chat_id),
                    cap_error,
                    reply_markup=self._main_keyboard(),
                )
                return
            self._upsert_subscription(
                int(chat_id),
                username=username,
                active=True,
                preferences={"max_alerts_per_day": cap_value},
            )
            await self._send_message(
                int(chat_id),
                self._preferences_text(
                    int(chat_id),
                    notice=("Daily cap updated." if cap_value is not None else "Daily cap cleared."),
                ),
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "market_hours":
            market_hours_only, market_error = self._parse_toggle(args[0] if args else "")
            if market_error:
                await self._send_message(
                    int(chat_id),
                    market_error,
                    reply_markup=self._main_keyboard(),
                )
                return
            self._upsert_subscription(
                int(chat_id),
                username=username,
                active=True,
                preferences={"market_hours_only": market_hours_only},
            )
            await self._send_message(
                int(chat_id),
                self._preferences_text(
                    int(chat_id),
                    notice=(
                        "Market-hours-only mode enabled."
                        if market_hours_only
                        else "Market-hours-only mode disabled."
                    ),
                ),
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "scan_mine":
            watchlist = self._watchlist_tickers(int(chat_id))
            if not watchlist:
                await self._send_message(
                    int(chat_id),
                    "Твой список тикеров пуст. Сначала добавь тикеры через /add AAPL.",
                    reply_markup=self._main_keyboard(),
                )
                return
            await self._send_message(
                int(chat_id),
                "Запускаю сканирование твоего списка...",
                reply_markup=self._main_keyboard(),
            )
            try:
                response = await asyncio.to_thread(scan_tickers, watchlist, None)
                await self._send_message(
                    int(chat_id),
                    self._scan_text(
                        response.results,
                        response.errors,
                        summary_notes=getattr(response.summary, "notes", None),
                    ),
                    reply_markup=self._main_keyboard(),
                )
            except Exception as exc:
                await self._send_message(
                    int(chat_id),
                    f"Не удалось выполнить сканирование твоего списка: {exc}",
                    reply_markup=self._main_keyboard(),
                )
            return

        if action == "status":
            await self._send_message(
                int(chat_id),
                self._status_text(int(chat_id)),
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "analyze":
            ticker = args[0] if args else None
            if not ticker:
                await self._send_message(
                    int(chat_id),
                    "Выбери кнопку с тикером для анализа.",
                    reply_markup=self._main_keyboard(),
                )
                return
            await self._send_message(int(chat_id), "Считаю анализ...", reply_markup=self._main_keyboard())
            try:
                analysis = await asyncio.to_thread(self._analyze_and_persist, ticker)
                await self._send_message(
                    int(chat_id),
                    self._analysis_text(analysis),
                    reply_markup=self._analysis_followup_keyboard(ticker),
                )
            except Exception as exc:
                await self._send_message(
                    int(chat_id),
                    f"Не удалось проанализировать {ticker}: {exc}",
                    reply_markup=self._main_keyboard(),
                )
            return

        if action == "scan":
            tickers = self._configured_tickers()
            if not tickers:
                await self._send_message(
                    int(chat_id),
                    "Список тикеров пуст. Проверь TELEGRAM_DEFAULT_TICKERS.",
                    reply_markup=self._main_keyboard(),
                )
                return
            await self._send_message(
                int(chat_id),
                "Запускаю сканирование рынка...",
                reply_markup=self._main_keyboard(),
            )
            try:
                response = await asyncio.to_thread(scan_tickers, tickers, None)
                await self._send_message(
                    int(chat_id),
                    self._scan_text(
                        response.results,
                        response.errors,
                        summary_notes=getattr(response.summary, "notes", None),
                    ),
                    reply_markup=self._main_keyboard(),
                )
            except Exception as exc:
                await self._send_message(
                    int(chat_id),
                    f"Не удалось выполнить сканирование: {exc}",
                    reply_markup=self._main_keyboard(),
                )
            return

        if action in {"why", "sources", "events", "freshness", "calendar", "risk", "audit"}:
            await self._handle_detail_command(
                int(chat_id),
                action=action,
                args=args,
                reply_markup=self._main_keyboard(),
            )
            return

        await self._send_message(
            int(chat_id),
            "Используй кнопки под сообщением.",
            reply_markup=self._main_keyboard(),
        )

    def _get_updates(self, offset: int, timeout_seconds: int) -> list[dict[str, Any]]:
        payload = {
            "timeout": timeout_seconds,
            "offset": offset,
            "allowed_updates": json.dumps(["message", "edited_message", "callback_query"]),
        }
        data = parse.urlencode(payload).encode("utf-8")
        response = self._request_json("getUpdates", data)
        if not response.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {response}")
        result = response.get("result", [])
        return result if isinstance(result, list) else []

    async def _handle_callback_query(self, callback_query: dict[str, Any]) -> None:
        callback_id = callback_query.get("id")
        data = str(callback_query.get("data") or "")
        message = callback_query.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")

        if callback_id:
            await self._answer_callback_query(str(callback_id))
        if chat_id is None:
            return
        if not self._chat_is_allowed(int(chat_id)):
            await self._send_message(int(chat_id), self._access_denied_text())
            return

        action, ticker = self._parse_callback_data(data)
        if not action or not ticker:
            await self._send_message(int(chat_id), "Не удалось распознать кнопку.", reply_markup=self._main_keyboard())
            return

        username = (callback_query.get("from") or {}).get("username")
        await self._handle_followup_action(
            int(chat_id),
            action=action,
            ticker=ticker,
            username=username,
        )

    async def _handle_followup_action(
        self,
        chat_id: int,
        *,
        action: str,
        ticker: str,
        username: str | None,
    ) -> None:
        followup_keyboard = self._analysis_followup_keyboard(ticker)

        if action in {"why", "sources", "events", "freshness", "audit"}:
            await self._handle_detail_command(
                chat_id,
                action=action,
                args=[ticker],
                reply_markup=followup_keyboard,
            )
            return

        if action == "risk":
            await self._send_message(chat_id, self._risk_text(ticker), reply_markup=followup_keyboard)
            return

        if action == "rescan":
            await self._send_message(
                chat_id,
                f"Пересчитываю {ticker.upper()}...",
                reply_markup=followup_keyboard,
            )
            try:
                analysis = await asyncio.to_thread(self._analyze_and_persist, ticker)
                await self._send_message(
                    chat_id,
                    self._analysis_text(analysis),
                    reply_markup=followup_keyboard,
                )
            except Exception as exc:
                await self._send_message(
                    chat_id,
                    f"Не удалось пересчитать {ticker.upper()}: {exc}",
                    reply_markup=followup_keyboard,
                )
            return

        if action in {"watchlist_add", "watchlist_remove", "mute"}:
            mode = "add" if action == "watchlist_add" else "remove"
            changed, invalid = self._update_watchlist(
                chat_id,
                username=username,
                tickers=[ticker],
                mode=mode,
            )
            notice = self._watchlist_update_text(
                chat_id=chat_id,
                mode=mode,
                changed_tickers=changed,
                invalid_tickers=invalid,
            )
            if action == "mute":
                notice = f"{notice}\nЗаглушение реализовано через снятие тикера с watchlist."
            await self._send_message(chat_id, notice, reply_markup=followup_keyboard)
            return

        await self._send_message(
            chat_id,
            "Неизвестное действие кнопки.",
            reply_markup=followup_keyboard,
        )

    async def _send_digest_to_active_subscribers(
        self,
        digest_mode: str | None = None,
        reference_time: datetime | None = None,
    ) -> None:
        subscribers = self._active_subscribers()
        if not subscribers:
            return

        mode = digest_mode or self._scheduled_digest_mode(reference_time)

        for subscriber in subscribers:
            skip_reason = self._digest_skip_reason(subscriber)
            if skip_reason:
                logger.info(
                    "telegram_digest_skipped",
                    extra={
                        "component": "telegram",
                        "chat_id": subscriber.chat_id,
                        "reason": skip_reason,
                    },
                )
                continue
            tickers = self._watchlist_tickers_for_subscription(subscriber)
            if not tickers:
                tickers = self._configured_tickers()
            if not tickers:
                continue

            response = await asyncio.to_thread(scan_tickers, tickers, None)
            digest = self._digest_text(
                response.results,
                response.errors,
                summary_notes=getattr(response.summary, "notes", None),
                digest_mode=mode,
            )
            logger.info(
                "telegram_digest_ready",
                extra={
                    "component": "telegram",
                    "subscriber_count": len(subscribers),
                    "chat_id": subscriber.chat_id,
                    "ticker_count": len(tickers),
                    "result_count": len(response.results),
                    "error_count": len(response.errors),
                },
            )
            await self._send_message(subscriber.chat_id, digest)
            self._mark_last_alert(subscriber.id)

    def _analyze_and_persist(self, ticker: str) -> Any:
        db = SessionLocal()
        try:
            return analyze_ticker(ticker, db=db, use_ai_explanation=False)
        finally:
            db.close()

    async def _handle_detail_command(
        self,
        chat_id: int,
        *,
        action: str,
        args: list[str],
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        ticker = self._detail_ticker(args)
        if action == "calendar":
            calendar_ticker = None if not args or args[0].strip().lower() in {"today", "сегодня", "now"} else ticker
            await self._send_message(
                chat_id,
                self._calendar_text(calendar_ticker),
                reply_markup=reply_markup,
            )
            return
        if action == "audit":
            await self._send_message(chat_id, self._audit_text(ticker), reply_markup=reply_markup)
            return
        if ticker is None:
            await self._send_message(
                chat_id,
                f"Укажи тикер для /{action}. Например: /{action} AAPL",
                reply_markup=reply_markup,
            )
            return
        builders = {
            "why": self._why_text,
            "sources": self._sources_text,
            "events": self._events_text,
            "freshness": self._freshness_text,
            "risk": self._risk_text,
        }
        builder = builders[action]
        await self._send_message(chat_id, builder(ticker), reply_markup=reply_markup)

    async def _answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        response = self._request_json(
            "answerCallbackQuery",
            parse.urlencode(payload).encode("utf-8"),
        )
        if not response.get("ok"):
            raise RuntimeError(f"Telegram answerCallbackQuery failed: {response}")

    def _parse_callback_data(self, data: str) -> tuple[str | None, str | None]:
        if not data or ":" not in data:
            return None, None
        action, ticker = data.split(":", 1)
        action = action.strip()
        ticker = ticker.strip().upper()
        if not action or not ticker:
            return None, None
        return action, ticker

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

    def _latest_analysis_snapshot(self, ticker: str) -> AnalysisSnapshot | None:
        db = SessionLocal()
        try:
            return (
                db.query(AnalysisSnapshot)
                .filter(AnalysisSnapshot.ticker == ticker.upper())
                .order_by(AnalysisSnapshot.created_at.desc(), AnalysisSnapshot.id.desc())
                .first()
            )
        finally:
            db.close()

    def _latest_source_snapshot(self, ticker: str) -> SourceSnapshot | None:
        db = SessionLocal()
        try:
            return (
                db.query(SourceSnapshot)
                .filter(SourceSnapshot.ticker == ticker.upper())
                .order_by(SourceSnapshot.fetched_at.desc(), SourceSnapshot.id.desc())
                .first()
            )
        finally:
            db.close()

    def _active_subscribers(self) -> list[TelegramSubscription]:
        db = SessionLocal()
        try:
            subscribers = (
                db.query(TelegramSubscription)
                .filter(TelegramSubscription.is_active.is_(True))
                .order_by(TelegramSubscription.created_at.asc())
                .all()
            )
            return [sub for sub in subscribers if self._chat_is_allowed(sub.chat_id)]
        finally:
            db.close()

    def _subscription_for_chat(self, chat_id: int) -> TelegramSubscription | None:
        db = SessionLocal()
        try:
            return (
                db.query(TelegramSubscription)
                .filter(TelegramSubscription.chat_id == chat_id)
                .one_or_none()
            )
        finally:
            db.close()

    def _upsert_subscription(
        self,
        chat_id: int,
        username: str | None,
        active: bool,
        watchlist_symbols: list[str] | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> None:
        db = SessionLocal()
        try:
            sub = (
                db.query(TelegramSubscription)
                .filter(TelegramSubscription.chat_id == chat_id)
                .one_or_none()
            )
            if sub is None:
                sub = TelegramSubscription(
                    chat_id=chat_id,
                    username=username,
                    is_active=active,
                    watchlist_symbols=watchlist_symbols or [],
                    **(preferences or {}),
                )
                db.add(sub)
            else:
                sub.username = username or sub.username
                sub.is_active = active
                if watchlist_symbols is not None:
                    sub.watchlist_symbols = watchlist_symbols
                for field_name, field_value in (preferences or {}).items():
                    setattr(sub, field_name, field_value)
            db.commit()
            logger.info(
                "telegram_subscription_updated",
                extra={
                    "component": "telegram",
                    "chat_id": chat_id,
                    "active": active,
                    "watchlist_size": len(sub.watchlist_symbols or []),
                },
            )
        except Exception:
            db.rollback()
            logger.exception(
                "telegram_subscription_update_failed",
                extra={"component": "telegram", "chat_id": chat_id},
            )
        finally:
            db.close()

    def _watchlist_tickers_for_subscription(self, subscription: TelegramSubscription) -> list[str]:
        symbols = subscription.watchlist_symbols or []
        normalized, _ = self._normalize_watchlist_symbols(symbols)
        return normalized

    def _watchlist_tickers(self, chat_id: int) -> list[str]:
        sub = self._subscription_for_chat(chat_id)
        if sub is None:
            return []
        return self._watchlist_tickers_for_subscription(sub)

    def _mark_last_alert(self, subscription_id: int) -> None:
        db = SessionLocal()
        try:
            sub = db.get(TelegramSubscription, subscription_id)
            if sub is None:
                return
            now = datetime.now(timezone.utc)
            today = now.date().isoformat()
            if sub.daily_alert_date != today:
                sub.daily_alert_date = today
                sub.daily_alert_count = 0
            sub.daily_alert_count = (sub.daily_alert_count or 0) + 1
            sub.last_alert_at = now
            db.commit()
            logger.debug(
                "telegram_alert_timestamp_updated",
                extra={"component": "telegram", "subscription_id": subscription_id},
            )
        except Exception:
            db.rollback()
            logger.exception(
                "telegram_alert_timestamp_update_failed",
                extra={"component": "telegram", "subscription_id": subscription_id},
            )
        finally:
            db.close()

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

    def _preferences_summary_text(self, subscription: TelegramSubscription) -> str:
        quiet_hours = self._format_quiet_hours(subscription)
        max_alerts = getattr(subscription, "max_alerts_per_day", None)
        daily_cap = "не ограничен" if max_alerts is None else str(max_alerts)
        market_hours_only = "да" if getattr(subscription, "market_hours_only", False) else "нет"
        today_key = self._current_day_key()
        daily_alert_date = getattr(subscription, "daily_alert_date", None)
        daily_alert_count = getattr(subscription, "daily_alert_count", 0) or 0
        current_count = daily_alert_count if daily_alert_date == today_key else 0
        return (
            "Настройки уведомлений:\n"
            f"• Quiet hours: {quiet_hours}\n"
            f"• Daily cap: {daily_cap}\n"
            f"• Market-hours-only: {market_hours_only}\n"
            f"• Сегодня отправлено: {current_count}"
        )

    def _preferences_text(self, chat_id: int, notice: str | None = None) -> str:
        sub = self._subscription_for_chat(chat_id)
        if sub is None:
            return (
                "Подписка не найдена. Используй /start, чтобы создать её, "
                "а затем /quiet, /cap и /markethours для настройки уведомлений."
            )

        lines = [self._preferences_summary_text(sub)]
        if notice:
            lines.extend(["", notice])
        lines.extend(
            [
                "",
                "Команды:",
                "• /quiet 22:00-07:00 или /quiet off",
                "• /cap 3 или /cap off",
                "• /markethours on или /markethours off",
            ]
        )
        return "\n".join(lines)

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

    def _parse_toggle(self, value: str) -> tuple[bool, str | None]:
        raw = value.strip().lower()
        if raw in {"on", "1", "true", "yes"}:
            return True, None
        if raw in {"off", "0", "false", "no"}:
            return False, None
        return False, "Use /markethours on or /markethours off."

    def _is_market_session_open(self, moment: datetime | None = None) -> bool:
        reference = moment or datetime.now(timezone.utc)
        local_reference = reference.astimezone(ZoneInfo("America/New_York"))
        if local_reference.weekday() >= 5:
            return False
        current_minutes = local_reference.hour * 60 + local_reference.minute
        return 9 * 60 + 30 <= current_minutes < 16 * 60

    def _digest_skip_reason(self, subscription: TelegramSubscription) -> str | None:
        now = datetime.now(timezone.utc)
        if self._quiet_hours_active(subscription, now):
            return "quiet_hours"
        if getattr(subscription, "market_hours_only", False) and not self._is_market_session_open(now):
            return "market_hours_only"
        max_alerts = getattr(subscription, "max_alerts_per_day", None)
        if max_alerts is not None:
            today_key = self._current_day_key(now)
            current_count = (
                subscription.daily_alert_count if subscription.daily_alert_date == today_key else 0
            )
            if current_count >= max_alerts:
                return "daily_cap"
        return None

    def _quiet_hours_active(self, subscription: TelegramSubscription, moment: datetime | None = None) -> bool:
        start = getattr(subscription, "quiet_hours_start_minute", None)
        end = getattr(subscription, "quiet_hours_end_minute", None)
        if start is None or end is None:
            return False
        reference = moment or datetime.now(timezone.utc)
        minute = reference.astimezone(timezone.utc).hour * 60 + reference.astimezone(timezone.utc).minute
        if start < end:
            return start <= minute < end
        return minute >= start or minute < end

    def _status_text(self, chat_id: int) -> str:
        if not self._chat_is_allowed(chat_id):
            return self._access_denied_text()

        db = SessionLocal()
        try:
            sub = (
                db.query(TelegramSubscription)
                .filter(TelegramSubscription.chat_id == chat_id)
                .one_or_none()
            )
            if sub is None:
                return "Подписка не найдена. Используй /start."
            last_alert = sub.last_alert_at.isoformat() if sub.last_alert_at else "ещё не отправлял"
            watchlist = self._watchlist_tickers_for_subscription(sub)
            watchlist_text = ", ".join(watchlist) if watchlist else "пусто"
            send_budget = runtime_budget_snapshot(
                "telegram_sends",
                getattr(self.settings, "telegram_send_budget", None),
            )
            if send_budget.limit is None:
                budget_text = "не ограничен"
            else:
                budget_text = f"{send_budget.remaining}/{send_budget.limit} осталось"
            return (
                f"Подписка активна: {'да' if sub.is_active else 'нет'}\n"
                f"Последняя рассылка: {last_alert}\n"
                f"Частота рассылки: {self.settings.telegram_digest_interval_minutes} мин.\n"
                f"Telegram send budget: {budget_text}\n"
                f"Твой список: {watchlist_text}\n"
                f"{self._preferences_summary_text(sub)}"
            )
        finally:
            db.close()

    def live_check(self) -> dict[str, Any]:
        if not self.settings.telegram_bot_token:
            raise RuntimeError("Telegram bot token is missing.")
        if not self.settings.telegram_enabled:
            raise RuntimeError("Telegram bot is disabled.")

        me = self._request_json("getMe")
        if not me.get("ok"):
            raise RuntimeError(f"Telegram getMe failed: {me}")

        result = me.get("result") or {}
        if not isinstance(result, dict):
            raise RuntimeError(f"Telegram getMe returned unexpected payload: {me}")

        return {
            "status": "ok",
            "bot_id": result.get("id"),
            "username": result.get("username"),
            "first_name": result.get("first_name"),
            "can_join_groups": result.get("can_join_groups"),
            "can_read_all_group_messages": result.get("can_read_all_group_messages"),
            "supports_inline_queries": result.get("supports_inline_queries"),
        }

    def _configured_tickers(self) -> list[str]:
        raw = self.settings.telegram_default_tickers
        tickers = [item.strip().upper() for item in raw.split(",")]
        return [ticker for ticker in tickers if ticker]

    def _resolve_action(self, text: str) -> tuple[str, list[str]]:
        normalized = text.strip()
        lowered = normalized.lower()

        if lowered in {"/start", "start"}:
            return "start", []
        if lowered in {"/help", "help", self._button_help().lower()}:
            return "help", []
        if lowered in {"/subscribe", "subscribe", self._button_subscribe().lower()}:
            return "subscribe", []
        if lowered in {"/unsubscribe", "unsubscribe", self._button_unsubscribe().lower()}:
            return "unsubscribe", []
        if lowered in {"/status", "status", self._button_status().lower()}:
            return "status", []
        if lowered in {"/watchlist", "watchlist", self._button_watchlist().lower()}:
            return "watchlist", []
        if lowered in {"/prefs", "prefs", "/preferences", "preferences", self._button_preferences().lower()}:
            return "preferences", []
        if lowered in {self._button_choose_ticker().lower()}:
            return "ticker_menu", []
        if lowered in {self._button_back().lower()}:
            return "back", []
        if lowered in {"/scan mine", "scan mine"}:
            return "scan_mine", []
        if lowered in {"/scan", "scan", self._button_scan().lower()}:
            return "scan", []

        for prefix, action in (
            ("/why ", "why"),
            ("why ", "why"),
            ("/sources ", "sources"),
            ("sources ", "sources"),
            ("/events ", "events"),
            ("events ", "events"),
            ("/freshness ", "freshness"),
            ("freshness ", "freshness"),
            ("/calendar ", "calendar"),
            ("calendar ", "calendar"),
            ("/risk ", "risk"),
            ("risk ", "risk"),
            ("/audit ", "audit"),
            ("audit ", "audit"),
        ):
            if lowered.startswith(prefix):
                parts = normalized.split(maxsplit=1)
                if len(parts) == 2:
                    return action, [parts[1].strip()]
                return action, []

        if lowered in {"/why", "why"}:
            return "why", []
        if lowered in {"/sources", "sources"}:
            return "sources", []
        if lowered in {"/events", "events"}:
            return "events", []
        if lowered in {"/freshness", "freshness"}:
            return "freshness", []
        if lowered in {"/calendar", "calendar"}:
            return "calendar", []
        if lowered in {"/risk", "risk"}:
            return "risk", []
        if lowered in {"/audit", "audit"}:
            return "audit", []

        if lowered.startswith("/quiet ") or lowered.startswith("quiet "):
            parts = normalized.split(maxsplit=1)
            if len(parts) == 2:
                return "quiet", [parts[1].strip()]
            return "quiet", []
        if lowered in {"/quiet", "quiet"}:
            return "preferences", []

        if lowered.startswith("/cap ") or lowered.startswith("cap "):
            parts = normalized.split(maxsplit=1)
            if len(parts) == 2:
                return "cap", [parts[1].strip()]
            return "cap", []
        if lowered in {"/cap", "cap"}:
            return "preferences", []

        if lowered.startswith("/markethours ") or lowered.startswith("/market-hours ") or lowered.startswith("markethours "):
            parts = normalized.split(maxsplit=1)
            if len(parts) == 2:
                return "market_hours", [parts[1].strip()]
            return "market_hours", []
        if lowered in {"/markethours", "markethours", "/market-hours", "market-hours"}:
            return "preferences", []

        if lowered.startswith("/add ") or lowered.startswith("add "):
            parts = normalized.split(maxsplit=1)
            if len(parts) == 2:
                return "add", self._parse_tickers(parts[1].split())
            return "add", []
        if lowered.startswith("/remove ") or lowered.startswith("remove "):
            parts = normalized.split(maxsplit=1)
            if len(parts) == 2:
                return "remove", self._parse_tickers(parts[1].split())
            return "remove", []

        if lowered.startswith("/analyze "):
            ticker = normalized.split(maxsplit=1)[1].strip().upper()
            return "analyze", [ticker] if ticker else []
        if lowered.startswith("анализ "):
            ticker = normalized.split(maxsplit=1)[1].strip().upper()
            return "analyze", [ticker] if ticker else []

        if lowered.startswith("/"):
            parts = normalized.split(maxsplit=1)
            if len(parts) == 2:
                return "analyze", [parts[1].strip().upper()]

        for ticker_button in self._ticker_buttons():
            if normalized == ticker_button:
                ticker = ticker_button.removeprefix("Анализ ").strip().upper()
                return "analyze", [ticker]

        return "unknown", []

    def _help_text(self) -> str:
        return (
            "Нажимай кнопки под сообщением.\n"
            "Доступно:\n"
            "• подписка и отписка\n"
            "• статус подписки\n"
            "• просмотр и редактирование личного списка тикеров\n"
            "• просмотр и изменение настроек уведомлений\n"
            "• анализ отдельных тикеров\n"
            "• сканирование рынка по списку из настроек или по команде /scan mine\n"
            "• source-backed детали: /why, /sources, /events, /freshness, /calendar, /risk, /audit\n"
        )

    def _welcome_text(self, is_first_use: bool = False) -> str:
        text = (
            "Привет. Я бот для анализа акций.\n"
            "Нажимай кнопки под сообщением, чтобы не вводить команды вручную."
        )
        if is_first_use:
            text = f"{text}\n\n{self._first_use_disclaimer()}"
        return text

    def _analysis_text(self, analysis: Any) -> str:
        recommendation = self._translate_recommendation(analysis.recommendation)
        lines = [
            f"{analysis.ticker}: {recommendation}",
            f"Цена: {analysis.price:.2f} {analysis.currency or ''}".strip(),
            f"Итоговая оценка: {analysis.scores.final_score:.2f}",
            f"Импульс: {analysis.scores.momentum_score:.2f}",
            f"Оценка стоимости: {analysis.scores.valuation_score:.2f}",
            f"Риск: {analysis.scores.risk_score:.2f}",
            f"Кратко: {self._translate_text(analysis.short_reason)}",
            f"Комментарий: {self._translate_text(analysis.explanation)}",
        ]
        operation_notes = getattr(analysis, "operation_notes", None) or []
        if operation_notes:
            lines.extend(["", "Операционные заметки:"])
            lines.extend(f"- {self._translate_text(note)}" for note in operation_notes)
        disclaimer = self._analysis_disclaimer(analysis)
        if disclaimer:
            lines.extend(["", disclaimer])
        return self._trim_message("\n".join(lines))

    def _scan_text(
        self,
        results: list[Any],
        errors: list[Any],
        *,
        summary_notes: list[str] | None = None,
    ) -> str:
        if not results and not errors:
            return "Ничего не найдено."

        lines = ["Результаты скана:"]
        for item in results[:5]:
            recommendation = self._translate_recommendation(item.recommendation)
            lines.append(
                f"{item.ticker}: {recommendation} | оценка {item.final_score:.2f} | цена {item.price:.2f}"
            )
            lines.append(f"  {self._translate_text(item.short_reason)}")
        if errors:
            lines.append("Ошибки:")
            for item in errors[:5]:
                lines.append(f"- {item.ticker}: {item.error}")
        if summary_notes:
            lines.extend(["", "Операционные заметки:"])
            lines.extend(f"- {self._translate_text(note)}" for note in summary_notes)
        disclaimer = self._scan_disclaimer(results)
        if disclaimer:
            lines.extend(["", disclaimer])
        return self._trim_message("\n".join(lines))

    def _why_text(self, ticker: str) -> str:
        snapshot = self._latest_analysis_snapshot(ticker)
        if snapshot is None:
            return (
                f"По {ticker.upper()} ещё нет сохранённой аналитики.\n"
                "Сначала запусти /analyze, чтобы появился source-backed контекст."
            )

        payload = snapshot.payload or {}
        scores = payload.get("scores") or {}
        source_provenance = payload.get("source_provenance") or {}
        lines = [
            f"{ticker.upper()}: почему это выглядит так",
            f"Последний анализ: {self._format_dt(snapshot.created_at)}",
            f"Рекомендация: {self._translate_recommendation(str(payload.get('recommendation') or snapshot.recommendation))}",
            f"Итоговая оценка: {scores.get('final_score', snapshot.final_score):.2f}",
        ]
        short_reason = payload.get("short_reason")
        if short_reason:
            lines.append(f"Кратко: {self._translate_text(str(short_reason))}")
        explanation = payload.get("explanation")
        if explanation:
            lines.extend(["", "Объяснение:", self._translate_text(str(explanation))])
        if source_provenance:
            lines.extend(
                [
                    "",
                    "Source-backed context:",
                    f"• provider: {source_provenance.get('provider_name')}",
                    f"• source tier: {source_provenance.get('source_tier')}",
                    f"• fetched_at: {source_provenance.get('fetched_at') or payload.get('generated_at')}",
                ]
            )
        return self._trim_message("\n".join(lines))

    def _sources_text(self, ticker: str) -> str:
        snapshot = self._latest_analysis_snapshot(ticker)
        source_snapshot = self._latest_source_snapshot(ticker)
        if snapshot is None and source_snapshot is None:
            return (
                f"По {ticker.upper()} нет сохранённых источников.\n"
                "Сначала запусти /analyze или /scan, чтобы сохранить source provenance."
            )

        lines = [f"{ticker.upper()}: источники и provenance"]
        if snapshot is not None:
            provenance = (snapshot.payload or {}).get("source_provenance") or {}
            data_quality = (snapshot.payload or {}).get("data_quality") or {}
            lines.extend(
                [
                    f"Последний анализ: {self._format_dt(snapshot.created_at)}",
                    f"Provider: {provenance.get('provider_name') or 'unknown'}",
                    f"Tier: {provenance.get('source_tier') or 'unknown'}",
                    f"URL: {provenance.get('source_url') or 'n/a'}",
                    f"Confidence: {data_quality.get('confidence', 1.0):.2f}",
                    f"Data quality: {data_quality.get('summary') or 'ok'}",
                ]
            )
        if source_snapshot is not None:
            lines.extend(
                [
                    "",
                    "Raw source snapshot:",
                    f"• provider: {source_snapshot.provider_name}",
                    f"• source tier: {source_snapshot.source_tier or 'unknown'}",
                    f"• fetched_at: {self._format_dt(source_snapshot.fetched_at)}",
                    f"• published_at: {self._format_dt(source_snapshot.published_at)}",
                    f"• observed_at: {self._format_dt(source_snapshot.observed_at)}",
                    f"• content hash: {source_snapshot.content_hash}",
                ]
            )
        return self._trim_message("\n".join(lines))

    def _events_text(self, ticker: str) -> str:
        snapshot = self._latest_analysis_snapshot(ticker)
        if snapshot is None:
            return (
                f"По {ticker.upper()} нет сохранённой аналитики для event context.\n"
                "Запусти /analyze, чтобы появился свежий риск и session context."
            )

        payload = snapshot.payload or {}
        market_session = payload.get("market_session") or {}
        data_quality = payload.get("data_quality") or {}
        lines = [
            f"{ticker.upper()}: event and session context",
            f"Session: {market_session.get('status') or 'unknown'}",
            f"Market open: {self._format_dt(market_session.get('market_open_at'))}",
            f"Market close: {self._format_dt(market_session.get('market_close_at'))}",
            f"Freshness: {market_session.get('freshness_state') or 'fresh'}",
        ]
        freshness_note = market_session.get("freshness_note")
        if freshness_note:
            lines.append(f"Note: {self._translate_text(str(freshness_note))}")
        if data_quality.get("summary"):
            lines.append(f"Data quality: {self._translate_text(str(data_quality.get('summary')))}")
        lines.extend(
            [
                "",
                "Breaking news / filing calendar is not wired yet; this view shows the latest stored market session context.",
            ]
        )
        return self._trim_message("\n".join(lines))

    def _freshness_text(self, ticker: str) -> str:
        snapshot = self._latest_analysis_snapshot(ticker)
        if snapshot is None:
            return (
                f"По {ticker.upper()} нет сохранённой аналитики.\n"
                "Сначала запусти /analyze, чтобы получить freshness context."
            )

        payload = snapshot.payload or {}
        source_provenance = payload.get("source_provenance") or {}
        market_session = payload.get("market_session") or {}
        data_quality = payload.get("data_quality") or {}
        lines = [
            f"{ticker.upper()}: freshness",
            f"Latest analysis: {self._format_dt(snapshot.created_at)}",
            f"Source fetched_at: {self._format_dt(source_provenance.get('fetched_at'))}",
            f"Source published_at: {self._format_dt(source_provenance.get('published_at'))}",
            f"Market session: {market_session.get('status') or 'unknown'}",
            f"Freshness state: {market_session.get('freshness_state') or 'fresh'}",
            f"Signal confidence: {data_quality.get('confidence', 1.0):.2f}",
        ]
        if market_session.get("freshness_note"):
            lines.append(f"Note: {self._translate_text(str(market_session.get('freshness_note')))}")
        return self._trim_message("\n".join(lines))

    def _risk_text(self, ticker: str) -> str:
        snapshot = self._latest_analysis_snapshot(ticker)
        if snapshot is None:
            return (
                f"По {ticker.upper()} нет сохранённой аналитики.\n"
                "Сначала запусти /analyze, чтобы увидеть risk context."
            )

        payload = snapshot.payload or {}
        scores = payload.get("scores") or {}
        market_session = payload.get("market_session") or {}
        data_quality = payload.get("data_quality") or {}
        explanation = payload.get("explanation") or ""
        lines = [
            f"{ticker.upper()}: risk context",
            f"Risk score: {scores.get('risk_score', 0.0):.2f}",
            f"Final score: {scores.get('final_score', snapshot.final_score):.2f}",
            f"Recommendation: {self._translate_recommendation(str(payload.get('recommendation') or snapshot.recommendation))}",
            f"Data confidence: {data_quality.get('confidence', 1.0):.2f}",
            f"Session state: {market_session.get('status') or 'unknown'}",
        ]
        if payload.get("short_reason"):
            lines.append(f"Short reason: {self._translate_text(str(payload.get('short_reason')))}")
        if explanation:
            lines.extend(["", self._translate_text(str(explanation))])
        return self._trim_message("\n".join(lines))

    def _calendar_text(self, ticker: str | None) -> str:
        if ticker:
            snapshot = self._latest_analysis_snapshot(ticker)
            if snapshot is None:
                return (
                    f"По {ticker.upper()} нет сохранённой аналитики.\n"
                    "Запусти /analyze, чтобы получить market session context."
                )
            payload = snapshot.payload or {}
            market_session = payload.get("market_session") or {}
            return self._trim_message(
                "\n".join(
                    [
                        f"{ticker.upper()}: calendar context",
                        f"Session: {market_session.get('status') or 'unknown'}",
                        f"Timezone: {market_session.get('timezone') or 'n/a'}",
                        f"Open: {self._format_dt(market_session.get('market_open_at'))}",
                        f"Close: {self._format_dt(market_session.get('market_close_at'))}",
                        "",
                        "This view uses the latest stored market session snapshot, not a live exchange calendar feed.",
                    ]
                )
            )

        now = datetime.now(timezone.utc)
        local_now = now.astimezone(ZoneInfo("America/New_York"))
        market_open = local_now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = local_now.replace(hour=16, minute=0, second=0, microsecond=0)
        session = "weekend" if local_now.weekday() >= 5 else "open" if market_open <= local_now < market_close else "closed"
        lines = [
            "Today: U.S. equity session baseline",
            f"Reference time: {local_now.isoformat()}",
            f"Session: {session}",
            f"Regular open: {market_open.isoformat()}",
            f"Regular close: {market_close.isoformat()}",
            "",
            "Use /calendar AAPL to see the latest stored market session for a ticker.",
        ]
        return self._trim_message("\n".join(lines))

    def _audit_text(self, ticker: str | None) -> str:
        if not ticker:
            return "Укажи тикер для /audit. Например: /audit AAPL"

        db = SessionLocal()
        try:
            snapshots = list_recent_snapshots(db, limit=3, ticker=ticker)
        finally:
            db.close()

        if not snapshots:
            return (
                f"По {ticker.upper()} нет сохранённых аудиторских данных.\n"
                "Сначала запусти /analyze, чтобы появились snapshot history и provenance."
            )

        lines = [f"{ticker.upper()}: audit trail"]
        for index, entry in enumerate(build_snapshot_audit_entries(snapshots), start=1):
            snapshot = entry.snapshot
            payload = snapshot.payload or {}
            provenance = payload.get("source_provenance") or {}
            data_quality = payload.get("data_quality") or {}
            market_session = payload.get("market_session") or {}
            lines.extend(
                [
                    f"{index}. {self._format_dt(snapshot.created_at)}",
                    f"   score={snapshot.final_score:.2f} recommendation={snapshot.recommendation}",
                    f"   provider={provenance.get('provider_name') or 'unknown'} tier={provenance.get('source_tier') or 'unknown'}",
                    f"   confidence={data_quality.get('confidence', 1.0):.2f} session={market_session.get('status') or 'unknown'}",
                ]
            )
            if payload.get("short_reason"):
                lines.append(f"   reason={self._translate_text(str(payload.get('short_reason')))}")
            if entry.changes:
                lines.append("   changes vs older snapshot:")
                lines.extend(f"   - {self._translate_text(change)}" for change in entry.changes)

        if len(snapshots) >= 2:
            latest, previous = snapshots[0], snapshots[1]
            delta = latest.final_score - previous.final_score
            lines.extend(["", f"Latest score delta vs previous: {delta:+.2f}"])
            latest_payload = latest.payload or {}
            previous_payload = previous.payload or {}
            latest_quality = latest_payload.get("data_quality") or {}
            previous_quality = previous_payload.get("data_quality") or {}
            latest_session = latest_payload.get("market_session") or {}
            previous_session = previous_payload.get("market_session") or {}
            if latest_quality.get("source_disagreed") or previous_quality.get("source_disagreed"):
                lines.append("Source disagreement flagged in one of the latest snapshots.")
            lines.append(
                "Freshness delta: "
                f"{previous_session.get('freshness_state') or 'unknown'} -> "
                f"{latest_session.get('freshness_state') or 'unknown'}"
            )
            lines.append(
                "Provenance delta: "
                f"{(previous_payload.get('source_provenance') or {}).get('provider_name') or 'unknown'} -> "
                f"{(latest_payload.get('source_provenance') or {}).get('provider_name') or 'unknown'}"
            )
            lines.append(
                "Recommendation delta: "
                f"{previous.recommendation} -> {latest.recommendation}"
            )

        return self._trim_message("\n".join(lines))

    def _digest_text(
        self,
        results: list[Any],
        errors: list[Any],
        *,
        summary_notes: list[str] | None = None,
        digest_mode: str = "market_open",
    ) -> str:
        limit = 5 if digest_mode == "weekly_review" else 3
        top = results[:limit]
        if not top and not errors:
            return "Дайджест пуст: данных для отчёта нет."

        lines = [self._digest_heading(digest_mode)]
        digest_note = self._digest_mode_note(digest_mode)
        if digest_note:
            lines.extend(["", digest_note])
        for item in top:
            recommendation = self._translate_recommendation(item.recommendation)
            lines.append(
                f"{item.ticker}: {recommendation}, оценка {item.final_score:.2f}, {self._translate_text(item.short_reason)}"
            )
        if errors:
            lines.append("Ошибки скана:")
            for item in errors[:3]:
                lines.append(f"- {item.ticker}: {item.error}")
        if summary_notes:
            lines.extend(["", "Операционные заметки:"])
            lines.extend(f"- {self._translate_text(note)}" for note in summary_notes)
        disclaimer = self._scan_disclaimer(top)
        if disclaimer:
            lines.extend(["", disclaimer])
        return self._trim_message("\n".join(lines))

    def _digest_heading(self, digest_mode: str) -> str:
        headings = {
            "pre_market": "Утренний pre-market дайджест:",
            "market_open": "Market-open дайджест:",
            "midday": "Midday check дайджест:",
            "close": "Close summary дайджест:",
            "after_hours": "After-hours news дайджест:",
            "weekly_review": "Weekly watchlist review:",
        }
        return headings.get(digest_mode, "Телеграм-дайджест рынка:")

    def _digest_mode_note(self, digest_mode: str) -> str | None:
        notes = {
            "pre_market": "До открытия рынка показываю свежий pre-market контекст и то, что может измениться к open.",
            "market_open": "На открытии фокус на первых реакциях и gap risk.",
            "midday": "Полуденный check помогает увидеть, что поменялось после открытия.",
            "close": "Close summary подводит итог регулярной сессии.",
            "after_hours": "After-hours дайджест выделяет то, что появилось после закрытия и может повлиять на завтрашний open.",
            "weekly_review": "Weekly review собирает контекст по сохранённым watchlist-тикерам и недельной динамике.",
        }
        return notes.get(digest_mode)

    def _scheduled_digest_mode(self, reference_time: datetime | None = None) -> str:
        reference = reference_time or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        local_reference = reference.astimezone(ZoneInfo("America/New_York"))

        if local_reference.weekday() >= 5:
            return "weekly_review"

        current_minutes = local_reference.hour * 60 + local_reference.minute
        if current_minutes < 9 * 60 + 30:
            return "pre_market"
        if current_minutes < 10 * 60 + 30:
            return "market_open"
        if current_minutes < 15 * 60 + 30:
            return "midday"
        if current_minutes < 17 * 60:
            return "close"
        return "after_hours"

    def _first_use_disclaimer(self) -> str:
        return (
            "Важно: это исследовательский инструмент, а не финансовый совет. "
            "Сигналы могут быть неполными, задержанными или устаревшими."
        )

    def _analysis_disclaimer(self, analysis: Any) -> str:
        notes: list[str] = []
        recommendation = str(getattr(analysis, "recommendation", ""))
        scores = getattr(analysis, "scores", None)
        final_score = getattr(scores, "final_score", None)
        risk_score = getattr(scores, "risk_score", None)

        if recommendation == "HIGH_INTEREST" or (isinstance(final_score, (int, float)) and final_score >= 80):
            notes.append(
                "Крупный сигнал: перед любыми действиями проверь источники, свежесть данных и контекст события."
            )

        if recommendation in {"CAUTION", "HIGH_RISK"} or (
            isinstance(risk_score, (int, float)) and risk_score >= 70
        ):
            notes.append(
                "Высокий риск: не полагайся на оценку без ручной проверки данных и новостей."
            )

        return "\n".join(notes)

    def _scan_disclaimer(self, results: list[Any]) -> str:
        if not results:
            return ""

        major_alerts = 0
        high_risk_alerts = 0
        for item in results:
            recommendation = str(getattr(item, "recommendation", ""))
            score = getattr(item, "final_score", None)
            risk = getattr(item, "risk_score", None)
            if recommendation == "HIGH_INTEREST" or (isinstance(score, (int, float)) and score >= 80):
                major_alerts += 1
            if recommendation in {"CAUTION", "HIGH_RISK"} or (
                isinstance(risk, (int, float)) and risk >= 70
            ):
                high_risk_alerts += 1

        notes: list[str] = []
        if major_alerts:
            notes.append(
                f"Крупные сигналы ({major_alerts}) требуют ручной проверки источников и свежести данных."
            )
        if high_risk_alerts:
            notes.append(
                f"Рискованные сигналы ({high_risk_alerts}) лучше перепроверить по источникам и новостям."
            )
        return "\n".join(notes)

    def _translate_recommendation(self, recommendation: str) -> str:
        return research_label_to_russian(recommendation)

    def _translate_text(self, text: str) -> str:
        replacements = {
            "analytical signal": "аналитический сигнал",
            "research signal": "исследовательский сигнал",
            "final score": "итоговая оценка",
            "price is above MA50": "цена выше 50-дневной скользящей средней",
            "price is below MA50": "цена ниже 50-дневной скользящей средней",
            "price is above MA200": "цена выше 200-дневной скользящей средней",
            "price is below MA200": "цена ниже 200-дневной скользящей средней",
            "1-month momentum is positive": "1-месячный импульс положительный",
            "1-month momentum is weak": "1-месячный импульс слабый",
            "6-month trend is strong": "6-месячный тренд сильный",
            "6-month trend is weak": "6-месячный тренд слабый",
            "RSI shows strong overheating": "индекс относительной силы показывает сильный перегрев",
            "RSI is overbought": "индекс относительной силы перекуплен",
            "RSI is deeply oversold": "индекс относительной силы сильно перепродан",
            "RSI may indicate oversold conditions": "индекс относительной силы может указывать на перепроданность",
            "trailing P/E is not meaningful": "трейлинг P/E неинформативен",
            "valuation looks inexpensive by trailing P/E": "оценка выглядит дешёвой по trailing P/E",
            "valuation looks reasonable by trailing P/E": "оценка выглядит разумной по trailing P/E",
            "trailing P/E is very high": "trailing P/E очень высокий",
            "trailing P/E is elevated": "trailing P/E повышенный",
            "forward P/E is high": "forward P/E высокий",
            "forward P/E is lower than trailing P/E": "forward P/E ниже trailing P/E",
            "revenue growth is strong": "рост выручки сильный",
            "revenue growth is positive": "рост выручки положительный",
            "revenue growth is negative": "рост выручки отрицательный",
            "profit margins are strong": "маржа высокая",
            "profit margins are healthy": "маржа здоровая",
            "profit margins are negative": "маржа отрицательная",
            "debt/equity is high": "debt/equity высокий",
            "debt/equity is elevated": "debt/equity повышенный",
            "debt/equity is conservative": "debt/equity консервативный",
            "volatility is low": "волатильность низкая",
            "volatility is very high": "волатильность очень высокая",
            "volatility is elevated": "волатильность повышенная",
            "max drawdown is limited": "максимальная просадка ограниченная",
            "max drawdown is severe": "максимальная просадка серьёзная",
            "max drawdown is large": "максимальная просадка большая",
            "overbought RSI adds short-term risk": "перекупленный RSI повышает краткосрочный риск",
            "daily move is unusually large": "дневное движение необычно большое",
            "not enough strong quantitative signals": "недостаточно сильных количественных сигналов",
            "This is a research signal, not financial advice.": "Это исследовательский сигнал, а не финансовый совет.",
            "This is a research signal, not financial advice": "Это исследовательский сигнал, а не финансовый совет",
            "This is a research signal": "Это исследовательский сигнал",
            "not financial advice": "не финансовый совет",
            "LLM explanation is unavailable, so rule-based explanation was used.": "Объяснение от LLM недоступно, поэтому использован rule-based вариант.",
            "LLM explanation is unavailable": "Объяснение от LLM недоступно",
            "rule-based explanation": "объяснение по правилам",
            "OpenAI explanation is disabled, so a rule-based explanation was used.": "Объяснение OpenAI отключено, поэтому использован rule-based вариант.",
            "OpenAI call budget was exhausted, so a rule-based explanation was used.": "Лимит вызовов OpenAI исчерпан, поэтому использован rule-based вариант.",
            "OpenAI response was unavailable, so a rule-based explanation was used.": "Ответ OpenAI недоступен, поэтому использован rule-based вариант.",
            "Data quality:": "Качество данных:",
            "Partial failure: review the per-ticker error lines for market-data issues or ticker-specific problems.": "Частичный сбой: проверь строки ошибок по тикерам для проблем с market-data или конкретным тикером.",
            "Market session is open, but the latest bar is from a prior trading day.": "Рыночная сессия открыта, но последняя свеча относится к предыдущему торговому дню.",
            "Market session is": "Рыночная сессия",
            "after-hours": "после закрытия",
            "pre-market": "до открытия",
            "weekend": "выходные",
            "fresh intraday coverage may be delayed.": "свежие внутридневные данные могут запаздывать.",
            "momentum": "импульс",
            "valuation": "оценка стоимости",
            "risk": "риск",
            "score": "оценка",
        }

        translated = text
        for source, target in replacements.items():
            translated = translated.replace(source, target)
        return translated

    def _parse_tickers(self, args: list[str]) -> list[str]:
        tickers: list[str] = []
        for item in args:
            if not item.startswith("/"):
                tickers.append(item)
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

    def _update_watchlist(
        self,
        chat_id: int,
        *,
        username: str | None,
        tickers: list[str],
        mode: str,
    ) -> tuple[list[str], list[str]]:
        normalized, invalid = self._normalize_watchlist_symbols(tickers)
        sub = self._subscription_for_chat(chat_id)
        current = self._watchlist_tickers_for_subscription(sub) if sub is not None else []

        if mode == "add":
            updated = current[:]
            for symbol in normalized:
                if symbol not in updated:
                    updated.append(symbol)
        else:
            updated = [symbol for symbol in current if symbol not in normalized]

        self._upsert_subscription(
            chat_id,
            username=username,
            active=True if sub is None else sub.is_active,
            watchlist_symbols=updated,
        )
        if mode == "add":
            changed = [symbol for symbol in updated if symbol not in current]
        else:
            changed = [symbol for symbol in current if symbol not in updated]
        return changed, invalid

    def _watchlist_text(self, chat_id: int) -> str:
        sub = self._subscription_for_chat(chat_id)
        if sub is None:
            return (
                "Подписка не найдена. Используй /start, затем /add AAPL MSFT NVDA, "
                "чтобы завести личный список."
            )

        watchlist = self._watchlist_tickers_for_subscription(sub)
        if watchlist:
            return (
                "Твой список тикеров:\n"
                f"{', '.join(watchlist)}\n\n"
                "Команды: /add AAPL, /remove AAPL, /scan mine"
            )

        default_list = ", ".join(self._configured_tickers()) or "пусто"
        return (
            "Личный список пока пуст.\n"
            f"По умолчанию для дайджестов используется: {default_list}\n\n"
            "Команды: /add AAPL, /watchlist, /scan mine"
        )

    def _watchlist_update_text(
        self,
        *,
        chat_id: int,
        mode: str,
        changed_tickers: list[str],
        invalid_tickers: list[str],
    ) -> str:
        current = self._watchlist_tickers(chat_id)
        if mode == "add":
            prefix = "Добавил в твой список"
        else:
            prefix = "Удалил из твоего списка"

        if changed_tickers:
            result = f"{prefix}: {', '.join(changed_tickers)}."
        else:
            result = "Ничего не изменилось."

        if invalid_tickers:
            result = f"{result}\nНекорректные тикеры пропущены: {', '.join(invalid_tickers)}."

        result = f"{result}\nТекущий список: {', '.join(current) if current else 'пусто'}."
        return result

    def _trim_message(self, text: str, limit: int = 3900) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    async def _send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        await asyncio.to_thread(self._send_message_sync, chat_id, text, reply_markup)

    def _send_message_sync(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        try:
            consume_runtime_budget(
                "telegram_sends",
                getattr(self.settings, "telegram_send_budget", None),
            )
        except RuntimeBudgetExceeded as exc:
            raise RuntimeError(f"Telegram send budget exhausted: {exc}") from exc

        payload = {
            "chat_id": chat_id,
            "text": self._trim_message(text),
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        response = self._request_json("sendMessage", parse.urlencode(payload).encode("utf-8"))
        if not response.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {response}")

    def _request_json(self, method: str, data: bytes | None = None) -> dict[str, Any]:
        token = self.settings.telegram_bot_token
        if not token:
            raise RuntimeError("Telegram bot token is not configured.")

        url = f"https://api.telegram.org/bot{token}/{method}"
        req = request.Request(url, data=data)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with request.urlopen(req, timeout=max(10, self.settings.telegram_poll_timeout_seconds + 10)) as response:
                body = response.read().decode("utf-8")
        except urlerror.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Telegram API error {exc.code}: {body}") from exc
        except Exception as exc:
            raise RuntimeError(f"Telegram API request failed: {exc}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Could not decode Telegram response: {body}") from exc


async def run_telegram_bot() -> None:
    service = TelegramBotService()
    if not service.settings.telegram_bot_token:
        raise RuntimeError(
            "Telegram bot token is missing. Set TELEGRAM_BOT_TOKEN in .env."
        )
    if not service.settings.telegram_enabled:
        raise RuntimeError(
            "Telegram bot is disabled. Set TELEGRAM_ENABLED=1 in .env."
        )

    await service.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await service.stop()
