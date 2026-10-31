"""量母版**真排**出来的邻字白，写成 `tools/kern_targets.bin`（字偶距的目标表）。

为什么要量「白」而不是抄母版的 GPOS：
  · 母版自己的字偶距值只对**它自己的字宽**成立。本字件的字宽是按本字墨迹自算的
    （`advance_of`），同一个 `Ay` 在母版里笔距 473、在本字件里 662，直接抄 −180
    会既不够也不对；
  · 真正决定观感的是**两个字形之间的白**，不是笔距。所以拿 HarfBuzz 把母版真排一遍
    （GPOS 生效），量出每一对的最小墨迹白，作为本字件要复现的目标；构建期再用本字
    自己的轮廓算出同样的最小白，两者相减就是字偶距。

量的口径必须与构建期**同一个尺**（否则两边比的是不同高度的墨迹）：
  · 同一张 y 网格 `cjk_vf.BAND_Y`、同样 48 条带、同样取每带最左/最右 x；
  · 同样取「两字都有墨的带」里的最小白（最窄处），不是平均、不是 bbox 相减。
  第一版字偶距失败就是因为换了一把尺（一律压到同一个绝对间隙），`HH`、`oo` 也被压到
  −30；这一版 `HH` 的目标白是 168、`oo` 是 96，只有母版自己压过的对（`Ay` 44、
  `AT` −3）才会被压。

只算 ASCII 可打印区（U+0020–U+007E）：这是本字件唯一逐对量过的区间；汉字是全角、
不参与字偶距，带音标的拉丁字母沿用侧距、不加字偶距。

输出格式（`kern_targets.bin`）：
    4 字节 magic `SFK1` + 95×95 个 int16（小端，行 = 前一个字，列 = 后一个字）
    −32768 表示「没有数据」（空格，或母版里缺这个字）。

运行需要 uharfbuzz（只在这个脚本里用，构建时不 import）：

    .venv/bin/python tools/kern_measure.py --master /path/maruko.ttf
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from cjk_vf import rings_from_pen, row_profile  # noqa: E402  同一把尺（1 单位一行）、同一个展开器

LOW, HIGH = 0x20, 0x7E
NONE = -32768
# 母版里有几个坏对（`W` `N` `U` 后面跟反引号）量出 −400 上下的白：那是母版自己的
# 数据错位，不是设计。收进来会让本字件跟着压出一串撞墨的字偶距，直接当没有数据。
IMPLAUSIBLE_LOW = -160
MAGIC = b"SFK1"


def _rings(glyphset, name):
    """一个字形拆成若干环：与构建期同一个展开器（`cjk_vf.rings_from_pen`）。"""
    from fontTools.pens.recordingPen import RecordingPen

    pen = RecordingPen()
    glyphset[name].draw(pen)
    return rings_from_pen(pen.value)


def measure(master: Path) -> np.ndarray:
    import uharfbuzz as hb
    from fontTools.ttLib import TTFont

    blob = hb.Blob.from_file_path(str(master))
    face = hb.Face(blob)
    font = hb.Font(face)
    font.scale = (face.upem, face.upem)
    tt = TTFont(str(master), lazy=True, recalcBBoxes=False)
    glyphset = tt.getGlyphSet()
    order = tt.getGlyphOrder()
    cmap = tt.getBestCmap()

    profiles = {}
    for cp in range(LOW, HIGH + 1):
        name = cmap.get(cp)
        if name is None:
            continue
        profiles[cp] = row_profile(_rings(glyphset, name))

    grid = np.full((HIGH - LOW + 1,) * 2, NONE, np.int16)
    for a in range(LOW, HIGH + 1):
        for b in range(LOW, HIGH + 1):
            if a not in profiles or b not in profiles:
                continue
            buf = hb.Buffer()
            buf.add_str(chr(a) + chr(b))
            buf.guess_segment_properties()
            hb.shape(font, buf, {"kern": True, "liga": True})
            if len(buf.glyph_positions) != 2:
                continue                       # 被合字改写过的对不量（ASCII 里不该有）
            pen = buf.glyph_positions[1].x_offset + buf.glyph_positions[0].x_advance
            _, right = profiles[a]
            left, _ = profiles[b]
            whites = pen + left - right
            whites = whites[~np.isnan(whites)]
            if len(whites) >= 20 and whites.min() > IMPLAUSIBLE_LOW:
                grid[a - LOW, b - LOW] = int(round(float(whites.min())))
    return grid


def main() -> int:
    ap = argparse.ArgumentParser(description="量母版真排的邻字白 → tools/kern_targets.bin")
    ap.add_argument("--master", required=True, type=Path, help="母版字体（Maruko Gothic）")
    ap.add_argument("--out", type=Path, default=ROOT / "kern_targets.bin")
    args = ap.parse_args()
    if not args.master.exists():
        print(f"母版不存在：{args.master}", file=sys.stderr)
        return 1
    grid = measure(args.master)
    data = grid.tobytes() if grid.dtype.byteorder in ("<", "=") else grid.byteswap().tobytes()
    args.out.write_bytes(MAGIC + data)
    known = int((grid != NONE).sum())
    print(f"{args.out}  {len(MAGIC) + len(data):,} B  有数据的对 {known:,} / {grid.size:,}")
    print(f"  白 区间 {grid[grid != NONE].min()} .. {grid[grid != NONE].max()}"
          "   网格：1 单位一行（逐行左右缘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
