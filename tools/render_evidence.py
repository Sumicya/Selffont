"""出证据图：只用自研字体自己，不拿别的字体当尺。

四张图，全部由真实字体文件经 FreeType 渲染（PIL 的 truetype 后端）：
  2026-10-28-行框.png    校准前后的行框与基线（同字号同基线，红框=行框，蓝线=基线）
  2026-10-28-三档字重.png  300/400/500 同一句话
  2026-10-28-大字细节.png  200px 八个字，看孔、转角、端头
  2026-10-28-小字号.png    12/16/24/48px，看小字会不会糊

行框从字体自己的 hhea 读，不做任何外部比较。
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

# 输入不是仓库里的字体（字体二进制不入 Git），由构建期产出：
#   python tools/render_evidence.py --vf build/SelffontCJK-VF.ttf
# 缺文件时默认到 work/ 找（本地工作区约定），命令行参数优先。

OUT = Path("/home/user/Selffont/docs/evidence")
OUT.mkdir(parents=True, exist_ok=True)
INK = (17, 17, 17)
BOX = (200, 60, 40)
BASE = (30, 120, 210)
GREY = (110, 110, 110)

SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/home/user/work/SelffontCJK-VF.ttf")
WORK = SOURCE.parent
STATIC = {w: str(WORK / f"static-{w}.ttf") for w in (300, 400, 500)}
BEFORE = str(WORK / "before-880.ttf")
LABEL_FONT = STATIC[400]


def metrics(path):
    font = TTFont(path, recalcBBoxes=False)
    ascent, descent = font["hhea"].ascent, font["hhea"].descent
    return ascent, descent, ascent - descent


def label(size=18):
    return ImageFont.truetype(LABEL_FONT, size)


def draw_line_box(draw, x0, x1, baseline, ascent, descent, size):
    up = round(ascent * size / 1000)
    down = round(descent * size / 1000)
    draw.rectangle([(x0, baseline - up), (x1, baseline - down)], outline=BOX, width=2)
    draw.line([(x0, baseline), (x1, baseline)], fill=BASE, width=2)


def figure_line_box():
    text = "天地玄黄 宇宙洪荒"
    size = 96
    rows = [("校准前  行框 880/−120", BEFORE), ("校准后  行框 930/−250", STATIC[400])]
    width, row_h = 1180, 250
    canvas = Image.new("RGB", (width, row_h * len(rows) + 40), (255, 255, 255))
    draw, small = ImageDraw.Draw(canvas), label()
    for index, (text_label, path) in enumerate(rows):
        ascent, descent, line = metrics(path)
        top = 40 + index * row_h
        baseline = top + 30 + round(ascent * size / 1000)
        draw.text((170, baseline), text, font=ImageFont.truetype(path, size), fill=INK, anchor="ls")
        draw_line_box(draw, 24, width - 24, baseline, ascent, descent, size)
        draw.text((30, baseline - round(ascent * size / 1000) - 26),
                  f"{text_label}   行框 {line}", font=small, fill=GREY)
    canvas.save(OUT / "2026-10-28-行框.png")
    print("写 2026-10-28-行框.png")


def figure_weights():
    text = "天地玄黄宇宙洪荒日月盈昃辰宿列张寒来暑往秋收冬藏"
    size = 44
    width, row_h = 1500, 90
    canvas = Image.new("RGB", (width, row_h * 3 + 20), (255, 255, 255))
    draw, small = ImageDraw.Draw(canvas), label(16)
    for index, weight in enumerate((300, 400, 500)):
        face = ImageFont.truetype(STATIC[weight], size)
        draw.text((18, 10 + index * row_h), f"wght {weight}", font=small, fill=GREY)
        draw.text((18, 34 + index * row_h), text, font=face, fill=INK)
    canvas.save(OUT / "2026-10-28-三档字重.png")
    print("写 2026-10-28-三档字重.png")


def figure_detail():
    text = "永国回目圆让认说"
    cell = 200
    canvas = Image.new("RGB", (cell * len(text) + 30, cell * 3 + 30), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    for row, weight in enumerate((300, 400, 500)):
        face = ImageFont.truetype(STATIC[weight], cell - 20)
        for column, ch in enumerate(text):
            draw.text((15 + column * cell, 10 + row * cell), ch, font=face, fill=INK)
    canvas.save(OUT / "2026-10-28-大字细节.png")
    print("写 2026-10-28-大字细节.png")


def figure_small():
    text = "天地玄黄宇宙洪荒日月盈昃辰宿列张"
    lines = [(12, 12), (16, 16), (24, 24), (48, 48)]
    canvas = Image.new("RGB", (1500, 40 + 12 + 20 + 26 + 36 + 70), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    y = 20
    for size, _ in lines:
        face = ImageFont.truetype(STATIC[400], size)
        draw.text((18, y), f"{size}px  {text}", font=face, fill=INK)
        y += int(size * 1.5) + 10
    canvas.save(OUT / "2026-10-28-小字号.png")
    print("写 2026-10-28-小字号.png")


def figure_paragraph():
    """段落：按字体自己的行框逐行推进，看行距是否撑得开、字有没有贴顶。"""
    text = "自研汉字字件的行框取自设备上的度量空壳，行距和同一段里的其它字件一致。"
    size = 40
    ascent, descent, line = metrics(STATIC[400])
    step = round(line * size / 1000)
    canvas = Image.new("RGB", (1180, step * 3 + 80), (255, 255, 255))
    draw, small = ImageDraw.Draw(canvas), label(16)
    draw.text((30, 14), f"行框 {line}，{size}px 下每行推进 {step}px（三行文字不应相互压到）",
              font=small, fill=GREY)
    face = ImageFont.truetype(STATIC[400], size)
    for index in range(3):
        draw.text((40, 60 + step * (index + 1)), text, font=face, fill=INK, anchor="ls")
    canvas.save(OUT / "2026-10-28-段落.png")
    print("写 2026-10-28-段落.png")


if __name__ == "__main__":
    figure_line_box()
    figure_weights()
    figure_detail()
    figure_small()
    figure_paragraph()
    for path in sorted(OUT.glob("2026-10-28-*.png")):
        print(f"{path.name}  {path.stat().st_size} 字节")
