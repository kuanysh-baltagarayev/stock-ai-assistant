import json
from typing import Any

from app.config import get_settings
from app.services.research_labels import research_label_to_russian
from app.services.runtime_budget import RuntimeBudgetExceeded, consume_runtime_budget


def explain_analysis(analysis_payload: dict[str, Any], reasons: list[str]) -> str:
    settings = get_settings()
    if not settings.openai_api_key:
        return rule_based_explanation(analysis_payload, reasons)

    try:
        consume_runtime_budget("openai_calls", settings.openai_call_budget)
        return _openai_explanation(analysis_payload, reasons)
    except RuntimeBudgetExceeded:
        fallback = rule_based_explanation(analysis_payload, reasons)
        return f"{fallback} Лимит OpenAI-вызовов исчерпан, поэтому использован rule-based вариант."
    except Exception:
        fallback = rule_based_explanation(analysis_payload, reasons)
        return f"{fallback} Объяснение от LLM недоступно, поэтому использован rule-based вариант."


def rule_based_explanation(analysis_payload: dict[str, Any], reasons: list[str]) -> str:
    ticker = analysis_payload["ticker"]
    final_score = analysis_payload["scores"]["final_score"]
    recommendation = analysis_payload["recommendation"]
    reason_text = "; ".join(reasons[:5]) if reasons else "недостаточно сильных количественных сигналов"
    return (
        f"{ticker}: исследовательский сигнал { research_label_to_russian(recommendation) } "
        f"с итоговой оценкой {final_score}/100. "
        f"Основные факторы: {_translate_reason_text(reason_text)}. "
        f"Это исследовательский сигнал, а не финансовый совет."
    )


def _openai_explanation(analysis_payload: dict[str, Any], reasons: list[str]) -> str:
    from openai import OpenAI

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    compact_payload = {
        "ticker": analysis_payload["ticker"],
        "price": analysis_payload["price"],
        "currency": analysis_payload.get("currency"),
        "fundamentals": analysis_payload["fundamentals"],
        "technicals": analysis_payload["technicals"],
        "scores": analysis_payload["scores"],
        "recommendation": analysis_payload["recommendation"],
        "short_reason": analysis_payload["short_reason"],
        "calculated_reasons": reasons,
    }

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Вы объясняете результаты количественного анализа акций для частного пользователя. "
                    "Используйте только JSON-данные, предоставленные приложением. Не выдумывайте, "
                    "не оценивайте и не добавляйте числа от себя. Пишите кратко. Укажите, что это "
                    "аналитический сигнал, а не финансовый совет."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Объясните этот анализ акции простыми словами:\n"
                    f"{json.dumps(compact_payload, ensure_ascii=False, indent=2)}"
                ),
            },
        ],
    )
    text = response.choices[0].message.content if response.choices else None
    if not text:
        return rule_based_explanation(analysis_payload, reasons)
    return text.strip()


def _translate_reason_text(text: str) -> str:
    replacements = {
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
        "trailing P/E is not meaningful": "trailing P/E неинформативен",
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
    }

    translated = text
    for source, target in replacements.items():
        translated = translated.replace(source, target)
    return translated
