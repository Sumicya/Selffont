#!/usr/bin/env python3
"""Restore reviewed glyph outlines from a source font into a research candidate.

Metrics, cmap, names, and all non-selected glyphs remain from the target font.
This is a conservative fallback for width-normalization glyphs whose raster
reconstruction changes component/counter topology; source and target must be
compatible static TrueType fonts with matching UPM and glyph mappings.
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path

from fontTools.ttLib import TTFont


def restore_glyph_outlines(source_path: Path, target_path: Path, output_path: Path, chars: str) -> int:
    if output_path.resolve() in (source_path.resolve(), target_path.resolve()):
        raise ValueError("output must not overwrite source or target")
    if not chars:
        raise ValueError("chars cannot be empty")
    source = TTFont(source_path)
    target = TTFont(target_path)
    try:
        if "glyf" not in source or "glyf" not in target:
            raise ValueError("both fonts must contain TrueType glyf outlines")
        if "fvar" in source or "fvar" in target:
            raise ValueError("variable fonts are not supported")
        if source["head"].unitsPerEm != target["head"].unitsPerEm:
            raise ValueError("source and target UPM values differ")
        source_cmap = source.getBestCmap()
        target_cmap = target.getBestCmap()
        restored = set()
        for char in dict.fromkeys(chars):
            codepoint = ord(char)
            if codepoint not in source_cmap or codepoint not in target_cmap:
                raise ValueError(f"missing cmap entry for {char!r} (U+{codepoint:04X})")
            source_name = source_cmap[codepoint]
            target_name = target_cmap[codepoint]
            source_glyph = source["glyf"][source_name]
            if source_glyph.isComposite():
                raise ValueError(
                    f"source glyph {char!r} is composite; expand it before outline restoration"
                )
            target["glyf"][target_name] = copy.deepcopy(source_glyph)
            restored.add(target_name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        target.recalcTimestamp = False
        target.save(output_path)
        return len(restored)
    finally:
        source.close()
        target.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="source static TTF supplying fallback outlines")
    parser.add_argument("target", type=Path, help="candidate static TTF to patch")
    parser.add_argument("output", type=Path, help="patched output TTF")
    parser.add_argument("--chars", required=True, help="characters whose outlines are restored")
    args = parser.parse_args()
    count = restore_glyph_outlines(args.source, args.target, args.output, args.chars)
    print(f"restored {count} unique glyph outlines -> {args.output}")


if __name__ == "__main__":
    main()
