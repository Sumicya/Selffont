#!/usr/bin/env python3
"""Render the 63-entry Tsukushi A D/400 hook-only research comparison."""
from __future__ import annotations

import argparse
from pathlib import Path as FilePath

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.path import Path as MplPath
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates

import hook_cut
from render_grid import MplPathPen, glyph_path
from tsukushi_a_preview_simplify import round_cap


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


def contour_path(font: TTFont, ch: str, contour_index: int) -> MplPath:
    """Draw only the changed contour, so nearby unrelated strokes do not clutter crops."""
    name = font.getBestCmap()[ord(ch)]
    glyph = font["glyf"][name]
    glyf = font["glyf"]
    coords, ends, flags = glyph.getCoordinates(glyf)
    start = 0 if contour_index == 0 else int(ends[contour_index - 1]) + 1
    end = int(ends[contour_index]) + 1
    one = Glyph()
    one.numberOfContours = 1
    one.coordinates = GlyphCoordinates(coords[start:end])
    one.endPtsOfContours = [end - start - 1]
    one.flags = list(flags[start:end])
    pen = MplPathPen(font.getGlyphSet())
    one.draw(pen, glyf)
    return MplPath(pen.verts, pen.codes)


def draw_contour(ax, font: TTFont, ch: str, contour_index: int, color: str,
                 alpha: float = 1.0, limits=None):
    ax.add_patch(PathPatch(contour_path(font, ch, contour_index),
                           facecolor=color, edgecolor="none", alpha=alpha))
    ax.set_xlim(limits[0], limits[1])
    ax.set_ylim(limits[2], limits[3])
    ax.set_aspect("equal")
    ax.axis("off")


def hook_rows(base: TTFont):
    cmap = base.getBestCmap()
    glyf = base["glyf"]
    rows = []
    for ch in HOOK_CANDIDATES:
        name = cmap[ord(ch)]
        coords, ends, flags = glyf[name].getCoordinates(glyf)
        contours = hook_cut.split_contours(coords, ends, flags)
        for ci, i, j, *_ in hook_cut.find_hooks(contours):
            contour = contours[ci]
            n = len(contour)
            segment = []
            k = i
            while True:
                segment.append(contour[k])
                if k == j:
                    break
                k = (k + 1) % n
            points = segment + round_cap(contour, n, i, j)
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            gate = max(1.0, ((contour[i][0] - contour[j][0]) ** 2
                             + (contour[i][1] - contour[j][1]) ** 2) ** .5)
            side = max(gate * 1.65, (max(xs) - min(xs)) * 1.2,
                       (max(ys) - min(ys)) * 1.2, 150)
            cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            rows.append((ch, ci, i, j, (cx - side / 2, cx + side / 2,
                                        cy - side / 2, cy + side / 2)))
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
    fig.text(.025, .965, "TSUKUSHI A · D/400 · HOOK-ONLY V3", fontsize=25,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.025, .928,
             "63 audit entries · 62 unique glyphs · same static source weight · research-only outline comparison",
             fontsize=11.5, color="#666a70", ha="left", va="top")
    fig.text(.025, .887, "BASELINE · original A-D outline", fontsize=14,
             fontweight="bold", color="#262930", ha="left", va="top")
    fig.text(.515, .887, "V3 · selected hook-end cuts only", fontsize=14,
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
    rows = hook_rows(base)
    fig = plt.figure(figsize=(15.5, 15.0), facecolor="#fbfaf7")
    gs = fig.add_gridspec(
        len(rows), 4, left=.035, right=.985, top=.90, bottom=.045,
        wspace=.10, hspace=.16, width_ratios=[.8, 1.1, 1.1, 1.1],
    )
    fig.text(.035, .965, "V3 · ROUND HOOK-END CLOSE-UPS", fontsize=22,
             fontweight="bold", color="#171a1f", ha="left", va="top")
    fig.text(.035, .925,
             "Eight selected cuts; each row uses the same crop and scale before and after.",
             fontsize=11, color="#666a70", ha="left", va="top")
    for x, title in ((.035, "CUT"), (.24, "BASELINE"), (.49, "V3"), (.74, "OVERLAY")):
        fig.text(x, .905, title, fontsize=10, fontweight="bold",
                 color="#55585d", ha="left", va="top")

    for row, (ch, ci, i, j, limits) in enumerate(rows):
        ax = fig.add_subplot(gs[row, 0])
        ax.axis("off")
        ax.text(.02, .88, f"U+{ord(ch):04X} · hook cut {row + 1}", fontsize=9.1,
                color="#45484d", ha="left", va="top", wrap=True)

        ax = fig.add_subplot(gs[row, 1])
        draw_contour(ax, base, ch, ci, color="#26364a", limits=limits)
        ax = fig.add_subplot(gs[row, 2])
        draw_contour(ax, variant, ch, ci, color="#20252d", limits=limits)
        ax = fig.add_subplot(gs[row, 3])
        ax.add_patch(PathPatch(contour_path(base, ch, ci), facecolor="#52677e",
                               edgecolor="none", alpha=.58))
        ax.add_patch(PathPatch(contour_path(variant, ch, ci), facecolor="#e97642",
                               edgecolor="none", alpha=.58))
        ax.set_xlim(limits[0], limits[1])
        ax.set_ylim(limits[2], limits[3])
        ax.set_aspect("equal")
        ax.axis("off")
    fig.savefig(out_path, dpi=165, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("saved", out_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Original static A D/400 TTF")
    parser.add_argument("--variant", required=True, help="Temporary hook-only preview TTF")
    parser.add_argument("--outdir", required=True, help="Directory for the two PNGs")
    args = parser.parse_args()
    base, variant = TTFont(args.baseline), TTFont(args.variant)
    for label, font in (("baseline", base), ("variant", variant)):
        if "fvar" in font or font["OS/2"].usWeightClass != 400:
            raise ValueError(f"{label} must be a static usWeightClass=400 instance")
        if any(ord(ch) not in font.getBestCmap() for ch in CHARS_63):
            raise ValueError(f"{label} is missing at least one sample character")
    outdir = FilePath(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    render_main(base, variant, outdir / "01-tsukushi-a-d-63-baseline-vs-hook-only-v3.png")
    render_detail(base, variant, outdir / "02-tsukushi-a-hook-end-detail-v3.png")


if __name__ == "__main__":
    main()
