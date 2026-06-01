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
from app.services.alert_rules import (
    evaluate_rules,
    format_rule,
    is_recently_fired,
    mark_fired,
    parse_rule,
)
from app.services.edgar_collector import fetch_recent_filings
from app.services.news_collector import build_news_context, high_impact_news
from app.services.history import build_snapshot_audit_entries, list_recent_snapshots
from app.services.runtime_budget import (
    RuntimeBudgetExceeded,
    consume_runtime_budget,
    runtime_budget_snapshot,
)
from app.services.exchange_calendar import get_session_state
from app.services.scanner import analyze_ticker, scan_tickers
from app.services.market_hours import should_defer_alert, time_until_market_open
from app.services.backtesting import backtest_report, calculate_metrics
from app.services.telegram._ui import UiMixin
from app.services.telegram._parsing import ParsingMixin
from app.services.telegram._formatting import FormattingMixin
from app.services.telegram._disclaimers import DisclaimerMixin


logger = logging.getLogger(__name__)


class TelegramBotService(
    UiMixin,
    ParsingMixin,
    FormattingMixin,
    DisclaimerMixin,
):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._running = False
        self._offset = 0
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def enabled(self) -> bool:
        return bool(self.settings.telegram_enabled and self.settings.telegram_bot_token)

















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
        self._tasks.append(
            asyncio.create_task(self._alert_loop(), name="telegram-alert-loop")
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

    async def _alert_loop(self) -> None:
        """Check threshold alert rules every 5 minutes and push triggered ones."""
        while self._running:
            try:
                await asyncio.sleep(300)
                await self._check_alert_rules()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - resilience path
                logger.exception("Telegram alert loop failed")

    async def _check_alert_rules(self) -> None:
        subscribers = self._active_subscribers()
        if not subscribers:
            return

        # Gather distinct tickers across all subscribers with rules.
        ticker_to_subs: dict[str, list[TelegramSubscription]] = {}
        for sub in subscribers:
            for rule in list(getattr(sub, "alert_rules", None) or []):
                ticker = rule.get("ticker", "").upper()
                if ticker:
                    ticker_to_subs.setdefault(ticker, []).append(sub)

        if not ticker_to_subs:
            return

        from app.services.market_data import get_market_data

        for ticker, subs in ticker_to_subs.items():
            try:
                market = await asyncio.to_thread(get_market_data, ticker)
            except Exception:
                continue

            price = float(market.get("price", 0) or 0)
            info = market.get("info") or {}
            prev_close = float(info.get("previousClose") or 0) or None
            recommendation = None  # recommendation requires full analyze_ticker; skip for speed

            for sub in subs:
                skip_reason = self._digest_skip_reason(sub)
                if skip_reason:
                    continue
                rules = list(getattr(sub, "alert_rules", None) or [])
                fired = [
                    r for r in evaluate_rules(rules, ticker=ticker, price=price, prev_close=prev_close, recommendation=recommendation)
                    if not is_recently_fired(r)
                ]
                if not fired:
                    continue

                # Update last_fired_at in the stored rules.
                updated_rules = []
                for r in rules:
                    match = next((f for f in fired if f.get("ticker") == r.get("ticker") and f.get("kind") == r.get("kind") and f.get("value") == r.get("value")), None)
                    updated_rules.append(mark_fired(r) if match else r)
                self._upsert_subscription(sub.chat_id, username=None, active=True, preferences={"alert_rules": updated_rules})

                for rule in fired:
                    reason = rule.get("reason", format_rule(rule))
                    text = f"🔔 Алерт сработал!\n{reason}"
                    await self._send_message(sub.chat_id, text)
                    self._mark_last_alert(sub.id)

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
            self._clear_subscription_state(int(chat_id), username=username)
            await self._send_message(
                int(chat_id),
                "Подписка отключена, данные списка и уведомлений очищены.",
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

        if action == "confidence":
            confidence_value, confidence_error = self._parse_confidence_threshold(args[0] if args else "")
            if confidence_error:
                await self._send_message(
                    int(chat_id),
                    confidence_error,
                    reply_markup=self._main_keyboard(),
                )
                return
            self._upsert_subscription(
                int(chat_id),
                username=username,
                active=True,
                preferences={"min_confidence": confidence_value},
            )
            await self._send_message(
                int(chat_id),
                self._preferences_text(
                    int(chat_id),
                    notice=(
                        "Minimum confidence updated."
                        if confidence_value is not None
                        else "Minimum confidence cleared."
                    ),
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
                subscription = self._subscription_for_chat(int(chat_id))
                min_confidence = getattr(subscription, "min_confidence", None) if subscription else None
                await self._send_message(
                    int(chat_id),
                    self._scan_text(
                        response.results,
                        response.errors,
                        summary_notes=getattr(response.summary, "notes", None),
                        min_confidence=min_confidence,
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

        if action == "coverage":
            await self._send_message(
                int(chat_id),
                self._coverage_text(),
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "backtest":
            ticker = args[0] if args else None
            if not ticker:
                await self._send_message(
                    int(chat_id),
                    "Используй /backtest AAPL для анализа accuracy скоров.",
                    reply_markup=self._main_keyboard(),
                )
                return
            await self._send_message(int(chat_id), f"Анализирую accuracy для {ticker}...", reply_markup=self._main_keyboard())
            try:
                backtest_text = await asyncio.to_thread(self._backtest_ticker, ticker)
                await self._send_message(
                    int(chat_id),
                    backtest_text,
                    reply_markup=self._main_keyboard(),
                )
            except Exception as exc:
                await self._send_message(
                    int(chat_id),
                    f"Не удалось провести backtest {ticker}: {exc}",
                    reply_markup=self._main_keyboard(),
                )
            return

        if action == "portfolio":
            watchlist = args[0:] if args else None
            if not watchlist:
                # Get user's watchlist
                watchlist = self._get_user_watchlist(int(chat_id))
            if not watchlist:
                await self._send_message(
                    int(chat_id),
                    "Твой портфель пуст. Добавь тикеры с /add AAPL MSFT",
                    reply_markup=self._main_keyboard(),
                )
                return
            await self._send_message(int(chat_id), f"Анализирую портфель ({len(watchlist)} акций)...", reply_markup=self._main_keyboard())
            try:
                portfolio_text = await asyncio.to_thread(self._portfolio_analysis, watchlist)
                await self._send_message(
                    int(chat_id),
                    portfolio_text,
                    reply_markup=self._main_keyboard(),
                )
            except Exception as exc:
                await self._send_message(
                    int(chat_id),
                    f"Не удалось проанализировать портфель: {exc}",
                    reply_markup=self._main_keyboard(),
                )
            return

        if action == "holding_buy":
            # /buy AAPL 10 175.5  (ticker shares cost_basis)
            parts = args
            if len(parts) < 3:
                await self._send_message(
                    int(chat_id),
                    "Формат: /buy AAPL 10 175.50  (тикер кол-во цена_покупки)",
                    reply_markup=self._main_keyboard(),
                )
                return
            try:
                ticker_b = parts[0].strip().upper()
                shares = float(parts[1])
                cost = float(parts[2])
            except (ValueError, IndexError):
                await self._send_message(int(chat_id), "Неверный формат. Пример: /buy AAPL 10 175.50", reply_markup=self._main_keyboard())
                return
            sub = self._subscription_for_chat(int(chat_id))
            holdings = dict(getattr(sub, "holdings", None) or {}) if sub else {}
            if ticker_b in holdings:
                # Average down/up existing position.
                existing = holdings[ticker_b]
                total_shares = existing["shares"] + shares
                avg_cost = (existing["shares"] * existing["cost_basis"] + shares * cost) / total_shares
                holdings[ticker_b] = {"shares": total_shares, "cost_basis": avg_cost}
            else:
                holdings[ticker_b] = {"shares": shares, "cost_basis": cost}
            self._upsert_subscription(int(chat_id), username=None, active=True, preferences={"holdings": holdings})
            await self._send_message(
                int(chat_id),
                f"✅ {ticker_b}: добавлено {shares} акц. по ${cost:.2f}\nПросмотр: /holdings",
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "holding_sell":
            # /sell AAPL [shares]
            parts = args
            if not parts:
                await self._send_message(int(chat_id), "Формат: /sell AAPL 10  (или /sell AAPL для всей позиции)", reply_markup=self._main_keyboard())
                return
            ticker_s = parts[0].strip().upper()
            shares_to_sell = float(parts[1]) if len(parts) > 1 else None
            sub = self._subscription_for_chat(int(chat_id))
            holdings = dict(getattr(sub, "holdings", None) or {}) if sub else {}
            if ticker_s not in holdings:
                await self._send_message(int(chat_id), f"{ticker_s} нет в портфеле.", reply_markup=self._main_keyboard())
                return
            if shares_to_sell is None or shares_to_sell >= holdings[ticker_s]["shares"]:
                del holdings[ticker_s]
                msg = f"✅ {ticker_s}: позиция закрыта."
            else:
                holdings[ticker_s]["shares"] -= shares_to_sell
                msg = f"✅ {ticker_s}: продано {shares_to_sell} акц. Осталось {holdings[ticker_s]['shares']:.2f}."
            self._upsert_subscription(int(chat_id), username=None, active=True, preferences={"holdings": holdings})
            await self._send_message(int(chat_id), msg, reply_markup=self._main_keyboard())
            return

        if action == "holdings":
            sub = self._subscription_for_chat(int(chat_id))
            holdings = dict(getattr(sub, "holdings", None) or {}) if sub else {}
            if not holdings:
                await self._send_message(int(chat_id), "Портфель пуст. Добавь: /buy AAPL 10 175.50", reply_markup=self._main_keyboard())
                return
            await self._send_message(int(chat_id), "Считаю P&L...", reply_markup=self._main_keyboard())
            text = await asyncio.to_thread(self._holdings_pnl_text, holdings)
            await self._send_message(int(chat_id), text, reply_markup=self._main_keyboard())
            return

        if action == "alert_add":
            rule_text = " ".join(args).strip()
            rule = parse_rule(rule_text) if rule_text else None
            if rule is None:
                await self._send_message(
                    int(chat_id),
                    "Формат: /alert AAPL < 300  |  /alert AAPL > 350  |  /alert AAPL move 5  |  /alert AAPL sell",
                    reply_markup=self._main_keyboard(),
                )
                return
            sub = self._subscription_for_chat(int(chat_id))
            existing = list(getattr(sub, "alert_rules", None) or []) if sub else []
            existing.append(rule)
            self._upsert_subscription(int(chat_id), username=None, active=True, preferences={"alert_rules": existing})
            await self._send_message(
                int(chat_id),
                f"✅ Алерт добавлен: {format_rule(rule)}\nПросмотр всех: /alerts",
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "alerts_list":
            sub = self._subscription_for_chat(int(chat_id))
            rules = list(getattr(sub, "alert_rules", None) or []) if sub else []
            await self._send_message(
                int(chat_id),
                self._alert_rules_text(rules),
                reply_markup=self._main_keyboard(),
            )
            return

        if action == "alert_clear":
            ticker_arg = args[0].strip().upper() if args else None
            sub = self._subscription_for_chat(int(chat_id))
            rules = list(getattr(sub, "alert_rules", None) or []) if sub else []
            if ticker_arg:
                rules = [r for r in rules if r.get("ticker", "").upper() != ticker_arg]
                msg = f"Алерты для {ticker_arg} удалены."
            else:
                rules = []
                msg = "Все алерты удалены."
            self._upsert_subscription(int(chat_id), username=None, active=True, preferences={"alert_rules": rules})
            await self._send_message(int(chat_id), msg, reply_markup=self._main_keyboard())
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
            tickers = args or self._configured_tickers()
            if not tickers:
                await self._send_message(
                    int(chat_id),
                    "Список тикеров пуст. Проверь TELEGRAM_DEFAULT_TICKERS.",
                    reply_markup=self._main_keyboard(),
                )
                return
            if args:
                scan_intro = f"Запускаю сканирование: {', '.join(tickers)}..."
            else:
                scan_intro = "Запускаю сканирование рынка..."
            await self._send_message(
                int(chat_id),
                scan_intro,
                reply_markup=self._main_keyboard(),
            )
            try:
                response = await asyncio.to_thread(scan_tickers, tickers, None)
                subscription = self._subscription_for_chat(int(chat_id))
                min_confidence = getattr(subscription, "min_confidence", None) if subscription else None
                await self._send_message(
                    int(chat_id),
                    self._scan_text(
                        response.results,
                        response.errors,
                        summary_notes=getattr(response.summary, "notes", None),
                        min_confidence=min_confidence,
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

        if action in {"why", "sources", "events", "filings", "freshness", "calendar", "risk", "audit", "news"}:
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

        if action in {"why", "sources", "events", "filings", "freshness", "audit"}:
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

        # Fetch market-wide news once per digest cycle (respects rate limits).
        news_context = await asyncio.to_thread(
            build_news_context, None, self.settings, include_macro=True
        )

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
            impact_items = high_impact_news(news_context)
            min_confidence = getattr(subscriber, "min_confidence", None)
            digest_fingerprint = self._digest_fingerprint(
                response.results,
                response.errors,
                summary_notes=getattr(response.summary, "notes", None),
                digest_mode=mode,
                min_confidence=min_confidence,
                news_urls=[item.url or item.title for item in impact_items],
            )
            if getattr(subscriber, "last_digest_fingerprint", None) == digest_fingerprint:
                logger.info(
                    "telegram_digest_skipped",
                    extra={
                        "component": "telegram",
                        "chat_id": subscriber.chat_id,
                        "reason": "duplicate_digest",
                    },
                )
                continue
            digest = self._digest_text(
                response.results,
                response.errors,
                summary_notes=getattr(response.summary, "notes", None),
                digest_mode=mode,
                min_confidence=min_confidence,
                news_items=impact_items,
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
            self._mark_last_alert(subscriber.id, digest_fingerprint=digest_fingerprint)

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
        if action == "filings":
            filings_ticker = ticker or (args[0].strip().upper() if args else None)
            if not filings_ticker:
                await self._send_message(
                    chat_id,
                    "Укажи тикер для /filings. Например: /filings AAPL",
                    reply_markup=reply_markup,
                )
                return
            text = await asyncio.to_thread(self._filings_text, filings_ticker)
            await self._send_message(chat_id, text, reply_markup=reply_markup)
            return
        if action == "news":
            news_ticker = ticker or (args[0].strip().upper() if args else None)
            text = await asyncio.to_thread(self._news_text, news_ticker)
            await self._send_message(chat_id, text, reply_markup=reply_markup)
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

    def _clear_subscription_state(self, chat_id: int, username: str | None) -> None:
        db = SessionLocal()
        try:
            sub = (
                db.query(TelegramSubscription)
                .filter(TelegramSubscription.chat_id == chat_id)
                .one_or_none()
            )
            if sub is None:
                return
            sub.username = username or sub.username
            sub.is_active = False
            sub.watchlist_symbols = []
            sub.quiet_hours_start_minute = None
            sub.quiet_hours_end_minute = None
            sub.max_alerts_per_day = None
            sub.market_hours_only = False
            sub.last_digest_fingerprint = None
            sub.daily_alert_count = 0
            sub.daily_alert_date = None
            sub.last_alert_at = None
            db.commit()
            logger.info(
                "telegram_subscription_cleared",
                extra={"component": "telegram", "chat_id": chat_id},
            )
        except Exception:
            db.rollback()
            logger.exception(
                "telegram_subscription_clear_failed",
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

    def _mark_last_alert(self, subscription_id: int, *, digest_fingerprint: str | None = None) -> None:
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
            if digest_fingerprint is not None:
                sub.last_digest_fingerprint = digest_fingerprint
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











    def _is_market_session_open(self, moment: datetime | None = None) -> bool:
        reference = moment or datetime.now(timezone.utc)
        local_reference = reference.astimezone(ZoneInfo("America/New_York"))
        return get_session_state(local_reference) == "regular_open"

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
            configured = self._configured_tickers()
            configured_tickers = ", ".join(configured) if configured else "пусто"
            min_confidence = getattr(sub, "min_confidence", None)
            min_confidence_text = "off" if min_confidence is None else f"{min_confidence:.2f}"
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
                f"Список для /scan: {configured_tickers}\n"
                f"Порог уверенности: {min_confidence_text}\n"
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
        raw = getattr(self.settings, "telegram_default_tickers", "")
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
        if lowered in {"/coverage", "coverage"}:
            return "coverage", []
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
        if lowered.startswith("/scan ") or lowered.startswith("scan "):
            parts = normalized.split(maxsplit=1)
            if len(parts) == 2:
                return "scan", self._parse_tickers(parts[1].split())
            return "scan", []
        if lowered in {"/scan", "scan", self._button_scan().lower()}:
            return "scan", []

        for prefix, action in (
            ("/why ", "why"),
            ("why ", "why"),
            ("/sources ", "sources"),
            ("sources ", "sources"),
            ("/events ", "events"),
            ("events ", "events"),
            ("/filings ", "filings"),
            ("filings ", "filings"),
            ("/freshness ", "freshness"),
            ("freshness ", "freshness"),
            ("/calendar ", "calendar"),
            ("calendar ", "calendar"),
            ("/risk ", "risk"),
            ("risk ", "risk"),
            ("/audit ", "audit"),
            ("audit ", "audit"),
            ("/news ", "news"),
            ("news ", "news"),
            ("/alert ", "alert_add"),
            ("alert ", "alert_add"),
            ("/buy ", "holding_buy"),
            ("buy ", "holding_buy"),
            ("/sell ", "holding_sell"),
            ("sell ", "holding_sell"),
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
        if lowered in {"/filings", "filings"}:
            return "filings", []
        if lowered in {"/news", "news"}:
            return "news", []
        if lowered in {"/alerts", "alerts"}:
            return "alerts_list", []
        if lowered in {"/holdings", "holdings"}:
            return "holdings", []
        if lowered in {"/alert_clear", "alert_clear"}:
            return "alert_clear", []

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

        if lowered.startswith("/confidence ") or lowered.startswith("confidence "):
            parts = normalized.split(maxsplit=1)
            if len(parts) == 2:
                return "confidence", [parts[1].strip()]
            return "confidence", []
        if lowered in {"/confidence", "confidence"}:
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

        if lowered.startswith("/backtest ") or lowered.startswith("backtest "):
            ticker = normalized.split(maxsplit=1)[1].strip().upper()
            return "backtest", [ticker] if ticker else []

        if lowered.startswith("/portfolio ") or lowered.startswith("portfolio "):
            parts = normalized.split(maxsplit=1)
            return "portfolio", [parts[1].strip().upper()] if len(parts) > 1 else []
        if lowered in {"/portfolio", "portfolio"}:
            return "portfolio", []

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

    def _holdings_pnl_text(self, holdings: dict[str, Any]) -> str:
        """Compute P&L for each holding using live prices and return a formatted report."""
        from app.services.market_data import get_market_data

        lines = ["💼 Портфель (P&L):"]
        total_cost = 0.0
        total_value = 0.0
        for ticker, pos in holdings.items():
            shares = float(pos.get("shares", 0))
            cost_basis = float(pos.get("cost_basis", 0))
            try:
                market = get_market_data(ticker)
                price = float(market.get("price", 0) or 0)
            except Exception:
                lines.append(f"  {ticker}: нет данных о цене")
                continue
            position_cost = shares * cost_basis
            position_value = shares * price
            pnl = position_value - position_cost
            pnl_pct = (pnl / position_cost * 100) if position_cost else 0
            sign = "+" if pnl >= 0 else ""
            arrow = "📈" if pnl >= 0 else "📉"
            lines.append(
                f"{arrow} {ticker}: {shares:.0f} акц. × ${price:.2f} = ${position_value:.2f}  "
                f"({sign}{pnl:.2f}, {sign}{pnl_pct:.1f}%)"
            )
            total_cost += position_cost
            total_value += position_value
        if total_cost:
            total_pnl = total_value - total_cost
            total_pct = total_pnl / total_cost * 100
            sign = "+" if total_pnl >= 0 else ""
            lines.append(f"\nИтого: ${total_value:.2f}  ({sign}{total_pnl:.2f}, {sign}{total_pct:.1f}%)")
        lines.append("\nДобавить: /buy AAPL 10 175.50  |  Продать: /sell AAPL")
        return self._trim_message("\n".join(lines))

    def _news_text(self, ticker: str | None) -> str:
        """Fetch and format news + sentiment for a ticker (or market-wide)."""
        scope = ticker.upper() if ticker else "Рынок и макро"
        try:
            context = build_news_context(ticker, self.settings)
        except Exception as exc:
            return (
                f"Не удалось получить новости для {scope}: {exc}\n"
                "Проверь соединение или повтори позже."
            )

        if not context.items:
            return (
                f"Новости: {scope}\n"
                "Свежих новостей не найдено (или не настроены ключи источников)."
            )

        label_ru = {"positive": "позитивный 📈", "negative": "негативный 📉"}.get(
            context.overall_sentiment_label, "нейтральный ➖"
        )
        lines = [f"Новости: {scope}", f"Общий настрой: {label_ru}"]
        if context.summary:
            lines.append(context.summary)

        high_impact = {id(item) for item in high_impact_news(context)}
        lines.append("\nЗаголовки:")
        for item in context.items:
            mark = {"positive": "📈", "negative": "📉"}.get(item.sentiment_label, "➖")
            flag = "‼️ " if id(item) in high_impact else ""
            source = f" ({item.source})" if item.source else ""
            lines.append(f"{flag}{mark} {item.title}{source}")
            if item.url:
                lines.append(f"  {item.url}")

        lines.append("\nИсточники: Alpha Vantage, Finnhub, GDELT, ФРС (RSS)")
        return self._trim_message("\n".join(lines))

    def _filings_text(self, ticker: str) -> str:
        """Fetch and format recent SEC EDGAR filings for a ticker."""
        try:
            collection = fetch_recent_filings(ticker)
        except Exception as exc:
            return (
                f"Не удалось получить данные SEC EDGAR для {ticker.upper()}: {exc}\n"
                "Проверь соединение с интернетом или повтори позже."
            )

        if collection.error:
            return (
                f"SEC EDGAR: {ticker.upper()}\n"
                f"Ошибка: {collection.error}"
            )

        lines = [f"SEC EDGAR: {ticker.upper()}"]
        if collection.company_name:
            lines.append(f"Компания: {collection.company_name}")
        if collection.cik:
            lines.append(f"CIK: {collection.cik}")
        lines.append(f"Запрошено: {collection.fetched_at.strftime('%Y-%m-%d %H:%M UTC')}")

        if not collection.filings:
            lines.append("\nПоследние подачи не найдены или раздел пустой.")
        else:
            lines.append("\nПоследние подачи:")
            for filing in collection.filings:
                lines.append(
                    f"• {filing.filing_date}  {filing.form_type}  {filing.description}\n"
                    f"  {filing.sec_url}"
                )

        lines.append("\nИсточник: SEC EDGAR (публичные данные SEC, Tier 1)")
        return self._trim_message("\n".join(lines))






    def _scheduled_digest_mode(self, reference_time: datetime | None = None) -> str:
        reference = reference_time or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        local_reference = reference.astimezone(ZoneInfo("America/New_York"))
        session_state = get_session_state(local_reference)
        current_minutes = local_reference.hour * 60 + local_reference.minute

        if session_state in {"weekend", "holiday"}:
            return "weekly_review"
        if session_state == "pre_market":
            return "pre_market"
        if session_state in {"after_hours", "early_close"}:
            return "close" if current_minutes < 17 * 60 else "after_hours"
        if session_state == "closed":
            return "after_hours"

        if current_minutes < 10 * 60 + 30:
            return "market_open"
        if current_minutes < 15 * 60 + 30:
            return "midday"
        if current_minutes < 16 * 60:
            return "close"
        return "after_hours"









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



    def _get_user_watchlist(self, chat_id: int) -> list[str]:
        """Get user's watchlist from preferences."""
        db = SessionLocal()
        try:
            sub = db.query(TelegramSubscription).filter_by(chat_id=chat_id).first()
            if sub and sub.watchlist:
                return sub.watchlist.split(",")
            return []
        finally:
            db.close()

    def _get_user_watchlist_for_analysis(self, analysis: Any) -> list[str]:
        """Get user's watchlist from analysis context."""
        # Try to get from analysis object if it has chat context
        if hasattr(analysis, "_chat_id"):
            return self._get_user_watchlist(analysis._chat_id)
        # Otherwise get all tickers that have been analyzed
        db = SessionLocal()
        try:
            recent_tickers = (
                db.query(AnalysisSnapshot.ticker)
                .order_by(AnalysisSnapshot.created_at.desc())
                .limit(10)
                .all()
            )
            return [t[0] for t in recent_tickers if t[0]]
        finally:
            db.close()

    def _backtest_ticker(self, ticker: str) -> str:
        """Analyze backtest accuracy for a ticker."""
        db = SessionLocal()
        try:
            # Get recent analysis snapshots for this ticker
            snapshots = (
                db.query(AnalysisSnapshot)
                .filter_by(ticker=ticker)
                .order_by(AnalysisSnapshot.created_at.desc())
                .limit(30)
                .all()
            )

            if not snapshots:
                return f"❌ Нет анализов для {ticker}. Запусти /analyze {ticker}"

            # Group by recommendation type and calculate metrics
            results = []
            for snapshot in snapshots:
                # We'd need real price data to backtest properly
                # For now, just show recommendation count
                pass

            if not results:
                return (
                    f"📊 Анализы для {ticker}:\n"
                    f"• Всего анализов: {len(snapshots)}\n"
                    f"• Последний: {snapshots[0].created_at.strftime('%d.%m %H:%M')}\n"
                    f"• Рекомендация: {snapshots[0].recommendation}\n"
                    f"\nДля полного backtesting нужны исторические цены."
                )

            metrics = calculate_metrics(results)
            if metrics:
                report = backtest_report(metrics)
                return "\n".join(report)

            return f"Недостаточно данных для backtesting {ticker}"

        finally:
            db.close()


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

    async def send_alert_with_market_context(
        self,
        chat_id: int,
        alert_text: str,
        is_high_impact: bool = False,
    ) -> None:
        """Send alert, deferring to market open if outside trading hours.

        Args:
            chat_id: Telegram chat ID
            alert_text: Alert message
            is_high_impact: If True (FOMC, jobs), send immediately regardless of hours
        """
        now = datetime.now(ZoneInfo("America/New_York"))

        if should_defer_alert(now, is_high_impact=is_high_impact):
            # Outside market hours and not high-impact
            time_to_open = time_until_market_open(now)
            deferred_note = (
                f"ℹ️ Alert buffered (market closed, opens in "
                f"{int(time_to_open.total_seconds() // 3600)}h)\n\n{alert_text}"
            )
            await self._send_message(chat_id, deferred_note)
        else:
            # Market open or high-impact event
            await self._send_message(chat_id, alert_text)

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
