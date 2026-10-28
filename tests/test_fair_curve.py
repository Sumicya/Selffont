import unittest

import numpy as np

from tools.fair_curve import _resample, fair, tangent_score


def _circle(radius=200.0, count=2000):
    theta = np.linspace(0.0, 2.0 * np.pi, count, endpoint=False)
    return np.stack([radius * np.cos(theta), radius * np.sin(theta)], axis=1)


def _stair(count=200, step=2.0):
    """一条水平线上的一段 4 fu 宽、3 fu 高的台阶：描摹字体上最典型的小折角。

    1 fu 高的台阶在 30 fu 的切线窗口里会被平均成 2°，测不出来——这正是为什么
    磨平必须用"窗口极差"而不是相邻点的角度跳变。
    """
    x = np.arange(count) * step
    y = np.zeros(count)
    y[97:101] = [0.0, 3.0, 3.0, 0.0]
    return np.stack([x, y], axis=1)


class TangentScoreTests(unittest.TestCase):
    def test_closed_circle_does_not_report_a_fake_360_degree_kink(self):
        """闭合轮廓绕一圈本身转 360°：旧实现先取全局相对角再开窗，首尾附近会算出 356°。"""
        radius = 200.0
        points = _circle(radius)

        score = tangent_score(points, window=30.0, span=34.0)

        # 34 fu 弧长在半径 200 fu 的圆上对应 34/200 弧度 ≈ 9.74°
        expected = np.degrees(34.0 / radius)
        self.assertLess(score.max(), 20.0)
        self.assertAlmostEqual(float(score.max()), expected, delta=0.5)
        # 整圈都不该出现"短窗口内转了半圈"这种量级
        self.assertTrue(np.all(score < 180.0))

    def test_straight_line_scores_zero_away_from_the_ring_seam(self):
        # tangent_score 把点序列当闭合环处理，开曲线的首尾相接处本来就不连续，
        # 所以只检查离开接缝的部分。
        points = np.stack([np.arange(300) * 2.0, np.zeros(300)], axis=1)

        score = tangent_score(points, window=30.0, span=34.0)

        self.assertLess(score[40:-40].max(), 0.01)


class FairTests(unittest.TestCase):
    def test_stair_edits_stay_local_and_do_not_blow_up(self):
        points = _stair()

        output, applied = fair(points, window=30.0, span=34.0, threshold=3.0)

        self.assertGreaterEqual(applied, 1)
        self.assertEqual(output.shape, points.shape)
        moved = np.where(np.abs(output[:, 1] - points[:, 1]) > 1e-9)[0]
        self.assertGreater(len(moved), 0)
        self.assertGreater(moved.min(), 50)
        self.assertLess(moved.max(), 150)
        # 离台阶远的地方一个点都不许动（x 会被沿轮廓重分布，所以只比 y）
        np.testing.assert_allclose(output[:70, 1], points[:70, 1])
        np.testing.assert_allclose(output[110:, 1], points[110:, 1])
        # Hermite 会过冲，但幅度得留在台阶本身附近
        self.assertLess(float(np.abs(output[:, 1]).max()), 4.0)

    def test_smooth_circle_is_left_alone_below_threshold(self):
        points = _resample(_circle(400.0), 2.0)

        output, applied = fair(points, window=30.0, span=34.0, threshold=200.0)

        self.assertEqual(applied, 0)
        np.testing.assert_allclose(output, points)


if __name__ == "__main__":
    unittest.main()
