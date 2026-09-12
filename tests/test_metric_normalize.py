"""Aggressive fix: normalise WenYuan line metrics to the Android carrier.

These tests prove the packaged font stops pushing compact digits down (the badge
bug) WITHOUT editing outlines, cmap, family or axes, and that a font whose ink
would overflow the normalised line box is refused rather than shipped clipped.
"""
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))

from font_fixtures import metrics_carrier, primary_font
from fontTools.ttLib import TTFont
from metric_normalize import ClipError, assert_glyphs_preserved, normalize_metrics
from prepare_font import layout_metrics


def carrier_metrics(**kw):
    return layout_metrics(TTFont(io.BytesIO(metrics_carrier(**kw))))


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.carrier = carrier_metrics()  # hhea 930/-250, upm 1000

    def test_line_metrics_match_carrier(self):
        font = primary_font(hhea=(1160, -288, 0), typo=(880, -120, 0))
        norm, report = normalize_metrics(font, self.carrier)
        nf = TTFont(io.BytesIO(norm))
        # hhea and typo both collapse to the carrier's nominal envelope.
        self.assertEqual((nf['hhea'].ascent, nf['hhea'].descent), (930, -250))
        self.assertEqual((nf['OS/2'].sTypoAscender, nf['OS/2'].sTypoDescender), (930, -250))
        self.assertEqual(report['normalized']['hhea'], [930, -250, 0])
        # The original oversized metrics are recorded for the report.
        self.assertEqual(report['original']['hhea'], [1160, -288, 0])

    def test_scales_when_units_per_em_differ(self):
        # WenYuan-like 2048 UPM against a 1000 UPM carrier scales proportionally.
        font = primary_font(upm=2048, hhea=(2400, -600, 0), typo=(1800, -400, 0),
                            digit_ink=(-20, 1500))
        norm, _ = normalize_metrics(font, self.carrier)
        nf = TTFont(io.BytesIO(norm))
        self.assertEqual(nf['hhea'].ascent, round(930 * 2048 / 1000))
        self.assertEqual(nf['hhea'].descent, round(-250 * 2048 / 1000))

    def test_glyphs_cmap_axes_preserved(self):
        font = primary_font()
        norm, _ = normalize_metrics(font, self.carrier)
        # Does not raise: outlines, order, cmap, family, axes are all identical.
        assert_glyphs_preserved(font, norm)
        before, after = TTFont(io.BytesIO(font)), TTFont(io.BytesIO(norm))
        self.assertEqual(before.getBestCmap(), after.getBestCmap())
        self.assertEqual(before['name'].getDebugName(1), after['name'].getDebugName(1))
        self.assertEqual([(a.axisTag, a.minValue, a.maxValue) for a in before['fvar'].axes],
                         [(a.axisTag, a.minValue, a.maxValue) for a in after['fvar'].axes])

    def test_use_typo_metrics_follows_carrier(self):
        for flag in (False, True):
            carrier = self.carrier if not flag else dict(self.carrier, useTypoMetrics=True)
            norm, _ = normalize_metrics(primary_font(), carrier)
            nf = TTFont(io.BytesIO(norm))
            self.assertEqual(bool(nf['OS/2'].fsSelection & 0x80), flag)

    def test_win_envelope_covers_real_ink(self):
        # usWin must stay wide enough to cover actual ink so nothing is cropped.
        font = primary_font(digit_ink=(-10, 744))
        norm, report = normalize_metrics(font, self.carrier)
        nf = TTFont(io.BytesIO(norm))
        self.assertGreaterEqual(nf['OS/2'].usWinAscent, 744)
        self.assertGreaterEqual(nf['OS/2'].usWinAscent, report['digitInkY'][1])

    def test_refuses_to_clip_digit_ink(self):
        # A font whose digit ink overflows the normalised ascent must be rejected.
        overflow = primary_font(digit_ink=(-10, 1200))  # 1200 > carrier ascent 930
        with self.assertRaises(ClipError):
            normalize_metrics(overflow, self.carrier)

    def test_refuses_to_clip_descent(self):
        overflow = primary_font(digit_ink=(-400, 744))  # -400 < carrier descent -250
        with self.assertRaises(ClipError):
            normalize_metrics(overflow, self.carrier)

    def test_detects_outline_tampering(self):
        a = primary_font(digit_ink=(-10, 744))
        b = primary_font(digit_ink=(-10, 700))  # different outline
        with self.assertRaises(ValueError):
            assert_glyphs_preserved(a, b)


if __name__ == '__main__':
    unittest.main()
