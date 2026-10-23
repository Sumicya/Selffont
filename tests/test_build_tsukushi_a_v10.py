import unittest

from tools.build_tsukushi_a_v10 import (
    HOOK_CUT_PLAN_V10,
    VECTOR_OVERRIDE_CHARS,
    bird_gesture_paths,
    yi_gesture_paths,
)


class TsukushiV10DesignPlanTests(unittest.TestCase):
    def test_vector_overrides_cover_flagged_glyphs(self):
        self.assertEqual(
            VECTOR_OVERRIDE_CHARS,
            frozenset("颜暖己已巳也乙包鸟龙色子"),
        )
        self.assertEqual(
            set(HOOK_CUT_PLAN_V10),
            set("己已巳也包色龙子"),
        )
        self.assertEqual(sum(map(len, HOOK_CUT_PLAN_V10.values())), 9)

    def test_bird_redraw_keeps_three_distinct_gestures(self):
        paths = bird_gesture_paths()
        self.assertEqual(len(paths), 3)
        self.assertTrue(all(path for path in paths))
        self.assertTrue(all(len(segment) == 4 for path in paths for segment in path))

    def test_yi_redraw_is_one_open_sweep(self):
        (path,) = yi_gesture_paths()
        self.assertEqual(len(path), 4)
        self.assertNotEqual(path[0][0], path[-1][-1])
        self.assertEqual(path[-1][-1], (810, 180))


if __name__ == "__main__":
    unittest.main()
