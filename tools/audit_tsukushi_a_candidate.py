#!/usr/bin/env python3
"""Independent raster/topology audit for a Tsukushi A research candidate.

This checks every CHARS_63 entry through Pillow's FreeType renderer, validates cmap
coverage and advances, and compares source → geometry → candidate connected-component
and counter topology at large em size. It is a structural/measurement gate, not an
esthetic approval or a production-font validator. The source and candidate TTFs are
local inputs only and must not be added to the repository.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import fontTools
from PIL import Image, ImageDraw, ImageFont, __version__ as PILLOW_VERSION, features
from fontTools.ttLib import TTFont
from skimage.measure import euler_number, label

from tools.stroke_width_audit import measure_widths, rasterize_glyph
from tools.tsukushi_a_preview_simplify import CHARS_63

DEFAULT_RENDER_SIZE = 1000
DEFAULT_SMALL_SIZE = 48
CANVAS_SIZE = 1400
RENDER_ORIGIN = (170, 1120)


@dataclass(frozen=True)
class RenderMetrics:
    components: int
    holes: int
    bbox: tuple[int, int, int, int]
    area_px: int


def _font_metrics(font: TTFont, ch: str) -> tuple[str, tuple[int, int, int, int], int, int]:
    codepoint = ord(ch)
    cmap = font.getBestCmap()
    if codepoint not in cmap:
        raise ValueError(f"Missing sample character {ch!r} U+{codepoint:04X}")
    name = cmap[codepoint]
    glyph = font["glyf"][name]
    if glyph.isComposite():
        raise ValueError(f"Composite sample outline is unsupported: {ch!r} ({name})")
    glyph.recalcBounds(font["glyf"])
    advance, lsb = font["hmtx"][name]
    bbox = (int(glyph.xMin), int(glyph.yMin), int(glyph.xMax), int(glyph.yMax))
    return name, bbox, int(advance), int(lsb)


def _render_mask(font_path: Path, ch: str, size: int, cache: dict) -> np.ndarray:
    key = (str(font_path.resolve()), size)
    font = cache.get(key)
    if font is None:
        font = ImageFont.truetype(str(font_path), size)
        cache[key] = font
    canvas = Image.new("L", (CANVAS_SIZE, CANVAS_SIZE), 0)
    ImageDraw.Draw(canvas).text(
        RENDER_ORIGIN, ch, font=font, fill=255, anchor="ls"
    )
    return np.asarray(canvas) >= 128


def _render_metrics(mask: np.ndarray) -> RenderMetrics:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("FreeType rendered an empty sample glyph")
    components = int(label(mask, connectivity=2).max())
    euler = int(euler_number(mask, connectivity=2))
    return RenderMetrics(
        components=components,
        holes=components - euler,
        bbox=(int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1),
        area_px=int(mask.sum()),
    )


def _iou(left: np.ndarray, right: np.ndarray) -> float:
    union = int(np.logical_or(left, right).sum())
    if union == 0:
        return 1.0
    return float(np.logical_and(left, right).sum() / union)


def _stroke_summary(font: TTFont, chars: str, px: int) -> dict[str, float | int]:
    medians = []
    cvs = []
    for ch in chars:
        name = font.getBestCmap()[ord(ch)]
        mask, units_per_pixel = rasterize_glyph(font, name, px=px)
        widths = measure_widths(mask, units_per_pixel)
        if len(widths) < 5:
            raise ValueError(f"Too few skeleton samples for {ch!r}: {len(widths)}")
        medians.append(float(np.median(widths)))
        cvs.append(float(np.std(widths) / np.mean(widths)))
    values = np.asarray(medians)
    return {
        "glyphs": len(medians),
        "median_of_medians_fu": float(np.median(values)),
        "across_glyph_cv": float(np.std(values) / np.mean(values)),
        "within_glyph_cv_mean": float(np.mean(cvs)),
        "within_glyph_cv_max": float(np.max(cvs)),
    }


def audit(
    source_path: Path,
    geometry_path: Path,
    candidate_path: Path,
    render_size: int = DEFAULT_RENDER_SIZE,
    small_size: int = DEFAULT_SMALL_SIZE,
    width_px: int = 900,
) -> tuple[list[dict], dict]:
    fonts = {
        "source": TTFont(source_path),
        "geometry": TTFont(geometry_path),
        "candidate": TTFont(candidate_path),
    }
    paths = {
        "source": source_path,
        "geometry": geometry_path,
        "candidate": candidate_path,
    }
    cache = {}
    rows: list[dict] = []
    seen: dict[str, dict] = {}
    topology_errors = []
    advance_errors = []
    mapping_errors = []
    small_topology_differences = []

    if len(CHARS_63) != 63 or len(set(CHARS_63)) != 62:
        raise AssertionError("The fixed sample must remain 63 entries / 62 unique glyphs")
    for role, font in fonts.items():
        missing = [ch for ch in CHARS_63 if ord(ch) not in font.getBestCmap()]
        if missing:
            mapping_errors.append(f"{role}: missing {''.join(missing)}")
        if font["head"].unitsPerEm != 1000:
            mapping_errors.append(f"{role}: expected UPM 1000")
        if font["OS/2"].usWeightClass != 400:
            mapping_errors.append(f"{role}: expected usWeightClass 400")

    for sample_index, ch in enumerate(CHARS_63, start=1):
        if ch in seen:
            duplicate = dict(seen[ch])
            duplicate["sample_index"] = sample_index
            duplicate["duplicate_of"] = seen[ch]["sample_index"]
            rows.append(duplicate)
            continue

        glyph_data = {
            role: _font_metrics(font, ch)
            for role, font in fonts.items()
        }
        masks = {
            role: _render_mask(paths[role], ch, render_size, cache)
            for role in fonts
        }
        metrics = {role: _render_metrics(masks[role]) for role in fonts}
        small_masks = {
            role: _render_mask(paths[role], ch, small_size, cache)
            for role in fonts
        }
        small_metrics = {
            role: _render_metrics(small_masks[role])
            for role in fonts
        }
        if (
            metrics["source"].components,
            metrics["source"].holes,
        ) != (
            metrics["geometry"].components,
            metrics["geometry"].holes,
        ):
            topology_errors.append(
                f"{ch} U+{ord(ch):04X}: source → geometry "
                f"{metrics['source'].components}/{metrics['source'].holes} → "
                f"{metrics['geometry'].components}/{metrics['geometry'].holes}"
            )
        if (
            metrics["geometry"].components,
            metrics["geometry"].holes,
        ) != (
            metrics["candidate"].components,
            metrics["candidate"].holes,
        ):
            topology_errors.append(
                f"{ch} U+{ord(ch):04X}: geometry → candidate "
                f"{metrics['geometry'].components}/{metrics['geometry'].holes} → "
                f"{metrics['candidate'].components}/{metrics['candidate'].holes}"
            )
        if (
            small_metrics["source"].components,
            small_metrics["source"].holes,
        ) != (
            small_metrics["candidate"].components,
            small_metrics["candidate"].holes,
        ):
            small_topology_differences.append(ch)

        source_advance = glyph_data["source"][2]
        for role in ("geometry", "candidate"):
            if glyph_data[role][2] != source_advance:
                advance_errors.append(
                    f"{ch} U+{ord(ch):04X}: source {source_advance}, "
                    f"{role} {glyph_data[role][2]}"
                )
        names = {role: glyph_data[role][0] for role in fonts}
        if len(set(names.values())) != 1:
            mapping_errors.append(f"{ch} U+{ord(ch):04X}: glyph mapping differs {names}")

        row = {
            "sample_index": sample_index,
            "duplicate_of": "",
            "character": ch,
            "codepoint": f"U+{ord(ch):04X}",
            "glyph_name": names["source"],
            "advance_source": glyph_data["source"][2],
            "advance_geometry": glyph_data["geometry"][2],
            "advance_candidate": glyph_data["candidate"][2],
            "lsb_source": glyph_data["source"][3],
            "lsb_geometry": glyph_data["geometry"][3],
            "lsb_candidate": glyph_data["candidate"][3],
            "bbox_width_source_fu": glyph_data["source"][1][2] - glyph_data["source"][1][0],
            "bbox_width_geometry_fu": glyph_data["geometry"][1][2] - glyph_data["geometry"][1][0],
            "bbox_width_candidate_fu": glyph_data["candidate"][1][2] - glyph_data["candidate"][1][0],
            "x_min_source": glyph_data["source"][1][0],
            "y_min_source": glyph_data["source"][1][1],
            "x_max_source": glyph_data["source"][1][2],
            "y_max_source": glyph_data["source"][1][3],
            "x_min_geometry": glyph_data["geometry"][1][0],
            "y_min_geometry": glyph_data["geometry"][1][1],
            "x_max_geometry": glyph_data["geometry"][1][2],
            "y_max_geometry": glyph_data["geometry"][1][3],
            "x_min_candidate": glyph_data["candidate"][1][0],
            "y_min_candidate": glyph_data["candidate"][1][1],
            "x_max_candidate": glyph_data["candidate"][1][2],
            "y_max_candidate": glyph_data["candidate"][1][3],
            "source_components": metrics["source"].components,
            "source_holes": metrics["source"].holes,
            "geometry_components": metrics["geometry"].components,
            "geometry_holes": metrics["geometry"].holes,
            "candidate_components": metrics["candidate"].components,
            "candidate_holes": metrics["candidate"].holes,
            "candidate_vs_geometry_iou": _iou(masks["geometry"], masks["candidate"]),
            "small_source_components": small_metrics["source"].components,
            "small_source_holes": small_metrics["source"].holes,
            "small_candidate_components": small_metrics["candidate"].components,
            "small_candidate_holes": small_metrics["candidate"].holes,
        }
        seen[ch] = row
        rows.append(row)

    width_summaries = {
        role: _stroke_summary(font, "".join(dict.fromkeys(CHARS_63)), width_px)
        for role, font in fonts.items()
    }
    for font in fonts.values():
        font.close()

    electric = seen["电"]
    summary = {
        "renderer_versions": {
            "pillow": PILLOW_VERSION,
            "freetype": features.version_module("freetype2") or "unavailable",
            "fonttools": fontTools.__version__,
        },
        "electric_bbox_widths_fu": {
            role: electric[f"bbox_width_{role}_fu"]
            for role in ("source", "geometry", "candidate")
        },
        "electric_x_bounds_fu": {
            role: (electric[f"x_min_{role}"], electric[f"x_max_{role}"])
            for role in ("source", "geometry", "candidate")
        },
        "electric_advances_fu": {
            role: electric[f"advance_{role}"]
            for role in ("source", "geometry", "candidate")
        },
        "sample_entries": len(CHARS_63),
        "unique_glyphs": len(set(CHARS_63)),
        "large_render_px_per_em": render_size,
        "small_render_px_per_em": small_size,
        "topology_errors": topology_errors,
        "advance_errors": advance_errors,
        "mapping_errors": mapping_errors,
        "small_size_topology_differences_source_vs_candidate": len(small_topology_differences),
        "small_size_topology_difference_codepoints": [ord(ch) for ch in small_topology_differences],
        "width_summaries": width_summaries,
    }
    return rows, summary


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, summary: dict, csv_path: Path | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    widths = summary["width_summaries"]
    csv_evidence = (
        f"See [`{csv_path.name}`]({csv_path.name}) for all {summary['sample_entries']} sample entries, "
        "including the duplicate entry, advances, full glyph bounds, FreeType component/counter counts, "
        "and geometry-to-candidate IoU."
        if csv_path is not None
        else "No CSV was requested for this run."
    )
    difference_codes = ", ".join(
        f"U+{codepoint:04X}"
        for codepoint in summary["small_size_topology_difference_codepoints"]
    ) or "none"
    lines = [
        "# V9 sample-wide raster/topology audit",
        "",
        f"- Sample scope: {summary['sample_entries']} entries / {summary['unique_glyphs']} unique glyphs.",
        f"- Independent renderer: Pillow {summary['renderer_versions']['pillow']} / FreeType {summary['renderer_versions']['freetype']}; FontTools {summary['renderer_versions']['fonttools']}; large audit size {summary['large_render_px_per_em']} px per em.",
        "- Raster method: alpha threshold ≥128; 8-connected components; counters = components minus Euler number; binary-mask IoU.",
        "- Hard checks: source → geometry and geometry → candidate component/counter topology, cmap mapping, UPM/weight, and advance widths.",
        f"- Hard-check topology failures: {len(summary['topology_errors'])}.",
        f"- Advance-width failures: {len(summary['advance_errors'])}.",
        f"- Font/sample mapping failures: {len(summary['mapping_errors'])}.",
        f"- Diagnostic only: source-vs-candidate topology differs in {summary['small_size_topology_differences_source_vs_candidate']} unique glyph(s) at {summary['small_render_px_per_em']} px/em ({difference_codes}); low-resolution rasterization is not a vector-topology pass/fail gate.",
        "",
        "## U+7535 exterior-width constraint",
        "",
        f"- Advance widths (source / geometry / candidate): {summary['electric_advances_fu']['source']} / {summary['electric_advances_fu']['geometry']} / {summary['electric_advances_fu']['candidate']} FU.",
        f"- Ink-bbox widths (source / geometry / candidate): {summary['electric_bbox_widths_fu']['source']} / {summary['electric_bbox_widths_fu']['geometry']} / {summary['electric_bbox_widths_fu']['candidate']} FU.",
        f"- Candidate x bounds: source {summary['electric_x_bounds_fu']['source']} FU → candidate {summary['electric_x_bounds_fu']['candidate']} FU. Any residual difference is reported, not represented as exact exterior-width preservation.",
        "",
        "## Stroke-width proxies (900 px skeleton-distance audit)",
        "",
        "| Stage | Glyphs | Median of per-glyph medians (FU) | Across-glyph CV | Within-glyph CV mean | Within-glyph CV max |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for role in ("source", "geometry", "candidate"):
        values = widths[role]
        lines.append(
            f"| {role} | {values['glyphs']} | {values['median_of_medians_fu']:.3f} | "
            f"{values['across_glyph_cv']:.5f} | {values['within_glyph_cv_mean']:.5f} | "
            f"{values['within_glyph_cv_max']:.5f} |"
        )
    lines.extend([
        "",
        "These width values are skeleton-distance proxies, not proof of equal perceived weight at joins or small device sizes.",
        "",
        "## Per-entry evidence",
        "",
        csv_evidence,
        "",
        "The 48 px diagnostic is intentionally reported separately because the source contains hinting and the research candidate does not; pixel-level component counts at small sizes are renderer-dependent.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="local static D/400 source TTF")
    parser.add_argument("--geometry", required=True, type=Path, help="local edited geometry-base TTF")
    parser.add_argument("--candidate", required=True, type=Path, help="local shared-width candidate TTF")
    parser.add_argument("--csv", type=Path, help="write a per-sample CSV")
    parser.add_argument("--markdown", type=Path, help="write a summary Markdown report")
    parser.add_argument("--render-size", type=int, default=DEFAULT_RENDER_SIZE, help="large size in px/em; default 1000")
    parser.add_argument("--small-size", type=int, default=DEFAULT_SMALL_SIZE, help="diagnostic raster size in px/em; default 48")
    parser.add_argument("--width-px", type=int, default=900, help="skeleton-width audit canvas size")
    args = parser.parse_args()
    rows, summary = audit(
        args.source, args.geometry, args.candidate,
        render_size=args.render_size,
        small_size=args.small_size,
        width_px=args.width_px,
    )
    if args.csv:
        write_csv(args.csv, rows)
    if args.markdown:
        write_markdown(args.markdown, summary, args.csv)
    print(f"samples={summary['sample_entries']} entries / {summary['unique_glyphs']} unique")
    print(f"topology failures={len(summary['topology_errors'])}")
    for issue in summary["topology_errors"]:
        print("TOPOLOGY:", issue)
    print(f"advance failures={len(summary['advance_errors'])}")
    for issue in summary["advance_errors"]:
        print("ADVANCE:", issue)
    print(f"mapping/UPM/weight failures={len(summary['mapping_errors'])}")
    for issue in summary["mapping_errors"]:
        print("MAPPING:", issue)
    print(
        f"small-size topology diagnostics={summary['small_size_topology_differences_source_vs_candidate']} "
        f"at {summary['small_render_px_per_em']} px/em (not a hard gate)"
    )
    for role, values in summary["width_summaries"].items():
        print(
            f"{role}: glyphs={values['glyphs']}, median-of-medians="
            f"{values['median_of_medians_fu']:.3f} FU, across-CV="
            f"{values['across_glyph_cv']:.5f}, within-CV mean="
            f"{values['within_glyph_cv_mean']:.5f}, max="
            f"{values['within_glyph_cv_max']:.5f}"
        )
    if summary["topology_errors"] or summary["advance_errors"] or summary["mapping_errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
