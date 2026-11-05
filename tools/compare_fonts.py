"""同题同卷地比两个字体的直度，并把「两组数」之间的集合关系算出来。

为什么要有这个工具
------------------
2026-11-03 我报「默认全关自交 115/200，所以 130 里有 115 是管线画的，三个默认再添 15」。
两个数都是真的，但关系是假的：求交只有 106，150 个里有 24 个是默认新添的、9 个是默认修好的。
算术（净差 15）对，因果（包含）反。同一次报告还把母版 154 字、本版 141 字两套分母并排放，
被踢掉的 17 字恰好是最差的那些——等于把最难的题从本版卷子里撕掉再比分数。

所以判据只留两种形式，这个工具把它们固化成命令：

1. **同题比差**：只在两边都量得出的共同字集上逐字相减。母版自比恒为 0，天然满分；
   分母不再有两套，也就没有「谁被撕掉」的空间。
2. **绝对量**：自交数、丢笔数（母版量得出、本版量不出）这些不与分母有关的硬数。

集合关系单独打印：共有、各自独有、净差三个数必须一起出现。净差推不出包含。

用法
----
    # 直度：母版 vs 本版，共同字集上逐字差
    python tools/compare_fonts.py straight 母版.ttf 本版.ttf --chars "字串"

    # 自交：两个本版配置各一份失败清单，求交并差
    python tools/compare_fonts.py selfx 本版A.ttf 本版B.ttf --chars "字串"

    # 两样一起（母版 + 两个配置）
    python tools/compare_fonts.py all 母版.ttf 本版A.ttf --b 本版B.ttf --chars "字串"

退出码：0 = 全部判据通过；1 = 有判据不过。判据口径写在 `--json` 输出的 `verdict` 里。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_self_intersect as csi  # noqa: E402
import check_straight as cs  # noqa: E402


def straight_per_char(master: Path, other: Path, chars: str, size: int = 800) -> dict:
    """逐字取「左边缘 rms_med 的中位」与墨带宽中位。测不出的字不出现。"""
    out = {}
    for ch in dict.fromkeys(chars):
        bands = cs.measure_char(other, ch, size)
        if not bands:
            continue
        mbands = cs.measure_char(master, ch, size)
        if not mbands:
            continue
        out[ch] = dict(
            master=float(np.median([b["left"]["rms_med"] for b in mbands])),
            other=float(np.median([b["left"]["rms_med"] for b in bands])),
            master_w=float(np.median([b["width"] for b in mbands])),
            other_w=float(np.median([b["width"] for b in bands])),
        )
    return out


def measurable(master: Path, other: Path, chars: str, size: int = 800) -> dict:
    """哪些字母版能量出长竖、哪些不能——「丢笔」就靠这个差集。"""
    have = {}
    for ch in dict.fromkeys(chars):
        have[ch] = bool(cs.measure_char(other, ch, size))
    mother = {}
    for ch in dict.fromkeys(chars):
        mother[ch] = bool(cs.measure_char(master, ch, size))
    return dict(mother=mother, other=have)


def selfx_set(font: Path, chars: str) -> set[str]:
    from fontTools.ttLib import TTFont
    out = set()
    with TTFont(str(font), lazy=True) as f:
        cmap = f.getBestCmap()
        for ch in dict.fromkeys(chars):
            cp = ord(ch)
            if cp not in cmap:
                continue
            bad, _ = csi.check_glyph(f, cmap[cp])
            if bad:
                out.add(ch)
    return out


def set_relation(a: set, b: set) -> dict:
    return dict(
        a=len(a), b=len(b),
        both=len(a & b),
        only_a=len(a - b), only_b=len(b - a),
        net=len(a) - len(b),
        only_a_chars="".join(sorted(a - b)),
        only_b_chars="".join(sorted(b - a)),
    )


def quant(xs, p):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    i = (len(xs) - 1) * p
    lo = int(i)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def report_straight(rows: dict) -> dict:
    """判据落在逐字差上，不落在分位数画的圈上。"""
    diffs = [v["other"] - v["master"] for v in rows.values()]
    wrs = [v["other_w"] / v["master_w"] for v in rows.values() if v["master_w"] > 0]
    return dict(
        n=len(diffs),
        diff_p50=statistics.median(diffs) if diffs else float("nan"),
        diff_mean=float(np.mean(diffs)) if diffs else float("nan"),
        diff_p95=float(quant(diffs, 0.95)) if diffs else float("nan"),
        diff_max=max(diffs) if diffs else float("nan"),
        diff_min=min(diffs) if diffs else float("nan"),
        width_ratio_p50=statistics.median(wrs) if wrs else float("nan"),
        worst5=sorted(((v["other"] - v["master"], ch) for ch, v in rows.items()),
                      reverse=True)[:5],
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="同题同卷比字体：共同字集逐字差 + 集合求交并差")
    ap.add_argument("mode", choices=["straight", "selfx", "all"])
    ap.add_argument("master", type=Path, help="母版（直度的对照体）")
    ap.add_argument("a", type=Path, help="本版 A（通常是默认全开）")
    ap.add_argument("--b", type=Path, default=None, help="本版 B（通常是默认全关）")
    ap.add_argument("--chars", required=True, help="样本字串（仓内固定清单的一行）")
    ap.add_argument("--size", type=int, default=800)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    result: dict = dict(mode=args.mode, chars=len(set(args.chars)), verdict={})

    if args.mode in ("straight", "all"):
        rows = straight_per_char(args.master, args.a, args.chars, args.size)
        rep = report_straight(rows)
        meas = measurable(args.master, args.a, args.chars, args.size)
        lost = [ch for ch in meas["mother"] if meas["mother"][ch] and not meas["other"][ch]]
        rep["lost"] = len(lost)
        rep["lost_chars"] = "".join(lost)
        rep["per_char"] = rows
        # 绝对量判据：丢笔必须为 0；逐字差中位不超过 0.25 px，p95 不超过 1.0 px
        result["verdict"]["lost==0"] = rep["lost"] == 0
        result["verdict"]["diff_p50<=0.25"] = rep["diff_p50"] <= 0.25
        result["verdict"]["diff_p95<=1.00"] = rep["diff_p95"] <= 1.00
        result["straight"] = rep
        print(f"共同字 {rep['n']}｜逐字差 中位 {rep['diff_p50']:+.2f} 均值 {rep['diff_mean']:+.2f} "
              f"p95 {rep['diff_p95']:+.2f} 最差 {rep['diff_max']:+.2f}")
        print(f"墨宽比 中位 {rep['width_ratio_p50']:.3f}｜丢笔 {rep['lost']} 字：{rep['lost_chars']}")
        print("最差五字：" + "  ".join(f"{c}{d:+.2f}" for d, c in rep["worst5"]))

    if args.mode in ("selfx", "all"):
        sa = selfx_set(args.a, args.chars)
        result["selfx_a"] = len(sa)
        if args.b:
            sb = selfx_set(args.b, args.chars)
            rel = set_relation(sa, sb)
            result["selfx_relation"] = rel
            print(f"自交 A {rel['a']}／B {rel['b']}｜共有 {rel['both']}｜"
                  f"A 独有 {rel['only_a']}｜B 独有 {rel['only_b']}｜净差 {rel['net']}")
            print(f"  A 独有：{rel['only_a_chars']}")
            print(f"  B 独有：{rel['only_b_chars']}")
        else:
            print(f"自交 A {len(sa)}")

    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print("写入", args.json)

    ok = all(result["verdict"].values()) if result["verdict"] else True
    print("判据：" + ("全部通过" if ok else "不过：" + "、".join(k for k, v in result["verdict"].items() if not v)))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
