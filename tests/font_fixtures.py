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
