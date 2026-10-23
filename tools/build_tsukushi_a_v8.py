#!/usr/bin/env python3
"""Build a reversible V8 Tsukushi A D/400 research candidate.

The source font and generated TTF are temporary inputs/outputs, never release assets.
The shared width target is informed by the median of Noto Sans SC 400's 62 sample
medians (OFL-1.1 reference only); its outlines are not copied. The glyph skeletons are
reconstructed at a common radius, and 电's four-cell frame is horizontally narrowed
around its own divider centerline before that same radius is restored.
"""
from __future__ import annotations

import argparse
import math
import tempfile
from pathlib import Path

import numpy as np
from scipy import ndimage
from fontTools.ttLib import TTFont

from tools.hook_cut import split_contours
from tools.stroke_width_audit import signed_area
from tools.stroke_width_normalize_prototype import (
    glyph_from_mask,
    normalize_font,
    raster_mask,
    skeleton_widths,
    transform_skeleton_x,
)
from tools.tsukushi_a_preview_simplify import CHARS_63, simplify

DEFAULT_SHARED_WIDTH = 74.0
DEFAULT_FRAME_X_SCALE = 0.94
DEFAULT_RASTER_PX = 1400
DEFAULT_MARGIN_FRAC = 0.08


def electric_frame_geometry(
    font: TTFont,
    target_width: float,
    px: int = DEFAULT_RASTER_PX,
) -> tuple[float, float, float]:
    """Derive 电's divider center and frame centerline band from its four counters."""
    cmap = font.getBestCmap()
    glyph_name = cmap.get(ord("电"))
    if glyph_name is None:
        raise ValueError("Source font is missing U+7535 电")
    glyph = font["glyf"][glyph_name]
    if glyph.isComposite():
        raise ValueError("电 must have a simple TrueType outline")
    coordinates, ends, flags = glyph.getCoordinates(font["glyf"])
    contours = split_contours(coordinates, ends, flags)
    if len(contours) != 5:
        raise ValueError(f"Expected 电 to have one exterior and four counters; got {len(contours)}")

    areas = [abs(signed_area([(x, y) for x, y, _on in contour])) for contour in contours]
    exterior_index = int(np.argmax(areas))
    counters = [contour for i, contour in enumerate(contours) if i != exterior_index]
    if len(counters) != 4:
        raise AssertionError("Failed to isolate 电's four internal counters")
    boxes = [
        (
            min(x for x, _y, _on in contour),
            min(y for _x, y, _on in contour),
            max(x for x, _y, _on in contour),
            max(y for _x, y, _on in contour),
        )
        for contour in counters
    ]
    left = sorted((box for box in boxes if (box[0] + box[2]) * 0.5 < font["head"].unitsPerEm / 2),
                  key=lambda box: (box[1] + box[3]) * 0.5)
    right = sorted((box for box in boxes if (box[0] + box[2]) * 0.5 >= font["head"].unitsPerEm / 2),
                   key=lambda box: (box[1] + box[3]) * 0.5)
    if len(left) != 2 or len(right) != 2:
        raise ValueError("Could not separate 电's left and right counters")
    left_inner = max(box[2] for box in left)
    right_inner = min(box[0] for box in right)
    if left_inner >= right_inner:
        raise ValueError("电's inner counters do not leave a central divider gap")

    # Use the centerline of the actual vertical divider, not the midpoint between
    # its bounding-box edges; this preserves a deliberately asymmetric source axis.
    top_counters = sorted(counters, key=lambda contour: np.mean([p[1] for p in contour]), reverse=True)[:2]
    top_boxes = [
        (
            min(x for x, _y, _on in contour),
            min(y for _x, y, _on in contour),
            max(x for x, _y, _on in contour),
            max(y for _x, y, _on in contour),
        )
        for contour in top_counters
    ]
    divider_y_min = max(box[1] for box in top_boxes) + 8.0
    divider_y_max = min(box[3] for box in top_boxes) - 8.0
    if divider_y_min >= divider_y_max:
        raise ValueError("电's top counters are too short to sample the divider centerline")
    mask, transform = raster_mask(font, glyph_name, px, DEFAULT_MARGIN_FRAC)
    skeleton, _widths = skeleton_widths(mask, transform[4])
    rows, columns = np.nonzero(skeleton)
    xmin, ymin, scale, margin_px, _units_per_pixel, _outer_sign = transform
    x_units = (columns - margin_px) / scale + xmin
    y_units = ((skeleton.shape[0] - rows) - margin_px) / scale + ymin
    sample = (
        (y_units >= divider_y_min)
        & (y_units <= divider_y_max)
        & (x_units >= left_inner - target_width)
        & (x_units <= right_inner + target_width)
    )
    if not np.any(sample):
        raise ValueError("Could not sample 电's central vertical divider")
    center_x = float(np.median(x_units[sample]))
    frame_y_min = min(box[1] for box in boxes) - target_width * 0.5
    frame_y_max = max(box[3] for box in boxes) + target_width * 0.5
    return center_x, frame_y_min, frame_y_max


def _sample_glyph_names(font: TTFont) -> set[str]:
    cmap = font.getBestCmap()
    missing = [ch for ch in CHARS_63 if ord(ch) not in cmap]
    if missing:
        raise ValueError(f"Font is missing sample glyphs: {''.join(missing)}")
    return {cmap[ord(ch)] for ch in CHARS_63}


def _refresh_font_bounds(font: TTFont) -> None:
    glyf = font["glyf"]
    bounds = []
    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if glyph.numberOfContours != 0:
            glyph.recalcBounds(glyf)
            bounds.append((glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax))
    if bounds:
        head = font["head"]
        head.xMin = min(box[0] for box in bounds)
        head.yMin = min(box[1] for box in bounds)
        head.xMax = max(box[2] for box in bounds)
        head.yMax = max(box[3] for box in bounds)
    font["maxp"].recalc(font)
    font.recalcTimestamp = False


def build_candidate(
    source_path: Path,
    output_path: Path,
    shared_width: float = DEFAULT_SHARED_WIDTH,
    frame_scale_x: float = DEFAULT_FRAME_X_SCALE,
    px: int = DEFAULT_RASTER_PX,
) -> None:
    if not math.isfinite(shared_width) or shared_width <= 0:
        raise ValueError("shared_width must be a finite positive number")
    if not math.isfinite(frame_scale_x) or not 0 < frame_scale_x < 1:
        raise ValueError("frame_scale_x must be finite and in the interval (0, 1)")
    if px < 600:
        raise ValueError("px must be at least 600 for the outline reconstruction")
    if source_path.resolve() == output_path.resolve():
        raise ValueError("Source and output paths must differ")

    source = TTFont(source_path)
    if "glyf" not in source or "fvar" in source:
        raise ValueError("Expected a static TrueType font with glyf outlines")
    if source["OS/2"].usWeightClass != 400:
        raise ValueError(f"Expected usWeightClass=400, got {source['OS/2'].usWeightClass}")
    if source["head"].unitsPerEm != 1000:
        raise ValueError(f"Expected UPM=1000, got {source['head'].unitsPerEm}")
    sample_names = _sample_glyph_names(source)

    geometry_font, _reports = simplify(source)
    geometry_metrics = {}
    for name in sample_names:
        glyph = geometry_font["glyf"][name]
        glyph.recalcBounds(geometry_font["glyf"])
        advance, lsb = geometry_font["hmtx"][name]
        geometry_metrics[name] = (advance, lsb, glyph.xMin)
    center_x, frame_y_min, frame_y_max = electric_frame_geometry(geometry_font, shared_width, px)
    electric_name = geometry_font.getBestCmap()[ord("电")]

    with tempfile.TemporaryDirectory(prefix="selffont-tsukushi-v8-") as tmpdir:
        tmpdir = Path(tmpdir)
        geometry_path = tmpdir / "geometry-base.ttf"
        normalized_path = tmpdir / "shared-width.ttf"
        geometry_font.recalcTimestamp = False
        geometry_font.save(geometry_path)
        normalize_font(
            geometry_path,
            normalized_path,
            CHARS_63,
            mode="global",
            px=px,
            margin_frac=DEFAULT_MARGIN_FRAC,
            global_strength=0.0,
            shared_target_width=shared_width,
        )
        candidate = TTFont(normalized_path)

        # Reconstruct 电 from the same geometry base as every other glyph, but first
        # bring the four-cell frame side-to-side distance in by 6%. Its divider axis
        # stays fixed; redilation at the shared radius prevents the side strokes from
        # becoming heavier. The lower hook and advance width remain untouched.
        mask, transform = raster_mask(
            geometry_font, electric_name, px, DEFAULT_MARGIN_FRAC
        )
        skeleton, _widths = skeleton_widths(mask, transform[4])
        adjusted_skeleton = transform_skeleton_x(
            skeleton,
            transform,
            center_x=center_x,
            y_min=frame_y_min,
            y_max=frame_y_max,
            scale_x=frame_scale_x,
        )
        target_radius_px = shared_width / (2 * transform[4])
        adjusted_mask = ndimage.distance_transform_edt(~adjusted_skeleton) <= target_radius_px
        candidate["glyf"][electric_name] = glyph_from_mask(adjusted_mask, candidate, transform)

        if _sample_glyph_names(candidate) != sample_names:
            raise AssertionError("Candidate sample glyph mapping changed")
        _refresh_font_bounds(candidate)
        for name, (advance, old_lsb, old_xmin) in geometry_metrics.items():
            new_xmin = candidate["glyf"][name].xMin
            new_lsb = old_lsb + (new_xmin - old_xmin)
            if not -32768 <= new_lsb <= 32767:
                raise ValueError(f"Recalculated LSB is outside int16 range for {name}: {new_lsb}")
            candidate["hmtx"][name] = (advance, new_lsb)
            if candidate["hmtx"][name][0] != advance:
                raise AssertionError(f"Advance width changed for {name}")
            if candidate["hmtx"][name][1] - new_xmin != old_lsb - old_xmin:
                raise AssertionError(f"Rendered left-bearing offset changed for {name}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        candidate.save(output_path)
        print(
            f"V8 candidate saved to {output_path}; shared width={shared_width:.2f} FU; "
            f"电 frame x-scale={frame_scale_x:.3f} about divider centerline {center_x:.1f} FU; "
            f"frame centerline y-band={frame_y_min:.1f}..{frame_y_max:.1f} FU; "
            "62 unique glyphs, 63 sample entries; advances are unchanged and LSBs are "
            "recalculated to preserve each geometry-base origin offset."
        )
        candidate.close()
    geometry_font.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", required=True, type=Path, help="static Tsukushi A D/400 source TTF")
    parser.add_argument("--out", required=True, type=Path, help="temporary V8 research-preview TTF")
    parser.add_argument("--shared-width", type=float, default=DEFAULT_SHARED_WIDTH,
                        help="shared stroke width in font units (default: 74, Noto SC 400 reference)")
    parser.add_argument("--electric-frame-scale-x", type=float, default=DEFAULT_FRAME_X_SCALE,
                        help="horizontal centerline spacing scale for 电's 田 frame (default: 0.94)")
    parser.add_argument("--px", type=int, default=DEFAULT_RASTER_PX,
                        help="raster canvas size for width reconstruction (default: 1400)")
    args = parser.parse_args()
    build_candidate(args.font, args.out, args.shared_width, args.electric_frame_scale_x, args.px)


if __name__ == "__main__":
    main()
