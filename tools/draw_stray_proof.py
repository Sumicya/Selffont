#!/usr/bin/env python3
"""碎块证据图渲染器：docs/figures/ 里每张图的可复算来源。

为什么存在：罚篇二十九（2026-11-27，没图罚 5）认定「图在 /tmp 等于没图」。
图必须落盘进仓库、附 sha、并且**可重画**——不可重画的图是一次性图片，
可重画的图才是证据。本脚本就是重画通道。

窗口纪律（罚篇二十九 §4）：渲染窗口由数据定，不由直觉定。先 dump 目标
轮廓的 bbox，窗口 = bbox 外扩 20%。第一次渲染「谚」用 y[0,400] 看不到
y[-52,-3] 的碎块，就是窗口凭直觉定的后果。

用法：
    python tools/draw_stray_proof.py <修前.ttf> <修后.ttf> <字> [--out docs/figures]
输出两张 png 并打印 sha256 与字节数；把打印结果贴进回复即满足 §4 读证格式。
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drop_stray_ring as D  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def rings(path: str, ch: str):
    font = TTFont(path, fontNumber=0, lazy=False)
    glyph = font["glyf"][font.getBestCmap()[ord(ch)]]
    return D.rings_of(glyph)


def window(rs, pad=0.2):
    """窗口 = 全部轮廓 bbox 外扩 pad 比例。不接受手填。"""
    xs = [p[0] for r in rs for p in r]
    ys = [p[1] for r in rs for p in r]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    dx, dy = (x1 - x0) * pad, (y1 - y0) * pad
    return x0 - dx, y0 - dy, x1 + dx, y1 + dy


def panel(dr, rs, ox, oy, size, win, title, baseline=False):
    x0, y0, x1, y1 = win
    s = size / max(x1 - x0, y1 - y0)
    dr.rectangle([ox, oy, ox + (x1 - x0) * s, oy + (y1 - y0) * s], outline=(180, 180, 180))
    if baseline and y0 < 0 < y1:
        yb = oy + (y1 - 0) * s
        for xx in range(int(ox), int(ox + (x1 - x0) * s), 12):
            dr.line([xx, yb, xx + 6, yb], fill="red")
    for r in rs:
        dr.polygon([(ox + (p[0] - x0) * s, oy + (y1 - p[1]) * s) for p in r],
                   outline="black", fill=(225, 225, 225))
    dr.text((ox, oy - 18), title, fill="blue")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("ch")
    ap.add_argument("--out", default="docs/figures")
    args = ap.parse_args()

    rb, ra = rings(args.before, args.ch), rings(args.after, args.ch)
    # 窗口由**判据命中的碎块轮廓**的 bbox 外扩定，而不是整字 bbox：整字窗口会把
    # 基线以下那颗 50 单位的碎块缩成一个像素。修前字体上跑判据拿 kill 下标；
    # 判据没命中（例如字已修过）才退回整字 bbox。窗口永远来自数据，不来自直觉。
    from fontTools.ttLib import TTFont as _T
    gb = _T(args.before, fontNumber=0, lazy=False)["glyf"]
    gn = _T(args.before, fontNumber=0, lazy=False).getBestCmap()[ord(args.ch)]
    kill, _ = D.stray_rings(gb[gn])
    win = window([rb[i] for i in kill], pad=1.5) if kill else window(rb)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (960, 520), "white")
    dr = ImageDraw.Draw(img)
    panel(dr, rb, 20, 40, 440, win, f"修前 {args.ch} 轮廓{len(rb)} 窗口由bbox外扩20%定", True)
    panel(dr, ra, 500, 40, 440, win, f"修后 {args.ch} 轮廓{len(ra)} 同窗口", True)
    target = out / f"stray-proof-{args.ch}.png"
    img.save(target)

    blob = target.read_bytes()
    print(f"{target}  {len(blob)} B  sha256 {hashlib.sha256(blob).hexdigest()}")
    print(f"窗口 x[{win[0]:.0f},{win[2]:.0f}] y[{win[1]:.0f},{win[3]:.0f}]（修前 bbox 外扩 20%）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
