from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.models import TelegramSubscription
from app.services.alert_rules import format_rule
from app.services.operation_summaries import format_operation_summary
from app.services.coverage import format_coverage_text
from app.services.exchange_calendar import get_market_hours_info
from app.services.correlation import calculate_correlation_matrix, correlation_insights


class FormattingMixin:
    def _help_text(self) -> str:
        return (
            "Нажимай кнопки под сообщением.\n"
            "Доступно:\n"
            "• подписка и отписка\n"
            "• статус подписки\n"
            "• coverage matrix по /coverage\n"
            "• просмотр и редактирование личного списка тикеров\n"
            "• просмотр и изменение настроек уведомлений\n"
            "• анализ отдельных тикеров (/analyze AAPL)\n"
            "• сканирование рынка (/scan mine или /scan AAPL MSFT)\n"
            "• анализ портфеля (/portfolio)\n"
            "• backtest accuracy (/backtest AAPL)\n"
            "• source-backed детали: /why, /sources, /events, /filings, /freshness, /calendar, /risk, /audit\n"
            "• новости и настрой: /news AAPL (или /news для рынка и макро)\n"
            "• алерты: /alert AAPL < 300  |  /alert AAPL move 5  |  /alerts  |  /alert_clear\n"
            "• портфель P&L: /buy AAPL 10 175.50  |  /sell AAPL  |  /holdings\n"
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

        # Add correlation insight if user has watchlist
        try:
            watchlist = self._get_user_watchlist_for_analysis(analysis)
            if watchlist and len(watchlist) > 1:
                matrix = calculate_correlation_matrix(watchlist, lookback_days=90)
                if matrix:
                    insights = correlation_insights(matrix)
                    if insights:
                        lines.extend(["", "Диверсификация портфеля:"])
                        lines.extend(f"- {self._translate_text(insight)}" for insight in insights[:2])
        except Exception:
            # Silently skip correlation on error
            pass

        quality_lines = self._data_quality_warning_lines(getattr(analysis, "data_quality", None))
        if quality_lines:
            lines.extend(["", "Качество данных:"])
            lines.extend(f"- {line}" for line in quality_lines)
        event_calendar = getattr(analysis, "event_calendar", None)
        event_lines = self._event_calendar_lines(event_calendar)
        if event_lines:
            lines.extend(["", "События:"])
            lines.extend(event_lines)
        filing_lines = self._sec_filing_lines(getattr(analysis, "sec_filings", None))
        if filing_lines:
            lines.extend(["", "SEC filings:"])
            lines.extend(filing_lines)
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
        min_confidence: float | None = None,
    ) -> str:
        top = self._filter_results_by_confidence(results[:5], min_confidence)
        hidden_count = len(results[:5]) - len(top)
        if not top and not errors:
            if min_confidence is not None and hidden_count:
                return f"Нет результатов выше порога уверенности {min_confidence:.2f}."
            return "Ничего не найдено."

        lines = ["Результаты скана:"]
        for item in top:
            recommendation = self._translate_recommendation(item.recommendation)
            lines.append(
                f"{item.ticker}: {recommendation} | оценка {item.final_score:.2f} | цена {item.price:.2f}"
            )
            lines.append(f"  {self._translate_text(item.short_reason)}")
        if min_confidence is not None:
            lines.append(f"Порог уверенности: {min_confidence:.2f}")
        if hidden_count:
            lines.append(f"Скрыто низкоуверенных сигналов: {hidden_count}")
        if errors:
            lines.extend(["", *format_operation_summary(errors, summary_notes)])
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
            quality_lines = self._data_quality_warning_lines(data_quality)
            if quality_lines:
                lines.extend(["", "Quality warnings:"])
                lines.extend(f"• {line}" for line in quality_lines)
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
        event_calendar = payload.get("event_calendar") or {}
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
        quality_lines = self._data_quality_warning_lines(data_quality)
        if quality_lines:
            lines.extend(["", "Quality warnings:"])
            lines.extend(f"- {line}" for line in quality_lines)
        event_lines = self._event_calendar_lines(event_calendar)
        if event_lines:
            lines.extend(["", "Upcoming company events:"])
            lines.extend(event_lines)
        else:
            lines.extend(
                [
                    "",
                    "No stored company event calendar is available yet; this view shows the latest stored market session context.",
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
        event_calendar = payload.get("event_calendar") or {}
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
        quality_lines = self._data_quality_warning_lines(data_quality)
        if quality_lines:
            lines.extend(["", "Quality warnings:"])
            lines.extend(f"- {line}" for line in quality_lines)
        event_lines = self._event_calendar_lines(event_calendar)
        if event_lines:
            lines.extend(["", "Upcoming company events:"])
            lines.extend(event_lines)
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
        event_calendar = payload.get("event_calendar") or {}
        sec_filings = payload.get("sec_filings") or {}
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
        quality_lines = self._data_quality_warning_lines(data_quality)
        if quality_lines:
            lines.extend(["", "Quality warnings:"])
            lines.extend(f"- {line}" for line in quality_lines)
        event_lines = self._event_calendar_lines(event_calendar)
        if event_lines:
            lines.extend(["", "Upcoming company events:"])
            lines.extend(event_lines)
        filing_lines = self._sec_filing_lines(sec_filings)
        if filing_lines:
            lines.extend(["", "Recent SEC filings:"])
            lines.extend(filing_lines)
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
            event_calendar = payload.get("event_calendar") or {}
            event_lines = self._event_calendar_lines(event_calendar)
            return self._trim_message(
                "\n".join(
                    [
                        f"{ticker.upper()}: calendar context",
                        f"Session: {market_session.get('status') or 'unknown'}",
                        f"Timezone: {market_session.get('timezone') or 'n/a'}",
                        f"Open: {self._format_dt(market_session.get('market_open_at'))}",
                        f"Close: {self._format_dt(market_session.get('market_close_at'))}",
                        *([""] + ["Upcoming company events:"] + event_lines if event_lines else []),
                        "",
                        "This view uses the latest stored market session snapshot and stored company event calendar, not a live exchange calendar feed.",
                    ]
                )
            )

        now = datetime.now(timezone.utc)
        hours_info = get_market_hours_info(now)
        lines = [
            "Today: U.S. equity session baseline",
            f"Reference time: {hours_info['reference_time_et']}",
            f"Session: {hours_info['state']}",
            f"Next open: {hours_info['next_open']}",
            f"Market close: {hours_info['market_close'] or 'n/a'}",
            "",
            "Use /calendar AAPL to see the latest stored market session for a ticker.",
        ]
        return self._trim_message("\n".join(lines))

    def _event_calendar_lines(self, event_calendar: Any) -> list[str]:
        if not event_calendar:
            return []

        events = getattr(event_calendar, "upcoming_events", None)
        if events is None and isinstance(event_calendar, dict):
            events = event_calendar.get("upcoming_events")
        if not events:
            return []

        lines: list[str] = []
        summary = getattr(event_calendar, "summary", None)
        if summary is None and isinstance(event_calendar, dict):
            summary = event_calendar.get("summary")
        if summary:
            lines.append(self._translate_text(str(summary)))

        for event in events[:4]:
            if isinstance(event, dict):
                name = event.get("name") or "event"
                scheduled_at = event.get("scheduled_at")
                window_start_at = event.get("window_start_at")
                window_end_at = event.get("window_end_at")
                note = event.get("note")
            else:
                name = getattr(event, "name", "event")
                scheduled_at = getattr(event, "scheduled_at", None)
                window_start_at = getattr(event, "window_start_at", None)
                window_end_at = getattr(event, "window_end_at", None)
                note = getattr(event, "note", None)

            parts = [f"• {name}"]
            if scheduled_at is not None:
                parts.append(f"at {self._format_dt(scheduled_at)}")
            if window_start_at is not None or window_end_at is not None:
                parts.append(
                    "window "
                    f"{self._format_dt(window_start_at)} -> {self._format_dt(window_end_at)}"
                )
            if note:
                parts.append(self._translate_text(str(note)))
            lines.append(" | ".join(parts))

        return lines

    def _sec_filing_lines(self, sec_filings: Any) -> list[str]:
        if not sec_filings:
            return []

        filings = getattr(sec_filings, "recent_filings", None)
        if filings is None and isinstance(sec_filings, dict):
            filings = sec_filings.get("recent_filings")
        if not filings:
            return []

        lines: list[str] = []
        summary = getattr(sec_filings, "summary", None)
        if summary is None and isinstance(sec_filings, dict):
            summary = sec_filings.get("summary")
        if summary:
            lines.append(self._translate_text(str(summary)))

        for filing in filings[:3]:
            if isinstance(filing, dict):
                form_type = filing.get("form_type") or "filing"
                filing_date = filing.get("filing_date")
                description = filing.get("description")
            else:
                form_type = getattr(filing, "form_type", "filing")
                filing_date = getattr(filing, "filing_date", None)
                description = getattr(filing, "description", None)

            parts = [f"• {form_type}"]
            if filing_date:
                parts.append(str(filing_date))
            if description:
                parts.append(self._translate_text(str(description)))
            lines.append(" | ".join(parts))

        return lines

    def _digest_text(
        self,
        results: list[Any],
        errors: list[Any],
        *,
        summary_notes: list[str] | None = None,
        digest_mode: str = "market_open",
        min_confidence: float | None = None,
        news_items: list[Any] | None = None,
    ) -> str:
        limit = 5 if digest_mode == "weekly_review" else 3
        top = self._filter_results_by_confidence(results[:limit], min_confidence)
        hidden_count = len(results[:limit]) - len(top)
        if not top and not errors:
            if min_confidence is not None and hidden_count:
                return f"Нет результатов выше порога уверенности {min_confidence:.2f}."
            return "Дайджест пуст: данных для отчёта нет."

        lines = [self._digest_heading(digest_mode)]
        digest_note = self._digest_mode_note(digest_mode)
        if digest_note:
            lines.extend(["", digest_note])
        if min_confidence is not None:
            lines.extend(["", f"Порог уверенности: {min_confidence:.2f}"])
        for item in top:
            recommendation = self._translate_recommendation(item.recommendation)
            lines.append(
                f"{item.ticker}: {recommendation}, оценка {item.final_score:.2f}, {self._translate_text(item.short_reason)}"
            )
        if errors:
            lines.extend(["", *format_operation_summary(errors, summary_notes)])
            lines.append("Ошибки скана:")
            for item in errors[:3]:
                lines.append(f"- {item.ticker}: {item.error}")
        if summary_notes:
            lines.extend(["", "Операционные заметки:"])
            lines.extend(f"- {self._translate_text(note)}" for note in summary_notes)
        if hidden_count:
            lines.append(f"Скрыто низкоуверенных сигналов: {hidden_count}")
        news_lines = self._high_impact_news_lines(news_items)
        if news_lines:
            lines.extend(["", *news_lines])
        disclaimer = self._scan_disclaimer(top)
        if disclaimer:
            lines.extend(["", disclaimer])
        return self._trim_message("\n".join(lines))

    def _alert_rules_text(self, rules: list[Any]) -> str:
        if not rules:
            return (
                "Алертов нет.\n"
                "Добавь: /alert AAPL < 300  |  /alert AAPL > 350  |  /alert AAPL move 5  |  /alert AAPL sell"
            )
        lines = [f"Твои алерты ({len(rules)}):"]
        for rule in rules:
            last = rule.get("last_fired_at")
            fired_str = f"  (сработал {last[:10]})" if last else ""
            lines.append(f"• {format_rule(rule)}{fired_str}")
        lines.append("\nУдалить: /alert_clear AAPL (для тикера) или /alert_clear (все)")
        return "\n".join(lines)

    def _high_impact_news_lines(self, news_items: list[Any] | None) -> list[str]:
        if not news_items:
            return []
        lines = ["📰 Важные новости:"]
        for item in news_items[:3]:
            mark = {"positive": "📈", "negative": "📉"}.get(
                getattr(item, "sentiment_label", "neutral"), "➖"
            )
            source = f" ({item.source})" if getattr(item, "source", None) else ""
            lines.append(f"{mark} {item.title}{source}")
        return lines

    def _digest_fingerprint(
        self,
        results: list[Any],
        errors: list[Any],
        *,
        summary_notes: list[str] | None = None,
        digest_mode: str = "market_open",
        min_confidence: float | None = None,
        news_urls: list[str] | None = None,
    ) -> str:
        limit = 5 if digest_mode == "weekly_review" else 3
        top = self._filter_results_by_confidence(results[:limit], min_confidence)
        payload = {
            "mode": digest_mode,
            "min_confidence": min_confidence,
            "results": [
                {
                    "ticker": item.ticker,
                    "recommendation": item.recommendation,
                    "final_score": round(float(item.final_score), 4),
                    "price": round(float(item.price), 4),
                    "short_reason": str(item.short_reason),
                }
                for item in top
            ],
            "errors": [
                {
                    "ticker": item.ticker,
                    "error": str(item.error),
                }
                for item in errors[:3]
            ],
            "summary_notes": [str(note) for note in (summary_notes or [])],
            "news_urls": sorted(news_urls or []),
        }
        encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

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

    def _coverage_text(self) -> str:
        return self._trim_message(
            "\n".join(
                [
                    "Coverage matrix:",
                    format_coverage_text(),
                    "",
                    "Unsupported areas stay explicit rather than falling back to incomplete coverage.",
                ]
            )
        )

    def _preferences_summary_text(self, subscription: TelegramSubscription) -> str:
        quiet_hours = self._format_quiet_hours(subscription)
        max_alerts = getattr(subscription, "max_alerts_per_day", None)
        daily_cap = "не ограничен" if max_alerts is None else str(max_alerts)
        min_confidence = getattr(subscription, "min_confidence", None)
        confidence_text = "off" if min_confidence is None else f"{min_confidence:.2f}"
        market_hours_only = "да" if getattr(subscription, "market_hours_only", False) else "нет"
        today_key = self._current_day_key()
        daily_alert_date = getattr(subscription, "daily_alert_date", None)
        daily_alert_count = getattr(subscription, "daily_alert_count", 0) or 0
        current_count = daily_alert_count if daily_alert_date == today_key else 0
        return (
            "Настройки уведомлений:\n"
            f"• Quiet hours: {quiet_hours}\n"
            f"• Daily cap: {daily_cap}\n"
            f"• Минимальная уверенность: {confidence_text}\n"
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
                "• /confidence 0.75 или /confidence off",
                "• /markethours on или /markethours off",
            ]
        )
        return "\n".join(lines)

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

    def _portfolio_analysis(self, tickers: list[str]) -> str:
        """Analyze portfolio correlation and concentration."""
        # Calculate correlation matrix
        matrix = calculate_correlation_matrix(tickers, lookback_days=90)

        if not matrix:
            return (
                f"❌ Не удалось получить корреляционные данные.\n"
                f"Проверь наличие цен для: {', '.join(tickers)}"
            )

        insights = correlation_insights(matrix)

        result = [
            f"📊 Анализ портфеля ({len(matrix.tickers)} акций)",
            "",
        ]

        result.extend(insights)

        # Show some pair correlations
        high_pairs = matrix.high_correlation_pairs(threshold=0.7)
        if high_pairs:
            result.append("")
            result.append("🔗 Высокие корреляции:")
            for pair in high_pairs[:5]:
                result.append(f"  {pair.ticker1}/{pair.ticker2}: {pair.correlation:.2f}")

        return "\n".join(result)
