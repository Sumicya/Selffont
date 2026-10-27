"""二创汉字字库的整块数据：读 `design_cjk.bin`，给构建脚本取字形。

数据从 Maruko（max32002/maruko-gothic@97e9dd4，SIL OFL 1.1）的骨架里量出来，
取笔规则见 `tools/maruko_skeleton.py` 与 `docs/design-principles.md`：笔画照母版原样取，
圆头描边，不做去钩、不自行加折。

文件格式（小端，定长，可 mmap 式顺序读，无需依赖）：
    b"SFCJ2" + uint32 字数
    每条记录：uint32 码位, uint16 半宽×100, uint16 笔画数
        每笔：uint8 标志（bit0 = 闭合环）, uint16 段数, 2 个 int16 = 首段起点
            每段：6 个 int16 = 3 个控制点 (x*10, y*10)，起点恒等于上一段终点

为什么不再用 Python 源码存：329 字时是 1.2 MB 源码还能忍，两万字就是 40 MB
源码、每次 import 都要编译一遍。二进制块 8 MB 左右，加载是几百毫秒。
"""
from __future__ import annotations

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "design_cjk.bin"
MAGIC = b"SFCJ2"

_CACHE: dict[int, dict] | None = None


def load(path: Path | None = None) -> dict[int, dict]:
    """码位 → {"hw": 半宽, "strokes": [{"closed": bool, "segs": [[(x, y) × 4], ...]}, ...]}"""
    global _CACHE
    if path is None and _CACHE is not None:
        return _CACHE
    source = Path(path) if path else DATA
    if not source.exists():
        raise FileNotFoundError(f"二创字库数据不存在：{source}")
    raw = source.read_bytes()
    if raw[:5] != MAGIC:
        raise ValueError(f"二创字库数据魔数不符：{source}")
    count = struct.unpack_from("<I", raw, 5)[0]
    out: dict[int, dict] = {}
    pos = 9
    for _ in range(count):
        cp, hw, nstroke = struct.unpack_from("<IHH", raw, pos)
        pos += 8
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
            strokes.append({"closed": bool(flag & 1), "segs": segs})
        out[cp] = {"hw": hw / 100.0, "strokes": strokes}
    if pos != len(raw):
        raise ValueError(f"二创字库数据长度不符：读到 {pos}，文件 {len(raw)}")
    if path is None:
        _CACHE = out
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
