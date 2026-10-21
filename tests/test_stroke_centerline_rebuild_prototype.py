import unittest

import numpy as np

from tools.stroke_centerline_rebuild_prototype import (
    _closed_contours,
    _contour_area,
    _contour_centroid,
    _match_contours,
    _resample_closed_contour,
)


class StrokeCenterlineRebuildPrototypeTests(unittest.TestCase):
    @staticmethod
    def square(top: float, left: float, size: float) -> np.ndarray:
        return np.asarray([
            [top, left],
            [top, left + size],
            [top + size, left + size],
            [top + size, left],
        ], dtype=float)

    def test_resample_keeps_point_count_and_winding(self):
        contour = self.square(2, 3, 20)
        sampled = _resample_closed_contour(contour, contour, 64)
        self.assertEqual(len(sampled), 64)
        self.assertEqual(np.sign(_contour_area(sampled)), np.sign(_contour_area(contour)))
        # Arc-length resampling must stay on the original closed boundary.
        self.assertTrue(np.all(sampled[:, 0] >= 2 - 1e-9))
        self.assertTrue(np.all(sampled[:, 0] <= 22 + 1e-9))
        self.assertTrue(np.all(sampled[:, 1] >= 3 - 1e-9))
        self.assertTrue(np.all(sampled[:, 1] <= 23 + 1e-9))

    def test_contour_matching_restores_reference_order(self):
        reference = [self.square(0, 0, 20), self.square(50, 50, 10)]
        candidate = [self.square(51, 50, 10), self.square(1, 0, 20)]
        matched = _match_contours(reference, candidate, px=100, char="回", weight="Medium")
        self.assertEqual(len(matched), 2)
        for expected, actual in zip(reference, matched):
            self.assertLess(
                np.linalg.norm(_contour_centroid(expected) - _contour_centroid(actual)),
                2.0,
            )

    def test_tiny_raster_contours_are_filtered(self):
        mask = np.zeros((24, 24), dtype=bool)
        mask[2:18, 2:18] = True
        mask[21, 21] = True  # one-pixel speck, below the 8-FU perimeter floor
        contours = _closed_contours(mask, units_per_pixel=1.0)
        self.assertEqual(len(contours), 1)
        self.assertGreater(_contour_area(contours[0]), 0)


if __name__ == "__main__":
    unittest.main()
