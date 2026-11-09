"""把「修前 / 修后」的逐字位置差画在一张图上：每个点是一个字，横轴单位是字体单位。

为什么要有这张图
----------------
`check_position.py` 出的是数字表。数字能定位问题，但看不出「一坨点整体挪到零线上」这件事。
这张图把 600 字的四个读数（横向中心差 dcx、纵向中心差 dcy、宽差 dW、高差 dH）各画成
一条点带：上一条是修前，下一条是修后，中间一条虚线是零。

用法
----
    python tools/fig_position_fix.py --before 修前.json --after 修后.json --out 图.png
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

INK = (26, 26, 26)
GREY = (150, 150, 150)
RED = (214, 40, 40)
BLUE = (36, 104, 210)


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["rows"]


def stats(values):
    ordered = sorted(values)
    n = len(ordered)

    def at(q):
        return ordered[min(n - 1, max(0, int(round(q * (n - 1)))))]

    return {"p50": at(0.5), "p05": at(0.05), "p95": at(0.95), "n": n}


def strip(d, x0, x1, y, values, color, label, label_font, axis_px_per_unit, rng, span=22.0):
    if label:
        d.text((x0 - 150, y - 14), label, font=label_font, fill=color)
    for v in values:
        if abs(v) > span:
            continue
        px = (x0 + x1) / 2 + v * axis_px_per_unit
        py = y + rng.uniform(-9, 9)
        d.ellipse([px - 2, py - 2, px + 2, py + 2], fill=color)
    s = stats(values)
    mx = (x0 + x1) / 2 + s["p50"] * axis_px_per_unit
    d.line([mx, y - 16, mx, y + 16], fill=color, width=2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", type=Path, required=True)
    ap.add_argument("--after", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--span", type=float, default=22.0, help="横轴半幅（字体单位）")
    ap.add_argument("--font", type=Path, required=True, help="画标签用的字体（给母版）")
    args = ap.parse_args()

    before, after = load(args.before), load(args.after)
    label_cjk = str(args.font)
    chars = [c for c in after if c in before]
    fields = [("dcx", "墨心横向差 dcx"), ("dcy", "墨心纵向差 dcy"),
              ("dW", "墨宽差 dW"), ("dH", "墨高差 dH")]

    W, H = 2440, 1200
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f_cjk_title = ImageFont.truetype(label_cjk, 34)
    f_s = ImageFont.truetype(label_cjk, 20)
    f_cjk_lab = ImageFont.truetype(label_cjk, 24)

    d.text((50, 28), f"600 字逐字位置差：修前 vs 修后（{len(chars)} 字，单位＝字体单位/1000 em）",
           font=f_cjk_title, fill=INK)
    d.text((50, 78), "每个点是一个字；横轴 0 是母版；竖线是该组中位。修前那一行整体偏，"
                     "修后这一行全压在零线上。", font=f_cjk_lab, fill=(110, 110, 110))

    x0, x1 = 330, 1180
    ppu = (x1 - x0) / (2 * args.span)
    rng = random.Random(7)
    y = 230
    for key, name in fields:
        d.text((90, y - 92), f"{name}（{key}）", font=f_cjk_lab, fill=INK)
        sb, sa = stats([before[c][key] for c in chars]), stats([after[c][key] for c in chars])
        d.text((90, y - 58), f"中位 {sb['p50']:+.1f} → {sa['p50']:+.1f}；"
                             f"p05/p95 {sb['p05']:+.0f}/{sb['p95']:+.0f} → {sa['p05']:+.0f}/{sa['p95']:+.0f}",
               font=f_s, fill=(90, 90, 90))
        d.line([x0, y - 34, x1, y - 34], fill=(232, 232, 232), width=1)
        cx = (x0 + x1) / 2
        d.line([cx, y - 40, cx, y + 92], fill=GREY, width=2)
        for unit in (-20, -10, 10, 20):
            if abs(unit) <= args.span:
                px = cx + unit * ppu
                d.line([px, y - 36, px, y + 88], fill=(240, 240, 240), width=1)
                d.text((px - 14, y + 92), f"{unit:+d}", font=f_s, fill=(150, 150, 150))
        d.text((x0 - 96, y - 10), "修前", font=f_cjk_lab, fill=RED)
        strip(d, x0, x1, y, [before[c][key] for c in chars], RED, "", f_s, ppu, rng, args.span)
        d.text((x0 - 96, y + 44), "修后", font=f_cjk_lab, fill=BLUE)
        strip(d, x0, x1, y + 54, [after[c][key] for c in chars], BLUE, "", f_s, ppu, rng, args.span)
        nonzero = sum(1 for c in chars if after[c][key] != 0)
        if nonzero == 0:
            d.text((x0, y + 118), f"修后：{sa['n']} 字全部落在 0", font=f_s, fill=BLUE)
        else:
            out_of_view = sum(1 for v in [after[c][key] for c in chars] if abs(v) > args.span)
            extra = f"，±{args.span:.0f} 外 {out_of_view} 点未画" if out_of_view else ""
            d.text((x0, y + 118), f"修后：≠0 的 {nonzero} 字{extra}", font=f_s, fill=BLUE)
        y += 250

    # 右栏：汇总表
    tx = 1290
    d.text((tx, 170), "汇总（600 字）", font=f_cjk_lab, fill=INK)
    lines = [
        ("读数", "修前", "修后"),
        ("dcx 中位", f"{stats([before[c]['dcx'] for c in chars])['p50']:+.1f}",
                     f"{stats([after[c]['dcx'] for c in chars])['p50']:+.1f}"),
        ("dcy 中位", f"{stats([before[c]['dcy'] for c in chars])['p50']:+.1f}",
                     f"{stats([after[c]['dcy'] for c in chars])['p50']:+.1f}"),
        ("dW 中位", f"{stats([before[c]['dW'] for c in chars])['p50']:+.1f}",
                    f"{stats([after[c]['dW'] for c in chars])['p50']:+.1f}"),
        ("dH 中位", f"{stats([before[c]['dH'] for c in chars])['p50']:+.1f}",
                    f"{stats([after[c]['dH'] for c in chars])['p50']:+.1f}"),
        ("|dcx|>5", str(sum(1 for c in chars if abs(before[c]['dcx']) > 5)),
                    str(sum(1 for c in chars if abs(after[c]['dcx']) > 5))),
        ("|dcy|>5", str(sum(1 for c in chars if abs(before[c]['dcy']) > 5)),
                    str(sum(1 for c in chars if abs(after[c]['dcy']) > 5))),
        ("|dW|>5", str(sum(1 for c in chars if abs(before[c]['dW']) > 5)),
                   str(sum(1 for c in chars if abs(after[c]['dW']) > 5))),
        ("|dH|>5", str(sum(1 for c in chars if abs(before[c]['dH']) > 5)),
                   str(sum(1 for c in chars if abs(after[c]['dH']) > 5))),
    ]
    yy = 230
    for i, (a, b, c) in enumerate(lines):
        color = INK if i == 0 else (60, 60, 60)
        d.text((tx, yy), a, font=f_cjk_lab, fill=color)
        d.text((tx + 300, yy), b, font=f_cjk_lab, fill=RED if i else color)
        d.text((tx + 470, yy), c, font=f_cjk_lab, fill=BLUE if i else color)
        yy += 52
    over = [sum(1 for c in chars if abs(after[c][k]) > 5) for k, _ in fields]
    d.text((tx, yy + 20), f"|差|>5 的 {'/'.join(map(str, over))} 字不是对齐没做，是形状本身：",
           font=f_s, fill=(110, 110, 110))
    d.text((tx, yy + 50), "锐角收笔在圆头固定拓扑下会被截掉 20–40 单位（式、验、铲）。", font=f_s, fill=(110, 110, 110))
    d.text((tx, yy + 80), "日 的 dH=−70 来自母版自带的一块 55×45 独立残墨，", font=f_s, fill=(110, 110, 110))
    d.text((tx, yy + 110), "字面本身（201,−10,802,763）与母版逐单位相同。", font=f_s, fill=(110, 110, 110))

    img.save(args.out)
    print("写出", args.out, img.size)


if __name__ == "__main__":
    main()
