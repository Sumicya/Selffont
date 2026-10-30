"""墨量比：逐字（本字库 / 母版，同字号同基线）的最大最小值清单。"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
OURS = ROOT / "work/fix5/static-400.ttf"
MASTER = Path("/tmp/w/maruko-regular.ttf")


def ink(font, ch, size=200, canvas=440):
    im = Image.new("L", (canvas, canvas), 255)
    ImageDraw.Draw(im).text((canvas // 4, canvas // 4), ch, font=font, fill=0)
    return np.asarray(im) < 128


codes = sorted(TTFont(OURS, recalcBBoxes=False).getBestCmap())
mine = ImageFont.truetype(str(OURS), 200)
mother = ImageFont.truetype(str(MASTER), 200)
rows = []
for cp in codes:
    if not (0x4E00 <= cp <= 0x9FFF):
        continue
    a, b = ink(mine, chr(cp)), ink(mother, chr(cp))
    if not a.any() or not b.any():
        continue
    rows.append((cp, a.sum() / max(1, b.sum())))
rows.sort(key=lambda r: -r[1])
print("墨量比最高的 25 个：", "、".join(f"{chr(c)}({v:.2f})" for c, v in rows[:25]))
print("墨量比最低的 25 个：", "、".join(f"{chr(c)}({v:.2f})" for c, v in rows[-25:]))
print(">1.20 的字数：", sum(1 for _, v in rows if v > 1.20), " >1.10：", sum(1 for _, v in rows if v > 1.10),
      " <0.85：", sum(1 for _, v in rows if v < 0.85), " / ", len(rows))
