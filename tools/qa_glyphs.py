"""单字结构体检：把字体里的 400 档和母版同一个字各自栅格，比较孔数、连通块数与 IoU。

判据（母版在这里只用来判「有没有画错」，不用来判风格）：
  · 孔数（封闭空白区）比母版少 → 实心口 / 黑团；
  · 连通块比母版多 2 个以上 → 笔画断成碎块；
  · 包围盒对齐、缩放到同一网格后 IoU < 0.55 → 已经不成字。
三项任一命中就写进排除表，构建期不再收这个字。

用法：
    python tools/qa_glyphs.py build/SelffontCJK-VF.ttf --mother fonts/Regular.ttf \
        --out tools/design_cjk_exclude.txt
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from fontTools.ttLib import TTFont

SIZE = 200
CANVAS = 420
GRID = 96
MIN_IOU = 0.55


def _ink(font: ImageFont.FreeTypeFont, ch: str) -> np.ndarray:
    image = Image.new("L", (CANVAS, CANVAS), 255)
    ImageDraw.Draw(image).text((CANVAS // 4, CANVAS // 4), ch, font=font, fill=0)
    return np.asarray(image) < 128


def _stats(mask: np.ndarray) -> tuple[int, int]:
    comps, _ = ndimage.label(mask)
    background, _ = ndimage.label(~mask)
    edge = (set(background[0, :].tolist()) | set(background[-1, :].tolist())
            | set(background[:, 0].tolist()) | set(background[:, -1].tolist()))
    holes = sum(1 for label in range(1, background.max() + 1) if label not in edge)
    return int(comps.max()), int(holes)


def _norm(mask: np.ndarray) -> np.ndarray:
    ys, xs = np.where(mask)
    crop = Image.fromarray((mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1] * 255).astype(np.uint8))
    return np.asarray(crop.resize((GRID, GRID), Image.BILINEAR)) > 128


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("font", type=Path, help="自研字体（取其中的静态实例或默认实例）")
    parser.add_argument("--mother", type=Path, required=True, help="母版 400 档，只用来判结构对错")
    parser.add_argument("--out", type=Path, required=True, help="排除表输出路径")
    args = parser.parse_args()

    codepoints = sorted(TTFont(args.font).getBestCmap())
    mine = ImageFont.truetype(str(args.font), SIZE)
    mother = ImageFont.truetype(str(args.mother), SIZE)
    bad = []
    for codepoint in codepoints:
        ch = chr(codepoint)
        a = _ink(mine, ch)
        b = _ink(mother, ch)
        if not a.any() or not b.any():
            continue
        comps_a, holes_a = _stats(a)
        comps_b, holes_b = _stats(b)
        inter = np.logical_and(_norm(a), _norm(b)).sum()
        iou = float(inter / max(1, np.logical_or(_norm(a), _norm(b)).sum()))
        if holes_a < holes_b:
            bad.append((codepoint, f"孔少 {holes_a}<{holes_b}"))
        elif comps_a > comps_b + 1:
            bad.append((codepoint, f"块多 {comps_a}>{comps_b}"))
        elif iou < MIN_IOU:
            bad.append((codepoint, f"IoU {iou:.2f}"))
    print(f"体检 {len(codepoints)} 字，剔除 {len(bad)}")

    lines = [
        "# 结构体检剔除表：孔数/连通块与母版不符或 IoU < "
        f"{MIN_IOU} 的字，不进字体（宁可缺字回退，也不发一个黑团）。",
        "# 由 tools/qa_glyphs.py 生成，改数据后重跑一次即可。",
        "# 每行一个十六进制码位；# 之后是原因。",
    ]
    for codepoint, reason in bad:
        lines.append(f"{codepoint:04X}  # {chr(codepoint)} {reason}")
    args.out.write_text("\n".join(lines) + "\n")
    print("写", args.out)


if __name__ == "__main__":
    main()
