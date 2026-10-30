"""出本轮证据图：拉丁间距与字偶距（只用最终字体文件 + FreeType 渲染，标签用本字库）。

一次性脚本，按规范不入库：图与字体同批生成，跑完即弃。

    .venv/bin/python work/evidence_latin.py work/fix11/static-400.ttf

为什么不能用 `ImageDraw.text` 整串落笔：PIL 不带 HarfBuzz（`getlength("Ay")` = 158.0，
正好是**没有**字偶距的 1135 × 0.14），整串画出来永远看不到字对咬合。这里用 HarfBuzz 取
每个字的笔位、再用 PIL 逐字贴上去——同一份 GPOS，看到的才是系统里看到的那一行。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import uharfbuzz as hb
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
POST = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "work/fix11/static-400.ttf"
PRE = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/w/prev_latin.ttf")
MASTER = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/tmp/w/maruko.ttf")
OUT = ROOT / "docs/evidence"
DATE = "2026-10-31"


class Line:
    """按 HarfBuzz 笔位逐字落笔的一行字。"""

    def __init__(self, path: Path, size: int):
        self.size = size
        self.pil = ImageFont.truetype(str(path), size)
        blob = hb.Blob.from_file_path(str(path))
        face = hb.Face(blob)
        self.font = hb.Font(face)
        self.upm = face.upem
        self.scale = size / self.upm
        self.font.scale = (self.upm, self.upm)

    def positions(self, text: str):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.font, buf, {"kern": True, "liga": False})
        out, x = [], 0
        for pos in buf.glyph_positions:
            out.append((x * self.scale, pos.x_offset * self.scale))
            x += pos.x_advance
        return out, x * self.scale

    def draw(self, image: Image.Image, text: str, x: float, baseline: float) -> float:
        pos, total = self.positions(text)
        for ch, (px, dx) in zip(text, pos):
            mask, off = self.pil.getmask2(ch, mode="L", anchor="ls")
            glyph = Image.frombytes("L", mask.size, bytes(mask))
            image.paste(0, (int(round(x + px + dx + off[0])), int(round(baseline + off[1]))), glyph)
        return total


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [("母版（对照）", MASTER), ("上一版", PRE), ("本版", POST)]
    label_font = ImageFont.truetype(str(POST), 26)
    small = ImageFont.truetype(str(POST), 20)

    # ① 三行对照：同一批字、同一字号、同一基线
    texts = ["Ay", "Ayden George", "Still Water", "Type", "How"]
    size, pad, gap, col = 130, 26, 46, 250
    blocks = {}
    for name, path in rows:
        line = Line(path, size)
        tiles = []
        for text in texts:
            width = int(line.positions(text)[1]) + 2 * pad
            tile = Image.new("L", (width, int(size * 1.85)), 255)
            line.draw(tile, text, pad, int(size * 1.38))
            tiles.append(tile)
        blocks[name] = tiles
    height = sum(max(t.height for t in blocks[n]) for n, _ in rows) + 30
    width = col + max(sum(t.width + gap for t in blocks[n]) for n, _ in rows)
    page = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(page)
    y = 0
    for name, _ in rows:
        draw.text((10, y + 66), name, font=label_font, fill=(90, 90, 90))
        x = col
        for tile in blocks[name]:
            page.paste(tile.convert("RGB"), (x, y))
            x += tile.width + gap
        y += max(t.height for t in blocks[name])
    page.save(OUT / f"{DATE}-拉丁-三行对照.png")

    # ② Ay 放大：字对到底有没有咬进去，看这一张
    size = 320
    tiles = []
    for name, path in rows:
        line = Line(path, size)
        width = int(line.positions("Ay")[1]) + 60
        tile = Image.new("L", (width, int(size * 1.6)), 255)
        line.draw(tile, "Ay", 30, int(size * 1.2))
        tiles.append((name, tile))
    width = sum(t.width + 80 for _, t in tiles) + 20
    height = max(t.height for _, t in tiles) + 46
    page = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(page)
    x = 20
    for name, tile in tiles:
        page.paste(tile.convert("RGB"), (x, 40))
        draw.text((x, 10), name, font=label_font, fill=(90, 90, 90))
        x += tile.width + 80
    draw.text((20, height - 24), "Ay @320px：母版靠 GPOS 把 y 咬进 A 的右腿（笔距 473、最小白 44）",
              font=small, fill=(120, 120, 120))
    page.save(OUT / f"{DATE}-Ay咬合.png")
    print("出图", *(p.name for p in sorted(OUT.glob(f"{DATE}-*.png"))), sep="\n  ")


main()
