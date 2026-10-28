"""出正式汉字字件：数据 → 可变字体 → 行框锚定设备空壳 → 三个静态实例。

产物（默认写到 /home/user/work，可传第二个参数改）：
  SelffontCJK-VF.ttf            可变字体（wght 300–500，默认 400）
  static-{300,400,500}.ttf      三个静态实例，给 FreeType 出图与真机核对用

用法：python tools/build_cjk.py [输出目录，默认 /home/user/work]
"""
import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.argv = ["build.py"]

import build
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else Path("/home/user/work")
OUT.mkdir(parents=True, exist_ok=True)

t0 = time.time()
glyphs = build.cjk_glyphs()
print(f"读数据 {len(glyphs)} 字 {time.time()-t0:.1f}s", flush=True)

# 空壳度量：设备上就是基础包里的 Roboto 度量空壳，这里用自检里的同一份夹具
carrier = build.layout_metrics(TTFont(io.BytesIO(build.make_carrier()), recalcBBoxes=False))
print("空壳度量", carrier, flush=True)

t1 = time.time()
data = build.build_cjk_font(glyphs, carrier)
print(f"编字体并校准 {len(data)/1e6:.1f} MB {time.time()-t1:.1f}s", flush=True)
path = OUT / "SelffontCJK-VF.ttf"
path.write_bytes(data)

font = TTFont(io.BytesIO(data), recalcBBoxes=False)
hhea, os2 = font["hhea"], font["OS/2"]
print(f"  hhea {hhea.ascent}/{hhea.descent}/{hhea.lineGap}"
      f"  typo {os2.sTypoAscender}/{os2.sTypoDescender}/{os2.sTypoLineGap}"
      f"  win {os2.usWinAscent}/{os2.usWinDescent}")
low, high = build.ink_envelope(font)
print(f"  墨迹包络 {low}..{high}  字形数 {len(font.getGlyphOrder())}", flush=True)
del font

for weight in (300, 400, 500):
    inst = instantiateVariableFont(TTFont(io.BytesIO(data)), {"wght": weight})
    buf = io.BytesIO()
    inst.save(buf)
    (OUT / f"static-{weight}.ttf").write_bytes(buf.getvalue())
    print(f"  静态 {weight} {len(buf.getvalue())/1e6:.1f} MB", flush=True)
print("完成", flush=True)
