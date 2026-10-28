#!/usr/bin/env python3
"""Render current V10 sample, focused corrections, and separate sketch studies."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageOps
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch, Rectangle
from fontTools.ttLib import TTFont

from tools.build_tsukushi_a_v10 import HOOK_CUT_PLAN_V10, VECTOR_OVERRIDE_CHARS
from tools.hook_cut import split_contours
from tools.render_grid import glyph_path
from tools.tsukushi_a_preview_simplify import (
    CHARS_63,
    _round_cap_axis,
    cap_extension_to_preserve_extent,
)

FOCUS_CHARS = "颜暖电己已巳也乙包鸟色龙子"
CHANGED_CHARS = VECTOR_OVERRIDE_CHARS | {"电"}
FOCUS_NOTES = {
    "颜": "Retain the original dot shapes and visual weight; avoid shared-width redrawing.",
    "暖": "Restore the left-side component and the visible weight of its left-falling stroke.",
    "电": "Narrow only the inner-frame spacing (0.97 scale); do not thicken the bars.",
    "己": "Straighten the terminal along its measured direction; round the cap; remove the extra +8 FU extension.",
    "已": "Use the same terminal direction as its related form; round the cap; remove the extra +8 FU extension.",
    "巳": "Remove the terminal hook and use a straight, rounded end aligned with the related terminal family.",
    "也": "Remove the hook; retain the source skeleton and compare against this glyph's own sketch separately.",
    "乙": "Open single-stroke sweep; no return hook; round terminal.",
    "包": "Replace both hook ends with straight, rounded terminals.",
    "鸟": "Redraw as three broad gestures from its own sketch; do not trace the contour.",
    "色": "Align the final terminal direction with the related straight-terminal family.",
    "龙": "Restore the vector skeleton; avoid raster-reconstruction deformation.",
    "子": "Restore the vector skeleton; avoid raster-reconstruction deformation.",
}
DEFAULT_LIMITS = (-100, 1100, -190, 1010)


def draw_glyph(ax, font: TTFont, char: str, color: str, limits=DEFAULT_LIMITS):
    name = font.getBestCmap().get(ord(char))
    if not name:
        raise ValueError(f"Font is missing {char!r}")
    ax.add_patch(PathPatch(glyph_path(font, name), facecolor=color, edgecolor="none"))
    ax.set_xlim(limits[0], limits[1])
    ax.set_ylim(limits[2], limits[3])
    ax.set_aspect("equal")
    ax.axis("off")


def _font_checks(font: TTFont, label: str) -> None:
    if "fvar" in font or font["OS/2"].usWeightClass != 400:
        raise ValueError(f"{label} must be a static usWeightClass=400 font")
    if "glyf" not in font or font["head"].unitsPerEm != 1000:
        raise ValueError(f"{label} must be TrueType with UPM 1000")
    missing = [char for char in CHARS_63 if ord(char) not in font.getBestCmap()]
    if missing:
        raise ValueError(f"{label} is missing sample glyphs: {''.join(missing)}")


def _sketch_crop(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    mask = ImageOps.grayscale(image).point(lambda value: 255 if value < 245 else 0)
    bbox = mask.getbbox()
    if bbox is None:
        raise ValueError(f"Sketch has no visible strokes: {path}")
    return image.crop(bbox)


def render_overview(source: TTFont, candidate: TTFont, out_path: Path) -> None:
    fig = plt.figure(figsize=(23.0, 13.0), facecolor="#fbfaf7")
    gs = fig.add_gridspec(
        9, 15, left=.025, right=.985, top=.83, bottom=.12,
        wspace=.075, hspace=.11, width_ratios=[1] * 7 + [.22] + [1] * 7,
    )
    fig.text(.025, .965, "TSUKUSHI A · D/400 · V10 RESEARCH CANDIDATE",
             fontsize=22, fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.025, .925,
             "63 entries / 62 unique glyphs · source vs V10 · static research only, not production or visual acceptance",
             fontsize=10.5, color="#666a70", ha="left", va="top")
    fig.text(.025, .875, "SOURCE · original A-D outlines", fontsize=11.5,
             fontweight="bold", color="#26364a", ha="left", va="top")
    fig.text(.535, .875, "V10 · targeted vector corrections + V9 shared-width baseline",
             fontsize=11.5, fontweight="bold", color="#20252d", ha="left", va="top")

    for index, char in enumerate(CHARS_63):
        row, column = divmod(index, 7)
        for font, grid_column, color in (
            (source, column, "#26364a"),
            (candidate, 8 + column, "#20252d"),
        ):
            ax = fig.add_subplot(gs[row, grid_column])
            ax.set_facecolor("#fffefa")
            draw_glyph(ax, font, char, color)
            ax.add_patch(Rectangle(
                (0, 0), 1, 1, transform=ax.transAxes, fill=False,
                edgecolor="#dfdcd4", linewidth=.65, clip_on=False, zorder=5,
            ))
            ax.text(.055, .945, f"{index + 1:02d}", transform=ax.transAxes,
                    ha="left", va="top", fontsize=6.2, color="#8a8984")
            if grid_column >= 8 and char in CHANGED_CHARS:
                ax.text(.94, .94, "V10", transform=ax.transAxes, ha="right", va="top",
                        fontsize=5.8, fontweight="bold", color="#b24a32")

    fig.text(.025, .075,
             "12 glyphs use restored or newly drawn vector outlines; the other sample glyphs retain the V9 74-FU reconstruction, including the electric glyph's 0.97 frame spacing edit.",
             fontsize=8.8, color="#53565b", ha="left", va="bottom")
    fig.text(.025, .043,
             "The glyph-specific vector overrides intentionally do not claim an exact 74-FU width; the independent audit reports the across-sample proxy and all residual topology/size diagnostics.",
             fontsize=8.5, color="#777a7e", ha="left", va="bottom")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("saved", out_path)


def render_focused(source: TTFont, candidate: TTFont, out_path: Path) -> None:
    fig = plt.figure(figsize=(18.5, 14.0), facecolor="#fbfaf7")
    gs = fig.add_gridspec(
        len(FOCUS_CHARS) + 1, 4, left=.025, right=.985, top=.88, bottom=.045,
        wspace=.06, hspace=.075, width_ratios=[.58, 1.0, 1.0, 1.65],
    )
    fig.text(.025, .96, "V10 · GLYPH-SPECIFIC CORRECTIONS", fontsize=21,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.025, .92,
             "Source and candidate are shown at the same em scale. Notes describe the implemented edit, not a claim of visual approval.",
             fontsize=9.8, color="#666a70", ha="left", va="top")
    for column, title in enumerate(("CHARACTER", "SOURCE", "V10", "EDIT INTENT")):
        ax = fig.add_subplot(gs[0, column])
        ax.axis("off")
        ax.text(.02, .8, title, transform=ax.transAxes, fontsize=8.5,
                fontweight="bold", color="#55585d", ha="left", va="top")

    for row, char in enumerate(FOCUS_CHARS):
        label_ax = fig.add_subplot(gs[row + 1, 0])
        draw_glyph(label_ax, source, char, "#26364a", limits=(-150, 1150, -250, 1150))

        source_ax = fig.add_subplot(gs[row + 1, 1])
        draw_glyph(source_ax, source, char, "#26364a")
        candidate_ax = fig.add_subplot(gs[row + 1, 2])
        draw_glyph(candidate_ax, candidate, char, "#20252d")
        note_ax = fig.add_subplot(gs[row + 1, 3])
        note_ax.axis("off")
        note_ax.text(.02, .55, FOCUS_NOTES[char], fontsize=9.0,
                     color="#3d4148", ha="left", va="center", wrap=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("saved", out_path)


def render_sketch_study(
    source: TTFont,
    candidate: TTFont,
    bird_sketch: Path,
    ye_sketch: Path,
    out_path: Path,
) -> None:
    sketches = {"鸟": bird_sketch, "也": ye_sketch}
    fig = plt.figure(figsize=(16.5, 8.2), facecolor="#fbfaf7")
    gs = fig.add_gridspec(
        3, 4, left=.035, right=.985, top=.84, bottom=.095,
        wspace=.08, hspace=.14, width_ratios=[.65, 1.0, 1.0, 1.0],
    )
    fig.text(.035, .96, "V10 · SEPARATE SKETCH GESTURE STUDY", fontsize=20,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.035, .915,
             "Each sketch is matched only to its own character. No trace overlay or point transfer; panels use independent scales.",
             fontsize=9.6, color="#666a70", ha="left", va="top")
    fig.text(.035, .875,
             "U+9E1F: three broad gestures rebuilt from its own sketch.  U+4E5F: distinct sketch used as whole-shape guidance; source skeleton retained.",
             fontsize=8.4, color="#53565b", ha="left", va="top")
    for column, title in enumerate(("CODEPOINT", "USER SKETCH", "SOURCE GLYPH", "V10 GLYPH")):
        ax = fig.add_subplot(gs[0, column])
        ax.axis("off")
        ax.text(.02, .8, title, transform=ax.transAxes, fontsize=8.5,
                fontweight="bold", color="#55585d", ha="left", va="top")

    for row, char in enumerate(("鸟", "也")):
        label_ax = fig.add_subplot(gs[row + 1, 0])
        draw_glyph(label_ax, source, char, "#26364a", limits=(-150, 1150, -250, 1150))
        label_ax.text(.5, .07, f"U+{ord(char):04X}", transform=label_ax.transAxes,
                      fontsize=7.3, color="#777a7e", ha="center", va="bottom")

        sketch_ax = fig.add_subplot(gs[row + 1, 1])
        sketch_ax.imshow(_sketch_crop(sketches[char]), origin="upper")
        sketch_ax.set_aspect("equal")
        sketch_ax.axis("off")
        draw_glyph(fig.add_subplot(gs[row + 1, 2]), source, char, "#26364a")
        draw_glyph(fig.add_subplot(gs[row + 1, 3]), candidate, char, "#20252d")

    fig.text(.035, .035,
             "V10 is a reversible research draft; the owner decides whether the displayed glyphs match the intended style.",
             fontsize=8.4, color="#777a7e", ha="left", va="bottom")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=165, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("saved", out_path)


def _terminal_detail_limits(source: TTFont, char: str, spec) -> tuple[float, float, float, float]:
    name = source.getBestCmap()[ord(char)]
    glyph = source["glyf"][name]
    glyph.recalcBounds(source["glyf"])
    if spec is None:
        pad = 35
        return glyph.xMin - pad, glyph.xMax + pad, glyph.yMin - pad, glyph.yMax + pad

    contour_index, start_index, end_index = spec
    coords, ends, flags = glyph.getCoordinates(source["glyf"])
    contour = split_contours(coords, ends, flags)[contour_index]
    axis, gate_width = _round_cap_axis(contour, len(contour), start_index, end_index)
    extension = cap_extension_to_preserve_extent(
        contour, len(contour), start_index, end_index, extra=0.0
    )
    a, b = contour[start_index], contour[end_index]
    midpoint = ((a[0] + b[0]) * .5, (a[1] + b[1]) * .5)
    center = (
        midpoint[0] + axis[0] * (extension * .5 + gate_width * .25),
        midpoint[1] + axis[1] * (extension * .5 + gate_width * .25),
    )
    half = max(gate_width * 1.3, extension * .5 + gate_width * 1.15, 72)
    return center[0] - half, center[0] + half, center[1] - half, center[1] + half


def render_terminal_details(source: TTFont, candidate: TTFont, out_path: Path) -> None:
    detail_rows = [
        ("己", 0, "terminal"),
        ("已", 0, "terminal"),
        ("巳", 0, "terminal"),
        ("也", 0, "terminal"),
        ("包", 0, "cap A"),
        ("包", 1, "cap B"),
        ("色", 0, "terminal"),
        ("龙", 0, "terminal"),
        ("子", 0, "terminal"),
        ("乙", None, "whole glyph"),
    ]
    fig = plt.figure(figsize=(14.5, 16.4), facecolor="#fbfaf7")
    gs = fig.add_gridspec(
        len(detail_rows) + 1, 3, left=.035, right=.985, top=.875, bottom=.035,
        hspace=.105, wspace=.07, width_ratios=[.76, 1.0, 1.0],
    )
    fig.text(.035, .96, "V10 · MAGNIFIED TERMINAL DETAILS", fontsize=20,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.035, .92,
             "Unhinted vector crops. Within each row, source and V10 share identical view limits; crop centers are chosen from the reviewed source gate.",
             fontsize=9.2, color="#666a70", ha="left", va="top")
    fig.text(.035, .89,
             "The final row shows the complete open-sweep glyph because it has no detector gate. These are research previews, not an aesthetic acceptance claim.",
             fontsize=8.6, color="#777a7e", ha="left", va="top")

    for column, title in enumerate(("TARGET", "SOURCE", "V10")):
        ax = fig.add_subplot(gs[0, column])
        ax.axis("off")
        ax.text(.02, .8, title, transform=ax.transAxes, fontsize=8.5,
                fontweight="bold", color="#55585d", ha="left", va="top")

    for row, (char, cap_index, label) in enumerate(detail_rows):
        if cap_index is None:
            spec = None
        else:
            spec = HOOK_CUT_PLAN_V10[char][cap_index]
        limits = _terminal_detail_limits(source, char, spec)
        label_ax = fig.add_subplot(gs[row + 1, 0])
        label_ax.axis("off")
        label_ax.text(.02, .62, f"U+{ord(char):04X}", fontsize=9.2,
                      fontweight="bold", color="#262930", ha="left", va="top")
        label_ax.text(.02, .28, label, fontsize=8.0,
                      color="#777a7e", ha="left", va="top")
        draw_glyph(fig.add_subplot(gs[row + 1, 1]), source, char, "#26364a", limits=limits)
        draw_glyph(fig.add_subplot(gs[row + 1, 2]), candidate, char, "#20252d", limits=limits)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=175, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("saved", out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="temporary static D/400 source TTF")
    parser.add_argument("--candidate", type=Path, required=True, help="temporary V10 TTF")
    parser.add_argument("--out-dir", type=Path, required=True, help="repository directory for current review PNGs")
    parser.add_argument("--bird-sketch", type=Path, default=Path("docs/round-preview/sketches/bird-reference.png"))
    parser.add_argument("--ye-sketch", type=Path, default=Path("docs/round-preview/sketches/ye-reference.png"))
    args = parser.parse_args()
    source, candidate = TTFont(args.source), TTFont(args.candidate)
    _font_checks(source, "source")
    _font_checks(candidate, "V10")
    render_overview(source, candidate, args.out_dir / "tsukushi-a-v10-63-sample-overview.png")
    render_focused(source, candidate, args.out_dir / "tsukushi-a-v10-focused-glyphs.png")
    render_sketch_study(
        source,
        candidate,
        args.bird_sketch,
        args.ye_sketch,
        args.out_dir / "tsukushi-a-v10-sketch-gesture-study.png",
    )
    render_terminal_details(
        source, candidate, args.out_dir / "tsukushi-a-v10-terminal-detail.png"
    )
    source.close()
    candidate.close()


if __name__ == "__main__":
    main()
