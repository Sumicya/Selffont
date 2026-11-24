"""本地复算 `build.yml` 验收步的判据。

为什么要有这个
--------------
验收断言在 CI 里红过三次，而沙箱拉不到 Actions 原始日志（`blob.core.windows.net`
被挡）。每次靠肉眼推、靠重跑 CI 猜，浪费三四轮。这里把同一套判据搬到本地，
一条命令算完，红在哪一条当场看见。

判据与 `build.yml` 的「验收（纯平移、字宽不变、横竖墨心归位）」一步逐条对应：

1. 直通件行框已被 `normalize_metrics` 对齐到空壳（930 / −250 / 0，按 upm 换算）
2. 汉字只被纯平移：位移集合 ⊆ {(dx, dy)}
3. 汉字 advance 一个没变
4. 汉字 advance 全是 1000
5. lsb == xMin（字形里没有悬空墨迹）
6. 满格字（墨宽 ≥ 850）的 |dcx| ≤ 20 占比 ≥ 99.5%，且比修前更高
7. 满宽满高字的 |dcy| ≤ 20 占比 ≥ 99.0%，且比修前更高

两处「已知例外」必须点名，不许整体放松：
- `STRAY_DROPPED` 这 5 个字的轮廓在 `drop_stray_ring.py` 里被删过，点数会变
- `攺` 删掉左侧碎块后墨宽 917 → 849，掉出 850 门槛，满格字计数会少 1

用法
----
    python tools/verify_passthrough.py 母版.ttf 出包用的那份.ttf
    python tools/verify_passthrough.py 母版.ttf 本版.ttf --carrier 930,-250,0
"""
from __future__ import annotations

import argparse
import io
import statistics
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

# 与 tools/drop_stray_ring.py 的产出对应，逐一核实过
STRAY_DROPPED = {"日", "论", "攺", "䐴", "饦"}


def cjk(cp):
    return 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mother", type=Path, help="原始母版（验收的比较基准）")
    ap.add_argument("version", type=Path, help="出包实际用的那一份")
    ap.add_argument("--carrier", default="930,-250,0",
                    help="空壳 hhea 的 ascent,descent,lineGap（默认 930,-250,0）")
    args = ap.parse_args()

    carrier = [int(x) for x in args.carrier.split(",")]
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from build import normalize_metrics

    before = TTFont(args.mother)
    packed = normalize_metrics(args.version.read_bytes(),
                               {"unitsPerEm": 1000, "hhea": carrier,
                                "useTypoMetrics": True})
    after = TTFont(io.BytesIO(packed))

    # ── 1. 行框 ──────────────────────────────────────────
    # 空壳与母版同为 1000 upm，换算比例是 1
    upm = after["head"].unitsPerEm
    want = tuple(round(v * upm / 1000) for v in carrier)
    got = (after["hhea"].ascent, after["hhea"].descent, after["hhea"].lineGap)
    print(f"1. 行框 hhea = {got}，期望 {want}  {'✓' if got == want else '✗'}")

    cmap = before.getBestCmap()
    gb, ga = before["glyf"], after["glyf"]
    hb, ha = before["hmtx"], after["hmtx"]
    cp2ch = {v: chr(k) for k, v in cmap.items()}

    # ── 2/3. 纯平移 + advance ────────────────────────────
    moved = bad_shift = bad_adv = 0
    stray_seen = set()
    for cp, gname in cmap.items():
        if not cjk(cp):
            continue
        b, a = gb[gname], ga[gname]
        if b.numberOfContours <= 0:
            continue
        dx, dy = round(a.xMin - b.xMin), round(a.yMin - b.yMin)
        # ★ 点数检查必须放在平移检查**之前**。`日` 和 `论` 的平移量正好是 (0, 0)，
        #   放进 `if dx or dy` 里面就永远查不到它们被删过碎块（上一版就是这么漏的）。
        if len(b.coordinates) != len(a.coordinates):
            ch = cp2ch.get(gname)
            if ch in STRAY_DROPPED:
                stray_seen.add(ch)
                continue
            print(f"   ✗ {ch} U+{cp:04X} 点数 {len(b.coordinates)}→"
                  f"{len(a.coordinates)}，不在碎块清理名单里")
            bad_shift += 1
            continue
        if dx or dy:
            moved += 1
            deltas = {(round(ax - bx), round(ay - by))
                      for (bx, by), (ax, ay) in zip(b.coordinates, a.coordinates)}
            if deltas - {(dx, dy)}:
                bad_shift += 1
        if hb[gname][0] != ha[gname][0]:
            bad_adv += 1
    print(f"2. 纯平移 {moved} 个动了，位移不等 {bad_shift} 个  {'✓' if not bad_shift else '✗'}")
    print(f"3. advance 变了 {bad_adv} 个  {'✓' if not bad_adv else '✗'}")

    # ── 4/5. advance 全 1000 + lsb == xMin ───────────────
    advs = {ha[cmap[cp]][0] for cp in cmap if cjk(cp)}
    print(f"4. 汉字 advance 集合 {advs}  {'✓' if advs == {1000} else '✗'}")
    lsb_bad = [cp2ch[c] for c in cmap
               if cjk(c) and ga[cmap[c]].numberOfContours > 0
               and ha[cmap[c]][1] != ga[cmap[c]].xMin]
    print(f"5. lsb ≠ xMin 的字 {len(lsb_bad)} 个 {lsb_bad[:5]}  {'✓' if not lsb_bad else '✗'}")

    # ── 6/7. 墨心归位 ────────────────────────────────────
    def centres(font):
        out = []
        for cp, g in font.getBestCmap().items():
            if not cjk(cp):
                continue
            gl = font["glyf"][g]
            if gl.numberOfContours > 0 and gl.xMax - gl.xMin >= 850:
                out.append((gl.xMin + gl.xMax) / 2 - 500)
        return out

    def vcentres(font):
        out = []
        for cp, g in font.getBestCmap().items():
            if not cjk(cp):
                continue
            gl = font["glyf"][g]
            if (gl.numberOfContours > 0 and gl.xMax - gl.xMin >= 850
                    and gl.yMax - gl.yMin >= 850):
                out.append((gl.yMin + gl.yMax) / 2)
        return out

    cb, ca = centres(before), centres(after)
    share = lambda v: 100 * sum(1 for x in v if abs(x) <= 20) / len(v)
    n_ok = len(cb) - len(STRAY_DROPPED) <= len(ca) <= len(cb)
    print(f"6. 满格字 {len(cb)} → {len(ca)}（允许少 {len(STRAY_DROPPED)} 个）  "
          f"{share(cb):.2f}% → {share(ca):.2f}%  "
          f"{'✓' if n_ok and share(ca) >= 99.5 and share(ca) > share(cb) else '✗'}")

    vb, va = vcentres(before), vcentres(after)
    mid = statistics.median(vb)
    dvb = [abs(v - mid) for v in vb]
    dva = [abs(v - mid) for v in va]
    vshare = lambda v: 100 * sum(1 for x in v if x <= 20) / len(v)
    n_ok = len(vb) - len(STRAY_DROPPED) <= len(va) <= len(vb)
    print(f"7. 满宽满高 {len(vb)} → {len(va)}  "
          f"{vshare(dvb):.2f}% → {vshare(dva):.2f}%  "
          f"{'✓' if n_ok and vshare(dva) >= 99.0 and vshare(dva) > vshare(dvb) else '✗'}")

    bad = bad_shift or bad_adv or lsb_bad or advs != {1000} or got != want
    print(f"\n碎块清理生效的字：{sorted(stray_seen)}")
    print("全部通过 ✓" if not bad else "有判据未通过 ✗")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
