from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from urllib import error as urlerror
from urllib import parse, request

from app.config import Settings, get_settings
from app.database import SessionLocal, init_db
from app.models import TelegramSubscription
from app.services.scanner import analyze_ticker, scan_tickers


class TelegramBotService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._running = False
        self._offset = 0
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def enabled(self) -> bool:
        return bool(self.settings.telegram_enabled and self.settings.telegram_bot_token)

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
                {"text": self._button_choose_ticker()},
                {"text": self._button_scan()},
                {"text": self._button_help()},
            ],
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

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                updates = await asyncio.to_thread(
                    self._get_updates, self._offset, self.settings.telegram_poll_timeout_seconds
                )
                for update in updates:
                    self._offset = max(self._offset, int(update["update_id"]) + 1)
                    await self._handle_update(update)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - resilience path
                print(f"[telegram] polling error: {exc}")
                await asyncio.sleep(5)

    async def _digest_loop(self) -> None:
        interval = max(1, int(self.settings.telegram_digest_interval_minutes)) * 60
        while self._running:
            try:
                await asyncio.sleep(interval)
                await self._send_digest_to_active_subscribers()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - resilience path
                print(f"[telegram] digest error: {exc}")

    async def _handle_update(self, update: dict[str, Any]) -> None:
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

        user = message.get("from") or {}
        username = user.get("username") or user.get("first_name") or user.get("last_name")

        action, args = self._resolve_action(text)

        if action == "start":
            await self._send_message(
                int(chat_id),
                self._welcome_text(),
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

        if action == "subscribe":
            self._upsert_subscription(int(chat_id), username=username, active=True)
            await self._send_message(
                int(chat_id),
                "Подписка активирована. Я буду отправлять тебе дайджесты и ответы на кнопки.",
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
                analysis = await asyncio.to_thread(analyze_ticker, ticker, None, False)
                await self._send_message(
                    int(chat_id),
                    self._analysis_text(analysis),
                    reply_markup=self._main_keyboard(),
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
                    self._scan_text(response.results, response.errors),
                    reply_markup=self._main_keyboard(),
                )
            except Exception as exc:
                await self._send_message(
                    int(chat_id),
                    f"Не удалось выполнить сканирование: {exc}",
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
            "allowed_updates": json.dumps(["message", "edited_message"]),
        }
        data = parse.urlencode(payload).encode("utf-8")
        response = self._request_json("getUpdates", data)
        if not response.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {response}")
        result = response.get("result", [])
        return result if isinstance(result, list) else []

    async def _send_digest_to_active_subscribers(self) -> None:
        subscribers = self._active_subscribers()
        if not subscribers:
            return

        tickers = self._configured_tickers()
        if not tickers:
            return

        response = await asyncio.to_thread(scan_tickers, tickers, None)
        digest = self._digest_text(response.results, response.errors)
        for subscriber in subscribers:
            await self._send_message(subscriber.chat_id, digest)
            self._mark_last_alert(subscriber.id)

    def _active_subscribers(self) -> list[TelegramSubscription]:
        db = SessionLocal()
        try:
            return (
                db.query(TelegramSubscription)
                .filter(TelegramSubscription.is_active.is_(True))
                .order_by(TelegramSubscription.created_at.asc())
                .all()
            )
        finally:
            db.close()

    def _upsert_subscription(self, chat_id: int, username: str | None, active: bool) -> None:
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
                )
                db.add(sub)
            else:
                sub.username = username or sub.username
                sub.is_active = active
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def _mark_last_alert(self, subscription_id: int) -> None:
        db = SessionLocal()
        try:
            sub = db.get(TelegramSubscription, subscription_id)
            if sub is None:
                return
            sub.last_alert_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def _status_text(self, chat_id: int) -> str:
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
            return (
                f"Подписка активна: {'да' if sub.is_active else 'нет'}\n"
                f"Последняя рассылка: {last_alert}\n"
                f"Частота рассылки: {self.settings.telegram_digest_interval_minutes} мин."
            )
        finally:
            db.close()

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
        if lowered in {self._button_choose_ticker().lower()}:
            return "ticker_menu", []
        if lowered in {self._button_back().lower()}:
            return "back", []
        if lowered in {"/scan", "scan", self._button_scan().lower()}:
            return "scan", []

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
            "• анализ отдельных тикеров\n"
            "• сканирование рынка по списку из настроек\n"
        )

    def _welcome_text(self) -> str:
        return (
            "Привет. Я бот для анализа акций.\n"
            "Нажимай кнопки под сообщением, чтобы не вводить команды вручную."
        )

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
        return self._trim_message("\n".join(lines))

    def _scan_text(self, results: list[Any], errors: list[Any]) -> str:
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
        return self._trim_message("\n".join(lines))

    def _digest_text(self, results: list[Any], errors: list[Any]) -> str:
        top = results[:3]
        if not top and not errors:
            return "Дайджест пуст: данных для отчёта нет."

        lines = ["Телеграм-дайджест рынка:"]
        for item in top:
            recommendation = self._translate_recommendation(item.recommendation)
            lines.append(
                f"{item.ticker}: {recommendation}, оценка {item.final_score:.2f}, {self._translate_text(item.short_reason)}"
            )
        if errors:
            lines.append("Ошибки скана:")
            for item in errors[:3]:
                lines.append(f"- {item.ticker}: {item.error}")
        return self._trim_message("\n".join(lines))

    def _translate_recommendation(self, recommendation: str) -> str:
        mapping = {
            "STRONG_BUY_CANDIDATE": "Сильный кандидат на покупку",
            "BUY_WATCHLIST": "Кандидат в список наблюдения",
            "HOLD": "Держать",
            "WAIT": "Ждать",
            "REDUCE": "Сократить",
            "AVOID": "Избегать",
        }
        return mapping.get(recommendation, recommendation)

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
