#!/usr/bin/env python3
"""Render the V8 research candidate, sketch study, width reference, and details."""
from __future__ import annotations

import argparse
import math
from pathlib import Path as FilePath

from PIL import Image, ImageOps
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch, Rectangle
from fontTools.ttLib import TTFont

if __package__:
    from . import hook_cut
    from .render_grid import glyph_path
    from .tsukushi_a_preview_simplify import (
        CAP_EXTENSION_RATIOS,
        CHARS_63,
        EXPECTED_HOOKS,
        EXPECTED_ROUND_CAPS,
        EXPECTED_ROUND_TIPS,
        SAMPLE_CHARS,
    )
else:
    import hook_cut
    from render_grid import glyph_path
    from tsukushi_a_preview_simplify import (
        CAP_EXTENSION_RATIOS,
        CHARS_63,
        EXPECTED_HOOKS,
        EXPECTED_ROUND_CAPS,
        EXPECTED_ROUND_TIPS,
        SAMPLE_CHARS,
    )


DETAIL_HOOK_CANDIDATES = "乙也了包子己已电"
REFERENCE_GLYPHS = "鸟也电森暖水马包书好国己已"
DEFAULT_LIMITS = (-100, 1100, -190, 1010)


def draw_glyph(ax, font: TTFont, ch: str, color="#20252d", alpha=1.0, limits=None):
    name = font.getBestCmap().get(ord(ch))
    if name:
        ax.add_patch(PathPatch(
            glyph_path(font, name), facecolor=color, edgecolor="none", alpha=alpha
        ))
    x0, x1, y0, y1 = limits or DEFAULT_LIMITS
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")


def _crop_sketch(image_path: FilePath) -> Image.Image:
    image = Image.open(image_path).convert("RGB")
    gray = ImageOps.grayscale(image).point(lambda value: 255 if value < 245 else 0)
    bbox = gray.getbbox()
    if bbox is None:
        raise ValueError(f"Sketch contains no visible strokes: {image_path}")
    return image.crop(bbox)


def _font_checks(font: TTFont, label: str) -> None:
    if "fvar" in font or font["OS/2"].usWeightClass != 400:
        raise ValueError(f"{label} must be a static usWeightClass=400 instance")
    missing = [ch for ch in CHARS_63 if ord(ch) not in font.getBestCmap()]
    if missing:
        raise ValueError(f"{label} is missing sample characters: {''.join(missing)}")


def hook_rows(base: TTFont):
    """Return full-glyph crops for eight representative manually reviewed hook caps."""
    cmap = base.getBestCmap()
    glyf = base["glyf"]
    rows = []
    for ch in DETAIL_HOOK_CANDIDATES:
        name = cmap[ord(ch)]
        glyph = glyf[name]
        coords, ends, flags = glyph.getCoordinates(glyf)
        contours = hook_cut.split_contours(coords, ends, flags)
        for ci, i, j, *_ in hook_cut.find_hooks(contours):
            contour = contours[ci]
            ax, ay = contour[i][0], contour[i][1]
            bx, by = contour[j][0], contour[j][1]
            gate = math.hypot(bx - ax, by - ay)
            extension = gate * CAP_EXTENSION_RATIOS.get(ch, 0.0)
            side = max(gate * 4.0 + extension * 2.0, 260.0)
            cx, cy = (ax + bx) * 0.5, (ay + by) * 0.5
            limits = (cx - side / 2, cx + side / 2,
                      cy - side / 2, cy + side / 2)
            rows.append((ch, limits, f"U+{ord(ch):04X} · end {len(rows) + 1:02d}"))
    if len(rows) != 8:
        raise AssertionError(f"Expected eight selected hook caps, got {len(rows)}")
    return rows


def render_overview(base: TTFont, geometry: TTFont, variant: TTFont, out_path: FilePath):
    if len(CHARS_63) != 63 or len(set(CHARS_63)) != 62:
        raise AssertionError("Audit sample must be 63 entries / 62 unique glyphs")
    fig = plt.figure(figsize=(27.0, 13.3), facecolor="#fbfaf7")
    col_widths = [1.0] * 7 + [.19] + [1.0] * 7 + [.19] + [1.0] * 7
    gs = fig.add_gridspec(
        9, len(col_widths), left=.018, right=.982, top=.835, bottom=.115,
        wspace=.075, hspace=.115, width_ratios=col_widths,
    )
    fig.text(.018, .965, "TSUKUSHI A · D/400 · V8 RESEARCH CANDIDATE", fontsize=24,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.018, .928,
             "63 sample entries · 62 unique glyphs · shared 74 FU stroke-width target · candidate only, not production",
             fontsize=11.2, color="#666a70", ha="left", va="top")
    fig.text(.018, .875, "SOURCE · original A-D outlines", fontsize=12.5,
             fontweight="bold", color="#262930", ha="left", va="top")
    fig.text(.355, .875, "GEOMETRY BASE · rounded ends + directed terminal edits", fontsize=12.5,
             fontweight="bold", color="#262930", ha="left", va="top")
    fig.text(.692, .875, "V8 · shared stroke radius + narrower frame at U+7535", fontsize=12.5,
             fontweight="bold", color="#262930", ha="left", va="top")

    for i, ch in enumerate(CHARS_63):
        row, col = divmod(i, 7)
        for font, grid_col in ((base, col), (geometry, 8 + col), (variant, 16 + col)):
            ax = fig.add_subplot(gs[row, grid_col])
            ax.set_facecolor("#fffefa")
            draw_glyph(ax, font, ch)
            ax.add_patch(Rectangle(
                (0, 0), 1, 1, transform=ax.transAxes, fill=False,
                edgecolor="#dfdcd4", linewidth=.65, clip_on=False, zorder=5,
            ))
            ax.text(.055, .945, f"{i + 1:02d}", transform=ax.transAxes,
                    ha="left", va="top", fontsize=6.1, color="#8a8984")

    fig.text(.018, .073,
             f"Geometry stage: {EXPECTED_HOOKS} manually reviewed semicircular hook caps + "
             f"{EXPECTED_ROUND_CAPS} safe free-end rounds + {EXPECTED_ROUND_TIPS} safe tip round; "
             "U+5DF1/U+5DF2 endings modestly extended. All 62 unique outlines then receive one shared stroke radius.",
             fontsize=8.9, color="#53565b", ha="left", va="bottom")
    fig.text(.018, .041,
             "U+7535: inner-frame centerline spacing ×0.94 about the measured divider axis; radius is restored to the shared target, not thickened. "
             "Geometry/width metrics are research proxies; no aesthetic approval or device-rendering claim.",
             fontsize=8.5, color="#777a7e", ha="left", va="bottom")
    fig.savefig(out_path, dpi=145, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("saved", out_path)


def render_sketch_study(
    base: TTFont,
    variant: TTFont,
    bird_sketch: FilePath,
    ye_sketch: FilePath,
    out_path: FilePath,
):
    sketches = {"鸟": bird_sketch, "也": ye_sketch}
    gesture_notes = {
        "鸟": "Compact enclosure\n+ crossing/rising accent\n(no traced paths)",
        "也": "Open turn\n+ long lower sweep\n(distinct from U+9E1F)",
    }
    fig = plt.figure(figsize=(16.0, 8.4), facecolor="#fbfaf7")
    gs = fig.add_gridspec(
        2, 4, left=.035, right=.985, top=.825, bottom=.12,
        wspace=.075, hspace=.11, width_ratios=[.72, 1.0, 1.0, 1.0],
    )
    fig.text(.035, .96, "V8 · SKETCH GESTURE STUDY", fontsize=22,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.035, .915,
             "Separate references for U+9E1F and U+4E5F. Sketch crops keep native aspect; sketch and glyph panels use independent scales, with no trace overlay or point map.",
             fontsize=10.2, color="#666a70", ha="left", va="top")
    for x, title in ((.035, "CODEPOINT / IDEA"), (.23, "USER SKETCH"),
                     (.49, "SOURCE GLYPH"), (.75, "V8 CANDIDATE")):
        fig.text(x, .86, title, fontsize=9.5, fontweight="bold",
                 color="#55585d", ha="left", va="top")

    for row, ch in enumerate(("鸟", "也")):
        sketch = _crop_sketch(sketches[ch])

        label_ax = fig.add_subplot(gs[row, 0])
        label_ax.axis("off")
        label_ax.text(.04, .79, f"U+{ord(ch):04X}", fontsize=16, fontweight="bold",
                      color="#262930", ha="left", va="top")
        label_ax.text(.04, .53, f"SKETCH {row + 1}", fontsize=8.5, fontweight="bold",
                      color="#777a7e", ha="left", va="top")
        label_ax.text(.04, .31, gesture_notes[ch], fontsize=8.0,
                      color="#55585d", ha="left", va="top")

        sketch_ax = fig.add_subplot(gs[row, 1])
        sketch_ax.imshow(sketch, origin="upper")
        sketch_ax.set_aspect("equal")
        sketch_ax.axis("off")

        source_ax = fig.add_subplot(gs[row, 2])
        draw_glyph(source_ax, base, ch, color="#26364a", limits=DEFAULT_LIMITS)
        candidate_ax = fig.add_subplot(gs[row, 3])
        draw_glyph(candidate_ax, variant, ch, color="#20252d", limits=DEFAULT_LIMITS)

    fig.text(.035, .047,
             "The candidate retains the distinct Tsukushi A structures; shared width normalization is applied without transferring sketch coordinates.",
             fontsize=8.8, color="#777a7e", ha="left", va="bottom")
    fig.savefig(out_path, dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("saved", out_path)


def render_width_reference(base: TTFont, variant: TTFont, reference: TTFont, out_path: FilePath):
    chars = REFERENCE_GLYPHS
    fig = plt.figure(figsize=(16.0, 17.0), facecolor="#fbfaf7")
    gs = fig.add_gridspec(
        len(chars), 4, left=.035, right=.985, top=.86, bottom=.15,
        wspace=.05, hspace=.075, width_ratios=[.7, 1.0, 1.0, 1.0],
    )
    fig.text(.035, .96, "V8 · LICENSED STROKE-WIDTH REFERENCE", fontsize=21,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.035, .92,
             "Noto Sans SC 400 (OFL 1.1) was studied for shared weight behavior only; no Noto outlines or glyph coordinates are copied.",
             fontsize=9.8, color="#666a70", ha="left", va="top")
    for x, title in ((.035, "CODEPOINT"), (.22, "SOURCE A-D"),
                     (.48, "V8 SHARED WIDTH"), (.74, "NOTO SC 400 · WIDTH REFERENCE")):
        fig.text(x, .885, title, fontsize=9.2, fontweight="bold",
                 color="#55585d", ha="left", va="top")

    for row, ch in enumerate(chars):
        label_ax = fig.add_subplot(gs[row, 0])
        label_ax.axis("off")
        label_ax.text(.04, .74, f"U+{ord(ch):04X}", fontsize=10.5,
                      fontweight="bold", color="#45484d", ha="left", va="top")
        for col, font in enumerate((base, variant, reference), start=1):
            ax = fig.add_subplot(gs[row, col])
            draw_glyph(ax, font, ch, limits=DEFAULT_LIMITS)

    fig.text(.035, .107,
             "900 px skeleton-distance proxy, 62 unique sample glyphs: source median-of-medians 76.74 FU; Noto SC 400 73.89 FU; V8 target 74.00 FU.",
             fontsize=9.0, color="#53565b", ha="left", va="bottom")
    fig.text(.035, .077,
             "Across-glyph CV of per-glyph median width: source 0.0781 → V8 0.0096. Within-glyph CV mean: source 0.0745 → V8 0.0529 (max 0.1585, U+68EE).",
             fontsize=8.8, color="#53565b", ha="left", va="bottom")
    fig.text(.035, .045,
             "These are raster/skeleton estimates, not an aesthetic pass or a claim that every junction has identical apparent weight. Noto was not a shape template.",
             fontsize=8.5, color="#777a7e", ha="left", va="bottom")
    fig.savefig(out_path, dpi=165, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("saved", out_path)


def render_endpoint_detail(base: TTFont, variant: TTFont, out_path: FilePath):
    rows = hook_rows(base)
    rows.append(("电", (145, 800, 190, 650), "U+7535 · inner frame"))
    fig = plt.figure(figsize=(17.0, 16.5), facecolor="#fbfaf7")
    gs = fig.add_gridspec(
        len(rows), 4, left=.035, right=.985, top=.89, bottom=.06,
        wspace=.055, hspace=.075, width_ratios=[.9, 1.0, 1.0, 1.0],
    )
    fig.text(.035, .965, "V8 · HOOK ENDS AND U+7535 FRAME", fontsize=21,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.035, .925,
             "Full glyph locations and detail crops. Blue = source; dark = V8; overlay aligns their rendered glyph coordinates.",
             fontsize=9.9, color="#666a70", ha="left", va="top")
    for x, title in ((.035, "LOCATION"), (.275, "SOURCE CROP"),
                     (.515, "V8 CROP"), (.755, "OVERLAY")):
        fig.text(x, .9, title, fontsize=9.2, fontweight="bold",
                 color="#55585d", ha="left", va="top")

    for row, (ch, limits, label) in enumerate(rows):
        loc_ax = fig.add_subplot(gs[row, 0])
        draw_glyph(loc_ax, base, ch)
        loc_ax.add_patch(Rectangle(
            (limits[0], limits[2]), limits[1] - limits[0], limits[3] - limits[2],
            fill=False, edgecolor="#e97642", linewidth=1.1, zorder=5,
        ))
        loc_ax.text(.03, .97, label, transform=loc_ax.transAxes,
                    ha="left", va="top", fontsize=7.5,
                    color="#45484d", fontweight="bold")
        source_ax = fig.add_subplot(gs[row, 1])
        draw_glyph(source_ax, base, ch, color="#26364a", limits=limits)
        candidate_ax = fig.add_subplot(gs[row, 2])
        draw_glyph(candidate_ax, variant, ch, color="#20252d", limits=limits)
        overlay_ax = fig.add_subplot(gs[row, 3])
        overlay_ax.add_patch(PathPatch(
            glyph_path(base, base.getBestCmap()[ord(ch)]),
            facecolor="#52677e", edgecolor="none", alpha=.55,
        ))
        overlay_ax.add_patch(PathPatch(
            glyph_path(variant, variant.getBestCmap()[ord(ch)]),
            facecolor="#e97642", edgecolor="none", alpha=.55,
        ))
        overlay_ax.set_xlim(limits[0], limits[1])
        overlay_ax.set_ylim(limits[2], limits[3])
        overlay_ax.set_aspect("equal")
        overlay_ax.axis("off")

    fig.text(.035, .026,
             "U+5DF1/U+5DF2 final strokes: +1.0×/+1.5× their gate width with rounded caps. U+7535: inner-frame x-spacing ×0.94 around the divider centerline; shared 74 FU width target is restored after spacing change.",
             fontsize=8.2, color="#777a7e", ha="left", va="bottom")
    fig.savefig(out_path, dpi=165, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("saved", out_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=FilePath, help="Original static A D/400 TTF")
    parser.add_argument("--geometry-base", required=True, type=FilePath,
                        help="Temporary output of tsukushi_a_preview_simplify.py")
    parser.add_argument("--variant", required=True, type=FilePath, help="Temporary V8 candidate TTF")
    parser.add_argument("--reference-font", required=True, type=FilePath,
                        help="Static Noto Sans SC 400 TTF used only as a width reference")
    parser.add_argument("--outdir", required=True, type=FilePath,
                        help="Directory for current V8 research PNGs")
    repo_root = FilePath(__file__).resolve().parents[1]
    parser.add_argument(
        "--bird-sketch", type=FilePath,
        default=repo_root / "docs/round-preview/sketches/bird-reference.png",
    )
    parser.add_argument(
        "--ye-sketch", type=FilePath,
        default=repo_root / "docs/round-preview/sketches/ye-reference.png",
    )
    args = parser.parse_args()
    base, geometry, variant, reference = (
        TTFont(args.baseline), TTFont(args.geometry_base),
        TTFont(args.variant), TTFont(args.reference_font),
    )
    for label, font in (("baseline", base), ("geometry base", geometry),
                        ("variant", variant), ("reference font", reference)):
        _font_checks(font, label)
    if len(CHARS_63) != 63 or len(SAMPLE_CHARS) != 62:
        raise AssertionError("V8 requires 63 sample entries / 62 unique glyphs")
    outdir = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    render_overview(base, geometry, variant, outdir / "tsukushi-a-v8-63-sample-overview.png")
    render_sketch_study(
        base, variant, args.bird_sketch, args.ye_sketch,
        outdir / "tsukushi-a-v8-sketch-gesture-study.png",
    )
    render_width_reference(
        base, variant, reference, outdir / "tsukushi-a-v8-stroke-width-reference.png"
    )
    render_endpoint_detail(
        base, variant, outdir / "tsukushi-a-v8-endpoint-electric-detail.png"
    )
    for font in (base, geometry, variant, reference):
        font.close()


if __name__ == "__main__":
    main()
