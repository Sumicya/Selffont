#!/usr/bin/env python3
"""把一个字形某一侧的墨迹往里收，其余不动。

用途：`A` 的右缘在**底部**才达到 xMax（顶部只有一半），所以 `AC` 的空白收不到
175 以下——kern 受限于「advance 不得小于墨宽」。这个脚本直接改轮廓：
把满足 `x > x_from` 的点按 `dy` 高度加权向左平移，越靠下移得越多。

不缩放、不动其他字形、不碰 advance。y 轴权重用平滑窗，避免折出硬角。

    .venv/bin/python tools/shrink_glyph_edge.py 入.ttf -o 出.ttf \
        --glyph A --from-x 500 --dx 60 --y-below 140
"""
from __future__ import annotations

import argparse
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--glyph", required=True)
    ap.add_argument("--from-x", type=float, required=True, help="只动 x 大于这个值的点")
    ap.add_argument("--dx", type=float, required=True, help="最大左移量（底部）")
    ap.add_argument("--y-below", type=float, required=True, help="这个高度以下才动")
    args = ap.parse_args()

    font = TTFont(args.source)
    glyf, hmtx = font["glyf"], font["hmtx"]
    gs = font.getGlyphSet()
    name = args.glyph
    if name not in glyf:
        raise SystemExit(f"没有字形 {name}")

    gl = glyf[name]
    gl.recalcBounds(glyf)
    x0, y0, x1, y1 = gl.xMin, gl.yMin, gl.xMax, gl.yMax
    print(f"{name}: 原 bbox x {x0}..{x1}  y {y0}..{y1}  adv {hmtx[name][0]}")

    rp = DecomposingRecordingPen(gs)
    gs[name].draw(rp)

    def shift(px, py):
        if px <= args.from_x or py >= args.y_below:
            return 0.0
        # 越靠下、越靠右，移得越多；两个方向都用平滑过渡，避免折角
        t_y = 1.0 - max(0.0, py - y0) / max(1.0, args.y_below - y0)   # 底部=1
        t_x = min(1.0, (px - args.from_x) / max(1.0, x1 - args.from_x))
        return -args.dx * (t_y ** 2) * (t_x ** 0.5)

    pen = TTGlyphPen(None)
    moved = 0
    for op, pts in rp.value:
        if op == "moveTo":
            p = pts[0]; d = shift(*p)
            if d: moved += 1
            pen.moveTo((p[0] + d, p[1]))
        elif op == "lineTo":
            p = pts[0]; d = shift(*p)
            if d: moved += 1
            pen.lineTo((p[0] + d, p[1]))
        elif op == "qCurveTo":
            new = []
            for p in pts:
                if p is None:
                    new.append(None); continue
                d = shift(*p)
                if d: moved += 1
                new.append((p[0] + d, p[1]))
            pen.qCurveTo(*new)
        elif op == "curveTo":
            raise SystemExit("出现三次曲线，本字体不该有")
        elif op == "closePath":
            pen.closePath()

    glyf[name] = pen.glyph()
    glyf[name].recalcBounds(glyf)
    newgl = glyf[name]
    # lsb 必须等于新 xMin，否则字心会偏
    hmtx[name] = (hmtx[name][0], int(round(newgl.xMin)))
    print(f"  动 {moved} 个控制点；新 bbox x {newgl.xMin}..{newgl.xMax}  "
          f"墨宽 {newgl.xMax - newgl.xMin}（原 {x1 - x0}）")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    font.save(args.output)
    print(f"写出 {args.output}（{args.output.stat().st_size:,} B）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
