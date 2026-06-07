from __future__ import annotations

from typing import Any

from app.services.research_labels import research_label_to_russian


class DisclaimerMixin:
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

    def _data_quality_warning_lines(self, data_quality: Any) -> list[str]:
        if not data_quality:
            return []

        def _get(name: str, default: Any = None) -> Any:
            if isinstance(data_quality, dict):
                return data_quality.get(name, default)
            return getattr(data_quality, name, default)

        lines: list[str] = []
        summary = _get("summary")
        if summary:
            lines.append(self._translate_text(str(summary)))

        confidence = _get("confidence", 1.0)
        if isinstance(confidence, (int, float)) and confidence < 0.8:
            lines.append(f"Низкая уверенность данных: {confidence:.2f}")

        if _get("source_disagreed"):
            lines.append("Источники не совпадают между собой.")
        if _get("stale"):
            lines.append("Данные выглядят устаревшими.")
        if _get("delayed"):
            lines.append("Поток данных может запаздывать.")
        if _get("missing"):
            lines.append("Есть пропуски в исходных данных.")
        if _get("estimated"):
            lines.append("Часть значений оценочная, а не подтверждённая.")
        if _get("split_detected"):
            lines.append("Обнаружен сплит (данные в raw-close).")
        if _get("dividend_detected"):
            lines.append("Обнаружен дивиденд (данные в raw-close).")
        missing_candles = _get("missing_candles", 0)
        if isinstance(missing_candles, (int, float)) and missing_candles > 0:
            lines.append(f"Обнаружено пропущенных торговых дней: {int(missing_candles)}.")
        if _get("partial_session"):
            lines.append("Обнаружена неполная торговая сессия.")
        adj_policy = _get("adjustment_policy_warning")
        if adj_policy:
            lines.append(f"Цены без коррекции: {adj_policy}.")
        return lines

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
