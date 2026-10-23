#!/usr/bin/env python3
"""Research prototype: make Hangul syllable outlines from Maruko's own Jamo.

This composes the existing conjoining-jamo outlines in their source coordinates;
it does not borrow Hangul outlines from another font or define Korean-localized
Hanja. The generated static TTF is for visual review, not production use.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

S_BASE = 0xAC00
S_COUNT = 11172
L_BASE = 0x1100
V_BASE = 0x1161
T_BASE = 0x11A7
L_COUNT = 19
V_COUNT = 21
T_COUNT = 28


def split_syllable(codepoint: int) -> tuple[int, int, int | None]:
    """Return conjoining leading, vowel, and optional trailing Jamo codepoints."""
    if not S_BASE <= codepoint < S_BASE + S_COUNT:
        raise ValueError(f"not an assigned Hangul syllable: U+{codepoint:04X}")
    index = codepoint - S_BASE
    leading = L_BASE + index // (V_COUNT * T_COUNT)
    vowel = V_BASE + (index % (V_COUNT * T_COUNT)) // T_COUNT
    trailing_index = index % T_COUNT
    trailing = T_BASE + trailing_index if trailing_index else None
    return leading, vowel, trailing


def compose_syllables(font: TTFont, codepoints: range | list[int] | tuple[int, ...] | None = None) -> int:
    """Add syllable glyphs by overlaying Maruko L/V/T Jamo at their source positions."""
    if "glyf" not in font or "cmap" not in font or "hmtx" not in font:
        raise ValueError("input must be a TrueType glyf font with cmap and hmtx")
    if "fvar" in font:
        raise ValueError("variable fonts are not supported by this static research prototype")

    codepoints = range(S_BASE, S_BASE + S_COUNT) if codepoints is None else tuple(codepoints)
    if not codepoints:
        return 0
    for cp in codepoints:
        split_syllable(cp)

    cmap = font.getBestCmap() or {}
    required = set()
    for cp in codepoints:
        required.update(jamo for jamo in split_syllable(cp) if jamo is not None)
    missing = sorted(required - set(cmap))
    if missing:
        examples = ", ".join(f"U+{cp:04X}" for cp in missing[:8])
        raise ValueError(f"source cmap lacks {len(missing)} required Jamo: {examples}")
    vertical_context = None
    if "vmtx" in font:
        contexts = set()
        for cp in required:
            source_glyph = font["glyf"][cmap[cp]]
            source_glyph.recalcBounds(font["glyf"])
            advance, side_bearing = font["vmtx"].metrics[cmap[cp]]
            contexts.add((advance, source_glyph.yMax + side_bearing))
        if len(contexts) != 1:
            raise ValueError("source Jamo do not share one vertical advance/origin; cannot safely compose vmtx")
        vertical_context = contexts.pop()
    already_present = sorted(cp for cp in codepoints if cp in cmap)
    if already_present:
        examples = ", ".join(f"U+{cp:04X}" for cp in already_present[:8])
        raise ValueError(f"refusing to overwrite existing Hangul syllables: {examples}")

    old_order = list(font.getGlyphOrder())
    existing_names = set(old_order)
    generated = {}
    glyf = font["glyf"]
    glyph_set = font.getGlyphSet()
    for cp in codepoints:
        name = f"hangul{cp:04X}"
        if name in existing_names:
            raise ValueError(f"generated glyph name already exists: {name}")
        pen = TTGlyphPen(glyph_set)
        for jamo_cp in split_syllable(cp):
            if jamo_cp is not None:
                glyph_set[cmap[jamo_cp]].draw(pen)
        glyph = pen.glyph()
        coordinates = getattr(glyph, "coordinates", None)
        if not coordinates:
            raise ValueError(f"empty composed glyph for U+{cp:04X}")
        glyph.recalcBounds(glyf)
        glyf[name] = glyph
        x_min = min(point[0] for point in coordinates)
        font["hmtx"].metrics[name] = (1000, x_min)
        if vertical_context is not None:
            vertical_advance, vertical_origin = vertical_context
            font["vmtx"].metrics[name] = (vertical_advance, vertical_origin - glyph.yMax)
        generated[cp] = name

    font.setGlyphOrder(old_order + list(generated.values()))
    font["maxp"].numGlyphs = len(old_order) + len(generated)
    for table in font["cmap"].tables:
        if table.isUnicode():
            table.cmap.update(generated)
    return len(generated)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("infont", type=Path)
    parser.add_argument("outfont", type=Path)
    args = parser.parse_args()
    if args.infont.resolve() == args.outfont.resolve():
        parser.error("input and output font paths must differ")
    font = TTFont(args.infont, lazy=False)
    added = compose_syllables(font)
    args.outfont.parent.mkdir(parents=True, exist_ok=True)
    font.recalcTimestamp = False
    font.save(args.outfont)
    font.close()
    print(f"added {added:,} Hangul syllables -> {args.outfont}")


if __name__ == "__main__":
    main()
