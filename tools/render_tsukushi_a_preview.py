#!/usr/bin/env python3
"""Render overview, full-glyph, and context-preserving detail views of the V4 study."""
from __future__ import annotations

import argparse
import math
from pathlib import Path as FilePath

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch, Rectangle
from fontTools.ttLib import TTFont

if __package__:
    from . import hook_cut
    from .render_grid import glyph_path
else:
    import hook_cut
    from render_grid import glyph_path


CHARS_63 = (
    "一二三十口日回国了乙人入八木林森永心必水走建进这远道你好中国"
    "语言文字书写规范长美丽颜色锦绣风雨雪龙马鸟虫鱼电子已己巳也包囚暖田"
)
HOOK_CANDIDATES = "乙也了包子己已电"


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
    """Return fixed-size full-glyph crops around the eight selected gates."""
    cmap = base.getBestCmap()
    glyf = base["glyf"]
    rows = []
    for ch in HOOK_CANDIDATES:
        name = cmap[ord(ch)]
        glyph = glyf[name]
        coords, ends, flags = glyph.getCoordinates(glyf)
        contours = hook_cut.split_contours(coords, ends, flags)
        for ci, i, j, *_ in hook_cut.find_hooks(contours):
            contour = contours[ci]
            ax, ay = contour[i][0], contour[i][1]
            bx, by = contour[j][0], contour[j][1]
            gate = math.hypot(bx - ax, by - ay)
            side = max(gate * 4.0, 260.0)
            cx, cy = (ax + bx) * 0.5, (ay + by) * 0.5
            limits = (cx - side / 2, cx + side / 2,
                      cy - side / 2, cy + side / 2)
            rows.append((ch, ci, i, j, limits))
    if len(rows) != 8:
        raise AssertionError(f"Expected eight selected hook cuts, got {len(rows)}")
    return rows


def render_main(base: TTFont, variant: TTFont, out_path: FilePath):
    changed = {ch for ch in dict.fromkeys(CHARS_63)
               if signature(base, ch) != signature(variant, ch)}
    changed_entries = sum(ch in changed for ch in CHARS_63)
    if len(CHARS_63) != 63 or len(set(CHARS_63)) != 62:
        raise AssertionError("Audit sample must be 63 entries / 62 unique characters")
    if len(changed) != 7:
        raise AssertionError(f"Expected seven changed unique glyphs, got {len(changed)}")

    fig = plt.figure(figsize=(18.4, 12.4), facecolor="#fbfaf7")
    gs = fig.add_gridspec(
        9, 15, left=.025, right=.975, top=.855, bottom=.105,
        wspace=.08, hspace=.12, width_ratios=[1] * 7 + [.22] + [1] * 7,
    )
    fig.text(.025, .965, "TSUKUSHI A · D/400 · HOOK-ONLY V4", fontsize=25,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.025, .928,
             "63 audit entries · 62 unique glyphs · same static source weight · research-only outline comparison",
             fontsize=11.5, color="#666a70", ha="left", va="top")
    fig.text(.025, .887, "BASELINE · original A-D outline", fontsize=14,
             fontweight="bold", color="#262930", ha="left", va="top")
    fig.text(.515, .887, "V4 · selected hook-end cuts only", fontsize=14,
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
             "8 rounded hook-end cuts. No general corner rounding or short-turn merging.",
             fontsize=9.1, color="#53565b", ha="left", va="bottom")
    fig.text(.025, .034,
             "All other outlines are unchanged. No stroke-width normalization, no other weight claim, "
             "no production-font edit, and no device-rendering test.",
             fontsize=8.7, color="#777a7e", ha="left", va="bottom")
    fig.savefig(out_path, dpi=155, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"changed unique glyphs={len(changed)}, sample entries={changed_entries}")
    print("saved", out_path)


def render_detail(base: TTFont, variant: TTFont, out_path: FilePath):
    """Review each changed glyph in context instead of displaying isolated contour scraps."""
    chars = [ch for ch in HOOK_CANDIDATES
             if signature(base, ch) != signature(variant, ch)]
    if len(chars) != 7:
        raise AssertionError(f"Expected seven changed full glyphs, got {len(chars)}")

    fig = plt.figure(figsize=(17.0, 17.0), facecolor="#fbfaf7")
    gs = fig.add_gridspec(
        len(chars), 4, left=.035, right=.985, top=.875, bottom=.045,
        wspace=.035, hspace=.10, width_ratios=[.72, 1.0, 1.0, 1.0],
    )
    fig.text(.035, .965, "V4 · FULL-GLYPH VISUAL REVIEW", fontsize=22,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.035, .925,
             "Same full-glyph scale in all columns; blue = baseline, orange = candidate in overlay. "
             "Research candidate only, not visually accepted.",
             fontsize=10.5, color="#666a70", ha="left", va="top")
    for x, title in ((.035, "GLYPH"), (.22, "BASELINE"), (.48, "V4 CANDIDATE"), (.74, "OVERLAY")):
        fig.text(x, .895, title, fontsize=10, fontweight="bold",
                 color="#55585d", ha="left", va="top")

    for row, ch in enumerate(chars):
        ax = fig.add_subplot(gs[row, 0])
        ax.axis("off")
        ax.text(.04, .80, f"U+{ord(ch):04X}", fontsize=11, fontweight="bold",
                color="#45484d", ha="left", va="top")
        ax.text(.04, .58, f"{row + 1:02d} / 07", fontsize=8.5,
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
             "Only the selected hook-end outlines change; full glyph context is retained for visual judgment. "
             "No production font was modified.",
             fontsize=8.5, color="#777a7e", ha="left", va="bottom")
    fig.savefig(out_path, dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("saved", out_path)


def render_local_detail(base: TTFont, variant: TTFont, out_path: FilePath):
    """Show local cap crops from complete glyph paths, with a miniature location map."""
    rows = hook_rows(base)
    fig = plt.figure(figsize=(18.0, 16.0), facecolor="#fbfaf7")
    gs = fig.add_gridspec(
        len(rows), 4, left=.035, right=.985, top=.895, bottom=.04,
        wspace=.08, hspace=.12, width_ratios=[1.0, 1.0, 1.0, 1.0],
    )
    fig.text(.035, .965, "V4 · END-CAP DETAILS WITH FULL-GLYPH CONTEXT", fontsize=21,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.035, .925,
             "Each crop is drawn from the complete glyph (not an isolated contour); the left thumbnail marks its location.",
             fontsize=10.3, color="#666a70", ha="left", va="top")
    for x, title in ((.035, "LOCATION"), (.285, "BASELINE CROP"),
                     (.535, "V4 CROP"), (.785, "OVERLAY")):
        fig.text(x, .905, title, fontsize=9.5, fontweight="bold",
                 color="#55585d", ha="left", va="top")

    for row, (ch, _ci, _i, _j, limits) in enumerate(rows):
        ax = fig.add_subplot(gs[row, 0])
        draw_glyph(ax, base, ch, color="#26364a")
        ax.add_patch(Rectangle(
            (limits[0], limits[2]), limits[1] - limits[0], limits[3] - limits[2],
            fill=False, edgecolor="#e97642", linewidth=1.4, zorder=5,
        ))
        ax.text(.03, .97, f"U+{ord(ch):04X} · cut {row + 1}",
                transform=ax.transAxes, ha="left", va="top", fontsize=7.7,
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
             "Orange outline on the thumbnail marks the crop; blue = baseline, orange = candidate. "
             "V4 remains a research candidate, not accepted artwork.",
             fontsize=8.2, color="#777a7e", ha="left", va="bottom")
    fig.savefig(out_path, dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("saved", out_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Original static A D/400 TTF")
    parser.add_argument("--variant", required=True, help="Temporary hook-only preview TTF")
    parser.add_argument("--outdir", required=True, help="Directory for the three PNGs")
    args = parser.parse_args()
    base, variant = TTFont(args.baseline), TTFont(args.variant)
    for label, font in (("baseline", base), ("variant", variant)):
        if "fvar" in font or font["OS/2"].usWeightClass != 400:
            raise ValueError(f"{label} must be a static usWeightClass=400 instance")
        if any(ord(ch) not in font.getBestCmap() for ch in CHARS_63):
            raise ValueError(f"{label} is missing at least one sample character")
    outdir = FilePath(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    render_main(base, variant, outdir / "tsukushi-a-d-63-hook-only-v4-overview.png")
    render_detail(base, variant, outdir / "tsukushi-a-v4-full-glyph-review.png")
    render_local_detail(base, variant, outdir / "tsukushi-a-v4-endpoint-detail.png")


if __name__ == "__main__":
    main()
