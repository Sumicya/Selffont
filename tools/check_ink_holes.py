"""光栅化之后数「洞里有没有多出来的洞」——几何自交到底看不看得见，用这个判。

为什么要有这个工具
------------------
2026-11-05：`check_self_intersect.py` 报 200 字里 130 字自交，分级工具又把其中 9 字判成
「大环差」。但几何无效 ≠ 渲染出错：本仓的笔画是**每笔一环、靠 nonzero 绕数叠加**，
内侧转角的偏移线本来就相交（`design_cjk._offset_ring` 的既定做法）。要判它到底有没有
伤到成品，只能光栅化之后数洞。

判据
----
**洞的个数必须相同**。个数一变就是多/少了一个封闭空腔，那是肉眼可见的缺陷。

洞的总面积**不作为判据**：笔画变粗（墨比 1.00–1.04）必然把洞挤小，实测 0.86–0.97 与
墨比一一对应。把面积写进判据，等于要求「更饱满」的同时「洞不变小」，两者矛盾。

用法
----
    python tools/check_ink_holes.py 母版.ttf 本版.ttf --chars "館尸胈門限" [--size 600]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage


def render(path: Path, ch: str, size: int) -> np.ndarray:
    font = ImageFont.truetype(str(path), size)
    canvas = Image.new("L", (size * 2, size * 3), 255)
    ImageDraw.Draw(canvas).text((size // 2, size * 2), ch, font=font, fill=0, anchor="ls")
    return np.asarray(canvas) < 128


def holes(mask: np.ndarray, min_area: int = 20):
    """返回 (墨量, 洞个数, 洞总面积)。洞 = 不与画布边界连通的空白连通块。"""
    empty = ~mask
    labels, n = ndimage.label(empty)
    border = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    count, area = 0, 0
    for k in range(1, n + 1):
        if k in border:
            continue
        a = int((labels == k).sum())
        if a >= min_area:
            count += 1
            area += a
    return int(mask.sum()), count, area


def main() -> int:
    ap = argparse.ArgumentParser(description="数渲染后的洞：判定几何自交有没有伤到成品")
    ap.add_argument("master", type=Path)
    ap.add_argument("other", type=Path)
    ap.add_argument("--chars", required=True)
    ap.add_argument("--size", type=int, default=600)
    args = ap.parse_args()

    bad = 0
    print(f"{'字':3s} {'母版墨量':>10s} {'本版墨量':>10s} {'墨比':>7s} {'洞 母/本':>9s} {'洞面积比':>9s}")
    for ch in dict.fromkeys(args.chars):
        im, hm, am = holes(render(args.master, ch, args.size))
        io, ho, ao = holes(render(args.other, ch, args.size))
        ratio = io / im if im else float("nan")
        aratio = ao / am if am else float("nan")
        flag = ""
        if hm != ho:
            flag = "  ← 洞数不同"
            bad += 1
        print(f"{ch:3s} {im:10d} {io:10d} {ratio:7.3f} {hm:4d}/{ho:<4d} {aratio:9.3f}{flag}")
    print(f"结论：{len(set(args.chars)) - bad}/{len(set(args.chars))} 字洞数一致（洞面积随墨量变，不计判据）")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
