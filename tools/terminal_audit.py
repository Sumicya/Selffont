"""端头审计：用骨架量每个笔尖的**净转角**，客观判断钩到底去掉没有。

为什么不看 `process` 的返回值
-----------------------------
`process` 报 `ok` 只说明它切了一刀，不说明钩没了。钩可能被削短一截还留着弯、也可能
切在交叉点内侧把笔身带走。唯一可靠的办法是**切完之后重新量**：把字形重新栅格化、重新
细化骨架，从每个笔尖往回走 3r，看笔势在这段里转了多少度。

Maruko 的原始设计里，自由端头是半圆（`docs/design-principles.md`），半圆端头的笔势在
3r 内基本是直的——净转角只有端头最后那几个像素的角度。所以：

    净转角 > 45°  = 还有钩（或端头向外卷）
    净转角 ≤ 45°  = 端头干净

这个量与原字、与切法都无关，可以用来做闭环：切完 → 量 → 不达标就调参数重切。

用法：
    python3 tools/terminal_audit.py 字体.ttf --chars 九乙了子也包必電
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from fontTools.ttLib import TTFont
from scipy import ndimage
from skimage.morphology import skeletonize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_erase import _graph  # noqa: E402

HOOK_DEG = 45.0  # 净转角超过这个度数就算钩还在


def _walk(adjacency, start, max_len):
    """从骨架端点走 max_len 步（遇分叉停），返回路径。"""
    path = [start]
    prev = None
    cur = start
    for _ in range(int(max_len)):
        nxt = [n for n in adjacency[cur] if n != prev]
        if len(nxt) != 1:
            break
        prev, cur = cur, nxt[0]
        path.append(cur)
    return path


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    if n < 1e-9:
        return None
    return (dx / n, dy / n)


def _tangent(p, i, w):
    """i 处的切向 = 前后各 w 个点的端点连线。

    单像素切向在数字骨架上只有 8 个方向，量出来的转角是 45° 的整数倍，没有分辨力
    （第一版就这样，全部读数只剩 0/45/90）。必须加窗。
    """
    a, b = p[max(0, i - w)], p[min(len(p) - 1, i + w)]
    return _unit(a, b)


def _angle(u, v):
    if u is None or v is None:
        return 0.0
    c = max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))
    return math.degrees(math.acos(c))


def _turn(p, i, j, w=3):
    return _angle(_tangent(p, i, w), _tangent(p, j, w))


def audit(mask, upm_ratio=1.0, reach=3.0):
    """返回每个笔尖的审计记录。

    `net` 是从笔尖到 3r 处的净转角（度）；`max` 是同一段里的最大局部转角（度）。
    平滑的端头 net 小、max 也小；钩则两者都大。
    """
    sk = skeletonize(mask)
    dist = ndimage.distance_transform_edt(mask)
    r = float(np.median(dist[sk]))
    if not np.isfinite(r) or r <= 1.0:
        return [], r
    _, adjacency = _graph(sk)
    out = []
    for y, x in zip(*np.nonzero(sk)):
        p = (int(y), int(x))
        if len(adjacency[p]) != 1:
            continue
        path = _walk(adjacency, p, reach * r)
        if len(path) < 6:
            continue
        n = len(path)
        w = max(2, int(0.30 * r))
        net = _turn(path, 0, n - 1, w)
        # 局部最大转角：在每个点上量前后 w_r 步的切向差，反映端头有没有急弯。
        wr = max(2, int(0.20 * r))
        maxl = max((_turn(path, i, min(i + 2 * wr, n - 1), wr)
                    for i in range(0, n - 1)), default=0.0)
        out.append(SimpleNamespace(
            tip=(x, y), r_px=r, r=r / upm_ratio,
            net=net, max=maxl, plen=n / upm_ratio,
            hook=net > HOOK_DEG,
        ))
    return out, r


def audit_glyph(font, name, px=1200, box=(-200, -200, 1200, 1200)):
    """栅格化一个字并审计。返回 (records, r_font_units)。"""
    from hook_erase import render_glyph_object

    mask = render_glyph_object(font['glyf'][name], font['glyf'], px=px, box=box)
    upm = font['head'].unitsPerEm
    upp = px / (box[2] - box[0]) * upm  # px per font unit
    return audit(mask, upm_ratio=upp)


def summarize(font, chars=None):
    cmap = font.getBestCmap()
    if chars is None:
        chars = [chr(c) for c in sorted(cmap)][:0]
    rows = []
    for ch in chars:
        name = cmap[ord(ch)]
        recs, r = audit_glyph(font, name)
        worst = max((x.net for x in recs), default=0.0)
        hooks = [x for x in recs if x.hook]
        rows.append(dict(ch=ch, r=r, tips=len(recs), hooks=len(hooks),
                         worst=worst, recs=recs))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('font')
    ap.add_argument('--chars', default='九乙了子也包必電')
    args = ap.parse_args()
    font = TTFont(args.font)
    bad = 0
    print(f'{"字":<3}{"笔尖":>4}{"残留钩":>6}{"最大净转角":>10}  明细')
    for row in summarize(font, list(args.chars)):
        bad += row['hooks']
        detail = ' '.join(
            f'{"钩" if x.hook else "净"}{x.net:5.1f}°' for x in
            sorted(row['recs'], key=lambda z: -z.net))
        print(f'{row["ch"]:<3}{row["tips"]:>4}{row["hooks"]:>6}'
              f'{row["worst"]:>10.1f}  {detail}')
    print(f'\n残留钩总数 {bad}')


if __name__ == '__main__':
    main()
