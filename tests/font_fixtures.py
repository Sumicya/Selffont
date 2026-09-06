"""Original tiny test fonts; never used as device resources."""
import io

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen


def metrics_carrier(visible=False):
    order = ['.notdef', 'space'] + (['A'] if visible else [])
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({32: 'space', **({65: 'A'} if visible else {})})
    builder.setupGlyf({name: TTGlyphPen(None).glyph() for name in order})
    builder.setupHorizontalMetrics({name: (500, 0) for name in order})
    builder.setupHorizontalHeader(ascent=930, descent=-250)
    builder.setupNameTable({'familyName': 'Test Metrics Fixture', 'styleName': 'Regular',
                           'uniqueFontIdentifier': 'TestMetricsFixture',
                           'fullName': 'Test Metrics Fixture', 'psName': 'TestMetricsFixture'})
    builder.setupOS2(sTypoAscender=930, sTypoDescender=-250, usWinAscent=930, usWinDescent=250)
    builder.setupPost()
    out = io.BytesIO()
    builder.save(out)
    return out.getvalue()


def _box_glyph(x_min, y_min, x_max, y_max):
    pen = TTGlyphPen(None)
    pen.moveTo((x_min, y_min))
    pen.lineTo((x_min, y_max))
    pen.lineTo((x_max, y_max))
    pen.lineTo((x_max, y_min))
    pen.closePath()
    return pen.glyph()


def primary_font(upm=1000, hhea=(1160, -288, 0), typo=(880, -120, 0),
                 use_typo_metrics=False, digit_ink=(-10, 744), family="WenYuan Rounded SC VF"):
    """A tiny variable font that mimics WenYuan's oversized line metrics.

    Digits carry visible ink at ``digit_ink`` (yMin, yMax) so the normalization
    guard has something to validate; outlines/cmap/axes must survive untouched.
    """
    order = ['.notdef', 'space'] + list('0123456789') + list('Ag')
    builder = FontBuilder(upm, isTTF=True)
    builder.setupGlyphOrder(order)
    cmap = {32: 'space', 65: 'A', 97: 'g'}
    for d in '0123456789':
        cmap[ord(d)] = d
    builder.setupCharacterMap(cmap)
    glyphs = {'.notdef': _box_glyph(0, 0, 500, 700), 'space': TTGlyphPen(None).glyph()}
    di_min, di_max = digit_ink
    for d in '0123456789':
        glyphs[d] = _box_glyph(40, di_min, 460, di_max)
    glyphs['A'] = _box_glyph(20, 0, 480, 700)
    glyphs['g'] = _box_glyph(20, -200, 480, 500)
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (500, 0) for name in order})
    builder.setupHorizontalHeader(ascent=hhea[0], descent=hhea[1], lineGap=hhea[2])
    builder.setupNameTable({'familyName': family, 'styleName': 'Regular',
                            'uniqueFontIdentifier': family.replace(' ', ''),
                            'fullName': family, 'psName': family.replace(' ', '')})
    fs_selection = 0x40 | (0x80 if use_typo_metrics else 0)
    builder.setupOS2(sTypoAscender=typo[0], sTypoDescender=typo[1], sTypoLineGap=typo[2],
                     usWinAscent=max(hhea[0], di_max), usWinDescent=max(-hhea[1], -di_min),
                     fsSelection=fs_selection)
    builder.setupPost()
    builder.setupFvar(axes=[
        ("wght", 100, 400, 900, "Weight"),
        ("ital", 0, 0, 1, "Italic"),
    ], instances=[])
    out = io.BytesIO()
    builder.save(out)
    return out.getvalue()
