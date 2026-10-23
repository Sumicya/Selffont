import unittest

from tools.tsukushi_a_preview_simplify import (
    CAP_EXTENSION_RATIOS,
    CAP_PRESERVE_EXTENT_EXTRA_FU,
    COMPONENT_SPACING_TRANSLATIONS_FU,
    CHARS_63,
    EXPECTED_CHANGED_GLYPHS,
    EXPECTED_HOOKS,
    EXPECTED_ROUND_CAPS,
    EXPECTED_ROUND_TIPS,
    HOOK_CUT_PLAN,
    SAMPLE_CHARS,
    TIP_ROUND_ALLOWLIST,
    cap_extension_to_preserve_extent,
    round_cap,
)


class TsukushiPreviewPlanTests(unittest.TestCase):
    def test_full_sample_and_safe_treatment_counts_are_pinned(self):
        self.assertEqual(len(CHARS_63), 63)
        self.assertEqual(len(SAMPLE_CHARS), 62)
        self.assertEqual(set(CHARS_63) - set(SAMPLE_CHARS), set())
        self.assertTrue(set(HOOK_CUT_PLAN).issubset(SAMPLE_CHARS))
        self.assertEqual(sum(map(len, HOOK_CUT_PLAN.values())), EXPECTED_HOOKS)
        self.assertEqual(EXPECTED_HOOKS, 21)
        self.assertEqual(TIP_ROUND_ALLOWLIST, frozenset({"走"}))
        self.assertEqual(EXPECTED_ROUND_TIPS, 1)
        self.assertEqual(EXPECTED_ROUND_CAPS, 11)
        self.assertEqual(EXPECTED_CHANGED_GLYPHS, 27)
        self.assertEqual(len(COMPONENT_SPACING_TRANSLATIONS_FU), 2)

    def test_bird_and_ye_are_distinct_confirmed_codepoints(self):
        self.assertIn("鸟", SAMPLE_CHARS)
        self.assertIn("也", SAMPLE_CHARS)
        self.assertEqual(ord("鸟"), 0x9E1F)
        self.assertEqual(ord("也"), 0x4E5F)
        self.assertIn("鸟", HOOK_CUT_PLAN)
        self.assertIn("也", HOOK_CUT_PLAN)
        self.assertNotIn("巳", HOOK_CUT_PLAN)
        self.assertEqual(HOOK_CUT_PLAN["鸟"], ((0, 56, 68),))
        self.assertEqual(HOOK_CUT_PLAN["也"], ((0, 8, 20),))

    def test_only_explicit_electric_run_uses_a_gate_ratio(self):
        self.assertEqual(CAP_EXTENSION_RATIOS, {"电": 0.41})
        self.assertNotIn("鸟", CAP_EXTENSION_RATIOS)
        self.assertNotIn("也", CAP_EXTENSION_RATIOS)

    def test_only_topology_collision_glyphs_receive_rigid_spacing_repairs(self):
        self.assertEqual(
            COMPONENT_SPACING_TRANSLATIONS_FU,
            {"颜": {0: (0, -15), 1: (4, 5), 5: (0, -21)}, "暖": {0: (0, -8), 2: (0, 8), 5: (0, -8)}},
        )
        self.assertNotIn("鸟", COMPONENT_SPACING_TRANSLATIONS_FU)
        self.assertNotIn("也", COMPONENT_SPACING_TRANSLATIONS_FU)

    def test_extent_preservation_extra_is_limited_to_reviewed_glyphs(self):
        self.assertEqual(
            CAP_PRESERVE_EXTENT_EXTRA_FU,
            {"色": 0.0, "龙": 0.0, "也": 0.0, "己": 8.0, "已": 8.0},
        )
        self.assertEqual(CAP_PRESERVE_EXTENT_EXTRA_FU["己"], 8.0)
        self.assertEqual(CAP_PRESERVE_EXTENT_EXTRA_FU["已"], 8.0)
        self.assertNotIn("鸟", CAP_PRESERVE_EXTENT_EXTRA_FU)


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
        import math

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
        self.assertAlmostEqual(cap[3][0], 64.0)
        self.assertAlmostEqual(cap[3][1], 40.0)

    def test_extent_preserving_extension_uses_the_quadratic_curve_not_control_points(self):
        contour = [
            (-100.0, 0.0, True),
            (0.0, 0.0, True),
            (200.0, 40.0, False),
            (0.0, 80.0, True),
            (-100.0, 80.0, True),
        ]
        # The control point reaches x=200, but the actual quadratic reaches only x=100.
        self.assertAlmostEqual(
            cap_extension_to_preserve_extent(contour, len(contour), 1, 3), 60.0
        )
        extension = cap_extension_to_preserve_extent(
            contour, len(contour), 1, 3, extra=12.0
        )
        self.assertAlmostEqual(extension, 72.0)
        cap = round_cap(contour, len(contour), 1, 3, extension=extension)
        self.assertAlmostEqual(cap[3][0], 112.0)
        self.assertAlmostEqual(cap[3][1], 40.0)

    def test_extent_preservation_rejects_negative_or_nonfinite_extra(self):
        for extra in (-1.0, float("inf"), float("nan")):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                cap_extension_to_preserve_extent(
                    self.contour, len(self.contour), 1, 3, extra=extra
                )

    def test_rejects_endpoint_tangents_that_do_not_share_a_cap_axis(self):
        import math

        angle = math.radians(40)
        incoming = (100.0 * math.cos(angle), 100.0 * math.sin(angle))
        contour = list(self.contour)
        contour[0] = (-incoming[0], -incoming[1], True)
        with self.assertRaisesRegex(AssertionError, "tangent mismatch"):
            round_cap(contour, len(contour), 1, 3)


if __name__ == "__main__":
    unittest.main()
