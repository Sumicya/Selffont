#!/usr/bin/env python3
"""Experimental stroke-width regularization prototype (not production).

A small research tool for the Maruko Gothic track. It accepts static TrueType
glyf outlines and offers three modes:

- ``median``: each glyph gets a constant-radius reconstruction at its own
  median centerline width.
- ``global``: each glyph interpolates between its own median and a shared
  per-weight median. ``--global-strength 0`` means fully shared; ``1`` means
  the per-glyph median baseline. ``--fallback-chars`` lets selected glyphs keep
  their local median after geometry review.
- ``roundtrip``: no width change; reconstructs the original raster mask as a
  control for rasterization and contour tracing effects.

Every mode rasterizes and retraces glyphs, so none is a production converter.
The output glyphs are simplified in a separate ``curve_simplify.py`` step.
Advances and font metrics are left untouched; variation data is unsupported.
Optional research dependencies are listed in ``requirements-research.txt``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage.measure import find_contours
from skimage.morphology import skeletonize

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.stroke_width_audit import FlattenPen, signed_area  # noqa: E402


def raster_mask(font: TTFont, glyph_name: str, px: int, margin_frac: float):
    """Rasterize a glyph using contour winding to distinguish holes."""
    glyph_set = font.getGlyphSet()
    pen = FlattenPen(glyph_set, steps_per_curve=20)
    glyph_set[glyph_name].draw(pen)
    contours = pen.contours
    if not contours:
        raise ValueError(f"字形 {glyph_name!r} 没有可处理的轮廓")

    points = np.asarray([point for contour in contours for point in contour], dtype=float)
    xmin, ymin = points.min(axis=0)
    xmax, ymax = points.max(axis=0)
    span = max(xmax - xmin, ymax - ymin)
    if span <= 0:
        raise ValueError(f"字形 {glyph_name!r} 的外接框宽高为零")

    margin_px = px * margin_frac
    scale = (px - 2 * margin_px) / span

    def to_pixel(point):
        x, y = point
        return ((x - xmin) * scale + margin_px,
                px - ((y - ymin) * scale + margin_px))

    pixel_contours = []
    for contour in contours:
        area = signed_area(contour)
        pixel_contours.append((abs(area), area, [to_pixel(point) for point in contour]))
    pixel_contours.sort(key=lambda row: -row[0])

    image = Image.new("L", (px, px), 0)
    draw = ImageDraw.Draw(image)
    outer_sign = 1 if pixel_contours[0][1] > 0 else -1
    for _, area, polygon in pixel_contours:
        if area == 0:
            continue
        sign = 1 if area > 0 else -1
        draw.polygon(polygon, fill=255 if sign == outer_sign else 0)

    units_per_pixel = span / (px - 2 * margin_px)
    transform = (xmin, ymin, scale, margin_px, units_per_pixel, outer_sign)
    return np.asarray(image) > 127, transform


def skeleton_widths(mask: np.ndarray, units_per_pixel: float):
    """Return the skeleton and valid local-width samples, excluding branches/edges."""
    px = mask.shape[0]
    distance = ndimage.distance_transform_edt(mask)
    skeleton = skeletonize(mask)
    skeleton_int = skeleton.astype(np.uint8)
    degree = ndimage.convolve(
        skeleton_int, np.ones((3, 3), dtype=np.uint8), mode="constant", cval=0
    ) - skeleton_int
    rows, columns = np.nonzero(skeleton)
    valid = degree[rows, columns] < 3
    valid &= (rows >= 3) & (columns >= 3)
    valid &= (rows < px - 3) & (columns < px - 3)
    widths = distance[rows[valid], columns[valid]] * 2 * units_per_pixel
    if widths.size == 0:
        raise ValueError("字形没有有效骨架宽度样本")
    return skeleton, widths


def glyph_from_mask(mask: np.ndarray, font: TTFont, transform):
    """Trace a binary mask back into a TrueType glyph, preserving contour winding."""
    xmin, ymin, scale, margin_px, _, outer_sign = transform
    px = mask.shape[0]
    contours = find_contours(
        mask.astype(float), 0.5, fully_connected="high", positive_orientation="low"
    )
    pen = TTGlyphPen(font.getGlyphSet())

    for contour in contours:
        if len(contour) > 1 and np.allclose(contour[0], contour[-1]):
            contour = contour[:-1]
        if len(contour) < 3:
            continue

        # find_contours returns (row, column); image-space winding distinguishes
        # outer boundaries from holes.
        area = 0.5 * np.sum(
            contour[:, 1] * np.roll(contour[:, 0], -1)
            - np.roll(contour[:, 1], -1) * contour[:, 0]
        )
        points = [
            ((column - margin_px) / scale + xmin,
             ((px - row) - margin_px) / scale + ymin)
            for row, column in contour
        ]
        desired_sign = outer_sign if area > 0 else -outer_sign
        output_area = signed_area(points)
        if output_area and (1 if output_area > 0 else -1) != desired_sign:
            points.reverse()

        rounded = [(round(x), round(y)) for x, y in points]
        pen.moveTo(rounded[0])
        for point in rounded[1:]:
            pen.lineTo(point)
        pen.closePath()

    return pen.glyph()


def unique_glyphs(font: TTFont, chars: str):
    """Map input characters to unique glyph names, preserving their first occurrence."""
    cmap = font.getBestCmap()
    glyphs = []
    seen = set()
    for char in dict.fromkeys(chars):
        codepoint = ord(char)
        if codepoint not in cmap:
            raise ValueError(f"字体缺少字符 {char!r} (U+{codepoint:04X})")
        glyph_name = cmap[codepoint]
        if glyph_name not in seen:
            seen.add(glyph_name)
            glyphs.append((char, codepoint, glyph_name))
    if not glyphs:
        raise ValueError("--chars 不能为空")
    return glyphs


def normalize_font(
    source: Path,
    output: Path,
    chars: str,
    mode: str = "median",
    px: int = 1200,
    margin_frac: float = 0.08,
    global_strength: float = 0.5,
    fallback_chars: str = "",
) -> None:
    if mode not in ("median", "global", "roundtrip"):
        raise ValueError("--mode 必须是 median/global/roundtrip")
    if px < 200:
        raise ValueError("--px 至少为 200；低分辨率会明显量化笔画边界")
    if not 0 < margin_frac < 0.25:
        raise ValueError("--margin-frac 必须在 0 到 0.25 之间")
    if not 0.0 <= global_strength <= 1.0:
        raise ValueError("--global-strength 必须在 0 到 1 之间")
    if source.resolve() == output.resolve():
        raise ValueError("输入和输出路径不能相同，避免覆盖原字体")

    source_font = TTFont(source)
    output_font = TTFont(source)
    if "glyf" not in source_font:
        raise ValueError("仅支持 TrueType glyf 轮廓字体")
    if "fvar" in source_font:
        raise ValueError("原型不处理可变字体；请传入静态字重实例")

    glyphs = unique_glyphs(source_font, chars)
    fallback_set = set(fallback_chars)
    if fallback_set and mode != "global":
        raise ValueError("--fallback-chars 仅适用于 global 模式")
    selected_chars = {char for char, _, _ in glyphs}
    unknown_fallbacks = fallback_set - selected_chars
    if unknown_fallbacks:
        raise ValueError(f"回退字符不在 --chars 中: {''.join(sorted(unknown_fallbacks))}")
    glyph_table = output_font["glyf"]

    # The shared target gives each glyph equal weight: take the median of the
    # per-glyph medians, rather than pooling all skeleton pixels (which would
    # let complex glyphs dominate the font-wide target).
    global_target = None
    if mode == "global":
        local_targets = []
        for char, codepoint, glyph_name in glyphs:
            mask, transform = raster_mask(source_font, glyph_name, px, margin_frac)
            _, widths = skeleton_widths(mask, transform[4])
            local_targets.append(float(np.median(widths)))
        global_target = float(np.median(local_targets))
        print(
            f"shared per-weight target_width={global_target:.2f} units from "
            f"{len(local_targets)} glyph medians; global_strength={global_strength:.2f} "
            f"(0=fully shared, 1=per-glyph)"
        )

    for char, codepoint, glyph_name in glyphs:
        mask, transform = raster_mask(source_font, glyph_name, px, margin_frac)
        if mode == "roundtrip":
            rebuilt_mask = mask
            print(f"{char} U+{codepoint:04X} glyph={glyph_name} roundtrip control; no width change")
        else:
            skeleton, widths = skeleton_widths(mask, transform[4])
            local_target = float(np.median(widths))
            use_fallback = mode == "global" and char in fallback_set
            target_width = (
                local_target if mode == "median" or use_fallback
                else global_target * (1.0 - global_strength) + local_target * global_strength
            )
            target_radius_px = target_width / (2 * transform[4])
            to_skeleton = ndimage.distance_transform_edt(~skeleton)
            rebuilt_mask = to_skeleton <= target_radius_px
            cv = float(np.std(widths) / np.mean(widths))
            shift = target_width / local_target - 1
            fallback_note = " fallback=per-glyph-median" if use_fallback else ""
            print(
                f"{char} U+{codepoint:04X} glyph={glyph_name} "
                f"target_width={target_width:.2f} units local_CV={cv:.4f} "
                f"target_shift={shift:+.1%}{fallback_note}"
            )

        glyph_table[glyph_name] = glyph_from_mask(rebuilt_mask, output_font, transform)

    output.parent.mkdir(parents=True, exist_ok=True)
    output_font.save(output)
    print(f"saved prototype -> {output} ({len(glyphs)} unique glyphs; mode={mode})")
    source_font.close()
    output_font.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", required=True, type=Path, help="static TrueType source font")
    parser.add_argument("--out", required=True, type=Path, help="output prototype TTF")
    parser.add_argument("--chars", required=True, help="characters to process; duplicate glyphs are deduplicated")
    parser.add_argument(
        "--mode", choices=("median", "global", "roundtrip"), default="median",
        help="per-glyph target, shared per-weight target, or no-width-change control",
    )
    parser.add_argument("--px", type=int, default=1200, help="raster canvas size (default: 1200)")
    parser.add_argument(
        "--margin-frac", type=float, default=0.08,
        help="canvas margin fraction (default: 0.08)",
    )
    parser.add_argument(
        "--global-strength", type=float, default=0.5,
        help="blend shared/per-glyph target in global mode (default: 0.5; 0=shared, 1=per-glyph)",
    )
    parser.add_argument(
        "--fallback-chars", default="",
        help="global-mode glyphs that retain their per-glyph median after geometry review",
    )
    args = parser.parse_args()
    normalize_font(
        args.font, args.out, args.chars, args.mode, args.px,
        args.margin_frac, args.global_strength, args.fallback_chars,
    )


if __name__ == "__main__":
    main()
