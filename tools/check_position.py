"""量「字放没放正」：每个字的墨迹外接框、字宽、竖向度量，逐字与本版相减。

为什么要有这个工具
------------------
2026-11-05 主人问「水平 y 轴定位问题」——此前所有报告只比了形状（直度、IoU、墨量），
没有一次比过**位置**：这个字的墨迹在字格里偏左还是偏右、偏高还是偏低、宽度是否一致。
形状全对而整体平移两三个单位，看上去就是「不居中、发飘」。

判据（都落在差值上，母版自比恒为 0）：
- `dx_left`：左边距差（字体单位）＝本版 xMin − 母版 xMin，负＝偏左
- `dx_right`：右边距差＝(advance − xMax) 之差，负＝右边空得多
- `dy_bottom`：底部差＝本版 yMin − 母版 yMin，负＝整体下沉
- `dy_top`：顶部差
- `dadv`：字宽差
- 中心偏移 `dcx = (xMin+xMax)/2 之差`、`dcy = (yMin+yMax)/2 之差`

用法
----
    python tools/check_position.py 母版.ttf 本版.ttf --chars "字串" [--json out.json]

退出码 0 恒返回（这是量具，不是判据）；判据看 `--json` 里的 `verdict`。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))


def bbox_of(font, gname):
    glyf = font["glyf"]
    g = glyf[gname]
    if g.numberOfContours == 0:
        return None
    g.recalcBounds(glyf)
    return (g.xMin, g.yMin, g.xMax, g.yMax)


def collect(path: Path, chars: str):
    out = {}
    with TTFont(str(path), lazy=True) as font:
        cmap = font.getBestCmap()
        hmtx = font["hmtx"]
        upem = font["head"].unitsPerEm
        for ch in dict.fromkeys(chars):
            cp = ord(ch)
            if cp not in cmap:
                continue
            gname = cmap[cp]
            bb = bbox_of(font, gname)
            if bb is None:
                continue
            adv, lsb = hmtx[gname]
            out[ch] = dict(bbox=bb, adv=adv, lsb=lsb, upem=upem)
    return out


def metrics(path: Path):
    with TTFont(str(path), lazy=True) as f:
        hhea = f["hhea"]
        os2 = f["OS/2"]
        return dict(
            upem=f["head"].unitsPerEm,
            hhea=[hhea.ascent, hhea.descent, hhea.lineGap],
            typo=[os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap],
            win=[os2.usWinAscent, os2.usWinDescent],
            cap=os2.sCapHeight, x=os2.sxHeight,
        )


def q(xs, p):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    i = (len(xs) - 1) * p
    lo = int(i)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def main() -> int:
    ap = argparse.ArgumentParser(description="量字在字格里的位置：左/右/底/顶/字宽/中心")
    ap.add_argument("master", type=Path)
    ap.add_argument("other", type=Path)
    ap.add_argument("--chars", required=True)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    m = collect(args.master, args.chars)
    o = collect(args.other, args.chars)
    common = [c for c in m if c in o]

    rows = {}
    for ch in common:
        a, b = m[ch], o[ch]
        ax0, ay0, ax1, ay1 = a["bbox"]
        bx0, by0, bx1, by1 = b["bbox"]
        rows[ch] = dict(
            dx_left=bx0 - ax0,
            dx_right=(b["adv"] - bx1) - (a["adv"] - ax1),
            dy_bottom=by0 - ay0,
            dy_top=by1 - ay1,
            dadv=b["adv"] - a["adv"],
            dcx=((bx0 + bx1) / 2) - ((ax0 + ax1) / 2),
            dcy=((by0 + by1) / 2) - ((ay0 + ay1) / 2),
            dW=(bx1 - bx0) - (ax1 - ax0),
            dH=(by1 - by0) - (ay1 - ay0),
        )

    def stat(k):
        xs = [r[k] for r in rows.values()]
        return dict(p50=q(xs, .5), mean=float(np.mean(xs)), p05=q(xs, .05),
                    p95=q(xs, .95), min=min(xs), max=max(xs),
                    absmax=max(abs(v) for v in xs), over5=sum(1 for v in xs if abs(v) > 5))

    summ = {k: stat(k) for k in ("dx_left", "dx_right", "dy_bottom", "dy_top",
                                 "dadv", "dcx", "dcy", "dW", "dH")}

    print(f"共同字 {len(rows)}")
    print(f"{'项':10s} {'中位':>8s} {'均值':>8s} {'p05':>8s} {'p95':>8s} {'极值':>8s} {'|>5|':>6s}")
    for k, v in summ.items():
        print(f"{k:10s} {v['p50']:+8.2f} {v['mean']:+8.2f} {v['p05']:+8.2f} "
              f"{v['p95']:+8.2f} {v['absmax']:8.2f} {v['over5']:6d}")
    print("竖向度量 母版", metrics(args.master))
    print("竖向度量 本版", metrics(args.other))

    worst = sorted(rows.items(), key=lambda kv: -abs(kv[1]["dcx"]))[:5]
    print("横向偏得最多：" + "  ".join(f"{c}{v['dcx']:+.1f}" for c, v in worst))
    worst_y = sorted(rows.items(), key=lambda kv: -abs(kv[1]["dcy"]))[:5]
    print("纵向偏得最多：" + "  ".join(f"{c}{v['dcy']:+.1f}" for c, v in worst_y))

    if args.json:
        args.json.write_text(json.dumps(dict(rows=rows, summary=summ,
                                             metrics_master=metrics(args.master),
                                             metrics_other=metrics(args.other)),
                                        ensure_ascii=False, indent=1), encoding="utf-8")
        print("写入", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
