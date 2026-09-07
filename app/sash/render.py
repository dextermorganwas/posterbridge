# app/sash/render.py
#
# Draws the sash: a thin line running the full width of the poster near the
# bottom, with a fully-rounded "pill" sitting on the line in the middle to
# hold the label text.
#
# v2: replaced the original hand-rolled polygon/arc math (which produced a
# bloated, broken-looking blob) with PIL's own ImageDraw.rounded_rectangle
# for the pill — a plain capsule shape (radius = half its own height) is a
# far more robust way to get a clean rounded tab than manually building the
# outline point-by-point.
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from app.config import SASH_HEIGHT_RATIO, SASH_FONT_SIZE_RATIO, SASH_BASELINE_HEIGHT_RATIO
from app.sash.color import sash_colors

_FONT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "fonts", "Inter-Bold.ttf",
)
_SS = 3  # supersample factor for crisp curves/text

# How far above the poster's bottom edge the line sits, as a fraction of
# poster height.
_BOTTOM_INSET_RATIO = 0.045
# Horizontal padding inside the pill, either side of the text, as a
# multiple of the pill's own height.
_PILL_H_PAD_RATIO = 0.85
# Pill can grow up to this fraction of the poster's width for long labels.
_MAX_PILL_WIDTH_RATIO = 0.62


def _load_font(size_px: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(_FONT_PATH, size_px)
    except IOError:
        return ImageFont.load_default()


def draw_sash(image: Image.Image, label: str) -> Image.Image:
    """Composite the sash onto *image* and return the result (RGBA)."""
    width, height = image.size
    fill, ink = sash_colors(image)

    ss_w, ss_h = width * _SS, height * _SS
    canvas = Image.new("RGBA", (ss_w, ss_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    pill_h = height * SASH_HEIGHT_RATIO * _SS
    line_h = max(_SS, height * SASH_BASELINE_HEIGHT_RATIO * _SS)
    # Line's vertical center — the pill's bottom edge aligns to this, so the
    # line reads as growing directly out of the base of the pill.
    line_cy = ss_h - (height * _BOTTOM_INSET_RATIO * _SS)

    font_px = max(10 * _SS, int(pill_h * SASH_FONT_SIZE_RATIO))
    font = _load_font(font_px)

    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pill_w = max(pill_h * 1.8, text_w + pill_h * _PILL_H_PAD_RATIO)
    pill_w = min(pill_w, ss_w * _MAX_PILL_WIDTH_RATIO)

    cx = ss_w / 2
    pill_bottom = line_cy + line_h / 2
    pill_top = pill_bottom - pill_h
    pill_left = cx - pill_w / 2
    pill_right = cx + pill_w / 2

    # Thin baseline, full width, drawn first so the pill sits on top of it.
    draw.rectangle(
        [(0, line_cy - line_h / 2), (ss_w, line_cy + line_h / 2)],
        fill=(*fill, 255),
    )

    # The pill — a plain capsule (corner radius = half its height).
    draw.rounded_rectangle(
        [(pill_left, pill_top), (pill_right, pill_bottom)],
        radius=pill_h / 2,
        fill=(*fill, 255),
    )

    # Label, centred in the pill.
    tx = cx - text_w / 2 - bbox[0]
    ty = (pill_top + pill_bottom) / 2 - text_h / 2 - bbox[1]
    draw.text((tx, ty), label, font=font, fill=(*ink, 250))

    overlay = canvas.resize((width, height), Image.Resampling.LANCZOS)
    result = image.convert("RGBA")
    result.alpha_composite(overlay)
    return result
