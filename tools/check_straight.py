"""量「笔画边直不直」——一条命令，可复算。

为什么要有这个工具
------------------
2026-11-02 主人指出「門 左竖不直」，我先量了折角，折角说没问题；真正的问题是
左竖被骨架切成三段、每段都直、三段之间拧了 0.548°。折角量不到这种歪，因为它
只看相邻切线的夹角，整根斜着走的线每处都很平滑。

所以判据要直接落在「边的形状」上：
- `rms_med`：边缘相对**中位**的残差 RMS。整体歪会全额进这个数——治「拧」看它。
- `rms_fit`：边缘相对**最小二乘直线**的残差 RMS。去掉整体倾斜后剩下的是毛刺与弯。
- `over2`：偏离中位超过 2 px 的行占比。2 px 是 800 px 渲染下肉眼能看出的一档。
- `width`：墨带宽度中位（px）。治「不饱满」看它。

判据：母版是人做的直边，四个数应当接近 0 差、宽度一致；本版越接近母版越好。

用法
----
    python tools/check_straight.py 母版.ttf 本版.ttf --chars 門口日
    python tools/check_straight.py 母版.ttf 本版.ttf --all --limit 200
    python tools/check_straight.py 母版.ttf 本版.ttf --chars 門 --json out.json

只量**竖直墨带**（宽的横画会让「逐行取左边缘」跳变，那是横画不是竖）；带子要同时
满足：宽在 em 的 1.5%–12% 之间、连续出现 ≥ em 的 15% 行数。这样挑出来的是竖笔，
横笔的边另有 `--edges h` 处理。
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

EM = 1000.0            # 字体单位，与仓里 upem 一致
OVER = 2.0             # 超标阈值（px），800 px 渲染下肉眼可见的一档
MIN_W = 0.015          # 墨带最窄 = em 的 1.5%
MAX_W = 0.12           # 墨带最宽 = em 的 12%，再宽就是横画或整块
MIN_ROWS = 0.30        # 至少跨 em 的 30% 才算「长竖」：斜笔、点、短撇的边本来就是弯的，混进来会把母版也量成 9 px


def render(path, char, size):
    """同原点渲染：anchor="ls"，基线落在画布 3/4 高处。"""
    font = ImageFont.truetype(str(path), size)
    canvas = Image.new("L", (size * 3, size * 4), 255)
    ImageDraw.Draw(canvas).text((size, size * 3), char, font=font, fill=0, anchor="ls")
    return np.array(canvas) < 128


def runs(row):
    """一行里的墨段：[(起点x, 宽度)]。"""
    idx = np.where(row)[0]
    if len(idx) == 0:
        return []
    out, s, p = [], idx[0], idx[0]
    for v in idx[1:]:
        if v == p + 1:
            p = v
        else:
            out.append((int(s), int(p - s + 1)))
            s = v
            p = v
    out.append((int(s), int(p - s + 1)))
    return out


def bands(mask, size):
    """把细长的竖直墨段**按 x 聚类**成墨带。

    不能按「行号连续」分组：竖笔与横笔相交的那些行，游程宽度会超标被剔除，行号出现
    空档（`日` 的左右两竖各被两条横打断），连续分组会把一根竖切成三截、每截都太短。
    按 x 聚类则空档无关，只要竖的 x 位置稳定就能串起来。
    """
    lo, hi = MIN_W * size, MAX_W * size
    cand = []
    for y in range(mask.shape[0]):
        for (x, w) in runs(mask[y]):
            if lo <= w <= hi:
                cand.append((y, x, w))
    if not cand:
        return []
    cand.sort(key=lambda t: t[1])
    groups, cur = [], [cand[0]]
    for r in cand[1:]:
        y, x, w = r
        # 与**整个簇**的中位比，不比最近几个：只比最近几个会允许圆弧一路漂过去，
        # 实测 `團` 的外框圆角被当成一根竖，量出 55 px 的假偏差。
        px = statistics.median([c[1] for c in cur])
        pw = statistics.median([c[2] for c in cur])
        if abs(x - px) <= max(1.5, 0.35 * pw):
            cur.append(r)
        else:
            groups.append(cur)
            cur = [r]
    groups.append(cur)
    keep = []
    for g in groups:
        ys = [c[0] for c in g]
        if len(set(ys)) < MIN_ROWS * size or (max(ys) - min(ys)) < MIN_ROWS * size:
            continue
        # 起点 x 的散布也是闸门：一根直竖的起点只会在抗锯齿那几像素里动
        starts = [c[1] for c in g]
        if max(starts) - min(starts) > 0.05 * size:
            continue
        # 同一行只留一条（x 聚类可能把相邻两笔并进来）
        by_y, uniq = {}, []
        for c in g:
            if c[0] not in by_y or abs(c[1] - by_y[c[0]][1]) < 0.5 * max(c[2], by_y[c[0]][2]):
                by_y[c[0]] = c
        uniq = sorted(by_y.values())
        keep.append(uniq)
    return keep


TRIM = 0.10            # 两端各裁掉的比例：端头圆头与交接过渡不是「边直不直」的问题


def measure_band(g):
    # 两端各裁 TRIM：圆头和与横画的交接会把边缘带弯，那不是这根竖本身不直。
    if len(g) > 8:
        k = int(len(g) * TRIM)
        g = g[k:len(g) - k]
    ys = np.array([r[0] for r in g], float)
    xs = np.array([r[1] for r in g], float)
    ws = np.array([r[2] for r in g], float)
    left, right = xs, xs + ws - 1

    def stats(edge):
        dev = edge - np.median(edge)
        A = np.vstack([ys, np.ones_like(ys)]).T
        coef, *_ = np.linalg.lstsq(A, edge, rcond=None)
        resid = edge - A @ coef
        return dict(rms_med=float(np.sqrt((dev ** 2).mean())),
                    rms_fit=float(np.sqrt((resid ** 2).mean())),
                    over2=float(100.0 * (np.abs(dev) > OVER).mean()),
                    slope=float(abs(coef[0]) * 100.0))   # px / 百行

    return dict(rows=int(len(g)), width=float(np.median(ws)),
                left=stats(left), right=stats(right))


def measure_char(path, char, size):
    return [measure_band(g) for g in bands(render(path, char, size), size)]


def summarise(per_char):
    """所有墨带的汇总：取各指标的中位。"""
    every = [b for bs in per_char.values() for b in bs]
    if not every:
        return None
    def med(f):
        return float(np.median([f(b) for b in every]))
    return dict(bands=len(every),
                rms_med=med(lambda b: b["left"]["rms_med"]),
                rms_fit=med(lambda b: b["left"]["rms_fit"]),
                over2=med(lambda b: b["left"]["over2"]),
                slope=med(lambda b: b["left"]["slope"]),
                width=med(lambda b: b["width"]))


def shared_hanzi(a, b):
    from fontTools.ttLib import TTFont
    with TTFont(str(a), lazy=True) as fa, TTFont(str(b), lazy=True) as fb:
        common = set(fa.getBestCmap()) & set(fb.getBestCmap())
    return sorted(c for c in common if 0x4E00 <= c <= 0x9FFF)


def main() -> None:
    ap = argparse.ArgumentParser(description="量笔画边的直度与宽度（一条命令复算）")
    ap.add_argument("master", type=Path, help="对照字体，通常是人做的母版")
    ap.add_argument("other", type=Path, help="要量的本版字体")
    ap.add_argument("--chars", default="", help="只量这些字；不给则用两者 cmap 交集")
    ap.add_argument("--all", action="store_true", help="量交集里的全部汉字")
    ap.add_argument("--limit", type=int, default=0, help="配合 --all，最多前 N 个码位")
    ap.add_argument("--size", type=int, default=800, help="渲染像素（默认 800）")
    ap.add_argument("--json", type=Path, default=None, help="把逐字结果写成 JSON")
    args = ap.parse_args()

    if args.chars:
        cps = [ord(c) for c in args.chars]
    else:
        cps = shared_hanzi(args.master, args.other)
        if not args.all:
            cps = cps[:12]
        if args.limit:
            cps = cps[:args.limit]

    out = {"size": args.size, "master": str(args.master), "other": str(args.other), "chars": {}}
    print(f"渲染 {args.size} px；墨带判据：宽 {MIN_W:.1%}–{MAX_W:.1%} em、连续 ≥{MIN_ROWS:.0%} em 行")
    print(f"{'字':2s} {'母版 RMS':>9s} {'本版 RMS':>9s} {'母版宽':>7s} {'本版宽':>7s} {'本版超标%':>9s}")
    m_all, o_all = {}, {}
    for cp in cps:
        ch = chr(cp)
        m = measure_char(args.master, ch, args.size)
        o = measure_char(args.other, ch, args.size)
        sm, so = summarise({ch: m}), summarise({ch: o})
        out["chars"][ch] = {"master": m, "other": o}
        if not sm or not so:
            print(f"{ch}  量不出（没有够长的竖直墨带）")
            continue
        m_all[ch], o_all[ch] = sm, so
        print(f"{ch}  {sm['rms_med']:8.2f}px {so['rms_med']:8.2f}px "
              f"{sm['width']:7.0f} {so['width']:7.0f} {so['over2']:8.1f}%")

    if m_all:
        def agg(d, k):
            return float(np.median([v[k] for v in d.values()]))
        print("\n汇总（各字中位再取中位）")
        for k, label in (("rms_med", "边缘相对中位 RMS"), ("rms_fit", "相对直线拟合 RMS"),
                         ("over2", "偏离中位 >2px 的行占比"), ("slope", "整体斜率 px/百行"),
                         ("width", "墨带宽度中位")):
            unit = "px" if "rms" in k else ("%" if k == "over2" else ("px/百行" if k == "slope" else "px"))
            print(f"  {label:22s} 母版 {agg(m_all, k):7.2f}{unit}   本版 {agg(o_all, k):7.2f}{unit}")
        out["summary"] = {"master": {k: agg(m_all, k) for k in m_all[next(iter(m_all))]},
                          "other": {k: agg(o_all, k) for k in o_all[next(iter(o_all))]}}

    if args.json:
        args.json.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n逐字结果写入 {args.json}")


if __name__ == "__main__":
    main()
