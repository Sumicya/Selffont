#!/usr/bin/env python3
"""Normalise an install copy's vertical line metrics to the Android carrier.

Why this exists: a compact fixed-height slot (notification group count, red-dot
badge, clock, chip) MEASURES its slot with the nominal Roboto metrics carrier but
DRAWS the number with the next fallback -- our own face, whose real hhea
ascent/descent are larger. Skia takes Paint font metrics from hhea (or the typo
pair when USE_TYPO_METRICS is set), so the baseline is pushed down and the ink
overshoots the slot.

The fix scales the face's own hhea/typo line metrics to the carrier's nominal
metrics, so measure-with-nominal and draw-with-fallback agree. Outlines, cmap,
family name, hinting and weight stay untouched; usWinAscent/Descent keep covering
the real ink box so nothing is cropped. A build-time guard refuses a font whose
normalised envelope would clip the digit ink that caused the report.
"""
import io

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

USE_TYPO_METRICS = 0x80

# Characters seen in the compact fixed-height slots. Their ink must stay inside
# the normalised line box or the build fails.
STRICT_INK = "0123456789"
# Broader Latin: reported, not a hard failure.
LATIN_INK = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


class ClipError(ValueError):
    """Raised when normalised metrics would clip glyph ink that must stay visible."""


def _ink_bounds(font, characters):
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap() or {}
    result = {}
    for character in characters:
        name = cmap.get(ord(character))
        if not name or name not in glyphs:
            continue
        pen = BoundsPen(glyphs)
        glyphs[name].draw(pen)
        if pen.bounds is not None:
            result[character] = pen.bounds  # (xMin, yMin, xMax, yMax)
    return result


def _envelope(bounds):
    if not bounds:
        return None
    return min(b[1] for b in bounds.values()), max(b[3] for b in bounds.values())


def _glyph_signature(font_bytes):
    """Identity of everything that must NOT change during normalisation."""
    font = TTFont(io.BytesIO(font_bytes), recalcBBoxes=False, recalcTimestamp=False)
    glyf = font["glyf"]
    return {
        "glyphOrder": font.getGlyphOrder(),
        "glyphs": {name: glyf[name].compile(glyf) for name in font.getGlyphOrder()},
        "cmap": font.getBestCmap(),
        "family": font["name"].getDebugName(1),
        "weight": font["OS/2"].usWeightClass,
    }


def assert_glyphs_preserved(original_bytes, normalized_bytes):
    """Fail unless only vertical line metrics changed between the two fonts."""
    before = _glyph_signature(original_bytes)
    after = _glyph_signature(normalized_bytes)
    if before["glyphOrder"] != after["glyphOrder"]:
        raise ValueError("Glyph order changed during metric normalization")
    if before["glyphs"] != after["glyphs"]:
        changed = [n for n in before["glyphs"] if before["glyphs"].get(n) != after["glyphs"].get(n)]
        raise ValueError(f"Glyph outlines changed during normalization: {changed[:8]}")
    if before["cmap"] != after["cmap"]:
        raise ValueError("cmap changed during metric normalization")
    if before["family"] != after["family"]:
        raise ValueError("Family name changed during metric normalization")
    if before["weight"] != after["weight"]:
        raise ValueError("Static weight changed during metric normalization")


def normalize_metrics(font_bytes, carrier_metrics):
    """Return (normalised bytes, report) for one verified install face."""
    font = TTFont(io.BytesIO(font_bytes), recalcBBoxes=False, recalcTimestamp=False)
    head, hhea, os2 = font["head"], font["hhea"], font["OS/2"]
    upm = head.unitsPerEm
    carrier_upm = carrier_metrics["unitsPerEm"]
    if upm <= 0 or carrier_upm <= 0:
        raise ValueError("Invalid units-per-em on font or carrier")

    c_asc, c_desc, c_gap = carrier_metrics["hhea"]
    asc, desc, gap = (round(value * upm / carrier_upm) for value in (c_asc, c_desc, c_gap))
    if asc <= 0 or desc >= 0:
        raise ValueError("Carrier nominal metrics are not a valid ascent/descent pair")

    original = {
        "unitsPerEm": upm,
        "hhea": [hhea.ascent, hhea.descent, hhea.lineGap],
        "typo": [os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap],
        "win": [os2.usWinAscent, os2.usWinDescent],
        "useTypoMetrics": bool(os2.fsSelection & USE_TYPO_METRICS),
    }

    strict_env = _envelope(_ink_bounds(font, STRICT_INK))
    if strict_env is None:
        raise ClipError("No digit ink found to validate the normalised envelope")
    ink_min, ink_max = strict_env
    if ink_max > asc or ink_min < desc:
        raise ClipError(
            "Normalised line box would clip digit ink: "
            f"ink=[{ink_min},{ink_max}] box=[{desc},{asc}]"
        )
    latin_env = _envelope(_ink_bounds(font, LATIN_INK))

    hhea.ascent, hhea.descent, hhea.lineGap = asc, desc, gap
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = asc, desc, gap
    # Match the carrier's USE_TYPO_METRICS flag so either metric path agrees.
    # Bit 7 is only defined in OS/2 version 4+, so raise the version if needed.
    if carrier_metrics.get("useTypoMetrics"):
        os2.version = max(os2.version, 4)
        os2.fsSelection |= USE_TYPO_METRICS
    else:
        os2.fsSelection &= ~USE_TYPO_METRICS
    os2.usWinAscent = max(asc, head.yMax, ink_max)
    os2.usWinDescent = max(-desc, -head.yMin, -ink_min)

    out = io.BytesIO()
    font.save(out)
    normalized = out.getvalue()
    report = {
        "unitsPerEm": upm,
        "carrierUnitsPerEm": carrier_upm,
        "original": original,
        "normalized": {
            "hhea": [asc, desc, gap],
            "typo": [asc, desc, gap],
            "win": [os2.usWinAscent, os2.usWinDescent],
            "useTypoMetrics": bool(os2.fsSelection & USE_TYPO_METRICS),
        },
        "digitInkY": [ink_min, ink_max],
        "latinInkY": list(latin_env) if latin_env else None,
        "fontBBoxY": [head.yMin, head.yMax],
    }
    return normalized, report
