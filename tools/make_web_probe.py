"""Generate the tiny original test font (A is a triangle); never a production font."""
from pathlib import Path
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

builder = FontBuilder(1000, isTTF=True)
builder.setupGlyphOrder([".notdef", "space", "triangle"])
builder.setupCharacterMap({32: "space", 65: "triangle"})
glyphs = {}
for name in (".notdef", "space", "triangle"):
    pen = TTGlyphPen(None)
    if name == "triangle":
        pen.moveTo((50, 0)); pen.lineTo((550, 0)); pen.lineTo((300, 700)); pen.closePath()
    glyphs[name] = pen.glyph()
builder.setupGlyf(glyphs)
builder.setupHorizontalMetrics({name: (600, 0) for name in glyphs})
builder.setupHorizontalHeader(ascent=800, descent=-200)
builder.setupNameTable({"familyName": "Selffont Probe", "styleName": "Regular", "uniqueFontIdentifier": "SelffontProbe-1", "fullName": "Selffont Probe", "psName": "SelffontProbe", "version": "Version 1.0"})
builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
builder.setupPost()
builder.font["head"].created = builder.font["head"].modified = 2082844800
builder.font.recalcTimestamp = False
builder.save(Path(__file__).resolve().parents[1] / "webroot/probe.ttf")
