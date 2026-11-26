#!/usr/bin/env python3
"""R2 栅格化对照：安装副本 vs 母版，同码位墨迹差（渲染层代理判据）。

为什么存在：真机渲染层挂不上（沙箱无 Android），主人批准的替代动作是栅格化对照。
判据形状：安装副本（包内字件）与母版之间**唯一**预期差异＝碎块清理的 20 个字；
其余码位栅格必须逐像素相同。于是「非相同码位集合 ⊆ 碎块名单」就是可证伪的读数：
多出任何一个码位，说明包内字件掺了母版没有的改动（渲染层污染的代理信号）。

用法：
    python tools/r2_raster_diff.py <母版.ttf> <安装副本.ttf> [--n 1500] [--seed 7] \
        [--out docs/evidence/2026-11-27-r2-worst.png]

读数口径：PIL/FreeType 48 px、mode L、阈值 64 二值化；相同＝两幅栅格数组逐字节相等；
IoU＝交/并（墨迹掩码）。碎块名单从 tools/drop_stray_ring.py --scan 的 stdout 解析
（不手写字面量，罚篇三十一纪律）。
"""
from __future__ import annotations

import argparse
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent


def stray_set(mother: str) -> set[int]:
    """碎块名单：解析 drop_stray_ring <母版> --scan 的输出，不接受手写字面量。"""
    proc = subprocess.run([sys.executable, str(ROOT / "tools/drop_stray_ring.py"),
                           mother, "-o", "/tmp/r2-scan-null.ttf", "--scan"],
                           capture_output=True, text=True, check=True)
    cps: set[int] = set()
    import re as _re
    for line in proc.stdout.splitlines():
        m = _re.search(r"U\+([0-9A-Fa-f]{4,6})\b", line)
        if m and "uni" in line:
            cps.add(int(m.group(1), 16))
    return cps


def raster(font: ImageFont.FreeTypeFont, cp: int, size: int = 48) -> np.ndarray:
    """同原点栅格：固定画布、固定落笔点，不按各自 bbox 对齐。

    按 bbox 对齐是错的（罚篇三十二）：碎块 removal 会缩小 bbox，主体随之平移，
    日 的 IoU 被口径假造到 0.314。同原点才能只量「墨迹本身变没变」。
    """
    img = Image.new("L", (size * 2, size * 2), 0)
    d = ImageDraw.Draw(img)
    # anchor="ls"＝左基线：跨字体对齐基线与笔原点。PIL 默认 y 是行盒顶，
    # 两字体 ascent 不同会整体错位（ASCII IoU 假成 0.000 的那次）。
    d.text((size // 3, int(size * 1.33)), chr(cp), font=font, fill=255, anchor="ls")
    a = np.asarray(img, dtype=np.uint8)
    return (a > 64).astype(np.uint8)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mother")
    ap.add_argument("installed")
    ap.add_argument("--n", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--size", type=int, default=48)
    ap.add_argument("--out", default="docs/evidence/2026-11-27-r2-worst.png")
    args = ap.parse_args()

    stray = stray_set(args.mother)
    fa = ImageFont.truetype(args.mother, args.size)
    fb = ImageFont.truetype(args.installed, args.size)
    cmap = set()
    for cp in range(0x20, 0x20000):
        try:
            if fa.getmask(chr(cp)).size[0] > 0:
                cmap.add(cp)
        except OSError:
            continue
    random.seed(args.seed)
    sample = sorted(random.sample(sorted(cmap), min(args.n, len(cmap))))
    probe = sorted(set(sample) | stray | set(range(0x21, 0x7F)))

    same, diff = 0, []
    for cp in probe:
        a = raster(fa, cp, args.size)
        b = raster(fb, cp, args.size)
        if a.shape == b.shape and np.array_equal(a, b):
            same += 1
        else:
            inter = np.logical_and(a, b).sum() if a.shape == b.shape else 0
            if a.shape != b.shape:
                h = max(a.shape[0], b.shape[0]); w = max(a.shape[1], b.shape[1])
                A = np.zeros((h, w), np.uint8); B = np.zeros((h, w), np.uint8)
                A[:a.shape[0], :a.shape[1]] = a; B[:b.shape[0], :b.shape[1]] = b
                a, b = A, B
                inter = np.logical_and(a, b).sum()
            union = np.logical_or(a, b).sum()
            diff.append((cp, inter / union if union else 0.0))

    diff_cps = {cp for cp, _ in diff}
    extra = diff_cps - stray
    missing = stray - diff_cps
    print(f"R2 读数：抽样 {len(probe)} 码位（随机 {len(sample)} + 碎块 {len(stray)} + ASCII）")
    print(f"  逐字节相同 {same}；不同 {len(diff)}")
    print(f"  不同集合 ⊆ 碎块名单：{not extra}（多出 {sorted(extra)[:10]}）")
    print(f"  碎块名单里未现差异：{sorted(missing)[:10]}（应为空）")
    if diff:
        worst = sorted(diff, key=lambda t: t[1])[:3]
        print("  最差 IoU 三例：" + "、".join(f"U+{cp:04X} IoU={iou:.3f}" for cp, iou in worst))
        # 图：最差三字，母版／安装副本／异或 三栏
        cell, pad, title_h = 72, 6, 34
        canvas = Image.new("L", (len(worst) * 3 * (cell + pad) + pad, cell + 2 * pad + title_h), 255)
        td = ImageDraw.Draw(canvas)
        td.text((pad, 4), f"R2 same-origin raster: probe {len(probe)}, identical {same}, "
                          f"diff {len(diff)}, diff-subset-of-stray {not extra}", fill=0)
        td.text((pad, 18), "cols per glyph: mother / installed / xor   worst IoU "
                           + " ".join(f"U+{c:04X}={i:.3f}" for c, i in worst), fill=0)
        for col, (cp, iou) in enumerate(worst):
            for row, fnt in enumerate((fa, fb, None)):
                m = raster(fa if fnt is None else fnt, cp, args.size) if fnt else None
                if fnt is None:
                    a = raster(fa, cp, args.size); b = raster(fb, cp, args.size)
                    h = max(a.shape[0], b.shape[0]); w = max(a.shape[1], b.shape[1])
                    A = np.zeros((h, w), np.uint8); B = np.zeros((h, w), np.uint8)
                    A[:a.shape[0], :a.shape[1]] = a; B[:b.shape[0], :b.shape[1]] = b
                    m = np.logical_xor(A, B).astype(np.uint8)
                im = Image.fromarray((1 - m) * 255).resize((cell, cell), Image.NEAREST)
                canvas.paste(im, (pad + col * 3 * (cell + pad) + row * (cell + pad),
                                  pad + title_h))
        out = ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(out)
        print(f"  图 {out.relative_to(ROOT)}  {out.stat().st_size} B")
    return 0 if not extra and not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
