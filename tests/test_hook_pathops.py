"""钩切除/核验的可回归测试。

这里守的是**事实**，不是「process 返回 ok」：
`g7` 那次就是因为只看返回值，宣称八字钩全部去掉，实际差分图里十个钩一个没少。
"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import hook_pathops as hp  # noqa: E402


def test_rdp_keeps_endpoints_and_shrinks():
    pts = [(0.0, 0.0)] + [(float(i), 0.2 * math.sin(i)) for i in range(1, 60)] + [(60.0, 0.0)]
    out = hp._rdp(pts, 0.5)
    assert out[0] == pts[0] and out[-1] == pts[-1]
    assert len(out) < 10


def test_rdp_keeps_corner():
    pts = [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0)]
    assert hp._rdp(pts, 1.0) == pts


def test_ball_is_round_and_closed():
    p = hp._ball(10.0, -5.0, 20.0, n=64)
    assert len(list(p.contours)) == 1
    assert abs(abs(p.area) - math.pi * 400) < 15


def test_drop_slivers_removes_tiny_contour():
    big = hp._ball(0.0, 0.0, 20.0)
    tiny = hp._ball(100.0, 0.0, 0.5)
    import pathops
    both = pathops.op(big, tiny, pathops.PathOp.UNION)
    kept = hp._drop_slivers(both, 6.0)
    assert abs(abs(kept.area) - abs(big.area)) < 20


def test_outer_sign_roundtrip():
    p = hp._ball(0.0, 0.0, 10.0)
    s = hp._outer_sign(p)
    assert s in (-1, 1)
    p.reverse()
    assert hp._outer_sign(p) == -s


def test_longest_branch_prefers_far_branch():
    """钩根落在交叉点时，要取最远的那条分支，不能取最近的。"""
    sk = np.zeros((40, 40), bool)
    for x in range(2, 6):        # 短分支（钩）
        sk[10, x] = True
    for y in range(10, 30):      # 长分支（笔身）
        sk[y, 6] = True
    for x in range(6, 12):
        sk[10, x] = True
    from hook_erase import _graph
    _, adj = _graph(sk)
    branch = hp._longest_branch((10, 5), {(10, x) for x in range(2, 6)}, sk, 5.0)
    assert branch[0] == (10, 5)
    # 必须走进长分支（y 增大），不能回头钻进短分支（x < 6）
    assert len(branch) > 1
    assert branch[-1][1] >= 6
    assert branch[-1] != branch[0]


def test_hook_axis_points_to_tip():
    """钩轴向必须指向钩尖：符号错了整个半平面就装反。"""
    # (y,x) 序列，末位是钩根。采样取离散的 45° 点，避免共线退化。
    pts = [(10, 10), (14, 13), (18, 17), (22, 22), (30, 30)]
    axis = hp._hook_axis(pts, 10.0)
    assert axis is not None
    dy, dx = axis
    assert dy < 0 and dx < 0   # 从钩根(30,30)指向钩尖(10,10)


def test_count_pieces_counts_outer_contours():
    import pathops
    a = hp._ball(0, 0, 10)
    b = hp._ball(100, 0, 10)
    two = pathops.op(a, b, pathops.PathOp.UNION)
    assert hp._count_pieces(a) == 1
    assert hp._count_pieces(two) == 2


def test_halves_do_not_leak_across_cut():
    """半平面 + 半圆盘的组合：切口一侧必须干净，另一侧必须完整。"""
    import pathops
    body = pathops.Path()
    body.moveTo(-100, -20); body.lineTo(100, -20)
    body.lineTo(100, 20); body.lineTo(-100, 20); body.close()
    c = (0.0, 0.0)
    half = pathops.Path()
    big = 400.0
    half.moveTo(c[0], c[1] - big)
    half.lineTo(c[0] + big, c[1] - big)
    half.lineTo(c[0] + big, c[1] + big)
    half.lineTo(c[0], c[1] + big)
    half.close()
    flat = pathops.op(body, half, pathops.PathOp.DIFFERENCE)
    cap = pathops.op(hp._ball(*c, 20.0), half, pathops.PathOp.INTERSECTION)
    out = pathops.op(flat, cap, pathops.PathOp.UNION)
    assert out.area > body.area * 0.5
    assert hp._count_pieces(out) == 1
