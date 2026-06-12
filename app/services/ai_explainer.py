import json
from typing import Any

from app.config import get_settings
from app.services.runtime_budget import RuntimeBudgetExceeded, consume_runtime_budget


def explain_analysis(analysis_payload: dict[str, Any], reasons: list[str], language: str = "ru") -> str:
    settings = get_settings()
    api_key = settings.deepseek_api_key or settings.openai_api_key
    if not api_key:
        return rule_based_explanation(analysis_payload, reasons, language=language)

    try:
        consume_runtime_budget("openai_calls", settings.openai_call_budget)
        return _llm_explanation(analysis_payload, reasons, api_key=api_key, language=language)
    except RuntimeBudgetExceeded:
        lang = _normalize_language(language)
        fallback = rule_based_explanation(analysis_payload, reasons, language=language)
        return f"{fallback} {_fallback_note(lang, 'budget')}"
    except Exception:
        lang = _normalize_language(language)
        fallback = rule_based_explanation(analysis_payload, reasons, language=language)
        return f"{fallback} {_fallback_note(lang, 'unavailable')}"


def rule_based_explanation(analysis_payload: dict[str, Any], reasons: list[str], language: str = "ru") -> str:
    ticker = analysis_payload["ticker"]
    final_score = analysis_payload["scores"]["final_score"]
    price = analysis_payload.get("price")
    language = _normalize_language(language)
    if language == "en":
        reason_text_en = "; ".join(reasons[:3]) if reasons else "not enough signals for a conclusion"
        sector = analysis_payload.get("fundamentals", {}).get("sector")
        lines = [
            f"📊 {ticker} — {_score_desc_en(final_score)}.",
            f"{f'Price around ${price:.2f}. ' if price else ''}Overall score {final_score:.0f}/100 — {_score_meaning_en(final_score)}.",
            f"What mattered: {reason_text_en}.",
        ]
        if sector:
            lines.append(f"Sector: {sector}.")
        lines.append("ℹ️ This is a research signal, not financial advice.")
        return " ".join(lines)
    if language == "kk":
        reason_text_kk = "; ".join(reasons[:3]) if reasons else "қорытынды жасауға сигнал жеткіліксіз"
        sector = analysis_payload.get("fundamentals", {}).get("sector")
        lines = [
            f"📊 {ticker} — {_score_desc_kk(final_score)}.",
            f"{f'Баға шамамен ${price:.2f}. ' if price else ''}Жалпы баға {final_score:.0f}/100 — {_score_meaning_kk(final_score)}.",
            f"Не әсер етті: {reason_text_kk}.",
        ]
        if sector:
            lines.append(f"Сектор: {sector}.")
        lines.append("ℹ️ Бұл зерттеу сигналы, қаржылық кеңес емес.")
        return " ".join(lines)

    # Score interpretation — conversational, no marketing.
    if final_score >= 80:
        score_desc = "выглядит привлекательно"
    elif final_score >= 60:
        score_desc = "выглядит неплохо"
    elif final_score >= 40:
        score_desc = "нейтральная картина"
    elif final_score >= 20:
        score_desc = "есть поводы для осторожности"
    else:
        score_desc = "выглядит рискованно"

    price_part = f"Цена около ${price:.2f}. " if price else ""

    if reasons:
        reason_text = _translate_reason_text("; ".join(reasons[:3]))
    else:
        reason_text = "недостаточно сигналов для вывода"

    lines = [
        f"📊 {ticker} — {score_desc}.",
        f"{price_part}Общая оценка {final_score:.0f} из 100 — {_score_meaning(final_score)}.",
        f"Что повлияло: {reason_text}.",
    ]

    sector = analysis_payload.get("fundamentals", {}).get("sector")
    if sector:
        lines.append(f"Сектор: {sector}.")

    lines.append("ℹ️ Это аналитический сигнал для исследования, а не рекомендация.")
    return " ".join(lines)


def _score_meaning(score: float) -> str:
    if score >= 85:
        return "акция привлекла внимание по нескольким параметрам"
    if score >= 70:
        return "есть несколько позитивных сигналов"
    if score >= 55:
        return "картина смешанная, без явного перевеса"
    if score >= 35:
        return "есть факторы, которые настораживают"
    if score >= 15:
        return "больше негативных сигналов, чем позитивных"
    return "преобладают негативные факторы — стоит быть осторожным"


def _normalize_language(language: str | None) -> str:
    lang = (language or "ru").strip().lower()
    if lang.startswith("en"):
        return "en"
    if lang.startswith(("kk", "kz", "kaz")):
        return "kk"
    return "ru"


def _score_desc_en(score: float) -> str:
    if score >= 80:
        return "looks interesting"
    if score >= 60:
        return "looks reasonably constructive"
    if score >= 40:
        return "has a mixed setup"
    if score >= 20:
        return "has reasons for caution"
    return "looks risky"


def _score_meaning_en(score: float) -> str:
    if score >= 85:
        return "several metrics stand out"
    if score >= 70:
        return "there are multiple positive signals"
    if score >= 55:
        return "the picture is mixed"
    if score >= 35:
        return "some factors are concerning"
    if score >= 15:
        return "negative signals outweigh positives"
    return "negative factors dominate"


def _score_desc_kk(score: float) -> str:
    if score >= 80:
        return "қызықты көрінеді"
    if score >= 60:
        return "жаман емес көрінеді"
    if score >= 40:
        return "аралас көрініс"
    if score >= 20:
        return "сақтық қажет"
    return "тәуекелі жоғары көрінеді"


def _score_meaning_kk(score: float) -> str:
    if score >= 85:
        return "бірнеше көрсеткіш назар аударады"
    if score >= 70:
        return "бірнеше оң сигнал бар"
    if score >= 55:
        return "көрініс аралас"
    if score >= 35:
        return "алаңдататын факторлар бар"
    if score >= 15:
        return "теріс сигналдар басым"
    return "теріс факторлар басым"


def _fallback_note(language: str, reason: str) -> str:
    if language == "en":
        if reason == "budget":
            return "The LLM call budget is exhausted, so the rule-based version was used."
        return "The LLM explanation is unavailable, so the rule-based version was used."
    if language == "kk":
        if reason == "budget":
            return "LLM шақыру лимиті таусылды, сондықтан rule-based нұсқа қолданылды."
        return "LLM түсіндірмесі қолжетімсіз, сондықтан rule-based нұсқа қолданылды."
    if reason == "budget":
        return "Лимит LLM-вызовов исчерпан, поэтому использован rule-based вариант."
    return "Объяснение от LLM недоступно, поэтому использован rule-based вариант."


def _llm_explanation(
    analysis_payload: dict[str, Any],
    reasons: list[str],
    api_key: str,
    language: str = "ru",
) -> str:
    from openai import OpenAI

    settings = get_settings()
    provider = (settings.llm_provider or "openai").lower()

    # Determine base_url and model based on provider.
    if provider == "deepseek":
        base_url = settings.llm_api_base_url or "https://api.deepseek.com"
        model = "deepseek-chat"
    else:
        base_url = settings.llm_api_base_url or "https://api.openai.com/v1"
        model = settings.openai_model or "gpt-4.1-mini"

    client = OpenAI(api_key=api_key, base_url=base_url)
    language = _normalize_language(language)
    language_instruction = {
        "ru": "Пишите на русском языке.",
        "en": "Write in English.",
        "kk": "Қазақ тілінде жазыңыз.",
    }[language]

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
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Вы объясняете результаты количественного анализа акций для частного пользователя. "
                    "Используйте только JSON-данные, предоставленные приложением. Не выдумывайте, "
                    "не оценивайте и не добавляйте числа от себя. Пишите кратко. "
                    f"{language_instruction} Укажите, что это "
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
        return rule_based_explanation(analysis_payload, reasons, language=language)
    return text.strip()


def _translate_reason_text(text: str) -> str:
    replacements = {
        "price is above MA50": "цена выше среднего за 50 дней — тренд вверх",
        "price is below MA50": "цена ниже среднего за 50 дней — тренд вниз",
        "price is above MA200": "цена выше среднего за 200 дней — долгосрочный тренд вверх",
        "price is below MA200": "цена ниже среднего за 200 дней — долгосрочный тренд вниз",
        "1-month momentum is positive": "за месяц динамика положительная",
        "1-month momentum is weak": "за месяц динамика слабая",
        "6-month trend is strong": "полугодовой тренд уверенный",
        "6-month trend is weak": "полугодовой тренд слабый",
        "RSI shows strong overheating": "RSI показывает сильный перегрев — возможна коррекция",
        "RSI is overbought": "RSI в зоне перекупленности",
        "RSI is deeply oversold": "RSI в зоне сильной перепроданности",
        "RSI may indicate oversold conditions": "RSI намекает на перепроданность",
        "trailing P/E is not meaningful": "мультипликатор P/E неинформативен (убытки?)",
        "valuation looks inexpensive by trailing P/E": "по мультипликатору P/E акция выглядит недорого",
        "valuation looks reasonable by trailing P/E": "P/E на разумном уровне",
        "trailing P/E is very high": "P/E очень высокий — рынок закладывает сильный рост",
        "trailing P/E is elevated": "P/E повышенный",
        "forward P/E is high": "ожидаемый P/E высокий",
        "forward P/E is lower than trailing P/E": "ожидаемая прибыль растёт (forward P/E ниже текущего)",
        "revenue growth is strong": "выручка уверенно растёт",
        "revenue growth is positive": "выручка растёт",
        "revenue growth is negative": "выручка падает",
        "profit margins are strong": "маржинальность высокая — компания эффективна",
        "profit margins are healthy": "маржинальность на здоровом уровне",
        "profit margins are negative": "компания работает в убыток",
        "debt/equity is high": "долговая нагрузка высокая",
        "debt/equity is elevated": "долговая нагрузка повышена",
        "debt/equity is conservative": "долговая нагрузка низкая — финансы в порядке",
        "volatility is low": "волатильность низкая — цена стабильна",
        "volatility is very high": "волатильность очень высокая — возможны резкие движения",
        "volatility is elevated": "волатильность повышена",
        "max drawdown is limited": "максимальная просадка небольшая",
        "max drawdown is severe": "историческая просадка серьёзная",
        "max drawdown is large": "просадка значительная",
        "overbought RSI adds short-term risk": "RSI перекуплен — повышен риск краткосрочной коррекции",
        "daily move is unusually large": "дневное движение необычно большое",
        "multiple high-impact macro events are imminent": "на этой неделе несколько важных макро-событий",
        "two high-impact macro events are imminent": "на этой неделе два важных макро-события",
        "a high-impact macro event is imminent": "на этой неделе важное макро-событие",
        "earnings are imminent and can sharply raise event risk": "отчётность на носу — возможны резкие движения",
        "upcoming earnings keep event risk elevated": "предстоящий отчёт добавляет неопределённости",
        "earnings are approaching": "приближается отчётность",
        "recent 8-K adds event risk": "свежая форма 8-K — компания сообщила о важном событии",
        "recent 8-K still adds event risk": "недавняя форма 8-K все еще добавляет событийный риск",
        "fresh 10-Q adds reporting-event risk": "свежий отчет 10-Q добавляет риск отчетного события",
        "recent 10-Q keeps reporting risk elevated": "недавний 10-Q сохраняет повышенный риск отчетности",
        "fresh 10-K adds annual-report event risk": "свежий 10-K добавляет риск годовой отчетности",
        "recent 10-K keeps event risk elevated": "недавний 10-K сохраняет повышенный событийный риск",
        "multiple near-term catalysts can amplify event risk": "несколько ближайших катализаторов могут усиливать событийный риск",
        " is rate-sensitive": " чувствителен к ставкам",
        " is more resilient to rising rates": " более устойчив к росту ставок",
        " is exposed to inflation pressure": " испытывает давление от инфляции",
        " can absorb inflation better": " лучше переносит инфляцию",
        " is economically sensitive": " чувствителен к экономическому циклу",
        " earnings reactions tend to be sharper": " обычно сильнее реагирует на отчетность",
        " earnings swings are often milder": " обычно слабее реагирует на отчетность",
        "not enough strong quantitative signals": "недостаточно сильных количественных сигналов",
    }

    translated = text
    for source, target in replacements.items():
        translated = translated.replace(source, target)
    return translated
