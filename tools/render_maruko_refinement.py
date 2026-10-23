#!/usr/bin/env python3
"""Render the single current Maruko SC Regular review image.

The image deliberately distinguishes an actual stroke-width prototype on the
pinned 62-unique-glyph sample from full-cmap curve/control-point re-fitting.
The latter is not semantic stroke simplification.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

from tools.stroke_width_audit import measure_widths, rasterize_glyph

CHARS_63 = (
    "一二三十口日回国了乙人入八木林森永心必水走建进这远道你好中国"
    "语言文字书写规范长美丽颜色锦绣风雨雪龙马鸟虫鱼电子已己巳也包囚暖田"
)
WIDTH_SAMPLE = "一人绣雪"
HANGUL_SAMPLE = "가각 한글 한국어"
LABEL_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def _label(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(LABEL_FONT), size)


def _glyph_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _point_stats(path: Path) -> tuple[int, int, int]:
    font = TTFont(path)
    cmap = font.getBestCmap() or {}
    names = list(dict.fromkeys(cmap.values()))
    points = 0
    for name in names:
        coordinates, _ends, _flags = font["glyf"][name].getCoordinates(font["glyf"])
        points += len(coordinates)
    return len(cmap), len(names), points


def _sample_width_cv(path: Path, px: int = 360) -> float:
    font = TTFont(path)
    cmap = font.getBestCmap() or {}
    means = []
    for char in CHARS_63:
        name = cmap[ord(char)]
        mask, units_per_pixel = rasterize_glyph(font, name, px=px)
        widths = measure_widths(mask, units_per_pixel)
        if len(widths) < 5:
            raise ValueError(f"Insufficient width samples for {char!r}")
        means.append(float(widths.mean()))
    font.close()
    values = np.asarray(means)
    return float(values.std() / values.mean())


def render_review(
    source_regular: Path,
    width_stage: Path,
    final_regular: Path,
    output: Path,
    source_flags: int = 24,
    candidate_flags: int = 14,
    new_flags: int = 8,
) -> Path:
    for path in (source_regular, width_stage, final_regular):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not LABEL_FONT.is_file():
        raise FileNotFoundError(f"Label font not found: {LABEL_FONT}")
    if len(CHARS_63) != 63 or len(set(CHARS_63)) != 62:
        raise AssertionError("Expected the pinned 63-item / 62-unique-glyph sample")

    source_cmap, source_unique, _source_points = _point_stats(source_regular)
    candidate_cmap, candidate_unique, candidate_points = _point_stats(final_regular)
    if candidate_unique != 45007:
        raise ValueError(f"Expected 45,007 unique mapped glyphs, got {candidate_unique}")
    final_font = TTFont(final_regular)
    final_map = final_font.getBestCmap() or {}
    if not all(ord(char) in final_map for char in HANGUL_SAMPLE.replace(" ", "")):
        final_font.close()
        raise ValueError("The candidate font is missing a Hangul preview character")
    hangul_count = sum(cp in final_map for cp in range(0xAC00, 0xD7A4))
    final_font.close()
    if hangul_count != 11172:
        raise ValueError(f"Expected 11,172 mapped Hangul syllables, got {hangul_count}")
    _input_cmap, _input_unique, input_points = _point_stats(width_stage)
    cv_before = _sample_width_cv(source_regular)
    cv_after = _sample_width_cv(final_regular)

    width, height = 1600, 1030
    image = Image.new("RGB", (width, height), "#f5f2e9")
    draw = ImageDraw.Draw(image)
    dark = "#19283a"
    ink = "#202c3b"
    muted = "#66707a"
    rust = "#a84e36"
    rule = "#d6d0c3"
    card = "#fffefa"

    draw.rounded_rectangle((46, 40, 1554, 152), radius=20, fill=dark)
    draw.text((76, 57), "CURRENT REVIEW / 2026-10-24", font=_label(40), fill="#fbfaf7")
    draw.text(
        (78, 111),
        "MARUKO SC REGULAR / 62-GLYPH STROKE-WIDTH PROTOTYPE / FULL-CMAP CURVE RE-FIT",
        font=_label(19),
        fill="#d6dde5",
    )

    draw.text((78, 184), "01 / ACTUAL STROKE-WIDTH PROTOTYPE", font=_label(27), fill=dark)
    draw.text((80, 231), "SOURCE", font=_label(18), fill=muted)
    draw.text((350, 206), WIDTH_SAMPLE, font=_glyph_font(source_regular, 90), fill=ink)
    draw.text((80, 332), "WIDTH + RE-FIT", font=_label(18), fill=rust)
    draw.text((350, 303), WIDTH_SAMPLE, font=_glyph_font(final_regular, 90), fill=ink)
    draw.text(
        (350, 414),
        f"63-item audit cross-glyph width CV at 360 px: {cv_before:.3f} -> {cv_after:.3f}",
        font=_label(17),
        fill=muted,
    )
    draw.text(
        (80, 442),
        "This measured stroke-width edit affects 62 unique sample glyphs only; it does not delete or merge semantic strokes.",
        font=_label(16),
        fill=muted,
    )

    draw.line((78, 474, 1520, 474), fill=rule, width=2)
    draw.text((78, 492), "02 / HANGUL COMPOSED FROM MARUKO'S OWN JAMO", font=_label(27), fill=dark)
    draw.text((80, 545), "HANGUL", font=_label(18), fill=muted)
    draw.text((350, 520), HANGUL_SAMPLE, font=_glyph_font(final_regular, 82), fill=rust)
    draw.text(
        (350, 628),
        "11,172 syllables U+AC00 to U+D7A3; no external Hangul outline source.",
        font=_label(17),
        fill=muted,
    )
    draw.line((78, 655, 1520, 655), fill=rule, width=2)

    cards = ((78, 684, 528, 824), (565, 684, 1015, 824), (1052, 684, 1520, 824))
    for box in cards:
        draw.rounded_rectangle(box, radius=16, fill=card, outline=rule, width=2)

    draw.text((100, 704), f"{candidate_unique:,}", font=_label(28), fill=dark)
    draw.text((100, 743), "unique mapped glyphs: curve re-fit", font=_label(17), fill=ink)
    points_line = (
        f"{input_points:,} -> {candidate_points:,} points ({(input_points - candidate_points) / input_points:.1%} fewer)"
        if input_points else f"{candidate_points:,} points after re-fit"
    )
    draw.text((100, 779), points_line, font=_label(16), fill=muted)

    draw.text((587, 704), "11,172", font=_label(28), fill=rust)
    draw.text((587, 743), "Hangul syllables composed", font=_label(17), fill=ink)
    draw.text((587, 779), "from Maruko L / V / T Jamo", font=_label(16), fill=muted)

    draw.text((1074, 704), "SC / Regular", font=_label(27), fill=dark)
    draw.text((1074, 743), f"{source_unique:,} source glyphs; {source_cmap:,} source cmap entries", font=_label(15), fill=ink)
    draw.text((1074, 779), f"candidate cmap: {candidate_cmap:,}; static research file", font=_label(15), fill=muted)

    draw.text(
        (80, 858),
        f"AUTO-SCREEN: single-contour flags source {source_flags}, candidate {candidate_flags}; {new_flags} new candidates are unreviewed.",
        font=_label(16),
        fill=rust,
    )
    draw.text(
        (80, 892),
        "CURVE SCOPE: all mapped outlines were re-fitted; fewer control points do not mean stroke simplification.",
        font=_label(16),
        fill=muted,
    )
    draw.text(
        (80, 926),
        "STROKE SCOPE: 62 sample glyphs only. TC / JP, Light / Medium, KR-localized Han, and source CJK gaps remain.",
        font=_label(16),
        fill=muted,
    )
    draw.text(
        (80, 960),
        "Not a visual sign-off or production font. Auto-screen flags are candidates, not confirmed defects.",
        font=_label(16),
        fill=muted,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-regular", type=Path, required=True)
    parser.add_argument("--width-stage", type=Path, required=True)
    parser.add_argument("--final-regular", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-flags", type=int, default=24)
    parser.add_argument("--candidate-flags", type=int, default=14)
    parser.add_argument("--new-flags", type=int, default=8)
    args = parser.parse_args()
    output = render_review(
        args.source_regular,
        args.width_stage,
        args.final_regular,
        args.output,
        args.source_flags,
        args.candidate_flags,
        args.new_flags,
    )
    print(output)


if __name__ == "__main__":
    main()
