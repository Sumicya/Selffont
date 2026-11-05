"""收笔尖补齐：母版的撇、捺、钩有一个尖，骨架量出来在离尖几十单位的地方就收住了。

为什么要这一步
--------------
`design_cjk` 的笔环 = 「中线 + 逐点半宽 + 圆头」。母版的撇尖、捺脚是**尖的**（墨宽一路收到 0），
骨架却在中线还没到头的位置就断了（距离变换在该处只剩一两个像素，取骨架时被剪掉）。
拿圆头一补，尖端就短了一截（600 字实测，单位＝字身单位）：

    基（U+57FA）母版墨迹 x[11, 992]，本版 x[31, 972] —— 左右各短 20，差 4.1%
    验（U+9A8C）母版墨迹 y[−81, 838]，本版 y[−54, 811] —— 上下各短 27，差 6.2%
    笺（U+7B3A）母版墨迹 y[−122, 856]，本版 y[−96, 830] —— 上下各短 26，差 5.6%

`tools/box_align.py` 对这种字**不缩放**（目标/现值比超过 4% 时那一轴不动，±2% 也夹不住），
只把中心摆正，于是 600 字里剩下 5 个 dW、14 个 dH 超过 5 单位——那不是位置差，是尖没了。

做法
----
把**自由端**的半圆端头拉成半椭圆：切向半轴 = 该端半宽 + 缺口，法向半轴仍是半宽。
端头外沿落在母版框上，**点数一个不动**（`ARC_STEPS` 不变），三档共用同一个缺口
（`_ext` 记在笔画上，三档只按各自半宽算 reach）。

- 缺口按**母版字面框**算（`tools/master_box.bin`，已剔掉 `日` 右上角那块残墨）。
- 每边最多补 `MAX_EXT` 单位；补长按端头的切向投影折算，投影太小（<`PROJ_MIN`）不补。
- 只补**自由端**；闭合环、零长度笔（字点）不动。
- 只补汉字；拉丁与标点的位置由侧距那条路管，不在这里动。
- 补多少用**真轮廓**量：先按 400 档描一遍得到实际墨迹框（不是拿「轴线 ± 半宽」估）。

用法
----
    python tools/tip_extend.py --chars "基验式席"                 # 打印要补的端头与长度
    python tools/tip_extend.py --chars "基验式席" --dry-run        # 只量不补，打印残差
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MAX_EXT = 60.0        # 单端最多补多长（字身单位）
MIN_GAP = 2.0         # 缺口小于这个不动（抖动不值得碰）
PROJ_MIN = 0.40       # 外向切向在该轴上的投影下限
PERP_TOL = 4.0        # 补端在**另一条轴**上最多允许多顶出这多少（单位）
EDGE_TOL = 8.0        # 端头离实测墨沿 half＋这个小容差之内才算「这条边上的端头」
MEASURE_WEIGHT = 400

SIDES = (("left", 0, -1.0), ("bottom", 1, -1.0), ("right", 0, 1.0), ("top", 1, 1.0))


def _free_ends(stroke, glyph, weight):
    """一笔的两端：[(点, 外向切向)]；闭合笔、零长度笔返回空。"""
    import design_cjk as D

    if stroke.get("closed") or not stroke.get("segs"):
        return []
    if D._zero_length(stroke):
        return []
    pts, ts, tans = D._dense_axis(stroke)
    if len(pts) < 2:
        return []
    half = D.stroke_half(stroke, glyph, weight)
    (tx0, ty0), (tx1, ty1) = tans[0], tans[-1]
    return [(pts[0], (-tx0, -ty0), 0, half), (pts[-1], (tx1, ty1), 1, half)]


def ink_box(glyph, weight=MEASURE_WEIGHT):
    """这一档的**实际**墨迹框：真描一遍（见 design_cjk.outline_points）。"""
    import design_cjk as D

    pts = [p for ring in D.outline_points(glyph, weight) for p in ring]
    if not pts:
        return None
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


def plan(glyph, target, weight=MEASURE_WEIGHT, box=None):
    """算这一字每笔两端要补多少：{笔画序号: (起点补长, 终点补长)}。"""
    box = box or ink_box(glyph, weight)
    if box is None:
        return {}
    got: dict[int, list[float]] = {}
    for side, axis, sign in SIDES:
        gap = (target[axis + 2] - box[axis + 2]) if sign > 0 else (box[axis] - target[axis])
        if not (MIN_GAP < gap <= MAX_EXT):
            continue
        d = (sign, 0.0) if axis == 0 else (0.0, sign)
        edge = box[axis + 2] if sign > 0 else box[axis]
        best = None
        for i, stroke in enumerate(glyph.get("strokes") or []):
            for p, t, which, half in _free_ends(stroke, glyph, weight):
                proj = d[0] * t[0] + d[1] * t[1]
                if proj < PROJ_MIN:
                    continue
                # 这个端头是不是那条边上的「最外点」：圆头的外沿比端点远 half，
                # 所以端点离墨沿 half（＋抖动容差）之内才算压在这条边上。
                if abs(p[axis] - edge) > half + EDGE_TOL:
                    continue
                length = min(gap / proj, MAX_EXT)
                # 斜端补长会顺带把另一条边顶出去（实测 `殴` 因此 dW 多 18 单位）。
                # 这里按母版框给这条边的**另一条轴**留 PERP_TOL 的余量，超了就按比例缩回来。
                perp = 1 - axis
                move = t[perp]
                if abs(move) > 1e-6:
                    if move > 0:
                        room = target[perp + 2] + PERP_TOL - box[perp + 2]
                    else:
                        room = box[perp] - (target[perp] - PERP_TOL)
                    length = min(length, max(0.0, room) / abs(move))
                if length < MIN_GAP:
                    continue
                if best is None or length > best[0]:
                    best = (length, i, which)
        if best is None:
            continue
        length, i, which = best
        slot = got.setdefault(i, [0.0, 0.0])
        slot[which] = max(slot[which], round(length, 1))
    return {i: (v[0], v[1]) for i, v in got.items()}


def apply(glyph, codepoint, table=None, dry_run=False):
    """把补长写进笔画（`_ext` 键），供 `design_cjk.stroke_contours` 读。返回补了哪些端。"""
    if table is None:
        import box_align

        table = box_align.load()
    target = table.get(codepoint)
    if target is None:
        return {}
    box = ink_box(glyph)
    plan_ = plan(glyph, target, box=box)
    if not dry_run:
        for i, ext in plan_.items():
            glyph["strokes"][i]["_ext"] = ext
    return {"plan": plan_, "before": box, "target": target}


def main() -> int:
    import design_cjk as D

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chars", default="基验式席铲笺")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import box_align

    table = box_align.load()
    data = D.load()
    for ch in args.chars:
        cp = ord(ch)
        glyph = data.get(cp)
        if glyph is None or cp not in table:
            print(f"  {ch} 无数据")
            continue
        work = copy.deepcopy(glyph)
        got = apply(work, cp, table, dry_run=args.dry_run)
        plan_ = got["plan"]
        text = ", ".join(f"笔{i} 起{a}/终{b}" for i, (a, b) in plan_.items()) or "不补"
        print(f"  {ch} 目标{got['target']} 现框{got['before']} {text}")
        if not args.dry_run and plan_:
            after = ink_box(work)
            print(f"      补后框 {tuple(round(v,1) for v in after)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
