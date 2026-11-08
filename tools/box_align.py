"""把重建出来的字摆回母版的位置与高度：逐字仿射对齐（平移 + 受限期缩放）。

为什么要有这一步
----------------
`tools/design_cjk.bin` 的中线是从母版量出来的，骨架位置本来就对；但「中线 + 半宽 +
圆头 + 直段吸附」这一串重建会各自带一点误差，叠加起来整块就漂了。2026-11-05 实测
600 字（GB2312 一级抽样）：

- 墨迹中心 x 差中位 −0.5，p05/p95 −7.0/+6.5，|差|>5 的 **102 字**
- 墨迹中心 y 差中位 +0.5，p05/p95 −5.5/+7.0，|差|>5 的 **97 字**
- `日` 上沿比母版少 64 单位（高比 0.924）

系统性偏移只能用系统性办法修：按母版逐字的墨迹外接框，把整块缩放并平移回去。

做法与边界
----------
- 目标框来自 `tools/master_box.bin`（MarukoGothicCJKsc-Regular.ttf @ 97e9dd4 逐字量的
  墨迹框，33931 字，zlib 压缩 141 KB）。它是**度量**，不是字体文件。
- 缩放系数**限幅 ±2%**；某一轴的目标/现值比超过 4% 时**这一轴不缩放**，只平移。
  超限的多半是母版自身带了不该算进字面的东西（`日` 右上角吊着一块 55×45 的孤立残墨，
  按母版 bbox 算高度会多 8.2%，把整个字拉长去盖它显然不对），也可能是本版真少了笔画——
  两种情况都不该用拉伸去凑，留着差值并在 `--report` 里点名。
- 变换施加在**三档共用的同一组系数**上：先按 400 档算一次，再原样套到 300/500，
  三档点数与对应关系一个不动（可变字体的硬前提）。
- 只动轮廓点，不动 advance。全角汉字的字宽由自身字格决定，不跟墨迹走。

用法
----
    python tools/box_align.py --check 母版.ttf 本版.ttf --chars "$(head -1 tools/endcap_sample200.txt)"
"""
from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

TABLE = Path(__file__).resolve().parent / "master_box.bin"
SCALE_CLAMP = 0.02
SCALE_SKIP = 0.04
# 横向归中（2026-11-08）：母版自己 10% 的满格字墨心偏中线 20~54 单位，本版按母版框对齐时
# 会把这个偏差原样抄过来。打开这个开关，满格字墨心平移到中线（只平移，不缩放、不动 advance）。
# 默认关：开了就不再与母版逐字重合，那是改设计，要主人点头。用 `python -c ...` 或环境变量
# `SELFFONT_CENTER=1` 打开（构建期读环境变量，见 apply_all）。
def _env_flag(name: str) -> bool:
    import os
    return os.environ.get(name, "").strip().lower() in ("1", "on", "true", "yes")


CENTER_X = _env_flag("SELFFONT_CENTER")
# 只做「防表坏」的兜底：全库满格字最远 54.5（U+6241 扁），超过 120 的只可能是表本身错了，
# 那一类不归中。不要拿它当「偏差太大就不修」的阈值——那会把最该修的字排除掉。
CENTER_MAX = 120
CENTER_WIDE = 850        # 「满格字」的墨宽下限，与 fix_hpos.py 同口径
_cache = None


def load() -> dict[int, tuple[int, int, int, int]]:
    """码位 → 母版墨迹外接框 (xMin, yMin, xMax, yMax)。"""
    global _cache
    if _cache is not None:
        return _cache
    raw = zlib.decompress(TABLE.read_bytes())
    out, i, cp = {}, 0, 0
    n = len(raw)
    while i < n:
        shift, delta = 0, 0
        while True:
            b = raw[i]
            i += 1
            delta |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
        cp += delta
        x0, y0, x1, y1 = struct.unpack_from("<4h", raw, i)
        i += 8
        out[cp] = (x0, y0, x1, y1)
    _cache = out
    return out


def factors(box, target, weight_only=False):
    """返回 (sx, sy, 目标中心)。box/target 都是 (x0, y0, x1, y1)。

    缩放只在这条轴上「目标/现值」落在 ±4% 以内才做，且结果再夹到 ±2%；
    超出的那条轴按 1.0 处理（只平移）。
    """
    x0, y0, x1, y1 = box
    mx0, my0, mx1, my1 = target
    w, h = x1 - x0, y1 - y0
    mw, mh = mx1 - mx0, my1 - my0

    def one(cur, want):
        if cur <= 1 or want <= 1:
            return 1.0
        ratio = want / cur
        if abs(ratio - 1.0) > SCALE_SKIP:
            return 1.0
        return min(1.0 + SCALE_CLAMP, max(1.0 - SCALE_CLAMP, ratio))

    return one(w, mw), one(h, mh), ((mx0 + mx1) / 2.0, (my0 + my1) / 2.0)


def center_x(rings, codepoint: int, target=None):
    """把满格字横向墨心平移到中线（只平移）。默认关，见 CENTER_X。

    判据：平移前后每个点的 x 位移完全相等（这是「只平移」的证明），advance 不参与。
    母版偏差超过 CENTER_MAX 的字不归中——那些字多半是母版把不该算进字面的东西算进去了，
    照它归中会把字挪歪。
    """
    if not CENTER_X:
        return rings
    box = load().get(codepoint) if target is None else target
    base = rings.get(400)
    if box is None or not base:
        return rings
    ink = [p for ring in base for p in ring]
    if not ink:
        return rings
    # 「满格」按**母版字面框**判（和 fix_hpos.py 同一口径）：本版轮廓在 apply 里被限幅缩过
    # 一两个百分点，拿缩完的宽度判会把 `伯` 那种 847 单位宽的窄格字也算成满格，两边判据打架。
    if box[2] - box[0] < CENTER_WIDE:
        return rings          # 不是满格字，侧距是母版逐个手调的，不归中
    x0 = min(p[0] for p in ink)
    x1 = max(p[0] for p in ink)
    dx = 500.0 - (x0 + x1) / 2.0
    if abs(dx) > CENTER_MAX:
        return rings
    if abs(dx) < 0.5:
        return rings
    return {weight: [[(round(x + dx, 3), y) for (x, y) in ring] for ring in glyph]
            for weight, glyph in rings.items()}


def apply_all(rings, codepoint: int):
    """构建期入口：先按母版框摆位，再（若开关打开）横向归中。"""
    rings = apply(rings, codepoint)
    return center_x(rings, codepoint)


def apply(rings: dict[int, list[list[tuple[float, float]]]], codepoint: int):
    """按母版框把三档轮廓一起摆正。rings 是 {档: [环点列]}，返回同结构。"""
    target = load().get(codepoint)
    base = rings.get(400) if isinstance(rings, dict) else None
    if target is None or not base:
        return rings
    # 母版的竖向偏差不能抄过去：表是未修正母版量的，这里套同一条竖向修正规则，
    # 让自版字体落在「修完之后」应该落的位置（见 tools/fix_vpos.py 的 corrected_box）。
    try:
        import fix_vpos
        centre = fix_vpos.table_centre()
        if centre is not None:
            target = fix_vpos.corrected_box(tuple(target), centre)
    except Exception:
        pass
    pts = [p for ring in base for p in ring]
    if not pts:
        return rings
    box = (min(p[0] for p in pts), min(p[1] for p in pts),
           max(p[0] for p in pts), max(p[1] for p in pts))
    sx, sy, (tx, ty) = factors(box, target)
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    if abs(sx - 1) < 1e-4 and abs(sy - 1) < 1e-4 and abs(tx - cx) < 1e-3 and abs(ty - cy) < 1e-3:
        return rings
    out = {}
    for weight, rs in rings.items():
        out[weight] = [[(round((x - cx) * sx + tx, 3), round((y - cy) * sy + ty, 3))
                        for (x, y) in ring] for ring in rs]
    return out


def main() -> int:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fontTools.ttLib import TTFont

    ap = argparse.ArgumentParser(description="检查对齐表：逐字打印缩放系数与残差")
    ap.add_argument("--chars", default="")
    ap.add_argument("--report", action="store_true", help="打印跳过了纵向/横向缩放的码位")
    ap.add_argument("--master", type=Path, default=None)
    ap.add_argument("--ours", type=Path, default=None)
    args = ap.parse_args()

    table = load()
    print(f"对齐表 {len(table)} 字")
    if args.report and args.ours:
        # 只报「某一轴因为差得太多而不缩放」的字：那是母版带残墨、或者本版真缺笔画的地方，
        # 需要人看一眼，不能靠拉伸凑过去。
        from fontTools.ttLib import TTFont as _TTFont

        skipped, clipped, seen = [], [], 0
        with _TTFont(str(args.ours), lazy=True) as fo:
            cmap, glyf = fo.getBestCmap(), fo["glyf"]
            for cp, name in cmap.items():
                if cp not in table:
                    continue
                g = glyf[name]
                if g.numberOfContours <= 0:
                    continue
                g.recalcBounds(glyf)
                box = (g.xMin, g.yMin, g.xMax, g.yMax)
                sx, sy, _ = factors(box, table[cp])
                want_x = (table[cp][2] - table[cp][0]) / max(1, box[2] - box[0])
                want_y = (table[cp][3] - table[cp][1]) / max(1, box[3] - box[1])
                seen += 1
                if sx == 1.0 and abs(want_x - 1) > SCALE_SKIP:
                    skipped.append((cp, "x", want_x))
                elif abs(want_x - 1) > SCALE_CLAMP:
                    clipped.append((cp, "x", want_x))
                if sy == 1.0 and abs(want_y - 1) > SCALE_SKIP:
                    skipped.append((cp, "y", want_y))
                elif abs(want_y - 1) > SCALE_CLAMP:
                    clipped.append((cp, "y", want_y))
        print(f"比过 {seen} 字：某轴不缩放（差 >{SCALE_SKIP:.0%}）{len(skipped)} 处，"
              f"夹到 ±{SCALE_CLAMP:.0%} 的 {len(clipped)} 处")
        for cp, axis, ratio in skipped[:40]:
            print(f"  不缩放 {chr(cp)} 轴{axis} 目标/现值 {ratio:.3f}")
        return 0
    if args.chars and args.master and args.ours:
        with TTFont(str(args.master), lazy=True) as fm, TTFont(str(args.ours), lazy=True) as fo:
            cms, co = fm.getBestCmap(), fo.getBestCmap()
            for ch in args.chars:
                cp = ord(ch)
                if cp not in table or cp not in co:
                    continue
                g = fo["glyf"][co[cp]]
                g.recalcBounds(fo["glyf"])
                box = (g.xMin, g.yMin, g.xMax, g.yMax)
                sx, sy, (tx, ty) = factors(box, table[cp])
                flag = ""
                if sx == 1.0 or sy == 1.0:
                    flag = "  ⇐ 该轴不缩放"
                print(f"  {ch} 现框 {box} 目标 {table[cp]} sx {sx:.3f} sy {sy:.3f}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
