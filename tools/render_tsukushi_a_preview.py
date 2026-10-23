#!/usr/bin/env python3
"""Render overview, whole-glyph, endpoint, and sketch-reference views of V7."""
from __future__ import annotations

import argparse
import math
from pathlib import Path as FilePath

import numpy as np
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
        EXPECTED_CHANGED_GLYPHS,
        EXPECTED_HOOKS,
        EXPECTED_TERMINAL_ROUNDS,
        SAMPLE_CHARS,
    )
else:
    import hook_cut
    from render_grid import glyph_path
    from tsukushi_a_preview_simplify import (
        CAP_EXTENSION_RATIOS,
        EXPECTED_CHANGED_GLYPHS,
        EXPECTED_HOOKS,
        EXPECTED_TERMINAL_ROUNDS,
        SAMPLE_CHARS,
    )


CHARS_63 = (
    "一二三十口日回国了乙人入八木林森永心必水走建进这远道你好中国"
    "语言文字书写规范长美丽颜色锦绣风雨雪龙马鸟虫鱼电子已己巳也包囚暖田"
)
DETAIL_HOOK_CANDIDATES = "乙也了包子己已电"


def signature(font: TTFont, ch: str):
    name = font.getBestCmap()[ord(ch)]
    coords, ends, flags = font["glyf"][name].getCoordinates(font["glyf"])
    return (
        tuple((int(x), int(y)) for x, y in coords),
        tuple(int(end) for end in ends),
        tuple(bool(flag) for flag in flags),
    )


def draw_glyph(ax, font: TTFont, ch: str, color="#20252d", alpha=1.0, limits=None):
    name = font.getBestCmap().get(ord(ch))
    if name:
        ax.add_patch(PathPatch(
            glyph_path(font, name), facecolor=color, edgecolor="none", alpha=alpha
        ))
    if limits:
        ax.set_xlim(limits[0], limits[1])
        ax.set_ylim(limits[2], limits[3])
    else:
        ax.set_xlim(-100, 1100)
        ax.set_ylim(-190, 1010)
    ax.set_aspect("equal")
    ax.axis("off")


def hook_rows(base: TTFont):
    """Return full-glyph crop limits around the eight selected gates."""
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
            rows.append((ch, ci, i, j, limits, f"U+{ord(ch):04X} · end {len(rows) + 1:02d}"))
    if len(rows) != 8:
        raise AssertionError(f"Expected eight selected hook cuts, got {len(rows)}")
    return rows


def render_main(base: TTFont, variant: TTFont, out_path: FilePath):
    changed = {ch for ch in dict.fromkeys(CHARS_63)
               if signature(base, ch) != signature(variant, ch)}
    changed_entries = sum(ch in changed for ch in CHARS_63)
    if len(CHARS_63) != 63 or len(set(CHARS_63)) != 62:
        raise AssertionError("Audit sample must be 63 entries / 62 unique characters")
    if len(changed) != EXPECTED_CHANGED_GLYPHS:
        raise AssertionError(
            f"Expected {EXPECTED_CHANGED_GLYPHS} changed unique glyphs, got {len(changed)}"
        )

    fig = plt.figure(figsize=(18.4, 12.4), facecolor="#fbfaf7")
    gs = fig.add_gridspec(
        9, 15, left=.025, right=.975, top=.855, bottom=.105,
        wspace=.08, hspace=.12, width_ratios=[1] * 7 + [.22] + [1] * 7,
    )
    fig.text(.025, .965, "TSUKUSHI A · D/400 · SKETCH-REFERENCED V7", fontsize=25,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.025, .928,
             "63 audit entries · 62 unique glyphs · two user sketches guide whole-glyph proportions · research only",
             fontsize=11.5, color="#666a70", ha="left", va="top")
    fig.text(.025, .887, "BASELINE · original A-D outline", fontsize=14,
             fontweight="bold", color="#262930", ha="left", va="top")
    fig.text(.515, .887, "V7 · sketch-led + text-directed refinement", fontsize=14,
             fontweight="bold", color="#262930", ha="left", va="top")

    for i, ch in enumerate(CHARS_63):
        row, col = divmod(i, 7)
        for font, grid_col in ((base, col), (variant, 8 + col)):
            ax = fig.add_subplot(gs[row, grid_col])
            ax.set_facecolor("#fffefa")
            edge = "#d9793f" if ch in changed else "#e0ddd7"
            lw = 1.25 if ch in changed else .65
            draw_glyph(ax, font, ch)
            ax.add_patch(Rectangle(
                (0, 0), 1, 1, transform=ax.transAxes, fill=False,
                edgecolor=edge, linewidth=lw, clip_on=False, zorder=5,
            ))
            ax.text(.055, .945, f"{i + 1:02d}", transform=ax.transAxes,
                    ha="left", va="top", fontsize=6.5,
                    color="#c36b36" if ch in changed else "#9a9995",
                    fontweight="bold" if ch in changed else "normal")
    fig.text(.025, .067,
             f"Orange frames mark {len(changed)} changed glyphs ({changed_entries} sample entries): "
             f"{EXPECTED_HOOKS} reviewed hook caps + {EXPECTED_TERMINAL_ROUNDS} terminal rounds, "
             "sketch-guided whole-glyph proportions in U+9E1F/U+4E5F, longer U+5DF1/U+5DF2 endings, "
             "and narrower U+7535 inner openings.",
             fontsize=9.1, color="#53565b", ha="left", va="bottom")
    fig.text(.025, .034,
             "All other outlines are unchanged. No general corner rounding, stroke-width normalization, "
             "production-font edit, or device-rendering test.",
             fontsize=8.7, color="#777a7e", ha="left", va="bottom")
    fig.savefig(out_path, dpi=155, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"changed unique glyphs={len(changed)}, sample entries={changed_entries}")
    print("saved", out_path)


def render_detail(base: TTFont, variant: TTFont, out_path: FilePath):
    """Review every changed glyph at a shared full-glyph scale."""
    chars = [ch for ch in SAMPLE_CHARS
             if signature(base, ch) != signature(variant, ch)]
    if len(chars) != EXPECTED_CHANGED_GLYPHS:
        raise AssertionError(
            f"Expected {EXPECTED_CHANGED_GLYPHS} changed full glyphs, got {len(chars)}"
        )

    fig = plt.figure(
        figsize=(17.0, max(17.0, len(chars) * 1.35)), facecolor="#fbfaf7"
    )
    gs = fig.add_gridspec(
        len(chars), 4, left=.035, right=.985, top=.875, bottom=.045,
        wspace=.035, hspace=.10, width_ratios=[.72, 1.0, 1.0, 1.0],
    )
    fig.text(.035, .965, "V7 · FULL-GLYPH VISUAL REVIEW", fontsize=22,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.035, .925,
             "Same full-glyph scale in all columns; blue = baseline, orange = V7 overlay. "
             "Research candidate only, not visually accepted.",
             fontsize=10.5, color="#666a70", ha="left", va="top")
    for x, title in ((.035, "GLYPH"), (.22, "BASELINE"), (.48, "V7 CANDIDATE"), (.74, "OVERLAY")):
        fig.text(x, .895, title, fontsize=10, fontweight="bold",
                 color="#55585d", ha="left", va="top")

    for row, ch in enumerate(chars):
        ax = fig.add_subplot(gs[row, 0])
        ax.axis("off")
        ax.text(.04, .80, f"U+{ord(ch):04X}", fontsize=11, fontweight="bold",
                color="#45484d", ha="left", va="top")
        ax.text(.04, .58, f"{row + 1:02d} / {len(chars):02d}", fontsize=8.5,
                color="#777a7e", ha="left", va="top")

        ax = fig.add_subplot(gs[row, 1])
        draw_glyph(ax, base, ch, color="#26364a")
        ax = fig.add_subplot(gs[row, 2])
        draw_glyph(ax, variant, ch, color="#20252d")
        ax = fig.add_subplot(gs[row, 3])
        ax.add_patch(PathPatch(glyph_path(base, base.getBestCmap()[ord(ch)]),
                               facecolor="#52677e", edgecolor="none", alpha=.58))
        ax.add_patch(PathPatch(glyph_path(variant, variant.getBestCmap()[ord(ch)]),
                               facecolor="#e97642", edgecolor="none", alpha=.58))
        ax.set_xlim(-100, 1100)
        ax.set_ylim(-190, 1010)
        ax.set_aspect("equal")
        ax.axis("off")

    fig.text(.035, .018,
             f"{len(chars)} of 62 unique sample glyphs change; all 63 entries were processed for applicable terminal features. "
             "No production font was modified.",
             fontsize=8.5, color="#777a7e", ha="left", va="bottom")
    fig.savefig(out_path, dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("saved", out_path)


def render_local_detail(base: TTFont, variant: TTFont, out_path: FilePath):
    """Show all eight rounded endpoints and 电's inner frame in full-glyph context."""
    rows = hook_rows(base)
    rows.append(("电", None, None, None, (145, 800, 190, 650), "U+7535 · inner frame"))
    fig = plt.figure(figsize=(18.0, 18.0), facecolor="#fbfaf7")
    gs = fig.add_gridspec(
        len(rows), 4, left=.035, right=.985, top=.895, bottom=.04,
        wspace=.08, hspace=.12, width_ratios=[1.0, 1.0, 1.0, 1.0],
    )
    fig.text(.035, .965, "V7 · ENDPOINT AND INNER-FRAME DETAILS", fontsize=21,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.035, .925,
             "Crops come from complete glyphs. The final row isolates U+7535's internal frame; "
             "blue = baseline, orange = V7.",
             fontsize=10.3, color="#666a70", ha="left", va="top")
    for x, title in ((.035, "LOCATION"), (.285, "BASELINE CROP"),
                     (.535, "V7 CROP"), (.785, "OVERLAY")):
        fig.text(x, .905, title, fontsize=9.5, fontweight="bold",
                 color="#55585d", ha="left", va="top")

    for row, (ch, ci, _i, _j, limits, label) in enumerate(rows):
        ax = fig.add_subplot(gs[row, 0])
        draw_glyph(ax, base, ch, color="#26364a")
        ax.add_patch(Rectangle(
            (limits[0], limits[2]), limits[1] - limits[0], limits[3] - limits[2],
            fill=False, edgecolor="#e97642", linewidth=1.4, zorder=5,
        ))
        ax.text(.03, .97, label, transform=ax.transAxes,
                ha="left", va="top", fontsize=7.7,
                color="#45484d", fontweight="bold")
        ax = fig.add_subplot(gs[row, 1])
        draw_glyph(ax, base, ch, color="#26364a", limits=limits)
        ax = fig.add_subplot(gs[row, 2])
        draw_glyph(ax, variant, ch, color="#20252d", limits=limits)
        ax = fig.add_subplot(gs[row, 3])
        ax.add_patch(PathPatch(glyph_path(base, base.getBestCmap()[ord(ch)]),
                               facecolor="#52677e", edgecolor="none", alpha=.58))
        ax.add_patch(PathPatch(glyph_path(variant, variant.getBestCmap()[ord(ch)]),
                               facecolor="#e97642", edgecolor="none", alpha=.58))
        ax.set_xlim(limits[0], limits[1])
        ax.set_ylim(limits[2], limits[3])
        ax.set_aspect("equal")
        ax.axis("off")

    fig.text(.035, .012,
             "U+5DF1/U+5DF2 crops include the longer rounded terminal; U+7535 keeps its exterior "
             "outline and center axis while the four inner openings narrow symmetrically.",
             fontsize=8.2, color="#777a7e", ha="left", va="bottom")
    fig.savefig(out_path, dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("saved", out_path)


def load_sketch_crop(image_path: FilePath) -> Image.Image:
    """Trim blank paper from a user reference without changing its drawn proportions."""
    image = Image.open(image_path).convert("RGB")
    mask = ImageOps.grayscale(image).point(lambda value: 255 if value < 245 else 0)
    bbox = mask.getbbox()
    if bbox is None:
        raise ValueError(f"Sketch reference contains no visible strokes: {image_path}")
    return image.crop(bbox)


def sketch_ink_rgba(image: Image.Image) -> np.ndarray:
    """Convert only dark sketch ink to transparent blue for a proportional overlay."""
    gray = np.asarray(ImageOps.grayscale(image), dtype=np.float32)
    alpha = np.clip((248.0 - gray) * 3.5, 0, 210).astype(np.uint8)
    rgba = np.empty((*gray.shape, 4), dtype=np.uint8)
    rgba[..., :3] = (38, 58, 82)
    rgba[..., 3] = alpha
    return rgba


def render_sketch_review(
    variant: TTFont, bird_sketch: FilePath, ye_sketch: FilePath, out_path: FilePath
):
    """Compare user sketches and V7 whole-glyph proportions for 鸟 and 也."""
    sketch_paths = {"鸟": bird_sketch, "也": ye_sketch}
    fig = plt.figure(figsize=(15.0, 8.0), facecolor="#fbfaf7")
    gs = fig.add_gridspec(
        2, 4, left=.035, right=.985, top=.855, bottom=.105,
        wspace=.08, hspace=.13, width_ratios=[.62, 1.0, 1.0, 1.0],
    )
    fig.text(.035, .965, "V7 · USER SKETCH REFERENCE REVIEW", fontsize=21,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.035, .922,
             "The sketches were confirmed as U+9E1F and U+4E5F. They guide whole-glyph proportions and style, not point-by-point tracing.",
             fontsize=10.3, color="#666a70", ha="left", va="top")
    for x, title in ((.035, "GLYPH"), (.205, "USER SKETCH"),
                     (.465, "V7 CANDIDATE"), (.725, "OVERLAY")):
        fig.text(x, .878, title, fontsize=10, fontweight="bold",
                 color="#55585d", ha="left", va="top")

    for row, ch in enumerate(("鸟", "也")):
        name = variant.getBestCmap()[ord(ch)]
        glyph = variant["glyf"][name]
        x0, y0, x1, y1 = glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax
        center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
        glyph_height = y1 - y0
        if glyph_height <= 0:
            raise AssertionError(f"{ch}: glyph has no visible height")
        limits = (center_x - 550, center_x + 550,
                  center_y - 550, center_y + 550)
        sketch = load_sketch_crop(sketch_paths[ch])
        scale = glyph_height / sketch.height
        sketch_width = sketch.width * scale
        extent = (
            center_x - sketch_width / 2, center_x + sketch_width / 2,
            center_y - glyph_height / 2, center_y + glyph_height / 2,
        )

        label_ax = fig.add_subplot(gs[row, 0])
        label_ax.axis("off")
        label_ax.text(.05, .72, f"U+{ord(ch):04X}", fontsize=17, fontweight="bold",
                      color="#262930", ha="left", va="top")
        label_ax.text(.05, .42, f"sketch ratio {sketch.width / sketch.height:.2f}",
                      fontsize=8.2, color="#777a7e", ha="left", va="top")
        label_ax.text(.05, .18, "whole-glyph reference", fontsize=8.2,
                      color="#777a7e", ha="left", va="top")

        sketch_ax = fig.add_subplot(gs[row, 1])
        sketch_ax.imshow(sketch, extent=extent, origin="upper")
        sketch_ax.set_xlim(limits[0], limits[1])
        sketch_ax.set_ylim(limits[2], limits[3])
        sketch_ax.set_aspect("equal")
        sketch_ax.axis("off")

        candidate_ax = fig.add_subplot(gs[row, 2])
        draw_glyph(candidate_ax, variant, ch, color="#20252d", limits=limits)

        overlay_ax = fig.add_subplot(gs[row, 3])
        overlay_ax.add_patch(PathPatch(
            glyph_path(variant, name), facecolor="#e97642", edgecolor="none", alpha=.56
        ))
        overlay_ax.imshow(sketch_ink_rgba(sketch), extent=extent, origin="upper")
        overlay_ax.set_xlim(limits[0], limits[1])
        overlay_ax.set_ylim(limits[2], limits[3])
        overlay_ax.set_aspect("equal")
        overlay_ax.axis("off")

    fig.text(.035, .045,
             "Overlay: orange = V7 outline, blue = sketch. Both are centered and matched by ink height; stroke construction is intentionally not traced or identical.",
             fontsize=8.8, color="#777a7e", ha="left", va="bottom")
    fig.savefig(out_path, dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("saved", out_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Original static A D/400 TTF")
    parser.add_argument("--variant", required=True, help="Temporary V7 research-preview TTF")
    parser.add_argument("--outdir", required=True, help="Directory for the four current PNGs")
    repo_root = FilePath(__file__).resolve().parents[1]
    parser.add_argument(
        "--bird-sketch", type=FilePath,
        default=repo_root / "docs/round-preview/sketches/bird-reference.png",
        help="User-provided 鸟 sketch used only as a whole-glyph reference",
    )
    parser.add_argument(
        "--ye-sketch", type=FilePath,
        default=repo_root / "docs/round-preview/sketches/ye-reference.png",
        help="User-provided 也 sketch used only as a whole-glyph reference",
    )
    args = parser.parse_args()
    base, variant = TTFont(args.baseline), TTFont(args.variant)
    for label, font in (("baseline", base), ("variant", variant)):
        if "fvar" in font or font["OS/2"].usWeightClass != 400:
            raise ValueError(f"{label} must be a static usWeightClass=400 instance")
        if any(ord(ch) not in font.getBestCmap() for ch in CHARS_63):
            raise ValueError(f"{label} is missing at least one sample character")
    outdir = FilePath(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    render_main(base, variant, outdir / "tsukushi-a-d-63-sketch-ref-v7-overview.png")
    render_detail(base, variant, outdir / "tsukushi-a-v7-full-glyph-review.png")
    render_local_detail(base, variant, outdir / "tsukushi-a-v7-endpoint-and-frame-detail.png")
    render_sketch_review(
        variant, args.bird_sketch, args.ye_sketch,
        outdir / "tsukushi-a-v7-sketch-reference-review.png",
    )


if __name__ == "__main__":
    main()
