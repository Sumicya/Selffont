#!/usr/bin/env python3
"""Build a reversible V10 Tsukushi A D/400 research candidate.

V10 keeps the V9 63-entry sample and its 74-FU shared-width baseline, but restores
vector geometry for the specifically flagged glyphs instead of forcing the raster
reconstruction over them. 鸟 is redrawn from three broad gestures in its own sketch;
乙 is simplified to a single open sweep with a straight rounded terminal. No sketch
coordinates or external-font outlines are copied. Source and output TTFs stay outside
this repository.
"""
from __future__ import annotations

import argparse
import copy
import math
from pathlib import Path
from typing import Iterable

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from tools.build_tsukushi_a_v9 import (
    DEFAULT_RASTER_PX,
    DEFAULT_SHARED_WIDTH,
    _refresh_font_bounds,
)
from tools.hook_cut import find_hooks, split_contours
from tools.tsukushi_a_preview_simplify import (
    CHARS_63,
    _round_cap_axis,
    cap_extension_to_preserve_extent,
    simplify,
)

# These glyphs keep the reviewed vector skeleton and hand-authored V10 terminal
# edits; their outlines are not replaced by the V9 raster-retraced contours.
HOOK_CUT_PLAN_V10 = {
    "己": ((0, 40, 52),),
    "已": ((0, 35, 48),),
    "巳": ((0, 9, 22),),
    "也": ((0, 8, 20),),
    "包": ((0, 12, 24), (1, 10, 20)),
    "色": ((0, 11, 23),),
    "龙": ((0, 77, 85),),
    "子": ((0, 8, 18),),
}

# Restored vector outlines for the glyph-specific corrections, plus the two
# independent gesture redraws. 电 remains the separately measured V9 frame edit.
VECTOR_OVERRIDE_CHARS = frozenset({
    "颜", "暖", "己", "已", "巳", "也", "乙", "包", "鸟", "龙", "色", "子",
})
EXPECTED_SAMPLE_ENTRIES = 63
EXPECTED_UNIQUE_GLYPHS = 62


def _cubic_samples(segment: tuple[tuple[float, float], ...], steps: int = 48) -> list[tuple[float, float]]:
    if len(segment) != 4:
        raise ValueError("A cubic segment must contain exactly four points")
    if steps < 2:
        raise ValueError("Cubic sampling requires at least two steps")
    p0, p1, p2, p3 = segment
    points = []
    for index in range(steps + 1):
        t = index / steps
        u = 1.0 - t
        points.append((
            u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
        ))
    return points


def _path_samples(segments: tuple[tuple[tuple[float, float], ...], ...]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for segment in segments:
        samples = _cubic_samples(segment)
        if points and math.dist(points[-1], samples[0]) < 1e-7:
            points.extend(samples[1:])
        else:
            points.extend(samples)
    if len(points) < 2:
        raise ValueError("A stroke path must contain at least two sampled points")
    return points


def _stroke_union(
    paths: tuple[tuple[tuple[tuple[float, float], ...], ...], ...],
    width: float,
) -> Polygon | object:
    if not math.isfinite(width) or width <= 0:
        raise ValueError("Stroke width must be a finite positive number")
    pieces = []
    for path in paths:
        line = LineString(_path_samples(path))
        if line.is_empty or line.length <= 0:
            raise ValueError("Stroke path is empty")
        pieces.append(line.buffer(width / 2.0, quad_segs=20, cap_style="round", join_style="round"))
    result = unary_union(pieces)
    if result.is_empty or not result.is_valid:
        raise ValueError("Stroke union produced empty or invalid geometry")
    return result


def _polygons(geometry) -> Iterable[Polygon]:
    if isinstance(geometry, Polygon):
        yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _polygons(part)


def _rounded_ring(ring) -> list[tuple[int, int]]:
    points = [(int(round(x)), int(round(y))) for x, y in list(ring.coords)[:-1]]
    compact: list[tuple[int, int]] = []
    for point in points:
        if not compact or point != compact[-1]:
            compact.append(point)
    if len(compact) > 2 and compact[0] == compact[-1]:
        compact.pop()
    if len(set(compact)) < 3:
        raise ValueError("Stroke outline collapsed while rounding to font units")
    return compact


def _glyph_from_strokes(font: TTFont, paths, width: float):
    geometry = _stroke_union(paths, width)
    pen = TTGlyphPen(font.getGlyphSet())
    for polygon in _polygons(geometry):
        polygon = orient(polygon, sign=-1.0)  # TrueType outer clockwise, counters opposite.
        rings = [(polygon.exterior, True)] + [(ring, False) for ring in polygon.interiors]
        for ring, _outer in rings:
            points = _rounded_ring(ring)
            pen.moveTo(points[0])
            for point in points[1:]:
                pen.lineTo(point)
            pen.closePath()
    glyph = pen.glyph()
    if glyph.numberOfContours < 1:
        raise ValueError("Stroke redraw produced no TrueType contours")
    glyph.recalcBounds(font["glyf"])
    return glyph


def _replace_with_strokes(
    font: TTFont,
    source: TTFont,
    char: str,
    paths,
    width: float,
) -> None:
    cmap = source.getBestCmap()
    name = cmap.get(ord(char))
    if name is None or name not in font["glyf"]:
        raise ValueError(f"Missing glyph {char!r} U+{ord(char):04X}")
    old_source = source["glyf"][name]
    if old_source.isComposite():
        raise ValueError(f"Refusing to replace composite source glyph {char!r}")
    old_source.recalcBounds(source["glyf"])
    old_lsb = source["hmtx"][name][1]
    advance = source["hmtx"][name][0]
    glyph = _glyph_from_strokes(font, paths, width)
    font["glyf"][name] = glyph
    glyph.recalcBounds(font["glyf"])
    new_lsb = old_lsb + glyph.xMin - old_source.xMin
    if not -32768 <= new_lsb <= 32767:
        raise ValueError(f"LSB outside int16 for {char!r}: {new_lsb}")
    font["hmtx"][name] = (advance, new_lsb)


def bird_gesture_paths():
    """Three separate gestures distilled from the 鸟 sketch, not traced from pixels."""
    return (
        (
            ((85, 285), (260, 350), (530, 510), (700, 580)),
            ((700, 580), (800, 620), (875, 565), (875, 300)),
        ),
        (
            ((300, 600), (285, 450), (300, 235), (335, 155)),
            ((335, 155), (470, 85), (700, 90), (850, 160)),
        ),
        (
            ((555, 775), (545, 650), (515, 485), (500, 360)),
        ),
    )


def yi_gesture_paths():
    """One open sweep for 乙: remove the return hook and end in 己's direction."""
    return (
        (
            ((820, 700), (650, 720), (365, 705), (205, 650)),
            ((205, 650), (160, 590), (175, 520), (260, 450)),
            ((260, 450), (365, 360), (520, 230), (610, 155)),
            ((610, 155), (670, 162), (740, 171), (810, 180)),
        ),
    )


def _round_cap_with_axis(contour, i: int, j: int, axis, extension: float):
    if not math.isfinite(extension) or extension < 0:
        raise ValueError("Cap extension must be finite and non-negative")
    ax, ay = contour[i][0], contour[i][1]
    bx, by = contour[j][0], contour[j][1]
    axis_length = math.hypot(axis[0], axis[1])
    if axis_length <= 1e-9:
        raise ValueError("Cap axis must be non-zero")
    axis = (axis[0] / axis_length, axis[1] / axis_length)
    original_axis, gate_length = _round_cap_axis(contour, len(contour), i, j)
    if axis[0] * original_axis[0] + axis[1] * original_axis[1] < math.cos(math.radians(15)):
        raise ValueError("Shared terminal direction differs from source cap axis by more than 15 degrees")

    start = (ax + axis[0] * extension, ay + axis[1] * extension)
    end = (bx + axis[0] * extension, by + axis[1] * extension)
    radius = gate_length * 0.5
    q1 = (start[0] + axis[0] * radius, start[1] + axis[1] * radius)
    apex = ((start[0] + end[0]) * 0.5 + axis[0] * radius,
            (start[1] + end[1]) * 0.5 + axis[1] * radius)
    q2 = (end[0] + axis[0] * radius, end[1] + axis[1] * radius)
    cap = [(ax, ay, True)]
    if extension > 1e-9:
        cap.append((start[0], start[1], True))
    cap.extend(((q1[0], q1[1], False), (apex[0], apex[1], True), (q2[0], q2[1], False)))
    if extension > 1e-9:
        cap.append((end[0], end[1], True))
    cap.append((bx, by, True))
    return cap


def _apply_v10_caps(glyph, glyf_table, char: str, specs, shared_axis=None):
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    contours = split_contours(coords, ends, flags)
    detected = find_hooks(contours)
    by_contour = {}
    for ci, i, j in specs:
        if ci in by_contour:
            raise ValueError(f"{char}: multiple caps in contour {ci} are unsupported")
        matches = [hook for hook in detected if hook[:3] == (ci, i, j)]
        if len(matches) != 1:
            raise ValueError(f"{char}: reviewed hook gate {(ci, i, j)} did not match source")
        contour = contours[ci]
        extension = cap_extension_to_preserve_extent(
            contour, len(contour), i, j, extra=0.0
        )
        axis = shared_axis or _round_cap_axis(contour, len(contour), i, j)[0]
        by_contour[ci] = (i, j, axis, extension)

    output_contours = []
    for contour_index, contour in enumerate(contours):
        if contour_index not in by_contour:
            output_contours.append(contour)
            continue
        i, j, axis, extension = by_contour[contour_index]
        replacement = _round_cap_with_axis(contour, i, j, axis, extension)
        result = [contour[i], *replacement[1:]]
        index = (j + 1) % len(contour)
        while index != i:
            result.append(contour[index])
            index = (index + 1) % len(contour)
        output_contours.append(result)

    flat, new_ends = [], []
    for contour in output_contours:
        flat.extend(contour)
        new_ends.append(len(flat) - 1)
    glyph.coordinates = GlyphCoordinates([
        (int(round(x)), int(round(y))) for x, y, _on in flat
    ])
    glyph.flags = [bool(on) for _x, _y, on in flat]
    glyph.endPtsOfContours = new_ends
    glyph.recalcBounds(glyf_table)


def _replace_with_source_caps(
    geometry_font: TTFont,
    source_font: TTFont,
    char: str,
    specs,
    shared_axis=None,
) -> None:
    name = source_font.getBestCmap().get(ord(char))
    if name is None:
        raise ValueError(f"Source is missing {char!r}")
    glyph = copy.deepcopy(source_font["glyf"][name])
    if glyph.isComposite():
        raise ValueError(f"Refusing implicit component expansion for {char!r}")
    _apply_v10_caps(glyph, source_font["glyf"], char, specs, shared_axis)
    glyph.recalcBounds(geometry_font["glyf"])
    geometry_font["glyf"][name] = glyph
    geometry_font["hmtx"][name] = source_font["hmtx"][name]


def _replace_with_source_outline(geometry_font: TTFont, source_font: TTFont, char: str) -> None:
    name = source_font.getBestCmap().get(ord(char))
    if name is None:
        raise ValueError(f"Source is missing {char!r}")
    glyph = copy.deepcopy(source_font["glyf"][name])
    if glyph.isComposite():
        raise ValueError(f"Refusing implicit component expansion for {char!r}")
    glyph.recalcBounds(source_font["glyf"])
    geometry_font["glyf"][name] = glyph
    geometry_font["hmtx"][name] = source_font["hmtx"][name]


def build_geometry(source_path: Path, shared_width: float = DEFAULT_SHARED_WIDTH) -> TTFont:
    source_font = TTFont(source_path)
    geometry_input = TTFont(source_path)
    if "glyf" not in source_font or "fvar" in source_font:
        source_font.close()
        geometry_input.close()
        raise ValueError("Expected a static TrueType font")
    if source_font["OS/2"].usWeightClass != 400 or source_font["head"].unitsPerEm != 1000:
        source_font.close()
        geometry_input.close()
        raise ValueError("Expected static D/400 with UPM 1000")
    if len(CHARS_63) != EXPECTED_SAMPLE_ENTRIES or len(set(CHARS_63)) != EXPECTED_UNIQUE_GLYPHS:
        source_font.close()
        geometry_input.close()
        raise AssertionError("The sample must remain 63 entries / 62 unique glyphs")

    geometry_font, _reports = simplify(geometry_input)
    for char in ("颜", "暖"):
        _replace_with_source_outline(geometry_font, source_font, char)

    reference_name = source_font.getBestCmap()[ord("己")]
    reference_coords, reference_ends, reference_flags = source_font["glyf"][reference_name].getCoordinates(
        source_font["glyf"]
    )
    reference_contour = split_contours(reference_coords, reference_ends, reference_flags)[0]
    shared_axis = _round_cap_axis(reference_contour, len(reference_contour), 40, 52)[0]

    for char, specs in HOOK_CUT_PLAN_V10.items():
        _replace_with_source_caps(
            geometry_font,
            source_font,
            char,
            specs,
            shared_axis=shared_axis if char in {"已", "巳", "也", "色"} else None,
        )

    _replace_with_strokes(
        geometry_font, source_font, "鸟", bird_gesture_paths(), shared_width
    )
    _replace_with_strokes(
        geometry_font, source_font, "乙", yi_gesture_paths(), shared_width
    )

    if _sample_glyph_names(source_font) != _sample_glyph_names(geometry_font):
        source_font.close()
        geometry_font.close()
        raise AssertionError("V10 geometry changed sample-to-glyph mapping")
    _refresh_font_bounds(geometry_font)
    source_font.close()
    return geometry_font


def _sample_glyph_names(font: TTFont) -> set[str]:
    cmap = font.getBestCmap()
    missing = [char for char in CHARS_63 if ord(char) not in cmap]
    if missing:
        raise ValueError(f"Font is missing sample glyphs: {''.join(missing)}")
    return {cmap[ord(char)] for char in CHARS_63}


def build_candidate(
    source_path: Path,
    baseline_path: Path,
    output_path: Path,
    shared_width: float = DEFAULT_SHARED_WIDTH,
    px: int = DEFAULT_RASTER_PX,
    geometry_path: Path | None = None,
) -> None:
    paths = [source_path.resolve(), baseline_path.resolve(), output_path.resolve()]
    if len(set(paths)) != len(paths):
        raise ValueError("Source, baseline, and output paths must differ")
    if geometry_path is not None and geometry_path.resolve() in paths:
        raise ValueError("Geometry output must differ from source, baseline, and candidate")
    if not math.isfinite(shared_width) or shared_width <= 0:
        raise ValueError("shared_width must be a finite positive number")
    if px < 600:
        raise ValueError("px must be at least 600")

    source = TTFont(source_path)
    baseline = TTFont(baseline_path)
    _sample_glyph_names(source)
    if _sample_glyph_names(source) != _sample_glyph_names(baseline):
        source.close()
        baseline.close()
        raise ValueError("Baseline sample glyph mapping differs from source")
    geometry = build_geometry(source_path, shared_width)
    candidate = TTFont(baseline_path)
    cmap = candidate.getBestCmap()

    # Keep source geometry for reviewed corrections. This avoids losing authored
    # curvature or small components to raster retracing; their natural width is
    # measured separately rather than silently claimed to be exactly 74 FU.
    for char in VECTOR_OVERRIDE_CHARS:
        name = cmap[ord(char)]
        glyph = copy.deepcopy(geometry["glyf"][name])
        glyph.recalcBounds(geometry["glyf"])
        candidate["glyf"][name] = glyph
        candidate["hmtx"][name] = geometry["hmtx"][name]

    # For non-overridden characters, keep V9's measured 0.97 frame treatment at 电.
    _refresh_font_bounds(candidate)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    candidate.recalcTimestamp = False
    candidate.save(output_path)
    if geometry_path is not None:
        geometry_path.parent.mkdir(parents=True, exist_ok=True)
        geometry.recalcTimestamp = False
        geometry.save(geometry_path)

    actual_unique = len({cmap[ord(char)] for char in CHARS_63})
    if len(CHARS_63) != EXPECTED_SAMPLE_ENTRIES or actual_unique != EXPECTED_UNIQUE_GLYPHS:
        raise AssertionError("V10 output lost entries or unique glyphs")
    print(
        f"V10 candidate saved: {output_path}; sample={len(CHARS_63)} entries / "
        f"{actual_unique} unique glyphs; vector overrides={''.join(sorted(VECTOR_OVERRIDE_CHARS))} "
        f"({len(VECTOR_OVERRIDE_CHARS)} glyphs); 74-FU V9 baseline retained for all other glyphs, "
        "including 电. Glyph advances are unchanged; source/derived fonts remain temporary."
    )
    candidate.close()
    geometry.close()
    baseline.close()
    source.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", required=True, type=Path, help="temporary static Tsukushi A D/400 TTF")
    parser.add_argument("--baseline", required=True, type=Path, help="temporary V9 candidate TTF")
    parser.add_argument("--out", required=True, type=Path, help="temporary V10 research candidate TTF")
    parser.add_argument("--geometry-out", type=Path, help="optional temporary V10 geometry TTF for audits")
    parser.add_argument("--shared-width", type=float, default=DEFAULT_SHARED_WIDTH)
    parser.add_argument("--px", type=int, default=DEFAULT_RASTER_PX)
    args = parser.parse_args()
    build_candidate(
        args.font, args.baseline, args.out, args.shared_width,
        args.px, args.geometry_out,
    )


if __name__ == "__main__":
    main()
