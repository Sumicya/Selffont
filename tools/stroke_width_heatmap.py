#!/usr/bin/env python3
"""把 stroke_width_audit.py 的骨架宽度量化结果画成热力图，给主人"看得见"的证据，
而不是只给一张数字表。蓝=偏细，红=偏粗，同一张图里颜色跳变的地方就是"粗细不统一"
的具体笔画位置（例如撇捺 vs 横竖）。
"""
import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np
from fontTools.ttLib import TTFont
from scipy import ndimage
from skimage.morphology import skeletonize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stroke_width_audit import rasterize_glyph


def glyph_heatmap(font, glyph_name, px=420):
    mask, upx = rasterize_glyph(font, glyph_name, px=px)
    if mask is None:
        return None
    dist = ndimage.distance_transform_edt(mask)
    skel = skeletonize(mask)
    widths = np.zeros_like(dist)
    widths[skel] = dist[skel] * 2.0 * upx
    # 把骨架宽度做一次小半径膨胀，方便肉眼看（骨架本来只有1像素宽线）
    dil = ndimage.grey_dilation(widths, size=(3, 3))
    dil[~ndimage.binary_dilation(skel, iterations=1)] = 0
    return mask, dil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", required=True)
    ap.add_argument("--chars", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cols", type=int, default=6)
    args = ap.parse_args()

    font = TTFont(args.font)
    cmap = font.getBestCmap()
    title_font = FontProperties(fname=args.font)

    chars = [c for c in args.chars if ord(c) in cmap]
    n = len(chars)
    cols = args.cols
    rows = (n + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=(cols * 2.4, rows * 2.6))
    axes = np.array(axes).reshape(rows, cols)

    all_vals = []
    results = []
    for ch in chars:
        glyph_name = cmap[ord(ch)]
        mask, dil = glyph_heatmap(font, glyph_name)
        results.append((ch, mask, dil))
        vals = dil[dil > 0]
        if len(vals):
            all_vals.append(vals)

    vmin = np.percentile(np.concatenate(all_vals), 2)
    vmax = np.percentile(np.concatenate(all_vals), 98)

    for idx in range(rows * cols):
        r, c = divmod(idx, cols)
        ax = axes[r, c]
        ax.axis("off")
        if idx >= n:
            continue
        ch, mask, dil = results[idx]
        bg = np.ones((*mask.shape, 3))
        bg[mask] = [0.88, 0.88, 0.88]
        ax.imshow(bg)
        dilm = np.ma.masked_where(dil <= 0, dil)
        im = ax.imshow(dilm, cmap="jet", vmin=vmin, vmax=vmax)
        ax.set_title(ch, fontsize=20, fontproperties=title_font)

    cbar_ax = fig.add_axes([0.92, 0.15, 0.015, 0.7])
    cb = fig.colorbar(im, cax=cbar_ax)
    cb.set_label("局部笔画宽度 (font units, 蓝=细 红=粗)", fontproperties=title_font)
    fig.suptitle(Path(args.font).name + "  笔画宽度热力图（骨架宽度量化，非目测）",
                 fontsize=14, fontproperties=title_font)
    fig.tight_layout(rect=[0, 0, 0.9, 0.95])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    print("saved", out)


if __name__ == "__main__":
    main()
