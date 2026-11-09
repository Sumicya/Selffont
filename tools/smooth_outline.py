"""轮廓接点平滑度：逐 on-curve 点量「入切线与出切线的夹角」。

主人 2026-11-02 指出的问题是「笔画平不平滑」。笔画分两层，这个脚本只量第二层：

1. **中线**（`tools/design_cjk.bin` 里的贝塞尔）——节点处前段出切线与后段入切线之差。
   实测中位 0.13°，P99 0.79°：中线是干净的。
2. **轮廓**（这个脚本量的）——字体文件里描出来的那圈边。中线干净不等于轮廓干净：
   描边 → 道格拉斯–普克简化 → 三次贝塞尔拟合 → 拆二次，四步里任何一步在接点放弃
   切向连续，屏幕上就是一圈细棱。

判据：θ 是「这一点的入切线」与「出切线」的夹角。

- θ ≈ 0：G1 接点，一整条弧被切成了几段，但看起来是连续的。
- θ 在 2°–25°：**该平滑却折了**——这就是肉眼觉得「不平」的来源。
- θ ≥ 60°：设计上的真折笔（横折的直角），不算缺陷。

为什么从字体文件量而不是从设计数据量：主人看到的是字体文件。
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import flagOnCurve

SOFT_LO, SOFT_HI = 2.0, 25.0   # 「不明不白的缓折」区间，与 docs/design-principles.md 一致


def angle(a, b):
    na, nb = math.hypot(*a), math.hypot(*b)
    if na < 1e-9 or nb < 1e-9:
        return None
    c = (a[0] * b[0] + a[1] * b[1]) / (na * nb)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def ring_points(coords, flags, start, end):
    """一个环 → [(x, y, on)]，连续两个 off-curve 之间补上隐式中点。"""
    pts = [(coords[i][0], coords[i][1], bool(flags[i] & flagOnCurve)) for i in range(start, end + 1)]
    out, n = [], len(pts)
    for i, p in enumerate(pts):
        out.append(p)
        nxt = pts[(i + 1) % n]
        if not p[2] and not nxt[2]:
            out.append(((p[0] + nxt[0]) / 2, (p[1] + nxt[1]) / 2, True))
    return out


def measure(font_path, chars=None):
    """→ ({码位: [θ…]}, 全部 θ 的升序表)。chars 为 None 时量字体里全部字形。"""
    font = TTFont(font_path)
    glyf, cmap = font["glyf"], font.getBestCmap()
    want = {ord(c) for c in chars} if chars else set(cmap)
    per_char, every = {}, []
    for cp in sorted(want):
        name = cmap.get(cp)
        if not name or name not in glyf:
            continue
        g = glyf[name]
        if g.numberOfContours <= 0:
            continue
        coords, ends, flags = g.getCoordinates(glyf)
        thetas, start = [], 0
        for end in ends:
            ring = ring_points(coords, flags, start, end)
            m = len(ring)
            for i, p in enumerate(ring):
                if not p[2]:
                    continue
                prev, nxt = ring[(i - 1) % m], ring[(i + 1) % m]
                t = angle((p[0] - prev[0], p[1] - prev[1]), (nxt[0] - p[0], nxt[1] - p[1]))
                if t is not None:
                    thetas.append(t)
            start = end + 1
        if thetas:
            per_char[cp] = thetas
            every.extend(thetas)
    return per_char, sorted(every)


def main() -> None:
    ap = argparse.ArgumentParser(description="逐 on-curve 点量轮廓接点折角")
    ap.add_argument("--font", required=True, help="要量的 ttf/otf")
    ap.add_argument("--chars", help="字符集文件（每行若干字）；不给就量字体里全部字形")
    ap.add_argument("--compare", help="对照字体（通常是母版）；给了就并排打印")
    ap.add_argument("--top", type=int, default=10, help="列出缓折最密的几个字")
    ap.add_argument("--json", help="把逐字结果写成 JSON")
    args = ap.parse_args()

    chars = None
    if args.chars:
        chars = "".join(Path(args.chars).read_text(encoding="utf-8").split())

    def report(path, label):
        per_char, every = measure(path, chars)
        n = len(every)
        if not n:
            print(f"{label}: 量不到 on-curve 点")
            return None
        median = every[n // 2]
        soft = sum(1 for t in every if SOFT_LO < t < SOFT_HI) / n
        print(f"[{label}] 字 {len(per_char)}  on-curve 点 {n}  折角中位 {median:.2f}°  "
              f"P75 {every[int(n * .75)]:.2f}°  P90 {every[int(n * .9)]:.2f}°  "
              f"θ<0.5° {100 * sum(1 for t in every if t < 0.5) / n:.1f}%  "
              f"缓折({SOFT_LO:.0f}–{SOFT_HI:.0f}°) {100 * soft:.1f}%")
        if args.json and label == "本版":
            import json
            Path(args.json).write_text(json.dumps(
                {"font": str(path), "median": median, "points": n,
                 "cdf": [[x, 100 * sum(1 for t in every if t <= x) / n] for x in [0.5 * i for i in range(61)]],
                 "per_char": {f"U+{cp:04X}": [round(t, 2) for t in thetas] for cp, thetas in per_char.items()}},
                ensure_ascii=False, indent=1), encoding="utf-8")
        rows = sorted(per_char.items(),
                      key=lambda kv: -sum(1 for t in kv[1] if SOFT_LO < t < SOFT_HI) / len(kv[1]))
        print(f"  缓折最密的 {min(args.top, len(rows))} 个字：", end="")
        for cp, thetas in rows[:args.top]:
            frac = sum(1 for t in thetas if SOFT_LO < t < SOFT_HI) / len(thetas)
            print(f" {chr(cp)}{100 * frac:.0f}%", end="")
        print()
        return per_char

    if args.compare:
        report(args.compare, "母版")
    report(args.font, "本版")


if __name__ == "__main__":
    main()
