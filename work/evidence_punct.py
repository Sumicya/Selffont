"""出标点/数字间距的证据图（母版 / 上一版 / 本版，同字号、同基线、标签用本字库）。

    .venv/bin/python work/evidence_punct.py work/fix13/static-400.ttf work/fix12/static-400.ttf /tmp/w/maruko.ttf

一次性脚本，跑完即弃；图与字体同批生成。
"""
from __future__ import annotations

import sys
from pathlib import Path

import uharfbuzz as hb
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
POST, PRE, MASTER = (Path(sys.argv[i]) for i in (1, 2, 3))
OUT = ROOT / "docs/evidence"
DATE = "2026-10-31"


class Line:
    """按 HarfBuzz 笔位逐字落笔（PIL 自己不带 GPOS）。"""

    def __init__(self, path: Path, size: int):
        self.pil = ImageFont.truetype(str(path), size)
        face = hb.Face(hb.Blob.from_file_path(str(path)))
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
    texts = ["[4+3]", "{Q}", "a—b", "(x)!?", "#5%&"]
    size, pad, gap, col = 120, 30, 44, 280
    label = ImageFont.truetype(str(POST), 28)
    small = ImageFont.truetype(str(POST), 20)
    tiles = {}
    for name, path in rows:
        line = Line(path, size)
        row = []
        for text in texts:
            w = int(line.positions(text)[1]) + 2 * pad
            tile = Image.new("L", (max(w, 120), int(size * 1.9)), 255)
            line.draw(tile, text, pad, int(size * 1.35))
            row.append(tile)
        tiles[name] = row
    height = sum(max(t.height for t in tiles[n]) for n, _ in rows) + 40
    width = col + max(sum(t.width + gap for t in tiles[n]) for n, _ in rows)
    page = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(page)
    y = 0
    for name, _ in rows:
        draw.text((12, y + 80), name, font=label, fill=(80, 80, 80))
        x = col
        for tile in tiles[name]:
            page.paste(tile.convert("RGB"), (x, y))
            x += tile.width + gap
        y += max(t.height for t in tiles[name])
    draw.text((12, height - 32),
              f"{DATE} · FreeType + HarfBuzz · 同字号 {size}px · 同基线 · 前进量取自 tools/side_targets.bin",
              font=small, fill=(120, 120, 120))
    path = OUT / f"{DATE}-标点与数字间距.png"
    page.save(path)
    print(path)


if __name__ == "__main__":
    main()
