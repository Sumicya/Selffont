"""出 `j` 修复的证据图：同一串字三行对照 + 逐字笔位线与实测数字。

    .venv/bin/python work/evidence_j.py work/fix13/static-400.ttf work/fix12/static-400.ttf /tmp/w/maruko.ttf

一次性脚本，跑完即弃；图与字体同批生成。数字全部从字体文件里现读，不手写。
"""
from __future__ import annotations

import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
POST, PRE, MASTER = (Path(sys.argv[i]) for i in (1, 2, 3))
OUT = ROOT / "docs/evidence"
DATE = "2026-10-31"
SIZE, PAD = 220, 40


def metrics(path: Path, ch: str) -> tuple[int, int, int, int, int, int]:
    font = TTFont(str(path))
    name = font.getBestCmap()[ord(ch)]
    glyph, (advance, lsb) = font["glyf"][name], font["hmtx"][name]
    return glyph.xMin, glyph.xMax, advance, lsb, glyph.yMin, glyph.yMax


def main() -> None:
    rows = [("母版（对照）", MASTER), ("本版", POST)]
    texts = ["j j j", "ja ju", "gjpqy"]
    label = ImageFont.truetype(str(POST), 30)
    note = ImageFont.truetype(str(POST), 24)
    small = ImageFont.truetype(str(POST), 20)

    tiles = {}
    for name, path in rows:
        f = ImageFont.truetype(str(path), SIZE)
        font = TTFont(str(path))
        cmap = font.getBestCmap()
        row = []
        for text in texts:
            pen = [PAD]
            for ch in text:
                pen.append(pen[-1] + font["hmtx"][cmap[ord(ch)]][0] * SIZE / 1000)
            tile = Image.new("L", (int(pen[-1] + PAD), int(SIZE * 1.9)), 255)
            d = ImageDraw.Draw(tile)
            base = int(SIZE * 1.4)
            for x in pen:
                d.line([(int(x), 12), (int(x), tile.height - 12)], fill=226)
            d.line([(0, base), (tile.width, base)], fill=(200,))
            for ch, x in zip(text, pen):
                d.text((x, base), ch, font=f, fill=0, anchor="ls")
            row.append(tile)
        tiles[name] = row

    height = sum(max(t.height for t in tiles[n]) for n, _ in rows) + 210
    width = 330 + max(sum(t.width + 50 for t in tiles[n]) for n, _ in rows)
    page = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(page)
    y = 0
    for name, _ in rows:
        draw.text((12, y + 110), name, font=label, fill=(80, 80, 80))
        x = 330
        for tile in tiles[name]:
            page.paste(tile.convert("RGB"), (x, y))
            x += tile.width + 50
        y += max(t.height for t in tiles[name])

    # 数字表：竖线 = 笔位原点；j 的墨在母版里跨到原点左边 63 单位，负 LSB 就是这件事
    draw.text((12, y + 8), "竖线 = 笔位原点（每个字的起点），横线 = 基线。数字现读自字体：",
              font=note, fill=(60, 60, 60))
    for k, (name, path) in enumerate(rows):
        xmin, xmax, advance, lsb, ymin, ymax = metrics(path, "j")
        text = (f"{name}：j 的墨 x {xmin}..{xmax}、前进量 {advance}、左边距 {lsb}"
                f"（y {ymin}..{ymax}）")
        draw.text((12, y + 44 + k * 30), text, font=note, fill=(90, 90, 90))
    draw.text((12, height - 34),
              f"{DATE} · FreeType 渲染 · 同字号 {SIZE}px · 同基线 · 数字用 fontTools 现读",
              font=small, fill=(130, 130, 130))
    path = OUT / f"{DATE}-j-负LSB修复.png"
    page.save(path)
    print(path)


if __name__ == "__main__":
    main()
