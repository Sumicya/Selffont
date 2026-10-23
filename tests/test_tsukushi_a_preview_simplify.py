import math
import unittest

from tools.tsukushi_a_preview_simplify import (
    CHARS_63,
    EXPECTED_CHANGED_GLYPHS,
    EXPECTED_HOOKS,
    EXPECTED_ROUND_CAPS,
    EXPECTED_ROUND_TIPS,
    HOOK_CUT_PLAN,
    SAMPLE_CHARS,
    SKETCH_PROPORTION_SCALES,
    TIP_ROUND_ALLOWLIST,
    compress_electric_frame_contours,
    round_cap,
    scale_outline_points,
)


class TsukushiPreviewPlanTests(unittest.TestCase):
    def test_full_sample_and_safe_treatment_counts_are_pinned(self):
        self.assertEqual(len(CHARS_63), 63)
        self.assertEqual(len(SAMPLE_CHARS), 62)
        self.assertTrue(set(HOOK_CUT_PLAN).issubset(SAMPLE_CHARS))
        self.assertEqual(sum(map(len, HOOK_CUT_PLAN.values())), EXPECTED_HOOKS)
        self.assertEqual(EXPECTED_HOOKS, 22)
        self.assertEqual(TIP_ROUND_ALLOWLIST, frozenset({"走"}))
        self.assertEqual(EXPECTED_ROUND_TIPS, 1)
        self.assertEqual(EXPECTED_ROUND_CAPS, 11)
        self.assertEqual(EXPECTED_CHANGED_GLYPHS, 26)


class TsukushiPreviewSketchProportionTests(unittest.TestCase):
    def test_only_the_two_user_identified_sketch_glyphs_are_scaled(self):
        self.assertEqual(
            SKETCH_PROPORTION_SCALES,
            {"鸟": (1.06, 0.92), "也": (1.0, 1.06)},
        )

    def test_whole_outline_scale_keeps_anchor_and_on_curve_flags(self):
        points = [(10, 20, True), (110, 220, False), (210, 120, True)]
        scaled = scale_outline_points(
            points, scale_x=1.1, scale_y=0.9, anchor_x=10, anchor_y=20
        )
        self.assertEqual(scaled, [(10, 20, True), (120, 200, False), (230, 110, True)])

    def test_whole_outline_scale_rejects_nonpositive_and_nonfinite_factors(self):
        for scale_x, scale_y in ((0, 1), (-1, 1), (1, float("inf")), (1, float("nan"))):
            with self.subTest(scale_x=scale_x, scale_y=scale_y), self.assertRaises(ValueError):
                scale_outline_points([], scale_x, scale_y, 0, 0)


class TsukushiPreviewRoundCapTests(unittest.TestCase):
    def setUp(self):
        # A and B form an 80-unit vertical gate. Both source tangents point along +x.
        self.contour = [
            (-100.0, 0.0, True),
            (0.0, 0.0, True),
            (20.0, 35.0, False),
            (0.0, 80.0, True),
            (-100.0, 80.0, True),
        ]

    def test_cap_is_balanced_and_bulges_outward(self):
        cap = round_cap(self.contour, len(self.contour), 1, 3)
        ax, bx = cap[0], cap[-1]
        q1, apex, q2 = cap[1], cap[2], cap[3]

        self.assertAlmostEqual(q1[0] - ax[0], 40.0)
        self.assertAlmostEqual(q1[1] - ax[1], 0.0)
        self.assertAlmostEqual(q2[0] - bx[0], 40.0)
        self.assertAlmostEqual(q2[1] - bx[1], 0.0)
        self.assertAlmostEqual(apex[0], 40.0)
        self.assertAlmostEqual(apex[1], 40.0)

        left = (apex[0] - q1[0], apex[1] - q1[1])
        right = (q2[0] - apex[0], q2[1] - apex[1])
        self.assertAlmostEqual(left[0] * right[1] - left[1] * right[0], 0.0)
        self.assertGreater(left[0] * right[0] + left[1] * right[1], 0.0)

    def test_cap_bisects_small_endpoint_tangent_difference(self):
        angle = math.radians(10)
        incoming = (100.0, 0.0)
        reverse_outgoing = (100.0 * math.cos(angle), 100.0 * math.sin(angle))
        outgoing = (-reverse_outgoing[0], -reverse_outgoing[1])
        contour = [
            (-100.0, 0.0, True),
            (0.0, 0.0, True),
            (20.0, 35.0, False),
            (0.0, 80.0, True),
            (outgoing[0], 80.0 + outgoing[1], True),
        ]
        cap = round_cap(contour, len(contour), 1, 3)
        axis = (cap[1][0] / 40.0, cap[1][1] / 40.0)
        expected = (math.cos(angle / 2), math.sin(angle / 2))
        self.assertAlmostEqual(axis[0], expected[0], places=5)
        self.assertAlmostEqual(axis[1], expected[1], places=5)

    def test_extension_adds_a_tangent_run_and_preserves_rounded_end(self):
        extension = 24.0
        cap = round_cap(self.contour, len(self.contour), 1, 3, extension=extension)
        self.assertEqual(len(cap), 7)
        start, extended_start = cap[0], cap[1]
        extended_end, end = cap[-2], cap[-1]

        self.assertEqual(start, self.contour[1])
        self.assertEqual(end, self.contour[3])
        self.assertAlmostEqual(extended_start[0] - start[0], extension)
        self.assertAlmostEqual(extended_start[1] - start[1], 0.0)
        self.assertAlmostEqual(extended_end[0] - end[0], extension)
        self.assertAlmostEqual(extended_end[1] - end[1], 0.0)
        self.assertTrue(extended_start[2])
        self.assertTrue(extended_end[2])
        # The apex moves with the new gate, but the rounded cap keeps the same radius.
        self.assertAlmostEqual(cap[3][0], 64.0)
        self.assertAlmostEqual(cap[3][1], 40.0)

    def test_rejects_endpoint_tangents_that_do_not_share_a_cap_axis(self):
        angle = math.radians(40)
        incoming = (100.0 * math.cos(angle), 100.0 * math.sin(angle))
        contour = list(self.contour)
        # Use a separate local approach point to induce a 40-degree mismatch.
        contour[0] = (-incoming[0], -incoming[1], True)
        with self.assertRaisesRegex(AssertionError, "tangent mismatch"):
            round_cap(contour, len(contour), 1, 3)


class TsukushiPreviewFrameTests(unittest.TestCase):
    def setUp(self):
        self.outer = [
            (0.0, 0.0, True), (800.0, 0.0, True),
            (800.0, 800.0, True), (0.0, 800.0, True),
        ]
        self.cells = [
            [(100.0, 400.0, True), (300.0, 400.0, True),
             (300.0, 600.0, True), (100.0, 600.0, True)],
            [(100.0, 100.0, True), (300.0, 100.0, True),
             (300.0, 300.0, True), (100.0, 300.0, True)],
            [(500.0, 100.0, True), (700.0, 100.0, True),
             (700.0, 300.0, True), (500.0, 300.0, True)],
            [(500.0, 400.0, True), (700.0, 400.0, True),
             (700.0, 600.0, True), (500.0, 600.0, True)],
        ]

    def test_inner_openings_narrow_from_center_and_preserve_outer_edges(self):
        contours = [self.outer, *self.cells]
        compressed = compress_electric_frame_contours(contours, 0.10)

        self.assertEqual(compressed[0], self.outer)
        # The left and right outer-side edges stay fixed; inner edges move inward 20 units.
        for ci in (1, 2):
            self.assertEqual(min(p[0] for p in compressed[ci]), 100.0)
            self.assertAlmostEqual(max(p[0] for p in compressed[ci]), 280.0)
        for ci in (3, 4):
            self.assertAlmostEqual(min(p[0] for p in compressed[ci]), 520.0)
            self.assertEqual(max(p[0] for p in compressed[ci]), 700.0)
        # The center divider expands equally around its original centerline.
        self.assertAlmostEqual((280.0 + 520.0) / 2, 400.0)
        for ci in range(1, 5):
            self.assertEqual([p[1] for p in compressed[ci]],
                             [p[1] for p in self.cells[ci - 1]])
            self.assertEqual([p[2] for p in compressed[ci]],
                             [p[2] for p in self.cells[ci - 1]])

    def test_rejects_invalid_shrink_fraction(self):
        contours = [self.outer, *self.cells]
        for fraction in (-0.1, 1.0, 1.1):
            with self.subTest(fraction=fraction), self.assertRaises(ValueError):
                compress_electric_frame_contours(contours, fraction)


if __name__ == "__main__":
    unittest.main()
