"""用 FreeType（Pillow 底层）渲染字形，与母版逐像素比对。

为什么用 FreeType，不用「按有向面积判内外」的自绘渲染
-----------------------------------------------------
早先那版自绘按轮廓**有向面积的符号**决定填白还是挖黑：面积最大的当外轮廓，符号相反的
当洞。这只是在模仿「非零环绕」，遇到同向重叠的轮廓就出错——`鬱` 上游 11 条轮廓**全
是同向**，该函数会把重叠区当洞挖掉。Android 上 FreeType 用的是真正的非零环绕，
所以量相似度必须用 FreeType 算。

同一网格：两个字体都用 `anchor="ls"` 在同一个原点落笔，按**同一基线、同一像素尺寸**对齐，
不按外接框归一化（否则整字会被重新缩放，相似度全是假的）。渲染位置落在整数像素上，两个
字体的 xMin 不同会让相位差最多 1 px，所以比对时允许 ±1 px 的整格平移，并把这个平移量
单独报出来——「差多少形状」和「差多少位置」分开算，不混成一个数。

命令行
------
    .venv/bin/python tools/freetype_iou.py 母版.ttf 本版.ttf --all        # 两边共有的全部汉字
    .venv/bin/python tools/freetype_iou.py 母版.ttf 本版.ttf 鬱 響 鬢    # 指定字
    .venv/bin/python tools/freetype_iou.py 母版.ttf 本版.ttf --all --size 400

`--all` 取两个字体 cmap 交集里 U+4E00–U+9FFF 的全部码位，不挑字：这是「不挑好看的报」
的最低要求。输出：逐字 IoU（指定字时）、中位 / p10 / 最低、最差 8 字、墨量比中位、
被平移修正的字占比。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import ImageFont


def bitmap(path, char, size=200):
    """渲染一个字符：返回（裁剪后的墨迹掩膜，左上角相对基线的像素偏移）。

    偏移按 PIL 的坐标（y 向下为正、基线 y=0）给，未落墨时返回空掩膜。
    """
    font = ImageFont.truetype(str(path), size)
    mask, offset = font.getmask2(char, mode="L", anchor="ls")
    if mask is None or mask.size[0] == 0 or mask.size[1] == 0:
        return np.zeros((0, 0), dtype=bool), (0, 0)
    array = np.frombuffer(bytes(mask), dtype=np.uint8).reshape(mask.size[1], mask.size[0])
    return array > 127, (offset[0], offset[1])


def render(path, char, size=300, margin=None):
    """渲染成固定画布上的掩膜（基线在 margin 处），供对齐比较用。"""
    margin = size if margin is None else margin
    ink, (dx, dy) = bitmap(path, char, size)
    canvas = np.zeros((size + 2 * margin, size + 2 * margin), dtype=bool)
    if ink.size:
        top = margin + dy
        left = margin + dx
        canvas[top:top + ink.shape[0], left:left + ink.shape[1]] = ink
    return canvas


def iou(a, b):
    union = (a | b).sum()
    return float((a & b).sum() / union) if union else 1.0


def _shift(mask, dx, dy):
    out = np.zeros_like(mask)
    h, w = mask.shape
    out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = \
        mask[max(-dy, 0):h + min(-dy, 0), max(-dx, 0):w + min(-dx, 0)]
    return out


def align(a, b, radius=1):
    """在 ±radius 像素内找让 IoU 最大的整格平移，返回（IoU, dx, dy）。"""
    best = (iou(a, b), 0, 0)
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx == 0 and dy == 0:
                continue
            score = iou(a, _shift(b, dx, dy))
            if score > best[0]:
                best = (score, dx, dy)
    return best


def compare(path_a, path_b, char, size=300, shift=True):
    """两字体同一字符的 IoU（默认允许 ±1 px 对齐）。"""
    a, b = render(path_a, char, size), render(path_b, char, size)
    return align(a, b)[0] if shift else iou(a, b)


def ink_ratio(path_a, path_b, char, size=300):
    """墨量比：本版墨像素 / 母版墨像素。"""
    a = render(path_a, char, size).sum()
    b = render(path_b, char, size).sum()
    return float(b / a) if a else float("nan")


def shared_hanzi(path_a, path_b):
    """两个字体 cmap 的交集，只取 U+4E00–U+9FFF，按码位排序。"""
    from fontTools.ttLib import TTFont

    with TTFont(path_a, lazy=True) as fa, TTFont(path_b, lazy=True) as fb:
        common = set(fa.getBestCmap()) & set(fb.getBestCmap())
    return sorted(cp for cp in common if 0x4E00 <= cp <= 0x9FFF)


def scan(master, other, chars, size=200, shift=True):
    """逐字量 IoU / 墨量比 / 对齐位移；返回统计与逐字结果。"""
    canvas_margin = size
    unit = 1000 / size  # 1 px 等于多少字体单位（upem=1000）
    rows = []
    for char in chars:
        a = render(master, char, size, canvas_margin)
        b = render(other, char, size, canvas_margin)
        score, dx, dy = align(a, b) if shift else (iou(a, b), 0, 0)
        ink = float(b.sum() / a.sum()) if a.sum() else float("nan")
        rows.append({"char": char, "iou": score, "ink": ink,
                     "shift_px": (dx, dy), "shift_units": ((dx * unit) ** 2 + (dy * unit) ** 2) ** 0.5})
    values = np.array([row["iou"] for row in rows])
    inks = np.array([row["ink"] for row in rows], dtype=float)
    moves = np.array([row["shift_units"] for row in rows])
    return {
        "rows": rows,
        "n": len(rows),
        "median": float(np.median(values)),
        "p10": float(np.percentile(values, 10)),
        "min": float(values.min()),
        "ink_median": float(np.nanmedian(inks)),
        "shift_share": float(np.mean([row["shift_px"] != (0, 0) for row in rows])),
        "moved_units_median": float(np.median(moves[moves > 0])) if (moves > 0).any() else 0.0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="FreeType 同渲染器逐像素比字（母版 vs 本版）")
    parser.add_argument("master", type=Path, help="母版字体")
    parser.add_argument("other", type=Path, help="本版字体")
    parser.add_argument("chars", nargs="*", help="要比的字；与 --all 二选一")
    parser.add_argument("--all", action="store_true", help="两边共有的全部汉字（U+4E00–U+9FFF）")
    parser.add_argument("--size", type=int, default=200, help="像素尺寸（默认 200，同基线）")
    parser.add_argument("--no-shift", action="store_true", help="不做 ±1 px 对齐（报未对齐的 IoU）")
    args = parser.parse_args(argv)

    chars = [chr(cp) for cp in shared_hanzi(args.master, args.other)] if args.all else args.chars
    if not chars:
        parser.error("给几个字，或用 --all")
    stats = scan(args.master, args.other, chars, args.size, shift=not args.no_shift)
    if not args.all:
        for row in stats["rows"]:
            print(f"{row['char']}  IoU {row['iou']:.3f}  墨量 {row['ink']:.3f}  "
                  f"平移 {row['shift_px']}")
    worst = sorted(stats["rows"], key=lambda row: row["iou"])[:8]
    print(f"字数 {stats['n']}  尺寸 {args.size} px 同基线  对齐 {'±1 px' if not args.no_shift else '无'}")
    print(f"IoU 中位 {stats['median']:.3f}  p10 {stats['p10']:.3f}  最低 {stats['min']:.3f}")
    print("最差 8：" + "、".join(f"{row['char']} {row['iou']:.3f}" for row in worst))
    print(f"墨量比中位 {stats['ink_median']:.3f}  被平移修正 {stats['shift_share'] * 100:.1f}%  "
          f"（非零平移中位 {stats['moved_units_median']:.1f} 单位）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
