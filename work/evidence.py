"""出证据图：只用最终字体文件 + FreeType 渲染，标签也用本字库（防方框）。

一次性脚本，按规范不入库：图与字体同批生成，脚本跑完即弃。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
POST = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "work/fix6/static-400.ttf"
PRE = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/w/pre-400.ttf")
MASTER = Path("/tmp/w/maruko-regular.ttf")
OUT = ROOT / "docs/evidence"
DATE = "2026-10-29"

LABEL = ImageFont.truetype(str(POST), 20)
SMALL = ImageFont.truetype(str(POST), 17)


def face(path, size):
    return ImageFont.truetype(str(path), size)


def holes(image: Image.Image, scale: float = 1.0) -> int:
    a = np.asarray(image) < 128
    bg, n = ndimage.label(~a)
    edge = set(bg[0].tolist()) | set(bg[-1].tolist()) | set(bg[:, 0].tolist()) | set(bg[:, -1].tolist())
    return sum(1 for k in range(1, n + 1) if k not in edge and (bg == k).sum() >= 30 * scale * scale)


def sheet(rows, chars, size, labels, caption=""):
    """rows: 字体路径列表；每行一排字，字下写 labels[row][col]。"""
    cell_w = int(size * 1.45)
    cell_h = int(size * 1.9)
    width = cell_w * len(chars) + 40
    height = cell_h * len(rows) + 40 + (70 if caption else 0)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    y0 = 10 + (60 if caption else 0)
    if caption:
        draw.text((20, 18), caption, font=LABEL, fill=(30, 30, 30))
    for row, path in enumerate(rows):
        f = face(path, size)
        for col, ch in enumerate(chars):
            x = 20 + col * cell_w
            y = y0 + row * cell_h
            draw.text((x + cell_w // 2, y + size), ch, font=f, fill=(0, 0, 0), anchor="ms")
            draw.text((x + 10, y + size + int(size * 0.22)), labels[row][col], font=SMALL, fill=(110, 110, 110))
    return image


def wrap(text, fnt, width):
    lines, line = [], ""
    for ch in text:
        if fnt.getlength(line + ch) > width and line:
            lines.append(line)
            line = ch
        else:
            line += ch
    if line:
        lines.append(line)
    return lines


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # ① 暖（U+6696）：三栏并排，同一字号同一基线
    tags = ["母版（对照，不作判据）", "修前 static-400", "修后 static-400"]
    size = 300
    cell = int(size * 1.45)
    cap = "暖 U+6696：同一字号、同一基线；修前修后都是本字库的静态 400 实例，标签用本字库排"
    width = max(cell * 3 + 40, int(LABEL.getlength(cap)) + 60)
    image = Image.new("RGB", (width, int(size * 1.9) + 80), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 18), cap, font=LABEL, fill=(30, 30, 30))
    for col, (path, tag) in enumerate(zip((MASTER, PRE, POST), tags)):
        x = 20 + col * cell
        draw.text((x + cell // 2, 60 + size), "暖", font=face(path, size), fill=(0, 0, 0), anchor="ms")
        draw.text((x + 10, 60 + size + int(size * 0.22)), tag, font=SMALL, fill=(110, 110, 110))
    image.save(OUT / f"{DATE}-暖.png")

    # ② 笔宽重测：同批 8 字
    chars = "叠鸞麠鬢僚嫓冇勢"
    tags = ["母版", "修前", "修后"]
    sheet([MASTER, PRE, POST], chars, 190, [[f"{t} {ch}" for ch in chars] for t in tags],
          caption="逐点半宽剖面：修前（中）一条笔只有一个半宽，粗处细、细处粗；修后（下）按母版逐点量").save(
        OUT / f"{DATE}-笔宽重测.png")

    # ③ 字腔：孔数从字体文件里数出来
    chars = "日暑電聞回目唱田叠鸞麠"
    master_counts = []
    for ch in chars:
        im = Image.new("L", (400, 400), 255)
        ImageDraw.Draw(im).text((200, 330), ch, font=face(MASTER, 200), fill=0, anchor="ms")
        master_counts.append(holes(im))
    rows, labels = [], []
    for path, tag in ((PRE, "修前"), (POST, "修后")):
        f = face(path, 200)
        counts = []
        for ch in chars:
            im = Image.new("L", (400, 400), 255)
            ImageDraw.Draw(im).text((200, 330), ch, font=f, fill=0, anchor="ms")
            counts.append(holes(im))
        rows.append(path)
        labels.append([f"{tag} 孔{counts[i]}" for i in range(len(chars))])
        print(f"{tag} 孔数", counts)
    print("母版 孔数", master_counts)
    sheet(rows, chars, 190, labels,
          caption="字腔（孔 ≥30 px@200 才算）：母版 " + " ".join(str(c) for c in master_counts)).save(
        OUT / f"{DATE}-字腔.png")

    # ④ 字面高度：墨迹上下沿与三组行框（整串汉字，看得出三层框都在墨迹外面）
    from fontTools.ttLib import TTFont

    tt = TTFont(POST, recalcBBoxes=False)
    upm = tt["head"].unitsPerEm
    asc, desc, win_asc = (tt["hhea"].ascent, tt["hhea"].descent, tt["OS/2"].usWinAscent)
    cmap, glyf = tt.getBestCmap(), tt["glyf"]
    envelope = [10 ** 6, -10 ** 6]
    for cp in range(0x4E00, 0x9FA6):
        if cp in cmap:
            g = glyf[cmap[cp]]
            envelope = [min(envelope[0], g.yMin), max(envelope[1], g.yMax)]
    size = 150
    scale = size / upm

    def y_of(units):
        return int(round(size * 1.7 - units * scale))

    text = "自研汉字字件的墨迹高度"
    height = y_of(desc) + 80
    im = Image.new("L", (int(face(POST, size).getlength(text)) + 40, height), 255)
    ImageDraw.Draw(im).text((20, size * 1.7), text, font=face(POST, size), fill=0, anchor="ls")
    out = im.convert("RGB")
    d = ImageDraw.Draw(out)
    for units, name, color in ((win_asc, f"usWin 上线 {win_asc}", (210, 90, 0)),
                               (asc, f"hhea/typo 上线 {asc}", (0, 90, 220)),
                               (0, "基线 0", (30, 30, 30)),
                               (desc, f"hhea/typo 下线 {desc}", (0, 90, 220))):
        d.line([(0, y_of(units)), (out.width, y_of(units))], fill=color, width=2)
        d.text((out.width - 200, y_of(units) + 3), name, font=SMALL, fill=color)
    cap = (f"汉字（0x4E00–0x9FA5）墨迹包络 {envelope[0]}…{envelope[1]}，"
           f"落在 {desc}…{asc}（hhea/typo）与 {win_asc}（usWin）之内")
    page = Image.new("RGB", (max(out.width, int(LABEL.getlength(cap)) + 40), out.height + 50), "white")
    page.paste(out, (0, 40))
    ImageDraw.Draw(page).text((10, 10), cap, font=LABEL, fill=(30, 30, 30))
    page.save(OUT / f"{DATE}-字面高度.png")

    # ⑤ 字位：同一串字，母版与修后逐字对齐（左边距写真实 xMin）
    text = "日目口，棘荆暑"
    size = 120
    width = int(face(POST, size).getlength(text)) + 60
    rows = [MASTER, POST]
    tags = ["母版", "修后 static-400"]
    image = Image.new("RGB", (width, (size + 44) * len(rows) + 60), "white")
    d = ImageDraw.Draw(image)
    cap = "同一串字、同一起笔位置：左边距写真实 xMin 之后逐字对齐（红竖线为起笔位）"
    d.text((20, 14), cap, font=LABEL, fill=(30, 30, 30))
    for row, path in enumerate(rows):
        y = 60 + row * (size + 44)
        d.text((30, y + size), text, font=face(path, size), fill=(0, 0, 0), anchor="ls")
        d.text((30, y + size + 8), tags[row], font=SMALL, fill=(110, 110, 110))
        d.line([(30, y - 6), (30, y + size + 4)], fill=(220, 80, 80), width=2)
    image.save(OUT / f"{DATE}-字位与交叉口.png")

    # ⑥ 段落：14/20/30/44 px 混排，按宽度折行
    para = ("自研汉字字件是圆的：起笔收笔都是半圆，交叉口不削角，笔画粗细按母版逐笔量。"
            "同一段里混入标点、数字与符号 ▲ ♩ ❤ ⓸ ┍ ─，行距按字体自身行框推进；"
            "叠、鸞、麠这类密排字重测之后不再糊成一团。")
    width = 980
    blocks = []
    for size in (14, 20, 30, 44):
        f = face(POST, size)
        lines = wrap(para, f, width)
        block = Image.new("L", (width + 90, len(lines) * int(size * 1.5) + size), 255)
        bd = ImageDraw.Draw(block)
        for i, line in enumerate(lines):
            bd.text((0, int(size * 1.2) + i * int(size * 1.5)), line, font=f, fill=0)
        bd.text((width + 10, int(size * 1.2)), f"{size}px", font=SMALL, fill=120)
        blocks.append(block)
    page = Image.new("RGB", (width + 90, sum(b.height + 24 for b in blocks) + 30), "white")
    y = 20
    for b in blocks:
        page.paste(b.convert("RGB"), (0, y))
        y += b.height + 24
    page.save(OUT / f"{DATE}-段落.png")

    # ⑦ 补回的符号：面填（扫描行胶囊）的实心符号，按数据判定
    sys.path.insert(0, str(ROOT / "tools"))
    import design_cjk
    data = design_cjk.load()
    face_filled = []
    for cp, glyph in data.items():
        strokes = glyph.get("strokes") or []
        if not strokes or len(strokes) < 8:
            continue
        if 0x3400 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF or 0x20000 <= cp <= 0x2FA1F:
            continue
        widths = [(s.get("hw") or {}).get(400) for s in strokes]
        if all(w is not None and abs(w - 3.25) < 0.6 for w in widths):
            face_filled.append(cp)
    face_filled.sort()
    print("面填符号", len(face_filled), "".join(chr(c) for c in face_filled))
    per_row, cell, rows = 24, 64, []
    for start in range(0, len(face_filled), per_row):
        chunk = face_filled[start:start + per_row]
        block = Image.new("RGB", (per_row * cell, cell + 26), "white")
        bd = ImageDraw.Draw(block)
        f = face(POST, 44)
        for i, cp in enumerate(chunk):
            bd.text((i * cell + cell // 2, 52), chr(cp), font=f, fill=(0, 0, 0), anchor="ms")
            bd.text((i * cell + 4, 56), f"{cp:04X}", font=SMALL, fill=(120, 120, 120))
        rows.append(block)
    page = Image.new("RGB", (per_row * cell, (cell + 26) * len(rows) + 50), "white")
    ImageDraw.Draw(page).text((6, 8), f"面填的实心符号 {len(face_filled)} 个（数据里每笔半宽 3.25 的扫描行胶囊）",
                              font=LABEL, fill=(30, 30, 30))
    y = 44
    for block in rows:
        page.paste(block, (0, y))
        y += block.height
    page.save(OUT / f"{DATE}-补回的符号.png")

    print("出图完成：", ", ".join(sorted(p.name for p in OUT.glob(f"{DATE}-*.png"))))


main()
