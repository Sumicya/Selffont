import math
import unittest

from tools.tsukushi_a_preview_simplify import round_cap


class TsukushiPreviewRoundCapTests(unittest.TestCase):
    def test_cap_is_balanced_and_bulges_outward(self):
        # A and B form an 80-unit vertical gate. Both source tangents point along +x.
        contour = [
            (-100.0, 0.0, True),
            (0.0, 0.0, True),
            (20.0, 35.0, False),
            (0.0, 80.0, True),
            (-100.0, 80.0, True),
        ]
        cap = round_cap(contour, len(contour), 1, 3)
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

    def test_rejects_endpoint_tangents_that_do_not_share_a_cap_axis(self):
        angle = math.radians(40)
        incoming = (100.0 * math.cos(angle), 100.0 * math.sin(angle))
        contour = [
            (-100.0, 0.0, True),
            (0.0, 0.0, True),
            (20.0, 35.0, False),
            (0.0, 80.0, True),
            (-100.0, 80.0, True),
        ]
        # Use a separate local approach point to induce a 40-degree mismatch.
        contour[0] = (-incoming[0], -incoming[1], True)
        with self.assertRaisesRegex(AssertionError, "tangent mismatch"):
            round_cap(contour, len(contour), 1, 3)


if __name__ == "__main__":
    unittest.main()
