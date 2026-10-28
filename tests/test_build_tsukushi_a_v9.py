import unittest

from tools.build_tsukushi_a_v9 import DEFAULT_FRAME_X_SCALE


class TsukushiV9BuildConfigurationTests(unittest.TestCase):
    def test_electric_frame_narrowing_is_tapered_and_modest(self):
        self.assertEqual(DEFAULT_FRAME_X_SCALE, 0.97)
        self.assertGreater(DEFAULT_FRAME_X_SCALE, 0.94)
        self.assertLess(DEFAULT_FRAME_X_SCALE, 1.0)


if __name__ == "__main__":
    unittest.main()
