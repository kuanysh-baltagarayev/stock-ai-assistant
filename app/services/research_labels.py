from __future__ import annotations

NEUTRAL_RESEARCH_LABELS: tuple[str, ...] = (
    "HIGH_INTEREST",
    "WATCH",
    "NEUTRAL",
    "CAUTION",
    "HIGH_RISK",
)

_RUSSIAN_LABELS = {
    "HIGH_INTEREST": "Высокий интерес",
    "WATCH": "Наблюдение",
    "NEUTRAL": "Нейтрально",
    "CAUTION": "Осторожно",
    "HIGH_RISK": "Высокий риск",
}

_ENGLISH_LABELS = {
    "HIGH_INTEREST": "High interest",
    "WATCH": "Watch",
    "NEUTRAL": "Neutral",
    "CAUTION": "Caution",
    "HIGH_RISK": "High risk",
}

_KAZAKH_LABELS = {
    "HIGH_INTEREST": "Жоғары қызығушылық",
    "WATCH": "Бақылау",
    "NEUTRAL": "Бейтарап",
    "CAUTION": "Сақтық",
    "HIGH_RISK": "Жоғары тәуекел",
}

_LABELS_BY_LANGUAGE = {
    "ru": _RUSSIAN_LABELS,
    "en": _ENGLISH_LABELS,
    "kk": _KAZAKH_LABELS,
}


def research_label_for_score(final_score: float, risk_score: float) -> str:
    if final_score >= 80 and risk_score <= 55:
        return "HIGH_INTEREST"
    if final_score >= 68 and risk_score <= 70:
        return "WATCH"
    if final_score >= 52:
        return "NEUTRAL"
    if final_score >= 40:
        return "CAUTION"
    return "HIGH_RISK"


def research_label_to_russian(label: str) -> str:
    return _RUSSIAN_LABELS.get(label, label.replace("_", " ").title())


def research_label_to_title(label: str) -> str:
    return label.replace("_", " ").title()


def research_label_localized(label: str, language: str = "ru") -> str:
    table = _LABELS_BY_LANGUAGE.get(language, _RUSSIAN_LABELS)
    return table.get(label, label.replace("_", " ").title())
