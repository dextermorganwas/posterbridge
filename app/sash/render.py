# app/sash/render.py
#
# Draws the sash shape itself: a thin line running the full width of the
# poster near the bottom, with a tab in the middle that curves up to hold
# the label text, then curves back down into the line. New shape (not
# present in PostersPlus, which floats a standalone hanging badge from the
# *top* edge) — colour comes from app/sash/color.py, which does reuse
# PostersPlus's dominant-colour algorithm.
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFont

from app.config import SASH_HEIGHT_RATIO, SASH_FONT_SIZE_RATIO, SASH_BASELINE_HEIGHT_RATIO
from app.sash.color import sash_colors

_FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "fonts", "Inter-Bold.ttf")
_SS = 3  # supersample factor for crisp curves/text


def _load_font(size_px: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(_FONT_PATH, size_px)
    except IOError:
        return ImageFont.load_default()


def _tab_path(cx: float, tab_w: float, tab_h: float, line_y: float, radius: float) -> list[tuple[float, float]]:
    """Points tracing the tab outline: up from the baseline on the left,
    across the flat top, down the right side, with rounded corners where the
    tab meets the vertical rise, back into the thin line."""
    left = cx - tab_w / 2
    right = cx + tab_w / 2
    top = line_y - tab_h
    pts: list[tuple[float, float]] = []

    def arc(cx_, cy_, r, a0, a1, steps=10):
        for i in range(steps + 1):
            a = a0 + (a1 - a0) * (i / steps)
            pts.append((cx_ + r * math.cos(a), cy_ + r * math.sin(a)))

    # Start at bottom-left of the tab's rise, sweep up-and-in (concave curve
    # into the underside of the tab), along the flat top, then back down.
    r = radius
    pts.append((left - r, line_y))
    arc(left, line_y - r, r, math.pi / 2, 0, steps=8)          # curve up into the tab, left side
    pts.append((left, top))
    pts.append((right, top))
    arc(right, line_y - r, r, math.pi, math.pi / 2, steps=8)   # curve back down, right side
    pts.append((right + r, line_y))
    return pts


def draw_sash(image: Image.Image, label: str) -> Image.Image:
    """Composite the sash onto *image* (already RGBA) and return the result."""
    width, height = image.size
    fill, ink = sash_colors(image)

    tab_h = int(height * SASH_HEIGHT_RATIO)
    line_h = max(1, int(height * SASH_BASELINE_HEIGHT_RATIO))
    line_y = height - int(height * 0.035) - line_h  # small inset from the bottom edge

    font_px = max(10, int(tab_h * SASH_FONT_SIZE_RATIO)) * _SS
    font = _load_font(font_px)

    ss_canvas = Image.new("RGBA", (width * _SS, height * _SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(ss_canvas)

    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    h_pad = tab_h * _SS * 0.9
    tab_w = max(tab_h * _SS * 2.4, text_w + h_pad)
    tab_w = min(tab_w, width * _SS * 0.7)
    radius = tab_h * _SS * 0.55

    cx = width * _SS / 2
    line_y_ss = line_y * _SS
    tab_h_ss = tab_h * _SS

    # Thin baseline across the full width.
    draw.rectangle(
        [(0, line_y_ss), (width * _SS, line_y_ss + line_h * _SS)],
        fill=(*fill, 235),
    )

    # Tab.
    poly = _tab_path(cx, tab_w, tab_h_ss, line_y_ss, radius)
    draw.polygon(poly, fill=(*fill, 235))

    # Label, centred in the tab.
    try:
        ascent, descent = font.getmetrics()
    except AttributeError:
        ascent, descent = font_px, 0
    text_cy = line_y_ss - tab_h_ss / 2
    tx = cx - text_w / 2 - bbox[0]
    ty = text_cy - (ascent + descent) / 2 - descent + int(ascent * 0.22)
    draw.text((tx, ty), label, font=font, fill=(*ink, 250))

    overlay = ss_canvas.resize((width, height), Image.Resampling.LANCZOS)
    result = image.convert("RGBA")
    result.alpha_composite(overlay)
    return result
