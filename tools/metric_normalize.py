#!/usr/bin/env python3
"""Derive an install artifact whose vertical line metrics match the Android carrier.

Root cause of low/clipped compact digits (notification group counts, red-dot
badges, clock, chips): a control MEASURES its fixed slot with the nominal Roboto
metrics carrier, but DRAWS the number with the WenYuan fallback, whose real hhea
ascent/descent are larger. Skia derives Paint FontMetrics from hhea (or typo when
USE_TYPO_METRICS is set), so the baseline is pushed down by the larger fallback
ascent and the glyph ink overshoots the slot.

The fix normalises WenYuan's OWN hhea/typo line metrics to the carrier's nominal
metrics (scaled to WenYuan's units-per-em). Then measure-with-nominal and
draw-with-fallback agree, so the baseline lands where the slot expects it. Glyph
outlines, cmap, family name and fvar axes are never touched, so bold, italic,
small-caps, language shaping and original codepoints are all preserved. The
usWinAscent/Descent are kept wide enough to cover the real glyph bbox so no
renderer clips ink; only the line metrics change.

A build-time guard refuses to ship a font whose normalised envelope would clip the
digit ink that caused the report, so we never trade one clipping bug for another.
"""
import io

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

USE_TYPO_METRICS = 0x80

# Characters that appear in the compact fixed-height slots we are correcting.
# Their ink must remain inside the normalised line box or the build fails.
STRICT_INK = "0123456789"
# Broader Latin whose ink is reported but not treated as a hard failure.
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
    y_min = min(b[1] for b in bounds.values())
    y_max = max(b[3] for b in bounds.values())
    return y_min, y_max


def _glyph_signature(font_bytes):
    """Identity of everything that must NOT change: outlines, cmap, family, axes."""
    font = TTFont(io.BytesIO(font_bytes), recalcBBoxes=False, recalcTimestamp=False)
    glyf = font["glyf"]
    glyph_data = {}
    for name in font.getGlyphOrder():
        glyph_data[name] = glyf[name].compile(glyf)
    return {
        "glyphOrder": font.getGlyphOrder(),
        "glyphs": glyph_data,
        "cmap": font.getBestCmap(),
        "family": font["name"].getDebugName(1),
        "axes": {a.axisTag: (a.minValue, a.defaultValue, a.maxValue)
                 for a in font["fvar"].axes},
    }


def assert_glyphs_preserved(original_bytes, normalized_bytes):
    """Fail unless only vertical line metrics changed between the two fonts."""
    before = _glyph_signature(original_bytes)
    after = _glyph_signature(normalized_bytes)
    if before["glyphOrder"] != after["glyphOrder"]:
        raise ValueError("Glyph order changed during metric normalization")
    if before["glyphs"] != after["glyphs"]:
        changed = [n for n in before["glyphs"]
                   if before["glyphs"].get(n) != after["glyphs"].get(n)]
        raise ValueError(f"Glyph outlines changed during normalization: {changed[:8]}")
    if before["cmap"] != after["cmap"]:
        raise ValueError("cmap changed during metric normalization")
    if before["family"] != after["family"]:
        raise ValueError("Family name changed during metric normalization")
    if before["axes"] != after["axes"]:
        raise ValueError("Variation axes changed during metric normalization")


def normalize_metrics(font_bytes, carrier_metrics):
    """Return (normalised_font_bytes, report). Input bytes are the verified original.

    ``carrier_metrics`` is the carrier's ``layoutMetrics`` dict (unitsPerEm, hhea,
    typo, win, useTypoMetrics) as produced by ``prepare_font.layout_metrics``.
    """
    font = TTFont(io.BytesIO(font_bytes), recalcBBoxes=False, recalcTimestamp=False)
    head, hhea, os2 = font["head"], font["hhea"], font["OS/2"]
    upm = head.unitsPerEm
    carrier_upm = carrier_metrics["unitsPerEm"]
    if upm <= 0 or carrier_upm <= 0:
        raise ValueError("Invalid units-per-em on font or carrier")

    def scale(value):
        return round(value * upm / carrier_upm)

    c_asc, c_desc, c_gap = carrier_metrics["hhea"]
    asc, desc, gap = scale(c_asc), scale(c_desc), scale(c_gap)
    if asc <= 0 or desc >= 0:
        raise ValueError("Carrier nominal metrics are not a valid ascent/descent pair")

    original = {
        "unitsPerEm": upm,
        "hhea": [hhea.ascent, hhea.descent, hhea.lineGap],
        "typo": [os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap],
        "win": [os2.usWinAscent, os2.usWinDescent],
        "useTypoMetrics": bool(os2.fsSelection & USE_TYPO_METRICS),
    }

    # Guard: the digit ink that caused the report must fit inside the new line box.
    strict = _ink_bounds(font, STRICT_INK)
    strict_env = _envelope(strict)
    if strict_env is None:
        raise ClipError("No digit ink found to validate the normalised envelope")
    ink_min, ink_max = strict_env
    if ink_max > asc or ink_min < desc:
        raise ClipError(
            "Normalised line box would clip digit ink: "
            f"ink=[{ink_min},{ink_max}] box=[{desc},{asc}]")
    latin_env = _envelope(_ink_bounds(font, LATIN_INK))

    # Line metrics carry the nominal envelope; Skia reads hhea (or typo).
    hhea.ascent, hhea.descent, hhea.lineGap = asc, desc, gap
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = asc, desc, gap
    # Match the carrier's USE_TYPO_METRICS flag so either metric path agrees.
    # Bit 7 is only defined in OS/2 version 4+, so raise the version if needed.
    if carrier_metrics.get("useTypoMetrics"):
        os2.version = max(os2.version, 4)
        os2.fsSelection |= USE_TYPO_METRICS
    else:
        os2.fsSelection &= ~USE_TYPO_METRICS
    # Keep the clipping envelope (usWin) wide enough for real ink so no renderer
    # crops CJK/accents; only the line metrics are normalised.
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
