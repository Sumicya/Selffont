import unittest

import numpy as np

from tools.stroke_length_audit import (
    analyze_mask,
    orientation_bucket,
    path_length_fu,
    trace_centerline_paths,
)


class SkeletonPathTests(unittest.TestCase):
    def test_horizontal_line_length_and_orientation(self):
        skeleton = np.zeros((5, 9), dtype=bool)
        skeleton[2, 1:8] = True
        paths = trace_centerline_paths(skeleton)
        self.assertEqual(len(paths), 1)
        self.assertAlmostEqual(path_length_fu(paths[0], 1.0), 6.0)
        self.assertEqual(orientation_bucket(paths[0]), "H")

    def test_vertical_line_length_and_orientation(self):
        skeleton = np.zeros((9, 5), dtype=bool)
        skeleton[1:8, 2] = True
        paths = trace_centerline_paths(skeleton)
        self.assertEqual(len(paths), 1)
        self.assertAlmostEqual(path_length_fu(paths[0], 1.0), 6.0)
        self.assertEqual(orientation_bucket(paths[0]), "V")

    def test_t_junction_is_split_into_four_centerline_branches(self):
        skeleton = np.zeros((7, 9), dtype=bool)
        skeleton[3, 1:8] = True
        skeleton[1:6, 4] = True
        paths = trace_centerline_paths(skeleton)
        lengths = sorted(path_length_fu(path, 1.0) for path in paths)
        self.assertEqual(len(paths), 4)
        self.assertEqual(lengths, [2.0, 2.0, 3.0, 3.0])
        self.assertAlmostEqual(sum(lengths), 10.0)

    def test_closed_cycle_is_traced_once(self):
        skeleton = np.array(
            [
                [1, 1, 1],
                [1, 0, 1],
                [1, 1, 1],
            ],
            dtype=bool,
        )
        paths = trace_centerline_paths(skeleton)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0][0], paths[0][-1])
        self.assertAlmostEqual(path_length_fu(paths[0], 1.0), 8.0)

    def test_analyze_mask_reports_intraglyph_and_orientation_metrics(self):
        skeleton = np.zeros((7, 9), dtype=bool)
        skeleton[3, 1:8] = True
        skeleton[1:6, 4] = True
        metrics = analyze_mask(skeleton, 2.0)
        self.assertEqual(metrics["branch_count"], 4)
        self.assertAlmostEqual(metrics["total_centerline_fu"], 20.0)
        self.assertIsNotNone(metrics["branch_cv"])
        self.assertGreater(metrics["by_orientation"]["H"]["count"], 0)
        self.assertGreater(metrics["by_orientation"]["V"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
