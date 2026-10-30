"""逐字校稿的尺子：真实字体文件 + FreeType，逐字量「孔（闭合字腔）」与「墨量」，
母版只用来判「有没有画错」，不用来判风格。

孔只数**成块的**（≥30 px @200px，约 0.07% 字面），几像素的锯齿缝不算孔——
那是栅格化的噪声，数进去只会把「孔少」变成假警报。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
OURS = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "work" / "fix6" / "static-400.ttf"
MASTER = Path("/tmp/w/maruko.ttf")
SIZE, CANVAS = 200, 440
MIN_HOLE = 30          # px @200：小于这个的是锯齿缝，不是字腔


def ink(font, ch):
    im = Image.new("L", (CANVAS, CANVAS), 255)
    ImageDraw.Draw(im).text((CANVAS // 4, CANVAS // 4), ch, font=font, fill=0)
    return np.asarray(im) < 128


def profile(a):
    comps, _ = ndimage.label(a)
    bg, n = ndimage.label(~a)
    edge = set(bg[0].tolist()) | set(bg[-1].tolist()) | set(bg[:, 0].tolist()) | set(bg[:, -1].tolist())
    areas = [int((bg == k).sum()) for k in range(1, n + 1) if k not in edge]
    big = [v for v in areas if v >= MIN_HOLE]
    return int(comps.max()), big


def norm(a):
    ys, xs = np.where(a)
    crop = Image.fromarray((a[ys.min():ys.max() + 1, xs.min():xs.max() + 1] * 255).astype(np.uint8))
    return np.asarray(crop.resize((96, 96), Image.BILINEAR)) > 128


def main() -> None:
    codes = sorted(TTFont(OURS, recalcBBoxes=False).getBestCmap())
    mine = ImageFont.truetype(str(OURS), SIZE)
    mother = ImageFont.truetype(str(MASTER), SIZE)
    lost, split, heavy, low = [], [], [], []
    for cp in codes:
        if not (0x4E00 <= cp <= 0x9FFF):
            continue
        ch = chr(cp)
        a, b = ink(mine, ch), ink(mother, ch)
        if not a.any() or not b.any():
            continue
        ca, ha = profile(a)
        cb, hb = profile(b)
        if len(ha) < len(hb):
            lost.append((cp, len(ha), len(hb), sum(hb) - sum(ha)))
        elif ca > cb + 1:
            split.append((cp, ca, cb))
        ratio = a.sum() / max(1, b.sum())
        if ratio > 1.20:
            heavy.append((cp, round(ratio, 2)))
        na, nb = norm(a), norm(b)
        iou = float(np.logical_and(na, nb).sum() / max(1, np.logical_or(na, nb).sum()))
        if iou < 0.80:
            low.append((cp, round(iou, 2)))
    total = sum(1 for cp in codes if 0x4E00 <= cp <= 0x9FFF)
    print(f"扫 {total} 个基本区汉字（孔 ≥{MIN_HOLE}px 才计数）")
    print(f"A 孔比母版少：{len(lost)}；B 连通块多 2+：{len(split)}；C 墨量比 >1.20：{len(heavy)}；D 归一化重合度 <0.80：{len(low)}")
    lost.sort(key=lambda r: -r[3])
    print("A 前 40（码位, 我孔/母版孔, 少掉的孔面积合计）：")
    print("   " + "、".join(f"{chr(c)}({ha}/{hb},{d})" for c, ha, hb, d in lost[:40]))
    print("C 全部：", "、".join(f"{chr(c)}({r})" for c, r in heavy))
    print("D 前 40：", "、".join(f"{chr(c)}({v})" for c, v in low[:40]))


if __name__ == "__main__":
    main()
