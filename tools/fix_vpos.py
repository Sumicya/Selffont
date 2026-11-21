"""把母版里「竖着坐歪」的字挪回设计中线：只沿 y 平移，不缩放、不改轮廓。

为什么要有这一步
----------------
母版 27,559 个汉字是 1000 字格，横向有 10.3% 的满格字墨心偏离 500（`fix_hpos.py` 处理）。
竖向同样有一批：在**满宽满高**（墨宽 ≥850 且墨高 ≥850）的 25,909 个字里，墨心
`(yMin+yMax)/2` 的中位是 377.5，而偏离这个中位超过 20 单位（2% em）的有 1,594 个，
最远 47 单位（`幵` `珥` `羽` `平` `雨` `研` `琿`）。屏幕上就是「有的字浮高、有的下沉」。

为什么只平移
------------
主人 2026-11-05 的原话是「修水平高度加定位」，且明令不许用 `box_align` 那种拉伸。
所以这里只做一件事：整字沿 y 平移 `dy`，让墨心落回设计中线。轮廓的点相对彼此一个不动，
`advance`（横向）与 `lsb` 都不碰——竖向没有 advance 概念，改 y 不影响排版宽度。

设计中线怎么定
--------------
取**原字体**满宽满高字墨心的中位数（母版是 377.5，Noto CJK 同口径约 380）。
用中位数而不用 500：汉字并不撑满 0..1000，母版自己的设计重心就在 377.5 附近，
强行对到 500 会把整库抬起来 122 单位，那是改设计，不是修定位。

不动的字
--------
- 非汉字（拉丁、符号、标点、假名）：竖排规则不同，不参与；
- 墨高 < 850 的字（`一` `二` `丶` `丿`）：它们本来就该落在设计指定位置，对齐会把它们拉走；
- |dcy| ≤ 20 的字：2% em，16px 下看不出来，动它只是让母版偏离自己的设计。

用法
----
    python tools/fix_vpos.py 母版.ttf -o 母版-校正.ttf       # 写文件
    python tools/fix_vpos.py 母版.ttf --dry-run               # 只报数字
    python tools/fix_vpos.py 母版.ttf -o out.ttf --threshold 30
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))

CJK_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF))
MIN_WIDE = 850         # 墨宽下限：和 fix_hpos 同一把尺子
MIN_TALL = 850         # 墨高下限：只修「撑满高度」的字
THRESHOLD = 20         # 偏差阈值：20 单位 = 2% em


def is_cjk(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in CJK_RANGES)


def face_boxes() -> dict[int, tuple[int, int, int, int]]:
    """母版的字面框（去掉残块）。没有表就退回 glyf bbox。

    和 `fix_hpos.py` 用同一张表、同一个理由：`日` 在母版里有一块 55×45 的残墨吊在右上角，
    按 glyf bbox 量它的墨心会被抬到 +34，看着像「浮高」，其实这块墨不是笔画。用去残墨的
    字面框量，`日` 的 dcy 只有 −1。
    """
    try:
        from box_align import load
        return load()
    except Exception:
        return {}


_table_centre: float | None = None


def table_centre() -> float | None:
    """字面框表上的设计中线（满宽满高字墨心的中位数）；没有表返回 None。"""
    global _table_centre
    if _table_centre is None:
        boxes = face_boxes()
        if not boxes:
            return None
        centres = [(b[1] + b[3]) / 2 for b in boxes.values()
                   if b[2] - b[0] >= MIN_WIDE and b[3] - b[1] >= MIN_TALL]
        _table_centre = statistics.median(centres)
    return _table_centre


def corrected_box(box: tuple[int, int, int, int], centre: float,
                  threshold: int = THRESHOLD) -> tuple[int, int, int, int]:
    """把母版字面框按竖向修正规则挪一下，返回「修完之后应该在的」框。

    `tools/cjk_vf.py` 的逐字对齐用的就是这张表；表本身是**未修正**母版量的，
    所以要在这里套同一条规则，否则自版字体会把母版的竖向偏差原样抄过去
    （实测：`平 −41.5`、`幵 −47.0`、`珥 −47.0`、`羽 −45.5`，与母版逐单位相同）。
    """
    x_min, y_min, x_max, y_max = box
    if x_max - x_min < MIN_WIDE or y_max - y_min < MIN_TALL:
        return box
    dy = round(centre - (y_min + y_max) / 2)
    if abs(dy) <= threshold:
        return box
    return (x_min, y_min + dy, x_max, y_max + dy)


def rows_of(font: TTFont, boxes: dict | None = None) -> list[tuple[int, str, float, int]]:
    """返回 [(码位, 字形名, 墨心 y, 墨高)]，只含汉字、有轮廓、满宽的字。

    框优先取 `tools/master_box.bin` 的字面框（去残墨），没有就退回 glyf bbox。
    """
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
        x_min, y_min, x_max, y_max = box if box else (glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax)
        if x_max - x_min < MIN_WIDE:
            continue
        rows.append((cp, name, (y_min + y_max) / 2, y_max - y_min))
    return rows


def design_centre(rows: list[tuple[int, str, float, int]]) -> float:
    """设计中线 = 满宽满高字墨心的中位数。"""
    tall = [cy for _cp, _n, cy, h in rows if h >= MIN_TALL]
    return statistics.median(tall)


def summarize(rows: list[tuple[int, str, float, int]], centre: float, label: str) -> None:
    tall = [abs(cy - centre) for _cp, _n, cy, h in rows if h >= MIN_TALL]
    dev = sorted(tall)
    n = len(dev)
    pct = lambda limit: f"{100 * sum(1 for d in dev if d <= limit) / n:.2f}%"
    print(f"{label}：满宽满高字 {n} 个（设计中线 {centre:.1f}）")
    print(f"  |dcy| 中位 {statistics.median(dev):.1f}  最大 {dev[-1]:.1f}"
          f"  ≤1 {pct(1)}  ≤20 {pct(20)}")


def fix(font: TTFont, centre: float, threshold: int, boxes: dict | None = None) -> dict:
    """整字沿 y 平移，返回统计。不动 advance、不动 lsb、不动轮廓形状。"""
    cmap, glyf = font.getBestCmap(), font["glyf"]
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
        x_min, y_min, x_max, y_max = box if box else (glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax)
        if x_max - x_min < MIN_WIDE or y_max - y_min < MIN_TALL:
            continue
        dy = round(centre - (y_min + y_max) / 2)
        if abs(dy) <= threshold:
            continue
        glyph.coordinates.translate((0, dy))
        glyph.yMin += dy
        glyph.yMax += dy
        shifts[name] = dy
        moved += 1
    return {"moved": moved, "shifts": shifts}


def verify(original: TTFont, fixed: TTFont, shifts: dict[str, int]) -> None:
    """三条硬判据：y 位移处处相等（纯平移）、x 一个点没动、advance / lsb 不变。"""
    og, fg = original["glyf"], fixed["glyf"]
    oh, fh = original["hmtx"], fixed["hmtx"]
    bad_shift = bad_x = bad_advance = 0
    for name, dy in shifts.items():
        a, b = og[name], fg[name]
        coords_a, coords_b = list(a.coordinates), list(b.coordinates)
        if not coords_a or not coords_b:
            continue
        deltas = {round(py2 - py1) for (_px1, py1), (_px2, py2) in zip(coords_a, coords_b)}
        if deltas - {dy}:
            bad_shift += 1
        if any(px1 != px2 for (px1, _y1), (px2, _y2) in zip(coords_a, coords_b)):
            bad_x += 1
    for name in fixed.getGlyphOrder():
        if oh[name][0] != fh[name][0] or oh[name][1] != fh[name][1]:
            bad_advance += 1
    print(f"验收：y 位移不等的字 {bad_shift} 个 · x 动过的字 {bad_x} 个 · "
          f"advance/lsb 变了的字 {bad_advance} 个")
    if bad_shift or bad_x or bad_advance:
        raise SystemExit("验收不过，不写文件")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    args = ap.parse_args()

    original = TTFont(args.source)
    boxes = face_boxes()
    print(f"字面框表：{'已加载 %d 字' % len(boxes) if boxes else '没有，退回 glyf bbox'}")
    rows = rows_of(original, boxes)
    centre = design_centre(rows)
    summarize(rows, centre, f"改前（{args.source.name}）")

    work = TTFont(args.source)
    stats = fix(work, centre, args.threshold, boxes)
    shifts = stats["shifts"]
    median = statistics.median([abs(v) for v in shifts.values()]) if shifts else 0
    print(f"阈值 |dcy|>{args.threshold}、墨宽≥{MIN_WIDE}、墨高≥{MIN_TALL}：平移 {stats['moved']} 个字"
          f"（位移中位 {median:.0f} 单位）")
    if shifts:
        sample = sorted(shifts.items(), key=lambda kv: -abs(kv[1]))[:5]
        print("  位移最大的 5 个：" + "、".join(f"{n}{v:+d}" for n, v in sample))
    shifted_boxes = {cp: (b[0], b[1] + stats["shifts"].get(original.getBestCmap().get(cp, ""), 0),
                          b[2], b[3] + stats["shifts"].get(original.getBestCmap().get(cp, ""), 0))
                     for cp, b in boxes.items()}
    summarize(rows_of(work, shifted_boxes), centre, "改后")
    verify(original, work, shifts)

    if args.dry_run or not args.output:
        print("（--dry-run：不写文件）")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    work.save(args.output)
    print(f"已写 {args.output}（{args.output.stat().st_size:,} B）")


if __name__ == "__main__":
    main()
