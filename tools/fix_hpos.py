"""把母版里「摆歪」的字挪回字格中线：只平移，不缩放、不改轮廓。

为什么要有这一步
----------------
母版 `MarukoGothicCJKsc-Regular.ttf` 的 27,559 个汉字全部是 1000 宽的字格，但墨迹
**不是**都落在格子中间。逐字量「墨心（xMin+xMax)/2 与 500 的距离」：

    满格字（墨宽 ≥ 850）26,560 个
      |dcx| ≤ 20   23,814 个（89.7%）
      |dcx| > 20    2,746 个（10.3%）
      |dcx| > 30      642
      |dcx| > 40       80
      最大             ±54.5（U+6241 扁 −54.5、U+37D5 㟕 +48.0）

偏差还带方向：−30 档 951 字，+30 档只有 241 字，整体偏左。屏幕上就是「有的字发飘、
有的挤边」，与笔画形状无关——形状完全一样，位置差 2%–5% 的 em。

为什么只平移
------------
主人 2026-11-05 的原话是「修水平高度加定位」，且明令不许用 `box_align` 那种拉伸。
所以这里只做一件事：整字沿 x 平移 `-dcx`，让墨心落到 500。轮廓的每个点相对彼此
一个都不动，只改绝对坐标；`advance` 不变（还是 1000），`lsb` 跟着平移量走，
改完 `lsb == xMin` 仍然成立。

判据（全部可复算）
------------------
1. 每个被动过的字，所有点的 x 位移**完全相等**（容差 0）——这就是「只平移」的证明；
2. `advance` 一个字都不变，仍全为 1000；
3. 改完 `lsb == xMin` 全库成立（母版原本也是 0 例外）；
4. 满格字 `|dcx| ≤ 1` 占比 100%。

不动的字
--------
- 非汉字（拉丁、符号、标点、假名）：它们的侧距是母版逐个手调的，见 `tools/side_measure.py`；
- 墨宽 < 600 的窄部件与笔画（`亻` `氵` `丨` `一`）：本来就该靠边或居中，按 bbox 一刀切会挪坏；
- `|dcx| ≤ 20` 的字：20 单位 = 2% em，肉眼在 16px 下看不出来，动它只会让母版偏离自己的设计。

用法
----
    python tools/fix_hpos.py 母版.ttf -o 母版-校正.ttf            # 写文件
    python tools/fix_hpos.py 母版.ttf --dry-run                    # 只报数字
    python tools/fix_hpos.py 母版.ttf -o out.ttf --threshold 30    # 只修偏得更多的
"""
from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from fontTools.ttLib import TTFont

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

CJK_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF))
FULL_WIDTH = 1000
MIN_INK = 600          # 墨宽下限：窄部件不参与
THRESHOLD = 20         # 偏差阈值：20 单位 = 2% em


def is_cjk(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in CJK_RANGES)


def face_boxes() -> dict[int, tuple[int, int, int, int]]:
    """母版的字面框（去掉残块）。没有表就退回 glyf bbox。

    `日`（U+65E5）在母版里有一块 55×45 的残墨吊在右上角，直接拿 glyf bbox 会把它的
    右边撑到 828，算出来的 dcx 是 +14.5，凭空让它「偏右」。`tools/master_box.bin`
    就是为这件事做的，能读就用它。
    """
    try:
        from box_align import load
        return load()
    except Exception:
        return {}


def measure(font: TTFont, boxes: dict | None = None) -> list[tuple[int, str, float, int]]:
    """返回 [(码位, 字形名, dcx, 墨宽)]，只含汉字且有轮廓的字。"""
    cmap, glyf = font.getBestCmap(), font["glyf"]
    boxes = boxes or {}
    rows = []
    for cp, name in cmap.items():
        if not is_cjk(cp):
            continue
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:
            continue
        box = boxes.get(cp)
        x_min, x_max = (box[0], box[2]) if box else (glyph.xMin, glyph.xMax)
        width = x_max - x_min
        rows.append((cp, name, (x_min + x_max) / 2 - FULL_WIDTH / 2, width))
    return rows


def summarize(rows: list[tuple[int, str, float, int]], label: str) -> None:
    full = [dc for _cp, _n, dc, w in rows if w >= 850]
    dev = sorted(abs(dc) for dc in full)
    n = len(full)
    def pct(limit: int) -> str:
        return f"{100 * sum(1 for d in dev if d <= limit) / n:.2f}%"
    print(f"{label}：满格字 {n} 个")
    print(f"  |dcx| 中位 {statistics.median(dev):.1f}  最大 {dev[-1]:.1f}"
          f"  ≤1 {pct(1)}  ≤20 {pct(20)}")


def fix(font: TTFont, threshold: int, min_ink: int, boxes: dict | None = None) -> dict:
    """整字平移，返回统计。不动 advance、不动轮廓形状。"""
    cmap, glyf, hmtx = font.getBestCmap(), font["glyf"], font["hmtx"]
    boxes = boxes or {}
    moved = 0
    shifts: dict[str, int] = {}
    for cp, name in cmap.items():
        if not is_cjk(cp):
            continue
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:
            continue
        box = boxes.get(cp)
        x_min, x_max = (box[0], box[2]) if box else (glyph.xMin, glyph.xMax)
        if x_max - x_min < min_ink:
            continue
        dx = round(FULL_WIDTH / 2 - (x_min + x_max) / 2)
        if abs(dx) <= threshold:
            continue
        glyph.coordinates.translate((dx, 0))
        glyph.xMin += dx
        glyph.xMax += dx
        advance, lsb = hmtx[name]
        hmtx[name] = (advance, lsb + dx)
        shifts[name] = dx
        moved += 1
    return {"moved": moved, "shifts": shifts}


def verify(original: TTFont, fixed: TTFont, shifts: dict[str, int]) -> None:
    """三条硬判据：位移处处相等、advance 不变、lsb == xMin。"""
    og, fg = original["glyf"], fixed["glyf"]
    oh, fh = original["hmtx"], fixed["hmtx"]
    bad_shift = bad_advance = bad_lsb = 0
    for name, dx in shifts.items():
        a, b = og[name], fg[name]
        coords_a = list(a.coordinates)
        coords_b = list(b.coordinates)
        if a.numberOfContours > 0 and coords_a and coords_b:
            deltas = {round(px2 - px1) for (px1, _), (px2, _) in zip(coords_a, coords_b)}
            if deltas - {dx}:
                bad_shift += 1
    for name in fixed.getGlyphOrder():
        if oh[name][0] != fh[name][0]:
            bad_advance += 1
        if name in fg and fg[name].numberOfContours > 0 and fh[name][1] != fg[name].xMin:
            bad_lsb += 1
    print(f"验收：位移不等的字 {bad_shift} 个 · advance 变了的字 {bad_advance} 个 · "
          f"lsb≠xMin 的字 {bad_lsb} 个")
    if bad_shift or bad_advance or bad_lsb:
        raise SystemExit("验收不过，不写文件")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    ap.add_argument("--min-ink", type=int, default=MIN_INK)
    args = ap.parse_args()

    original = TTFont(args.source)
    boxes = face_boxes()
    print(f"字面框表：{'已加载 %d 字' % len(boxes) if boxes else '没有，退回 glyf bbox'}")
    rows = measure(original, boxes)
    summarize(rows, f"改前（{args.source.name}）")

    work = TTFont(args.source)
    stats = fix(work, args.threshold, args.min_ink, boxes)
    shifts = stats["shifts"]
    print(f"阈值 |dcx|>{args.threshold}、墨宽≥{args.min_ink}：平移 {stats['moved']} 个字"
          f"（位移中位 {statistics.median([abs(v) for v in shifts.values()]) if shifts else 0:.0f} 单位）")
    if shifts:
        sample = sorted(shifts.items(), key=lambda kv: -abs(kv[1]))[:5]
        print("  位移最大的 5 个：" + "、".join(f"{n}{v:+d}" for n, v in sample))
    summarize(measure(work, {cp: (b[0] + shifts.get(n, 0), b[1], b[2] + shifts.get(n, 0), b[3])
                             for cp, b in boxes.items()
                             for n in [original.getBestCmap().get(cp, "")] if n}, ), "改后")
    verify(original, work, shifts)

    if args.dry_run or not args.output:
        print("（--dry-run：不写文件）")
        return
    work.save(args.output)
    print(f"已写 {args.output}（{args.output.stat().st_size:,} B）")


if __name__ == "__main__":
    main()
