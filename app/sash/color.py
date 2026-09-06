# app/sash/color.py
#
# Picks the sash's fill + text colour from the poster's own dominant colour.
# The clustering (_dominant_cluster / dominant_frost_rgb) is PostersPlus's
# (AGPLv3) algorithm, unchanged — see app/sash/awards_data.py and
# /NOTICE.md. The blend that turns that dominant colour into a *sash* fill
# (as opposed to PostersPlus's frosted-panel pastel) is new: colourless/very
# dark posters get a clean dark grey instead of being force-brightened, per
# spec.
from __future__ import annotations

import colorsys

from PIL import Image

from app.sash.awards_data import dominant_frost_rgb, _frost_ink

# Below this chroma (value * saturation) a poster region is treated as
# essentially black/white/grey — no hue worth building a tint from.
_CHROMA_FLOOR = 0.05
# Target lightness band for a genuine colour pick: bright enough to read as
# "that colour", not washed out to pastel.
_MIN_V = 0.32
_MAX_V = 0.60

_DARK_GRAY_FILL = (30, 30, 32)
_DARK_GRAY_INK = (225, 225, 228)


def _sample_region(image: Image.Image) -> Image.Image:
    """Bottom band of the poster, where the sash actually sits — the
    dominant-colour pick should reflect what's *behind* the sash, not the
    poster as a whole."""
    w, h = image.size
    top = max(0, int(h * 0.82))
    return image.crop((0, top, w, h))


def sash_colors(image: Image.Image) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Return ((fill_r, fill_g, fill_b), (ink_r, ink_g, ink_b)) for the sash."""
    region = _sample_region(image.convert("RGB"))
    dr, dg, db = dominant_frost_rgb(region, fallback=image.convert("RGB"))
    h, s, v = colorsys.rgb_to_hsv(dr / 255, dg / 255, db / 255)

    if v * s < _CHROMA_FLOOR:
        return _DARK_GRAY_FILL, _DARK_GRAY_INK

    v_out = min(_MAX_V, max(_MIN_V, v))
    s_out = min(1.0, s * 1.15)
    fr, fg, fb = (int(c * 255) for c in colorsys.hsv_to_rgb(h, s_out, v_out))
    ink = _frost_ink(fr, fg, fb)
    return (fr, fg, fb), ink
