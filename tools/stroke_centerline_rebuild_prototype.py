#!/usr/bin/env python3
"""Build research-only Maruko masters with shared centerlines and topology.

Maruko Gothic's Light/Regular/Medium static masters have incompatible outline
point topologies, so they cannot be interpolated directly as a variable font.
This prototype takes each glyph's medial skeleton from one reference master,
then rebuilds selected weights around that shared skeleton. An optional
external static font can supply the skeleton geometry; it is rasterized and
normalized to the Maruko reference glyph box, while the full source outline is
not copied point-for-point. The tool retraces the masks and can either emit
independent static previews or resample corresponding contours to compatible
point topology for an experimental variable-font subset.

This is an experimental static-master generator, not a production converter.
The raster skeleton can lose authored details, and fixed-point contour
resampling can distort small counters or sharp joins. Review output visually
and run topology/self-intersection checks before any further use.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from scipy import ndimage
from scipy.optimize import linear_sum_assignment
from skimage.measure import find_contours
from skimage.morphology import skeletonize

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.stroke_width_normalize_prototype import (  # noqa: E402
    raster_mask,
    skeleton_widths,
    unique_glyphs,
)


def _parse_font(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("字体参数格式应为 WEIGHT=PATH")
    weight, path = value.split("=", 1)
    if not weight or not path:
        raise argparse.ArgumentTypeError("字体参数格式应为 WEIGHT=PATH")
    return weight, Path(path)


def _closed_contours(
    mask: np.ndarray,
    units_per_pixel: float,
    min_perimeter_fu: float = 8.0,
) -> list[np.ndarray]:
    contours = find_contours(
        mask.astype(float), 0.5, fully_connected="high", positive_orientation="low"
    )
    cleaned = []
    for contour in contours:
        if len(contour) > 1 and np.allclose(contour[0], contour[-1]):
            contour = contour[:-1]
        contour = np.asarray(contour, dtype=float)
        if len(contour) >= 3 and _contour_perimeter(contour) * units_per_pixel >= min_perimeter_fu:
            cleaned.append(contour)
    if not cleaned:
        raise ValueError("rebuilt glyph has no contours above the tiny-contour filter")
    return cleaned


def _contour_area(contour: np.ndarray) -> float:
    row, col = contour[:, 0], contour[:, 1]
    return float(0.5 * np.sum(
        col * np.roll(row, -1) - np.roll(col, -1) * row
    ))


def _contour_perimeter(contour: np.ndarray) -> float:
    return float(np.sum(np.linalg.norm(np.roll(contour, -1, axis=0) - contour, axis=1)))


def _topology_signature(contours: list[np.ndarray]) -> tuple[int, ...]:
    return tuple(sorted(1 if _contour_area(c) > 0 else -1 for c in contours))


def _contour_centroid(contour: np.ndarray) -> np.ndarray:
    # The arithmetic centroid is stable enough for matching boundaries that
    # were generated from the same medial skeleton and share the same canvas.
    return np.mean(contour, axis=0)


def _ordered_reference(contours: list[np.ndarray]) -> list[np.ndarray]:
    # Largest contours first gives a deterministic reference ordering. When
    # areas tie, top-left position is a stable tie-breaker for separated parts.
    return sorted(
        contours,
        key=lambda c: (-abs(_contour_area(c)), float(c[:, 0].min()), float(c[:, 1].min())),
    )


def _match_contours(
    reference: list[np.ndarray], candidate: list[np.ndarray], px: int, char: str, weight: str
) -> list[np.ndarray]:
    if len(reference) != len(candidate):
        raise ValueError(
            f"contour topology differs for {char!r} in {weight}: "
            f"reference={len(reference)}, candidate={len(candidate)}"
        )
    ref_area = np.asarray([_contour_area(c) for c in reference])
    cand_area = np.asarray([_contour_area(c) for c in candidate])
    ref_centers = np.asarray([_contour_centroid(c) for c in reference])
    cand_centers = np.asarray([_contour_centroid(c) for c in candidate])
    cost = np.zeros((len(reference), len(candidate)), dtype=float)
    for i in range(len(reference)):
        for j in range(len(candidate)):
            center_distance = np.linalg.norm(ref_centers[i] - cand_centers[j]) / max(px, 1)
            area_ratio = abs(np.log(max(abs(cand_area[j]), 1e-9) / max(abs(ref_area[i]), 1e-9)))
            winding_penalty = 100.0 if np.sign(ref_area[i]) != np.sign(cand_area[j]) else 0.0
            cost[i, j] = center_distance + 0.08 * area_ratio + winding_penalty
    rows, cols = linear_sum_assignment(cost)
    matched = [None] * len(reference)
    for row, col in zip(rows, cols):
        matched[int(row)] = candidate[int(col)]
    if any(contour is None for contour in matched):
        raise ValueError(f"could not match contours for {char!r} in {weight}")
    return matched  # type: ignore[return-value]


def _find_radius_with_topology(
    distance_map: np.ndarray,
    units_per_pixel: float,
    reference_signature: tuple[int, ...],
    requested_radius: float,
    reference_radius: float,
    max_adjustment_fraction: float,
    char: str,
    weight: str,
) -> tuple[float, list[np.ndarray]]:
    """Keep the requested width unless it changes contour topology.

    If necessary, search a bounded neighborhood for the closest radius whose
    raster contours have the same filled/hole winding signature as the
    Regular reference master. This is a topology guard, not a visual target.
    """
    def contours_at(radius: float) -> list[np.ndarray]:
        return _closed_contours(distance_map <= radius, units_per_pixel)

    current = contours_at(requested_radius)
    if _topology_signature(current) == reference_signature:
        return requested_radius, current

    toward_reference = -1.0 if requested_radius > reference_radius else 1.0
    max_delta = requested_radius * max_adjustment_fraction
    if max_delta <= 0:
        raise ValueError(
            f"contour topology differs for {char!r} in {weight}; "
            "--max-topology-adjustment=0 disables width adjustment"
        )
    step = 0.5
    steps = int(math.ceil(max_delta / step))
    for index in range(1, steps + 1):
        delta = min(index * step, max_delta)
        for sign in (toward_reference, -toward_reference):
            radius = requested_radius + sign * delta
            if radius <= 1.0:
                continue
            candidate = contours_at(radius)
            if _topology_signature(candidate) == reference_signature:
                return radius, candidate
    raise ValueError(
        f"cannot preserve shared contour topology for {char!r} in {weight} "
        f"within +/-{max_adjustment_fraction:.0%} stroke-radius adjustment "
        f"(requested={requested_radius:.2f}px, Regular={reference_radius:.2f}px)"
    )


def _resample_closed_contour(
    contour: np.ndarray, reference: np.ndarray, count: int
) -> np.ndarray:
    """Orient and arc-length-resample a contour from a shared anchor point."""
    points = contour.copy()
    reference_area = _contour_area(reference)
    if np.sign(_contour_area(points)) != np.sign(reference_area):
        points = points[::-1]

    anchor = reference[int(np.argmin(reference[:, 0] * 1_000_000 + reference[:, 1]))]
    start_index = int(np.argmin(np.sum((points - anchor) ** 2, axis=1)))
    points = np.concatenate((points[start_index:], points[:start_index]), axis=0)

    next_points = np.roll(points, -1, axis=0)
    segment_lengths = np.linalg.norm(next_points - points, axis=1)
    keep = segment_lengths > 1e-9
    points = points[keep]
    segment_lengths = segment_lengths[keep]
    if len(points) < 3:
        raise ValueError("contour collapsed during resampling")
    cumulative = np.concatenate(([0.0], np.cumsum(segment_lengths)))
    total = float(cumulative[-1])
    distances = np.arange(count, dtype=float) * (total / count)
    indices = np.searchsorted(cumulative, distances, side="right") - 1
    indices = np.clip(indices, 0, len(points) - 1)
    fractions = (distances - cumulative[indices]) / segment_lengths[indices]
    return points[indices] + (next_points[keep][indices] - points[indices]) * fractions[:, None]


def _glyph_from_contours(
    contours: list[np.ndarray],
    reference_contours: list[np.ndarray],
    font: TTFont,
    transform: tuple,
    point_counts: list[int],
) -> tuple[object, list[int]]:
    xmin, ymin, scale, margin_px, _, outer_sign, px = transform
    pen = TTGlyphPen(font.getGlyphSet())
    points_per_loop = []
    for contour, reference, point_count in zip(contours, reference_contours, point_counts):
        sampled = _resample_closed_contour(contour, reference, point_count)
        area = _contour_area(contour)
        desired_sign = outer_sign if area > 0 else -outer_sign
        output_points = [
            ((col - margin_px) / scale + xmin,
             ((px - row) - margin_px) / scale + ymin)
            for row, col in sampled
        ]
        output_area = 0.5 * sum(
            output_points[i][0] * output_points[(i + 1) % len(output_points)][1]
            - output_points[(i + 1) % len(output_points)][0] * output_points[i][1]
            for i in range(len(output_points))
        )
        if output_area and (1 if output_area > 0 else -1) != desired_sign:
            output_points.reverse()
        rounded = [(round(x), round(y)) for x, y in output_points]
        if len(set(rounded)) < 3:
            raise ValueError("fixed contour point count collapsed after font-unit rounding")
        pen.moveTo(rounded[0])
        for point in rounded[1:]:
            pen.lineTo(point)
        pen.closePath()
        points_per_loop.append(len(rounded))
    return pen.glyph(), points_per_loop


def build_prototype(
    fonts: list[tuple[str, Path]],
    reference: str,
    chars: str,
    out_dir: Path,
    mode: str = "shared",
    fallback_chars: str = "",
    px: int = 1200,
    margin_frac: float = 0.08,
    points_per_contour: int = 512,
    max_topology_adjustment: float = 0.25,
    topology_policy: str = "compatible",
    centerline_font_path: Path | None = None,
) -> dict:
    if mode not in ("shared", "per-glyph"):
        raise ValueError("mode must be shared or per-glyph")
    if topology_policy not in ("compatible", "independent"):
        raise ValueError("topology_policy must be compatible or independent")
    if px < 400:
        raise ValueError("--px must be at least 400")
    if not 0 < margin_frac < 0.25:
        raise ValueError("--margin-frac must be between 0 and 0.25")
    if points_per_contour < 16:
        raise ValueError("--points-per-contour must be at least 16")
    if not 0.0 <= max_topology_adjustment <= 0.5:
        raise ValueError("--max-topology-adjustment must be between 0 and 0.5")
    font_map = dict(fonts)
    if len(font_map) != len(fonts):
        raise ValueError("duplicate font weight label")
    if reference not in font_map:
        raise ValueError(f"reference weight {reference!r} is not among --font inputs")
    if not chars:
        raise ValueError("--chars cannot be empty")
    for _, path in fonts:
        if not path.is_file():
            raise FileNotFoundError(path)

    source_fonts = {weight: TTFont(path) for weight, path in fonts}
    output_fonts = {weight: TTFont(path) for weight, path in fonts}
    owns_centerline_font = centerline_font_path is not None
    centerline_font = TTFont(centerline_font_path) if owns_centerline_font else source_fonts[reference]
    try:
        if "glyf" not in centerline_font or "fvar" in centerline_font:
            raise ValueError("centerline font must be a static TrueType glyf font")
        centerline_cmap = centerline_font.getBestCmap()
        for weight, font in source_fonts.items():
            if "glyf" not in font:
                raise ValueError(f"{weight} is not a TrueType glyf font")
            if "fvar" in font:
                raise ValueError(f"{weight} must be a static instance")
        cmap_by_weight = {w: f.getBestCmap() for w, f in source_fonts.items()}
        upm = {w: f["head"].unitsPerEm for w, f in source_fonts.items()}
        if len(set(upm.values())) != 1:
            raise ValueError(f"incompatible unitsPerEm values: {upm}")
        glyphs = unique_glyphs(source_fonts[reference], chars)
        for char, codepoint, ref_name in glyphs:
            for weight in source_fonts:
                if codepoint not in cmap_by_weight[weight]:
                    raise ValueError(f"{weight} is missing {char!r} (U+{codepoint:04X})")
        for weight, cmap in cmap_by_weight.items():
            names_seen = {}
            for char, codepoint, ref_name in glyphs:
                name = cmap[codepoint]
                previous = names_seen.get(name)
                if previous is not None and previous != ref_name:
                    raise ValueError(
                        f"{weight} maps multiple sample glyphs to {name!r}; "
                        "cannot rebuild them independently without de-aliasing"
                    )
                names_seen[name] = ref_name

        # First pass: keep compact skeleton coordinates and per-weight widths,
        # rather than retaining three full 1200px masks for every glyph.
        cache: dict[str, dict] = {}
        for char, codepoint, glyph_name in glyphs:
            _, ref_transform = raster_mask(
                source_fonts[reference], glyph_name, px=px, margin_frac=margin_frac
            )
            centerline_glyph_name = centerline_cmap.get(codepoint)
            if centerline_glyph_name is None:
                raise ValueError(
                    f"centerline font is missing {char!r} (U+{codepoint:04X})"
                )
            centerline_mask, _ = raster_mask(
                centerline_font, centerline_glyph_name, px=px, margin_frac=margin_frac
            )
            reference_skeleton = skeletonize(centerline_mask)
            rows, cols = np.nonzero(reference_skeleton)
            if len(rows) == 0:
                raise ValueError(f"reference glyph {char!r} produced an empty skeleton")
            local_widths = {}
            weight_glyph_names = {
                weight: cmap_by_weight[weight][codepoint] for weight in source_fonts
            }
            for weight, font in source_fonts.items():
                own_mask, own_transform = raster_mask(
                    font, weight_glyph_names[weight], px=px, margin_frac=margin_frac
                )
                _, samples = skeleton_widths(own_mask, own_transform[4])
                local_widths[weight] = float(np.median(samples))
            cache[glyph_name] = {
                "char": char,
                "codepoint": codepoint,
                "weight_glyph_names": weight_glyph_names,
                "centerline_glyph_name": centerline_glyph_name,
                "reference_transform": (*ref_transform, px),
                "skeleton_rows": rows.astype(np.uint16),
                "skeleton_cols": cols.astype(np.uint16),
                "local_widths": local_widths,
            }

        shared_targets = {
            weight: float(np.median([g["local_widths"][weight] for g in cache.values()]))
            for weight in source_fonts
        }
        fallback_set = set(fallback_chars)
        sample_chars = {char for char, _, _ in glyphs}
        unknown_fallbacks = fallback_set - sample_chars
        if unknown_fallbacks:
            raise ValueError(f"fallback chars not in sample: {''.join(sorted(unknown_fallbacks))}")
        if fallback_set and mode != "shared":
            raise ValueError("--fallback-chars only applies to shared mode")

        report_rows = []
        for glyph_name, item in cache.items():
            char = item["char"]
            transform = item["reference_transform"]
            ref_units_per_pixel = transform[4]
            skeleton = np.zeros((px, px), dtype=bool)
            skeleton[item["skeleton_rows"], item["skeleton_cols"]] = True
            to_skeleton = ndimage.distance_transform_edt(~skeleton)
            desired_widths = {
                weight: item["local_widths"][weight]
                if mode == "per-glyph" or char in fallback_set
                else shared_targets[weight]
                for weight in source_fonts
            }
            desired_radii = {
                weight: width / (2.0 * ref_units_per_pixel)
                for weight, width in desired_widths.items()
            }
            reference_radius = desired_radii[reference]
            ordered_by_weight = {}
            actual_radii = {}
            if topology_policy == "compatible":
                reference_contours = _ordered_reference(
                    _closed_contours(to_skeleton <= reference_radius, ref_units_per_pixel)
                )
                reference_signature = _topology_signature(reference_contours)
                ordered_by_weight[reference] = reference_contours
                actual_radii[reference] = reference_radius
                for weight in source_fonts:
                    if weight == reference:
                        continue
                    actual_radius, contours = _find_radius_with_topology(
                        to_skeleton,
                        ref_units_per_pixel,
                        reference_signature,
                        desired_radii[weight],
                        reference_radius,
                        max_topology_adjustment,
                        char,
                        weight,
                    )
                    actual_radii[weight] = actual_radius
                    ordered_by_weight[weight] = _match_contours(
                        reference_contours, contours, px, char, weight
                    )
            else:
                for weight in source_fonts:
                    actual_radii[weight] = desired_radii[weight]
                    ordered_by_weight[weight] = _ordered_reference(
                        _closed_contours(
                            to_skeleton <= desired_radii[weight], ref_units_per_pixel
                        )
                    )
                reference_contours = ordered_by_weight[reference]

            actual_widths = {
                weight: 2.0 * radius * ref_units_per_pixel
                for weight, radius in actual_radii.items()
            }
            point_counts_by_weight = {}
            if topology_policy == "compatible":
                shared_point_counts = []
                for index, _ in enumerate(reference_contours):
                    max_perimeter_fu = max(
                        _contour_perimeter(ordered_by_weight[weight][index]) * ref_units_per_pixel
                        for weight in source_fonts
                    )
                    desired = max(16, int(math.ceil(max_perimeter_fu / 8.0)))
                    desired = int(math.ceil(desired / 8.0) * 8)
                    shared_point_counts.append(min(points_per_contour, desired))
                point_counts_by_weight = {
                    weight: shared_point_counts for weight in source_fonts
                }
            else:
                for weight, contours in ordered_by_weight.items():
                    counts = []
                    for contour in contours:
                        perimeter_fu = _contour_perimeter(contour) * ref_units_per_pixel
                        desired = max(16, int(math.ceil(perimeter_fu / 8.0)))
                        desired = int(math.ceil(desired / 8.0) * 8)
                        counts.append(min(points_per_contour, desired))
                    point_counts_by_weight[weight] = counts

            per_weight_counts = {}
            for weight, font in output_fonts.items():
                contour_reference = (
                    reference_contours if topology_policy == "compatible"
                    else ordered_by_weight[weight]
                )
                new_glyph, loop_counts = _glyph_from_contours(
                    ordered_by_weight[weight], contour_reference, font,
                    transform, point_counts_by_weight[weight],
                )
                output_glyph_name = item["weight_glyph_names"][weight]
                font["glyf"][output_glyph_name] = new_glyph
                per_weight_counts[weight] = {
                    "contours": len(loop_counts),
                    "points_per_contour": loop_counts,
                }

            if topology_policy == "compatible" and len(
                {tuple(v["points_per_contour"]) for v in per_weight_counts.values()}
            ) != 1:
                raise AssertionError(f"fixed topology generation diverged for {char!r}")
            report_rows.append({
                "char": char,
                "codepoint": f"U+{item['codepoint']:04X}",
                "reference_glyph_name": glyph_name,
                "glyph_name_by_weight": item["weight_glyph_names"],
                "centerline_glyph_name": item["centerline_glyph_name"],
                "topology_by_weight": per_weight_counts,
                "local_median_width_fu": item["local_widths"],
                "desired_widths_fu": desired_widths,
                "actual_widths_fu": actual_widths,
                "topology_guard_adjustment_fu": {
                    weight: actual_widths[weight] - desired_widths[weight]
                    for weight in source_fonts
                },
                "shared_centerline_source": reference,
                "skeleton_pixels": len(item["skeleton_rows"]),
            })

        out_dir.mkdir(parents=True, exist_ok=True)
        outputs = {}
        for weight, out_font in output_fonts.items():
            output_path = out_dir / f"Maruko-{weight}-shared-centerline.ttf"
            out_font.save(output_path)
            outputs[weight] = str(output_path)

        report = {
            "prototype": "shared Maruko centerline outline reconstruction",
            "mode": mode,
            "topology_policy": topology_policy,
            "reference_weight": reference,
            "centerline_font": str(centerline_font_path) if centerline_font_path else f"Maruko {reference} master",
            "sample_occurrences": len(chars),
            "unique_glyphs": len(glyphs),
            "px": px,
            "max_points_per_contour": points_per_contour,
            "max_topology_adjustment_fraction": max_topology_adjustment,
            "shared_target_widths_fu": shared_targets,
            "outputs": outputs,
            "glyphs": report_rows,
            "limits": [
                "static preview masters only; no full variable font is built",
                "only selected glyphs are reconstructed; all other outlines remain source outlines",
                "the shared skeleton is rasterized from one reference font and normalized into the Maruko output glyph box",
                "the full external outline is not copied point-for-point; this remains a research reconstruction",
                "review counters, joins, self-intersections, and rendering at target sizes",
            ],
        }
        (out_dir / "prototype-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return report
    finally:
        for font in source_fonts.values():
            font.close()
        for font in output_fonts.values():
            font.close()
        if owns_centerline_font:
            centerline_font.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", action="append", type=_parse_font, required=True, metavar="WEIGHT=PATH")
    parser.add_argument("--reference", default="Regular", help="Maruko master supplying the output glyph box")
    parser.add_argument("--centerline-font", type=Path, help="optional external static TTF providing centerline geometry (e.g. Tsukushi; used as a normalized structural reference)")
    parser.add_argument("--chars", required=True, help="characters to rebuild")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("shared", "per-glyph"), default="shared")
    parser.add_argument("--fallback-chars", default="")
    parser.add_argument("--px", type=int, default=1200)
    parser.add_argument("--margin-frac", type=float, default=0.08)
    parser.add_argument("--points-per-contour", type=int, default=512, help="maximum points per contour after adaptive resampling")
    parser.add_argument("--max-topology-adjustment", type=float, default=0.25, help="maximum relative stroke-radius change allowed to preserve contour topology")
    parser.add_argument("--topology-policy", choices=("compatible", "independent"), default="compatible", help="compatible enforces matching topology; independent emits static masters even when contour counts differ")
    args = parser.parse_args()
    report = build_prototype(
        args.font, args.reference, args.chars, args.out_dir, args.mode,
        args.fallback_chars, args.px, args.margin_frac, args.points_per_contour,
        args.max_topology_adjustment, args.topology_policy, args.centerline_font,
    )
    print(json.dumps({k: v for k, v in report.items() if k != "glyphs"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
