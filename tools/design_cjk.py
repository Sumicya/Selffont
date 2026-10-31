"""自研汉字字库的数据与装配：读 `design_cjk.bin`，按字重描边成轮廓。

数据由 `tools/maruko_skeleton.py` 从 Maruko Gothic（SIL OFL 1.1，固定提交 97e9dd4）的字形里量出来：
笔画中线 + **逐笔**半宽（同一字里每条笔画各量各的，300/400/500 三档各一次）。
母版只提供「中线」和「笔宽」两样原料；轮廓数、面积比这些**不再拿来跟自己比**
（见 `docs/design-principles.md` 2026-10-28 条）。

文件格式（小端，顺序读）：
    SFCJ5 + uint32 字数 + uint8 档数
    每条记录：uint32 码位, uint16 笔画数
        每笔：uint8 标志（bit0 = 闭合环）, uint16 段数,
              3×uint16 该笔在 300/400/500 三档下的半宽×100, 2×int16 首段起点×10,
              uint16 剖面点数, 每点 uint8（该点半宽 ÷ 该笔 400 档半宽 ×128）,
            每段：6 个 int16 = 3 个控制点 (x*10, y*10)，起点恒等于上一段终点

为什么笔画数从 uint8 换成 uint16：实心符号走面填（扫描行胶囊）时，一个 `㉎` 这样的
方框图要一百多条胶囊，装不进 255。旧格式 SFCJ4 / SFCJ3 / SFCJ2 仍能读，只是不再写。

SFCJ5 在 SFCJ4 的每笔记录里多了一段**逐点半宽剖面**（uint16 点数 + 每点 uint8，
值是「该点半宽 ÷ 该笔 400 档半宽」×128）。为什么要有：母版的笔画不是等宽的，
同一条中线上的粗细从 0.7 倍变到 1.5 倍很常见（`暑` 的长撇实测 30.6 / 25.0 / 27.3 /
24.0 / 24.0）。只存一个中位数，粗的地方画细、细的地方画粗，2026-10-29 主人圈出的
四处「多墨 1–4%、缺墨却是 2–10 倍」正是这个两边不讨好。剖面只乘比例、不加点数，
300/400/500 三档的点数仍然一一对应（可变字体的硬约束）。
"""
from __future__ import annotations

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "design_cjk.bin"
MAGIC = b"SFCJ5"
FOUR_MAGIC = b"SFCJ4"
OLD_MAGIC = b"SFCJ3"
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
        out = _load5(raw)
    elif raw[:5] == FOUR_MAGIC:
        out = _load4(raw)
    elif raw[:5] == OLD_MAGIC:
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
    # `design_cjk.bin` 是「环+尾」修复之前抽出来的，重新全量抽取要三个多小时
    # （0.35 s/字 × 33,931 字），所以先按提取器的同一条规则在这里拆开。下次全量重抽
    # 之后这一步自动变成空操作：拆过的环 `closed=True`，不会再命中。
    from maruko_skeleton import split_ring_tail
    for glyph in out.values():
        if glyph.get("strokes"):
            glyph["strokes"], _ = split_ring_tail(glyph["strokes"])
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


def _load5(raw: bytes) -> dict[int, dict]:
    """当前格式：笔画数 uint16 + 每笔一段逐点半宽剖面（相对 400 档半宽的倍数 ×128）。"""
    count = struct.unpack_from("<I", raw, 5)[0]
    nweight = raw[9]
    weights = WEIGHTS[:nweight]
    out: dict[int, dict] = {}
    pos = 10
    for _ in range(count):
        cp, nstroke = struct.unpack_from("<IH", raw, pos)
        pos += 6
        strokes = []
        for _ in range(nstroke):
            flag, nseg = struct.unpack_from("<BH", raw, pos)
            pos += 3
            hws = struct.unpack_from("<" + "H" * nweight, raw, pos)
            pos += 2 * nweight
            start = struct.unpack_from("<2h", raw, pos)
            pos += 4
            nprof = struct.unpack_from("<H", raw, pos)[0]
            pos += 2
            prof = [v / 128.0 for v in raw[pos:pos + nprof]]
            pos += nprof
            segs = []
            for _ in range(nseg):
                v = struct.unpack_from("<6h", raw, pos)
                pos += 12
                segs.append([(start[0] / 10.0, start[1] / 10.0), (v[0] / 10.0, v[1] / 10.0),
                             (v[2] / 10.0, v[3] / 10.0), (v[4] / 10.0, v[5] / 10.0)])
                start = v[4:]
            stroke = {"closed": bool(flag & 1),
                      "hw": {w: h / 100.0 for w, h in zip(weights, hws)}, "segs": segs}
            if prof:
                stroke["prof"] = prof
            strokes.append(stroke)
        out[cp] = {"strokes": strokes}
    if pos != len(raw):
        raise ValueError(f"汉字字库数据长度不符：读到 {pos}，文件 {len(raw)}")
    return out


def _load4(raw: bytes) -> dict[int, dict]:
    """旧格式：笔画数是 uint16（面填的胶囊一格里能有一百多条），没有逐点剖面。"""
    count = struct.unpack_from("<I", raw, 5)[0]
    nweight = raw[9]
    weights = WEIGHTS[:nweight]
    out: dict[int, dict] = {}
    pos = 10
    for _ in range(count):
        cp, nstroke = struct.unpack_from("<IH", raw, pos)
        pos += 6
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


def write(glyphs: dict[int, dict], path: Path | None = None) -> int:
    """把「码位 → 笔画」整份写成 SFCJ5，返回字节数。

    只写 300/400/500 三档（缺的档按 400 补），逐点剖面缺就写 0 点（= 等宽笔）。
    剖面存的是「该点半宽 ÷ 该笔 400 档半宽」的倍数，量化到 1/128：`暑` 的 26 单位
    半宽下分辨率 0.2 单位，比要修的 1–2 单位误差细一个数量级，一个点占 1 字节。
    """
    target = Path(path) if path else DATA
    items = sorted(glyphs.items())
    out = bytearray(MAGIC)
    out += struct.pack("<IB", len(items), len(WEIGHTS))
    for cp, glyph in items:
        strokes = glyph.get("strokes") or []
        out += struct.pack("<IH", cp, len(strokes))
        for stroke in strokes:
            segs = stroke.get("segs") or []
            hw = stroke.get("hw")
            if not isinstance(hw, dict):
                hw = {w: float(hw or glyph.get("hw") or 1.0) for w in WEIGHTS}
            hws = []
            for w in WEIGHTS:
                v = hw.get(w) or hw.get(400) or 1.0
                hws.append(max(1, min(65535, int(round(float(v) * 100)))))
            start = segs[0][0] if segs else (0.0, 0.0)
            prof = stroke.get("prof") or []
            if len(prof) != len(segs) * SAMPLE_PER_SEG + 1:
                prof = []
            out += struct.pack("<BH", 1 if stroke.get("closed") else 0, len(segs))
            out += struct.pack("<" + "H" * len(WEIGHTS), *hws)
            out += struct.pack("<2h", int(round(start[0] * 10)), int(round(start[1] * 10)))
            out += struct.pack("<H", len(prof))
            out += bytes(max(1, min(255, int(round(float(v) * 128)))) for v in prof)
            prev = start
            for seg in segs:
                out += struct.pack("<6h", *[int(round(c * 10)) for c in seg[1]],
                                   *[int(round(c * 10)) for c in seg[2]],
                                   *[int(round(c * 10)) for c in seg[3]])
                prev = seg[3]
    target.write_bytes(bytes(out))
    return len(out)


def rewrite_half_widths(measured: dict[int, list[float]], path: Path | None = None) -> tuple[int, int]:
    """把重测的 400 档半宽原地写回数据文件，返回（改动字数, 改动笔数）。

    为什么要重测：旧数据里「一笔多宽」是取笔时用**横截面行走**量的——沿法向一直走到
    墨迹边界为止，上限是 2×整字半宽。密排字里两条笔画之间只隔十来个单位，行走会直接
    跨过白缝量到邻笔的另一侧，于是整字每一笔都被量成半宽 40–56（`叠` 29 笔存值中位
    52.1，母版同一批横截面的中位只有 21）。画出来就是黑团，字腔被糊掉。

    重测改用**距离变换**：字形按 1 单位 = 1 像素栅格化，沿中轴取样，取骨架上每点到
    背景距离的中位数。这个量在并集处只会被「最近的空隙」压低，不会被邻笔撑大——正是
    描边时要的那个半径。

    只改 400 档的绝对值；300/500 档按原值与 400 档的比例跟着走：三档之间本来只差
    笔画粗细，比例是母版实测出来的，重测要校正的是「同一笔被量胖」，不是三档关系。
    `measured` 里没有的码位、以及实测落在骨架外的笔（值为 None）保持原样。
    """
    source = Path(path) if path else DATA
    raw = bytearray(source.read_bytes())
    version = bytes(raw[:5])
    if version not in (MAGIC, FOUR_MAGIC):
        raise ValueError(f"只有 SFCJ4 / SFCJ5 格式支持重写半宽：{source}")
    has_profile = version == MAGIC
    count = struct.unpack_from("<I", raw, 5)[0]
    nweight = raw[9]
    weights = WEIGHTS[:nweight]
    if 400 not in weights:
        raise ValueError(f"数据文件里没有 400 档，无法重测：{source}")
    at400 = weights.index(400)
    pos = 10
    glyphs_changed = strokes_changed = 0
    for _ in range(count):
        cp, nstroke = struct.unpack_from("<IH", raw, pos)
        pos += 6
        wanted = measured.get(cp)
        changed = 0
        for index in range(nstroke):
            flag, nseg = struct.unpack_from("<BH", raw, pos)
            pos += 3
            field = pos
            hws = struct.unpack_from("<" + "H" * nweight, raw, field)
            # 布局必须与 `_load5` 逐字节一致：hw → start(4) → 剖面长度(2) → 剖面 → 段。
            # 上一版这里把段写在剖面之前（`2*nweight + 4 + 12*nseg` 再读剖面），SFCJ5 一有
            # 剖面就会越界——2026-10-31 重测字点半径时直接 struct.error 崩在读长度那一步。
            pos += 2 * nweight + 4
            if has_profile:
                pos += 2 + struct.unpack_from("<H", raw, pos)[0]
            pos += 12 * nseg
            if not wanted or index >= len(wanted) or wanted[index] is None:
                continue
            old = hws[at400] / 100.0
            new = wanted[index]
            if old <= 0 or new <= 0:
                continue
            ratio = new / old
            values = [max(1, min(65535, int(round(v * ratio)))) for v in hws]
            struct.pack_into("<" + "H" * nweight, raw, field, *values)
            changed += 1
        if changed:
            glyphs_changed += 1
            strokes_changed += changed
    if pos != len(raw):
        raise ValueError(f"数据文件长度不符：读到 {pos}，文件 {len(raw)}")
    source.write_bytes(bytes(raw))
    return glyphs_changed, strokes_changed


def glyph(codepoint: int) -> dict | None:
    return load().get(codepoint)


# ---------------------------------------------------------------- 可变字体用的固定拓扑描边

SAMPLE_PER_SEG = 6      # 数据里每段贝塞尔存几个剖面值（SFCJ5；与描边采样无关）
ARC_STEPS = 9           # 圆端头半圆取几个点（半径 28 时弦高 0.55 单位，6 点时是 1.9）
CHORD_TOL = 0.10        # 描边的中间点弦高误差（字体单位）；这是**拟合用的密点**，不是输出点
STATION_STEP = 8.0      # 中间点最大弧长间距（字体单位）：间距太大就估不出曲率
FAIR_UNITS = 18.0       # 半宽剖面的低通尺度（字体单位）：比它更短的起伏判为栅格噪声
PROFILE_TOL = 0.015     # 剖面（相对半宽）一维 DP 容差：1.5% ≈ 半宽 28 上的 0.42 单位


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



def _seg_d(seg, t):
    """三次贝塞尔在 t 处的切向（解析导数）。"""
    p0, p1, p2, p3 = seg
    u = 1.0 - t
    dx = 3 * u * u * (p1[0] - p0[0]) + 6 * u * t * (p2[0] - p1[0]) + 3 * t * t * (p3[0] - p2[0])
    dy = 3 * u * u * (p1[1] - p0[1]) + 6 * u * t * (p2[1] - p1[1]) + 3 * t * t * (p3[1] - p2[1])
    n = (dx * dx + dy * dy) ** 0.5
    return (1.0, 0.0) if n < 1e-9 else (dx / n, dy / n)


def _stations(segs):
    """每段按「弦高误差 ≤ CHORD_TOL」定采样数。只由几何决定，三档共用。"""
    import math

    counts = []
    for seg in segs:
        p0, p1, p2, p3 = seg
        d = max(_off_line(p0, p3, p1), _off_line(p0, p3, p2))
        L = 0.0
        for a, b in zip(seg, seg[1:]):
            L += math.hypot(a[0] - b[0], a[1] - b[1])
        by_len = int(math.ceil(L / STATION_STEP))
        by_curve = int(math.ceil(math.sqrt(max(d, 1e-9) * 0.75 / CHORD_TOL)))
        counts.append(min(max(by_len, by_curve), 48))
    return counts


def _dense_axis(stroke):
    """中线密采样（按弦高误差），返回 (点列, (段号, 参数) 列, 切向列)。结果缓存在笔画上。

    缓存的意义：三档要画同一笔画三次，采样只需算一次；而且**三档必须用同一套采样点**，
    否则 gvar 的点对不上。
    """
    cached = stroke.get("_dense")
    if cached is not None:
        return cached
    segs = stroke["segs"]
    pts, ts, tans = [], [], []
    for j, (seg, n) in enumerate(zip(segs, _stations(segs))):
        for k in range(n):
            t = k / n
            pts.append(_seg_point(seg, t))
            ts.append((j, t))
            tans.append(_seg_d(seg, t))
    pts.append(_seg_point(segs[-1], 1.0))
    ts.append((len(segs) - 1, 1.0))
    tans.append(_seg_d(segs[-1], 1.0))
    # 段与段之间是 G1：交界处把两侧切向平均一次，去掉浮点差造成的抖动
    for i in range(1, len(ts)):
        if ts[i][1] == 0.0 and ts[i - 1][0] == ts[i][0] - 1:
            ax, ay = tans[i - 1]
            bx, by = tans[i]
            vx, vy = ax + bx, ay + by
            nn = (vx * vx + vy * vy) ** 0.5 or 1.0
            tans[i - 1] = tans[i] = (vx / nn, vy / nn)
    stroke["_dense"] = (pts, ts, tans)
    return stroke["_dense"]


def _fair(values, spacing, sigma_units, closed=False):
    """沿弧长做高斯低通：把骨架与距离变换带来的 1–2 单位起伏压掉。

    `spacing` 是**点与点之间的弧长**（不是坐标差），剖面是一维序列也能用。
    开放曲线的首末点原样保留：端头位置是量出来的，不能被抹动。
    """
    import numpy as _np
    from scipy.ndimage import gaussian_filter1d

    v = _np.asarray(values, float)
    if len(v) < 5 or spacing <= 0:
        return v
    sigma = sigma_units / spacing
    if sigma < 0.45:
        return v
    mode = "wrap" if closed else "nearest"
    out = gaussian_filter1d(v, sigma, axis=0, mode=mode)
    if not closed:
        out[0], out[-1] = v[0], v[-1]
    return out


def _polyline1d(values, tol):
    """一维 Douglas–Peucker：把剖面压成少数几个节点，再线性插值回来。

    剖面的抖动是「量出来的噪声」（距离变换 + u8 量化），不是设计。高斯低通会把真拐点
    一起削弱（`暑` 长撇 30.6→24.0 会被抹成缓坡），一维 DP 只删「离弦不到 tol 的点」，
    真的趋势拐点离弦远，删不掉。
    """
    n = len(values)
    if n < 3:
        return list(values)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        va, vb = values[a], values[b]
        span = b - a
        best, bi = 0.0, None
        for k in range(a + 1, b):
            v = va + (vb - va) * (k - a) / span
            d = abs(values[k] - v)
            if d > best:
                best, bi = d, k
        if bi is not None and best > tol:
            keep[bi] = True
            stack.append((a, bi))
            stack.append((bi, b))
    idx = [i for i in range(n) if keep[i]]
    import numpy as _np
    return list(_np.interp(range(n), idx, [values[i] for i in idx]))


def _spacing(points):
    """点列的中位间距（去掉重合点）。"""
    import numpy as _np

    p = _np.asarray(points, float)
    if len(p) < 2:
        return 0.0
    seg = _np.hypot(*_np.diff(p, axis=0).T)
    seg = seg[seg > 1e-9]
    return float(_np.median(seg)) if len(seg) else 0.0


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


def _offset_ring(axis, normals, halves, side, ref_half=None):
    """轴线一侧的偏移环。`halves` 是逐点半宽。

    **外角补圆弧**：偏移线在凸侧会自交出一个尖楔，母版是「中线与半径 half 的圆的
    闵可夫斯基和」，那里应当是半径 half 的圆弧。圆弧按弦高误差采样，不用固定角度
    ——固定 9° 在半径 28 上仍有 0.3 单位的折面，放大就是一圈小棱。
    内侧不补：弧会朝笔画里凹，等于把里角挖掉一块；让两段偏移线相交即可。
    """
    import math

    n = len(axis)
    out = []
    for i in range(n):
        x, y = axis[i]
        nx, ny = normals[i]
        out.append((x + side * nx * halves[i], y + side * ny * halves[i]))
        if i + 1 >= n:
            continue
        mx, my = normals[i + 1]
        cross = nx * my - ny * mx
        if side * cross >= 0.0:
            continue
        dot = max(-1.0, min(1.0, nx * mx + ny * my))
        turn = abs(math.atan2(cross, dot))
        if turn < math.radians(6.0):
            continue
        # 补弧的点数必须与字重无关（三档点数要一一对应），半径用 400 档的参考值
        r = ref_half if ref_half else 0.5 * (halves[i] + halves[i + 1])
        step = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - CHORD_TOL / max(r, CHORD_TOL))))
        steps = max(1, min(24, int(math.ceil(turn / max(step, 1e-3)))))
        d = math.atan2(cross, dot)
        a0 = math.atan2(ny, nx)
        for k in range(1, steps):
            a = a0 + d * k / steps
            h = halves[i] + (halves[i + 1] - halves[i]) * k / steps
            out.append((x + side * h * math.cos(a), y + side * h * math.sin(a)))
    return out


def _zero_length(stroke) -> bool:
    """零长度笔：所有段的首末点重合，切向处处为零，单靠自己量不出形状。"""
    points = [pt for seg in stroke["segs"] for pt in seg]
    if not points:
        return True
    x0, y0 = points[0]
    return all(abs(x - x0) < 0.5 and abs(y - y0) < 0.5 for x, y in points)


def _centerline_points(stroke):
    return [p for seg in stroke["segs"] for p in seg]


def _covered(point, glyph, weight, own) -> bool:
    """这一点是不是**落在别的笔画身上**。

    骨架在交叉处会留下零长度笔当接点标记；这类笔不承载形状，画出来就是在交叉点盖一个
    半径 30 的圆盘——`日`、`暑` 这类字里圆盘正落在字腔上，把封闭的小方块填实，于是
    「孔少了」。但它跟 `.` `：` `·` `…` 的**字点**长得一模一样（也是一个零长度笔），
    不能一律不画：上一版就是一刀切，把所有字点全删了，`：` 整字变成空白。

    一刀切不成立，判据只能看**它是不是独立存在的墨**：点落在别的笔画的中线附近（到中线
    距离不超过那一笔的半宽），说明它是交叉口；离所有中线都远，说明它是母版里独立的一团
    圆墨，那就是字点，按半宽画圆。`·` `：` `…` 与 `日` 的交叉口在这条判据下分得干净。
    """
    px, py = point
    for other in glyph.get("strokes", []):
        if other is own or _zero_length(other):
            continue
        half = stroke_half(other, glyph, weight)
        for a, b in zip(_centerline_points(other), _centerline_points(other)[1:]):
            ax, ay = a
            bx, by = b
            dx, dy = bx - ax, by - ay
            length2 = dx * dx + dy * dy
            t = 0.0 if length2 < 1e-9 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
            qx, qy = ax + t * dx - px, ay + t * dy - py
            if qx * qx + qy * qy <= (half * 0.9) ** 2:
                return True
    return False


def _dot_contour(center, half):
    """零长度笔按字点画：固定 2×ARC_STEPS 个点的正多边形，三档只变半径。"""
    import math
    n = ARC_STEPS * 2
    ring = [(center[0] + half * math.cos(2 * math.pi * k / n),
             center[1] + half * math.sin(2 * math.pi * k / n)) for k in range(n)]
    return _as_cw(ring)


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
    if _zero_length(stroke):
        # 交叉口的接点标记：不画。独立的字点（`.` `·` `：`）按半宽画圆。
        # 判据只看 400 档：可变字体要求三档点数逐一相同，如果 300 档因为半宽小一点
        # 就把这个点判成「不画」，三档拓扑就对不上了（U+1E43 实测炸在构建期）。
        # 形状随档变、**有没有这个点**不随档变。
        if glyph is None or stroke_half(stroke, glyph, 400) < 1.0:
            return []
        center = stroke["segs"][0][0]
        if _covered(center, glyph, 400, stroke):
            return []
        return [_dot_contour(center, half)]
    # 中线按弦高误差密采样（三档共用同一套点），再沿弧长短程低通：
    # 栅格骨架带来的 1–2 单位起伏不抹掉，放大就是边上的「凹凸」。
    pts, ts, tans = _dense_axis(stroke)
    closed = bool(stroke.get("closed"))
    # 中线**不做低通**：它本来就是 splprep 拟合出的三次贝塞尔，在贝塞尔上按弦高采样
    # 得到的就是精确曲线。再抹一遍只会把钩、撇的曲率改掉（实测 XOR 反涨 15%）。
    # 抖动在剖面里，只低通剖面。
    axis = pts
    if len(axis) < 2:
        return []
    n = len(axis)
    normals = [(-ty, tx) for tx, ty in tans]
    # 逐点半宽剖面（SFCJ5）：值是相对该笔 400 档半宽的倍数。剖面本身也是量出来的，
    # 同样带栅格噪声，先按弧长低通再乘本档半宽。
    prof = stroke.get("prof")
    if prof and len(prof) == len(segs) * SAMPLE_PER_SEG + 1:
        raw = [prof[min(int((j + t) * SAMPLE_PER_SEG), len(prof) - 2)] * (1 - ((j + t) * SAMPLE_PER_SEG - int((j + t) * SAMPLE_PER_SEG)))
               + prof[min(int((j + t) * SAMPLE_PER_SEG) + 1, len(prof) - 1)] * ((j + t) * SAMPLE_PER_SEG - int((j + t) * SAMPLE_PER_SEG))
               for j, t in ts]
        faired = _fair(raw, _spacing(axis), FAIR_UNITS, closed)
        faired = _polyline1d(list(faired), PROFILE_TOL)
        halves = [float(v) * half for v in faired]
    else:
        halves = [half] * n
    ref_half = stroke_half(stroke, glyph or {}, 400)
    left = _offset_ring(axis, normals, halves, 1.0, ref_half)
    right = _offset_ring(axis, normals, halves, -1.0, ref_half)
    if closed:
        outer, inner = (left, right) if abs(_area(left)) >= abs(_area(right)) else (right, left)
        return [_as_cw(outer), _as_ccw(inner)]
    import math
    h_end = halves[-1]
    h_start = halves[0]
    end = _round_cap(axis[-1], math.atan2(normals[-1][1], normals[-1][0]), h_end, ARC_STEPS)
    start = _round_cap(axis[0], math.atan2(normals[0][1], normals[0][0]) + math.pi, h_start, ARC_STEPS)
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

SIMPLIFY_TOL = 6.0      # 字身单位：只是「曲线从哪起笔」的粗锚点；真拐角离弦几十单位，削不掉


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


def outline_curves(glyph, weights=None):
    """一个字 → ({档: [环点列]}, {档: [环 on/off 标志]})，是**真二次曲线**。

    与 `outline_points_all` 的区别只在最后一步：那个把点直接连成折线，这个把点拟合回
    曲线。三档点列同索引，拟合的段划分由 400 档的误差决定，所以三档点数与 on/off
    标志逐一相同——gvar 需要这个。
    """
    import curve_fit

    weights = tuple(weights or WEIGHTS)
    dense = {w: outline_points(glyph, w) for w in weights}
    if len({len(dense[w]) for w in weights}) != 1:
        return dense, {w: [[1] * len(r) for r in dense[w]] for w in weights}
    return curve_fit.fit_rings(dense, [[] for _ in dense[weights[0]]])


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
