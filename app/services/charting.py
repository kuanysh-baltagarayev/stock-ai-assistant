"""Price chart rendering — returns PNG bytes for Telegram sendPhoto.

Uses Pillow directly instead of matplotlib to avoid a deepcopy recursion
bug in matplotlib 3.x + Python 3.14 (github.com/matplotlib/matplotlib/issues).
"""
from __future__ import annotations

import io

import pandas as pd
from PIL import Image, ImageDraw

_MA_SHORT = 50
_MA_LONG = 200
_W, _H = 900, 450
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 70, 20, 40, 50
_PLOT_W = _W - _PAD_L - _PAD_R
_PLOT_H = _H - _PAD_T - _PAD_B

_BG = (30, 30, 46)
_PRICE_COLOR = (137, 180, 250)
_MA50_COLOR = (166, 227, 161)
_MA200_COLOR = (250, 179, 135)
_GRID_COLOR = (69, 71, 90)
_TEXT_COLOR = (205, 214, 244)


def render_price_chart(ticker: str, history: pd.DataFrame) -> bytes:
    """Return PNG bytes of a close-price chart with MA50/MA200 overlays."""
    close = history["Close"].dropna()
    if close.empty:
        return _error_png(f"{ticker}: нет данных")

    n = len(close)
    values = close.values.astype(float)
    lo, hi = float(values.min()), float(values.max())
    if hi == lo:
        hi = lo + 1.0

    ma50 = _rolling_mean(values, _MA_SHORT)
    ma200 = _rolling_mean(values, _MA_LONG)

    img = Image.new("RGB", (_W, _H), _BG)
    draw = ImageDraw.Draw(img)

    # Grid lines
    for i in range(5):
        y = _PAD_T + int(_PLOT_H * i / 4)
        draw.line([(_PAD_L, y), (_W - _PAD_R, y)], fill=_GRID_COLOR, width=1)
        price_label = f"{hi - (hi - lo) * i / 4:.1f}"
        draw.text((_PAD_L - 65, y - 7), price_label, fill=_TEXT_COLOR)

    # Polylines
    def _points(series: list[float | None]) -> list[tuple[int, int]]:
        pts = []
        for idx, v in enumerate(series):
            if v is None:
                continue
            x = _PAD_L + int(_PLOT_W * idx / max(n - 1, 1))
            y = _PAD_T + int(_PLOT_H * (1 - (v - lo) / (hi - lo)))
            pts.append((x, y))
        return pts

    _polyline(draw, _points(list(values)), _PRICE_COLOR, 2)
    if ma50:
        _polyline(draw, _points(ma50), _MA50_COLOR, 1)
    if ma200:
        _polyline(draw, _points(ma200), _MA200_COLOR, 1)

    # X-axis date labels (up to 6)
    if hasattr(close.index, 'to_pydatetime'):
        dates = [d.date() if hasattr(d, 'date') else d for d in close.index]
        step = max(1, n // 6)
        for i in range(0, n, step):
            x = _PAD_L + int(_PLOT_W * i / max(n - 1, 1))
            label = str(dates[i])[2:7]  # YY-MM
            draw.text((x - 15, _H - _PAD_B + 5), label, fill=_TEXT_COLOR)

    # Title
    last = float(values[-1])
    title = f"{ticker.upper()}   ${last:.2f}"
    if ma50 and ma50[-1] is not None:
        title += f"   MA50 ${ma50[-1]:.1f}"
    if ma200 and ma200[-1] is not None:
        title += f"   MA200 ${ma200[-1]:.1f}"
    draw.text((_PAD_L, 10), title, fill=_TEXT_COLOR)

    # Legend
    draw.line([(_PAD_L, _H - 10), (_PAD_L + 20, _H - 10)], fill=_PRICE_COLOR, width=2)
    draw.text((_PAD_L + 25, _H - 18), "Цена", fill=_PRICE_COLOR)
    if ma50:
        draw.line([(_PAD_L + 80, _H - 10), (_PAD_L + 100, _H - 10)], fill=_MA50_COLOR, width=2)
        draw.text((_PAD_L + 105, _H - 18), "MA50", fill=_MA50_COLOR)
    if ma200:
        draw.line([(_PAD_L + 165, _H - 10), (_PAD_L + 185, _H - 10)], fill=_MA200_COLOR, width=2)
        draw.text((_PAD_L + 190, _H - 18), "MA200", fill=_MA200_COLOR)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def _rolling_mean(values: list[float], window: int) -> list[float | None]:
    if len(values) < window:
        return []
    result: list[float | None] = [None] * (window - 1)
    for i in range(window - 1, len(values)):
        result.append(float(sum(values[i - window + 1:i + 1]) / window))
    return result


def _polyline(draw: ImageDraw.ImageDraw, pts: list[tuple[int, int]], color: tuple, width: int) -> None:
    if len(pts) < 2:
        return
    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i + 1]], fill=color, width=width)


def _error_png(message: str) -> bytes:
    img = Image.new("RGB", (_W, _H), _BG)
    ImageDraw.Draw(img).text((20, _H // 2), message, fill=_TEXT_COLOR)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()
