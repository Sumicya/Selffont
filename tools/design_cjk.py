"""自研汉字字库的数据与装配：读 `design_cjk.bin`，按字重描边成轮廓。

数据由 `tools/maruko_skeleton.py` 从 Maruko Gothic（SIL OFL 1.1，固定提交 97e9dd4）的字形里量出来：
笔画中线 + **逐笔**半宽（同一字里每条笔画各量各的，300/400/500 三档各一次）。
母版只提供「中线」和「笔宽」两样原料；轮廓数、面积比这些**不再拿来跟自己比**
（见 `docs/design-principles.md` 2026-10-28 条）。

文件格式（小端，顺序读）：
    SFCJ3 + uint32 字数 + uint8 档数
    每条记录：uint32 码位, uint8 笔画数
        每笔：uint8 标志（bit0 = 闭合环）, uint16 段数,
              3×uint16 该笔在 300/400/500 三档下的半宽×100, 2×int16 首段起点×10
            每段：6 个 int16 = 3 个控制点 (x*10, y*10)，起点恒等于上一段终点

也认旧格式 SFCJ2（整字一个半宽），过渡期用固定比例摊到三档。
"""
from __future__ import annotations

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "design_cjk.bin"
MAGIC = b"SFCJ3"
LEGACY_MAGIC = b"SFCJ2"
WEIGHTS = (300, 400, 500)

_CACHE: dict[int, dict] | None = None


def load(path: Path | None = None) -> dict[int, dict]:
    """码位 → {"strokes": [{"closed", "hw": {档: 半宽} 或 数值, "segs": [...]}]}。"""
    global _CACHE
    if path is None and _CACHE is not None:
        return _CACHE
    source = Path(path) if path else DATA
    if not source.exists():
        raise FileNotFoundError(f"汉字字库数据不存在：{source}")
    raw = source.read_bytes()
    if raw[:5] == MAGIC:
        out = _load3(raw)
    elif raw[:5] == LEGACY_MAGIC:
        out = _load2(raw)
    else:
        raise ValueError(f"汉字字库数据魔数不符：{source}")
    blanks = blank_characters()
    if blanks:
        # 空白字符（空格 / 不断行空格 / 全角空格 …）在母版里没有轮廓，取笔管线抓不到。
        # 不补的话，字件缺这些码位，系统逐字回退到别的字库——空格宽度跟着换家，
        # 行宽与断行位置全变。这里按母版的 advance 补成空字形（零条笔画）。
        for codepoint in blanks:
            if codepoint in out:
                continue
            out[codepoint] = {"strokes": [], "hw": 0.0}
    excluded = excluded_codepoints()
    if excluded:
        out = {cp: glyph for cp, glyph in out.items() if cp not in excluded}
    if path is None:
        _CACHE = out
    return out


EXCLUDE = Path(__file__).with_name("design_cjk_exclude.txt")
BLANK = Path(__file__).with_name("design_cjk_blank.txt")
DEFAULT_ADVANCE = 1000


def blank_characters() -> dict[int, int]:
    """码位 → 占位宽度：母版里**没有轮廓**的字符（空格一类），补成空字形用。

    这里只认码位，不认宽度——宽度由 `cjk_vf.advance_of` 按规则自算，
    整表搬运别人的 advance 属于抄袭，不是覆盖。
    """
    if not BLANK.exists():
        return {}
    out = {}
    for line in BLANK.read_text().splitlines():
        body = line.split("#", 1)[0].strip()
        if not body:
            continue
        try:
            out[int(body, 16)] = DEFAULT_ADVANCE
        except ValueError:
            continue
    return out


def advance_widths() -> dict[int, int]:
    """码位 → advance 宽度（从母版量的）。

    CJK 一律 1000，但空格 280、`a` 535、`A` 653、`1` 383——全写成 1000 的话空格会变成
    一个全角空、拉丁和数字被摊开。这个字件排在主字体之前，这些字符本来会被它接走。
    """
    if not ADVANCE.exists():
        return {}
    raw = ADVANCE.read_bytes()
    if raw[:4] != b"SFCA":
        raise ValueError(f"字宽数据魔数不符：{ADVANCE}")
    count = struct.unpack_from("<I", raw, 4)[0]
    out = {}
    pos = 8
    for _ in range(count):
        codepoint, advance = struct.unpack_from("<IH", raw, pos)
        pos += 6
        out[codepoint] = advance
    return out


def excluded_codepoints() -> frozenset[int]:
    """结构体检刷下来的字（见 tools/qa_glyphs.py）。

    宁可缺字回退系统字体，也不发一个实心口或黑团——缺字只是回到别的字库，
    发一个坏字是整行都难看。
    """
    if not EXCLUDE.exists():
        return frozenset()
    out = set()
    for line in EXCLUDE.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            out.add(int(line, 16))
        except ValueError:
            continue
    return frozenset(out)


def _load3(raw: bytes) -> dict[int, dict]:
    count = struct.unpack_from("<I", raw, 5)[0]
    nweight = raw[9]
    weights = WEIGHTS[:nweight]
    out: dict[int, dict] = {}
    pos = 10
    for _ in range(count):
        cp, nstroke = struct.unpack_from("<IB", raw, pos)
        pos += 5
        strokes = []
        for _ in range(nstroke):
            flag, nseg = struct.unpack_from("<BH", raw, pos)
            pos += 3
            hws = struct.unpack_from("<" + "H" * nweight, raw, pos)
            pos += 2 * nweight
            start = struct.unpack_from("<2h", raw, pos)
            pos += 4
            segs = []
            for _ in range(nseg):
                v = struct.unpack_from("<6h", raw, pos)
                pos += 12
                segs.append([(start[0] / 10.0, start[1] / 10.0), (v[0] / 10.0, v[1] / 10.0),
                             (v[2] / 10.0, v[3] / 10.0), (v[4] / 10.0, v[5] / 10.0)])
                start = v[4:]
            strokes.append({"closed": bool(flag & 1),
                            "hw": {w: h / 100.0 for w, h in zip(weights, hws)}, "segs": segs})
        out[cp] = {"strokes": strokes}
    if pos != len(raw):
        raise ValueError(f"汉字字库数据长度不符：读到 {pos}，文件 {len(raw)}")
    return out


def _load2(raw: bytes) -> dict[int, dict]:
    """旧格式：整字一个半宽。三档按实测的中位比例摊开（0.93 / 1.00 / 1.07）。"""
    count = struct.unpack_from("<I", raw, 5)[0]
    out: dict[int, dict] = {}
    pos = 9
    for _ in range(count):
        cp, hw, nstroke = struct.unpack_from("<IHH", raw, pos)
        pos += 8
        half = hw / 100.0
        strokes = []
        for _ in range(nstroke):
            flag, nseg = struct.unpack_from("<BH", raw, pos)
            pos += 3
            start = struct.unpack_from("<2h", raw, pos)
            pos += 4
            segs = []
            for _ in range(nseg):
                v = struct.unpack_from("<6h", raw, pos)
                pos += 12
                segs.append([(start[0] / 10.0, start[1] / 10.0), (v[0] / 10.0, v[1] / 10.0),
                             (v[2] / 10.0, v[3] / 10.0), (v[4] / 10.0, v[5] / 10.0)])
                start = v[4:]
            strokes.append({"closed": bool(flag & 1),
                            "hw": {300: half * 0.93, 400: half, 500: half * 1.07}, "segs": segs})
        out[cp] = {"hw": half, "strokes": strokes}
    return out


def glyph(codepoint: int) -> dict | None:
    return load().get(codepoint)


def outline(glyph: dict):
    """笔画中线 → 轮廓（2×半宽描边、圆端头 + 圆转角），返回 pathops.Path。

    与 `tools/design_symbols.py::_stroked` 同一套几何：轮廓是中线和半径 hw 的圆的
    闵可夫斯基和，所以端头构造上就是半圆、拐角构造上就是圆弧。零长度段（T 字路口
    补的圆盘）在圆头描边下**就是一个圆**，不需要单独处理。
    """
    import pathops

    acc = pathops.Path()
    hw = glyph["hw"]
    for stroke in glyph["strokes"]:
        segs = stroke["segs"]
        p = pathops.Path()
        p.moveTo(*segs[0][0])
        for seg in segs:
            p.cubicTo(*seg[1], *seg[2], *seg[3])
        if stroke.get("closed"):
            p.close()
        p.stroke(2 * hw, pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4)
        p.convertConicsToQuads(0.1)
        acc.addPath(p)
    acc.simplify(fix_winding=True, keep_starting_points=False)
    return acc

# ---------------------------------------------------------------- 可变字体用的固定拓扑描边

SAMPLE_PER_SEG = 6      # 每段贝塞尔取几个中线点（三档共用，只有偏移量不同）
ARC_STEPS = 6           # 圆端头半圆取几个点


def _seg_point(seg, t):
    p0, p1, p2, p3 = seg
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def _tangent(pts, i):
    a = pts[max(0, i - 1)]
    b = pts[min(len(pts) - 1, i + 1)]
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = (dx * dx + dy * dy) ** 0.5 or 1.0
    return dx / n, dy / n


def _centerline(segs):
    """贝塞尔段 → 等参数中线点列（点数只由段数决定，与该笔粗细无关）。"""
    pts = []
    for seg in segs:
        for k in range(SAMPLE_PER_SEG):
            pts.append(_seg_point(seg, k / SAMPLE_PER_SEG))
    pts.append(_seg_point(segs[-1], 1.0))
    return pts


def _round_cap(center, angle_from, half, steps):
    """半圆端头：从 angle_from 起**顺时针**扫 180°，只返回中间的点。

    方向不能反：端头必须朝笔画的「前方」凸出去。写反的话半圆绕到笔画背后，
    收笔处就凹成一个 V 形缺口（自测图里一眼可见）。
    """
    import math
    return [(center[0] + half * math.cos(angle_from - math.pi * k / steps),
             center[1] + half * math.sin(angle_from - math.pi * k / steps)) for k in range(1, steps)]


def _area(ring):
    """有向面积：负 = 顺时针（nonzero 下环内 winding +1）。"""
    total = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _as_cw(ring):
    return ring if _area(ring) <= 0 else ring[::-1]


def _as_ccw(ring):
    return ring if _area(ring) >= 0 else ring[::-1]


def _offset_ring(axis, normals, half, side):
    return [(axis[i][0] + side * normals[i][0] * half, axis[i][1] + side * normals[i][1] * half)
            for i in range(len(axis))]


def stroke_contours(stroke, weight, glyph=None):
    """一笔 → 一条闭合轮廓：左边界 → 终点半圆 → 右边界倒序 → 起点半圆。

    一笔一环，走一整圈，winding 恒为 +1。这样多笔重叠处 winding 相加（nonzero 规则下
    仍然填实），所以交叉口天然实心，不需要逐笔做并集——**这正是可变字体能做的原因**：
    并集会改变点数，而「每笔一环」的点数只由中线采样数决定，三档完全一致。

    点数只由中线采样数决定，与半宽无关。
    """
    segs = stroke["segs"]
    if not segs:
        return []
    half = stroke_half(stroke, glyph or {}, weight)
    axis = _centerline(segs)
    if len(axis) < 2:
        return []
    n = len(axis)
    # 切向必须平滑：笔画末端常有一小段急转，前后切线一翻向，偏移环就在内侧自交，
    # 交点处 winding 变成 0，描出来是一个白色月牙（自测图里一眼可见）。
    # 这里只改「方向」不改点数——切向只由轴线决定，与半宽无关，三档仍然同构。
    tangents = []
    for i in range(n):
        tx, ty = _tangent(axis, i)
        if tangents:
            px, py = tangents[-1]
            if tx * px + ty * py < 0.5:      # 夹角超过 60°：判为抖动，沿用前一个方向
                tx, ty = px, py
        tangents.append((tx, ty))
    normals = [(-ty, tx) for tx, ty in tangents]   # 左法向
    left = _offset_ring(axis, normals, half, 1.0)
    right = _offset_ring(axis, normals, half, -1.0)
    if stroke.get("closed"):
        # 闭合环（口/日/田 的外圈）：**两条**轮廓——外圈顺时针、内圈逆时针，
        # nonzero 下内圈正好抵消成空心。
        # 不能拼成「一条带缝的环」：那样缝上的两个点在三档共线合并时会被当成多余点删掉，
        # 一环就退化成顺着外圈跑完再顺着内圈跑的环，孔被填实（回/目 实测如此）。
        # 也不能假定 left 一定是外圈：骨架环的方向取决于分段顺序，回 的内口就是反着走的，
        # 于是内口的外环成了 +1，孔被填成一小团墨。按面积大小定内外，再按面积正负定方向。
        outer, inner = (left, right) if abs(_area(left)) >= abs(_area(right)) else (right, left)
        return [_as_cw(outer), _as_ccw(inner)]
    import math
    # 终点端头：从 left[-1]（左法向角）顺时针扫到 right[-1]（右法向角），凸向笔画前方。
    end = _round_cap(axis[-1], math.atan2(normals[-1][1], normals[-1][0]), half, ARC_STEPS)
    # 起点端头：从 right[0]（左法向 +180°）顺时针扫到 left[0]，凸向笔画后方。
    start = _round_cap(axis[0], math.atan2(normals[0][1], normals[0][0]) + math.pi, half, ARC_STEPS)
    return [_as_cw(left + end + right[::-1] + start)]


def stroke_contour(stroke, weight, glyph=None):
    got = stroke_contours(stroke, weight, glyph)
    return got[0] if got else []


# 旧数据（SFCJ2）只有整字一个半宽。比例来自 33,944 字逐笔配对的实测中位：
# 三档母版的笔画厚度比是 0.60 : 1.00 : 1.45（`一` 的扫描线厚度 20/33/50 单位），
# 早先那个 0.93 / 1.07 是照着旧的静态两档蒙的，作废。
_LEGACY_RATIO = {300: 0.60, 400: 1.0, 500: 1.45}


def stroke_half(stroke, glyph, weight):
    """取这一笔在该档的半宽：优先逐笔三档数据，缺了退回整字半宽 × 档位比例。"""
    hw = stroke.get("hw")
    if isinstance(hw, dict) and hw:
        return float(hw.get(weight) or hw.get(400) or next(iter(hw.values())))
    base = hw if isinstance(hw, (int, float)) else glyph.get("hw", 31.0)
    return float(base) * _LEGACY_RATIO[weight] / _LEGACY_RATIO[400]


def outline_points(glyph, weight):
    """一个字 → [轮廓点列]，点数在 300/400/500 三档之间一一对应。"""
    rings = []
    for stroke in glyph["strokes"]:
        rings.extend(stroke_contours(stroke, weight, glyph))
    return [c for c in rings if len(c) >= 3]


# ---------------------------------------------------------------- 共线点合并

SIMPLIFY_TOL = 1.0      # 字身单位：1000 单位 em 的千分之一，任何字号都看不出来（400 字实测形状面积差 <0.1%）


def _off_line(a, b, c):
    """点 c 到线段 ab 的距离。"""
    ax, ay = a
    bx, by = b
    cx, cy = c
    dx, dy = bx - ax, by - ay
    L = (dx * dx + dy * dy) ** 0.5
    if L < 1e-9:
        return ((cx - ax) ** 2 + (cy - ay) ** 2) ** 0.5
    return abs(dx * (cy - ay) - dy * (cx - ax)) / L


def _dp_keep(pts, tol):
    """闭合环的 Douglas–Peucker：返回保留标记。被删的点离保留弦线都不到 tol。"""
    n = len(pts)
    keep = [False] * n
    ax, ay = pts[0]
    j = max(range(n), key=lambda i: (pts[i][0] - ax) ** 2 + (pts[i][1] - ay) ** 2)
    keep[0] = keep[j] = True
    stack = [(0, j), (j, n)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        pa, pb = pts[a % n], pts[b % n]
        best, bi = -1.0, None
        for k in range(a + 1, b):
            d = _off_line(pa, pb, pts[k % n])
            if d > best:
                best, bi = d, k
        if bi is not None and best > tol:
            keep[bi % n] = True
            stack.append((a, bi))
            stack.append((bi, b))
    return keep


def outline_points_all(glyph, weights=None):
    """一个字 → {档: [轮廓点列]}，三档**共用一套点**，且已经合并掉共线点。

    为什么要合并：固定拓扑描边会沿每条直线笔画留下一串必在直线上的点——一横 24 个点里
    22 个是多余的。合并掉之后 glyf 和 gvar 都按点数线性变小（实测 400 字从 2.2 KB/字
    降到 1.2 KB/字），形状一个像素不动：判据是三个字重里都离弦线不到 0.5 单位。

    用 Douglas–Peucker 而不是「逐点看邻居」：后者每一步误差都合格，误差却会一路累积，
    一个圆角小环能被啃成一条斜线（回 的内口实测面积掉了 30%）。DP 的保距是对整环的。
    三档各算一次取**并集**，三档点仍一一对应，保距也同时对三档成立。
    """
    weights = tuple(weights or WEIGHTS)
    rings = {w: outline_points(glyph, w) for w in weights}
    if len({len(rings[w]) for w in weights}) != 1:
        return rings        # 点数本来就不一致，交给调用方报错
    out = {}
    result = []
    for ri, ring0 in enumerate(rings[weights[0]]):
        n = len(ring0)
        if n <= 4:
            result.append(list(range(n)))
            continue
        keep = [False] * n
        for w in weights:
            for i, flag in enumerate(_dp_keep(rings[w][ri], SIMPLIFY_TOL)):
                keep[i] = keep[i] or flag
        result.append([i for i in range(n) if keep[i]])
    for w in weights:
        out[w] = [[ring[i] for i in keep] for ring, keep in zip(rings[w], result)]
    return out
