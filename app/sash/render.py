# app/sash/render.py
#
# Draws the sash: a thin line running the full width of the poster near the
# bottom, with a rounded-rectangle "pill" sitting on the line in the middle
# to hold the label text. A soft drop shadow sits behind the whole shape so
# it stays legible even when the sash's own (dominant-colour-derived) fill
# is close in colour to whatever's directly behind it on the poster.
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.config import SASH_HEIGHT_RATIO, SASH_FONT_SIZE_RATIO, SASH_BASELINE_HEIGHT_RATIO, SASH_FONT
from app.sash.color import sash_colors

_FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "fonts",
)
DEFAULT_FONT = SASH_FONT
_SS = 3  # supersample factor for crisp curves/text
# Extra tracking (letter-spacing) between characters, as a fraction of font
# size. PIL has no built-in letter-spacing, so text is drawn glyph-by-glyph.
_TRACKING_RATIO = 0.02

# How far above the poster's bottom edge the line sits, as a fraction of
# poster height.
_BOTTOM_INSET_RATIO = 0.011
# Horizontal padding inside the pill, either side of the text, as a
# multiple of the pill's own height.
_PILL_H_PAD_RATIO = 0.45
# Pill can grow up to this fraction of the poster's width for long labels.
_MAX_PILL_WIDTH_RATIO = 0.62
# Corner radius as a fraction of the pill's own height — small, so the pill
# reads as a rounded rectangle/tag rather than a full stadium/capsule.
_PILL_RADIUS_RATIO = 0.12
# Drop shadow so the sash stays visible even against a similarly-coloured
# background (e.g. a fill picked from a dark sweater sitting on that same
# dark sweater). Both as a multiple of the pill's own height.
_SHADOW_BLUR_RATIO = 0.28
_SHADOW_OFFSET_RATIO = 0.10
_SHADOW_ALPHA = 130


def _load_font(size_px: int, font_name: str) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(os.path.join(_FONT_DIR, font_name), size_px)
    except IOError:
        return ImageFont.load_default()


def _tracked_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, tracking: float) -> float:
    total = 0.0
    for ch in text:
        total += draw.textlength(ch, font=font) + tracking
    return max(0.0, total - tracking)


def _draw_tracked(
    draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str,
    font: ImageFont.FreeTypeFont, fill: tuple[int, int, int, int], tracking: float,
) -> None:
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking


def draw_sash(image: Image.Image, label: str, *, font_name: str = DEFAULT_FONT) -> Image.Image:
    """Composite the sash onto *image* and return the result (RGBA)."""
    width, height = image.size
    fill, ink = sash_colors(image)

    ss_w, ss_h = width * _SS, height * _SS
    # Shape (pill + line) is drawn on its own layer first so a shadow can be
    # derived from its silhouette, independent of the fill colour.
    shape_layer = Image.new("RGBA", (ss_w, ss_h), (0, 0, 0, 0))
    shape_draw = ImageDraw.Draw(shape_layer)
    measure_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    pill_h = height * SASH_HEIGHT_RATIO * _SS
    line_h = max(_SS, height * SASH_BASELINE_HEIGHT_RATIO * _SS)
    # Line's vertical center — the pill's bottom edge aligns to this, so the
    # line reads as growing directly out of the base of the pill.
    line_cy = ss_h - (height * _BOTTOM_INSET_RATIO * _SS)

    font_px = max(10 * _SS, int(pill_h * SASH_FONT_SIZE_RATIO))
    font = _load_font(font_px, font_name)
    tracking = font_px * _TRACKING_RATIO
    label_upper = label.upper()

    text_w = _tracked_width(measure_draw, label_upper, font, tracking)
    ascent, descent = font.getmetrics()
    text_h = ascent + descent

    pill_w = max(pill_h * 1.8, text_w + pill_h * _PILL_H_PAD_RATIO)
    pill_w = min(pill_w, ss_w * _MAX_PILL_WIDTH_RATIO)

    cx = ss_w / 2
    pill_bottom = line_cy + line_h / 2
    pill_top = pill_bottom - pill_h
    pill_left = cx - pill_w / 2
    pill_right = cx + pill_w / 2

    # Thin baseline, full width, drawn first so the pill sits on top of it.
    shape_draw.rectangle(
        [(0, line_cy - line_h / 2), (ss_w, line_cy + line_h / 2)],
        fill=(*fill, 255),
    )

    # The pill — rounded on the top two corners only, flat across the
    # bottom so it flows directly into the line rather than floating above
    # it as a separate rounded shape.
    shape_draw.rounded_rectangle(
        [(pill_left, pill_top), (pill_right, pill_bottom)],
        radius=pill_h * _PILL_RADIUS_RATIO,
        fill=(*fill, 255),
        corners=(True, True, False, False),
    )

    # Drop shadow: a blurred, darkened, downward-offset copy of the shape's
    # own silhouette — keeps the sash readable even when its fill colour is
    # close to whatever's directly behind it.
    shadow_alpha = shape_layer.split()[3].point(lambda a: min(a, _SHADOW_ALPHA))
    shadow = Image.new("RGBA", (ss_w, ss_h), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 255), mask=shadow_alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(pill_h * _SHADOW_BLUR_RATIO))

    canvas = Image.new("RGBA", (ss_w, ss_h), (0, 0, 0, 0))
    canvas.alpha_composite(shadow, (0, int(pill_h * _SHADOW_OFFSET_RATIO)))
    canvas.alpha_composite(shape_layer)

    # Label, centred in the pill (tracked/letter-spaced).
    draw = ImageDraw.Draw(canvas)
    tx = cx - text_w / 2
    ty = (pill_top + pill_bottom) / 2 - text_h / 2
    _draw_tracked(draw, (tx, ty), label_upper, font, (*ink, 250), tracking)

    overlay = canvas.resize((width, height), Image.Resampling.LANCZOS)
    result = image.convert("RGBA")
    result.alpha_composite(overlay)
    return result
