"""量「放没放正」：按构建顺序把字重建一遍，逐字比横向、纵向、行框、字宽、越界。

为什么要这个探针
----------------
`tools/check_position.py` 要**两份成品字体**才能比（母版 vs 本版），可成品只能由
CI 构建出来，本机没有母版、也不许下载（见 README 的取字件说明）。而「摆歪」这件事
在**轮廓生成完、还没打包**的那一刻就已经定了——`tools/cjk_vf.py` 建字时按
`settle_junction_widths → align_face_height → box_align.apply` 的顺序摆位。
这个探针走同一条顺序，只到摆位为止，不打包，于是不需要任何字体文件就能量。

五个判据（都是差值，母版自比恒为 0）
------------------------------------
1. **横向**：满格字（墨宽 ≥ 850）对齐后墨心 `(xMin+xMax)/2` 与 500 的距离 `dcx`。
2. **纵向**：对齐后四边与「母版字面框 + 同一条竖向修正」的差（`fix_vpos.corrected_box`）。
3. **行框**：样本墨迹包络 `low..high` 与本字体写进 hhea / OS/2 的四个数比——包络超出
   `usWinAscent/usWinDescent` 的字，Skia 按行框裁字形，屏幕上就是切掉上下沿或成方块。
4. **字宽**：汉字 advance 是否恒为 1000（全角栅格约定）。
5. **越界**：点是否跑出 `cjk_vf.FRAME`。

用法
----
    python tools/probe_position.py                      # 默认抽 300 字
    python tools/probe_position.py --sample 0           # 全库（约 20 分钟）
    python tools/probe_position.py --chars "中日目田口一国十王平羽雨"
    python tools/probe_position.py --json out.json

退出码恒为 0（这是量具，不是判据）；判定看末尾的 `判定:` 行与 `--json` 里的 verdict。
"""
from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import box_align  # noqa: E402
import cjk_vf  # noqa: E402
import design_cjk  # noqa: E402
import fix_vpos  # noqa: E402

WIDE = 850            # 「满格字」的墨宽下限（与 fix_hpos.py 同口径）
NARROW = 600          # 窄部件/笔画，横向不参与
EM = 1000
TOL = 20              # 2% em：肉眼在 16px 下看不出来，判据线用它
TOL_HARD = 30         # 超过这条才是真问题；20~30 的多半是 box_align 的限幅（±2%/±4%）留下的
CENTER_TOL = 1        # 对齐后墨心允许的残余（单位）


def box_of(rings, weight=400):
    pts = [p for ring in rings[weight] for p in ring]
    if not pts:
        return None
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


def sample_codepoints(chars: str | None, count: int) -> list[int]:
    if chars:
        return [ord(c) for c in chars]
    keys = sorted(cjk_vf_glyphs().keys())
    hans = [cp for cp in keys if cjk_vf.is_han(cp)]
    if count <= 0 or count >= len(hans):
        return hans
    step = len(hans) / count
    return [hans[int(i * step)] for i in range(count)]


_GLYPHS = None


def cjk_vf_glyphs():
    global _GLYPHS
    if _GLYPHS is None:
        _GLYPHS = design_cjk.load()
    return _GLYPHS


def measure(codepoints: list[int]) -> dict:
    glyphs = cjk_vf_glyphs()
    targets = box_align.load()
    centre = fix_vpos.table_centre()
    rows = []
    for cp in codepoints:
        data = glyphs.get(cp)
        if not data:
            continue
        data = copy.deepcopy(data)
        cjk_vf.settle_junction_widths(data)
        rings, _flags = cjk_vf._glyph_rings_all(data, cp)
        if not rings.get(400):
            continue
        before = box_of(rings)
        rings = cjk_vf.align_face_height(rings)
        # 「满格」按母版字面框的宽度判，与 box_align.center_x 同一口径（本版轮廓在 apply 里
        # 会被限幅缩一两个百分点，拿缩完的宽度判会把 `伯` 那种 847 宽的窄格字误算成满格）。
        faced = box_of(rings)
        rings = box_align.apply_all(rings, cp)
        after = box_of(rings)
        target = targets.get(cp)
        if target is not None and centre is not None:
            target = fix_vpos.corrected_box(tuple(target), centre)
        advance = cjk_vf.advance_of(cp, rings)
        rows.append({
            "cp": cp, "char": chr(cp),
            "before": before, "after": after, "target": target,
            "advance": advance,
            "outside": cjk_vf._outside_frame(rings),
            "width": (target[2] - target[0]) if target else (faced[2] - faced[0] if faced else 0),
        })
    return {"rows": rows, "targets": len(targets), "centre": centre,
            "glyphs": len(glyphs)}


def percentiles(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    v = sorted(values)
    def at(q):
        return round(v[min(len(v) - 1, int(q * (len(v) - 1)))], 2)
    return {"n": len(v), "median": round(statistics.median(v), 2),
            "p05": at(0.05), "p95": at(0.95), "min": round(v[0], 2),
            "max": round(v[-1], 2)}


def report(data: dict) -> dict:
    rows = data["rows"]
    wide = [r for r in rows if r["width"] >= WIDE and r["after"]]
    out = {"sample": len(rows), "targets": data["targets"],
           "centre": data["centre"], "glyphs": data["glyphs"]}

    # 1. 横向
    #   dcx_built  = 本版对齐后墨心 − 500（「做出来的字歪不歪」）
    #   dcx_master = 母版字面框墨心 − 500（「歪是母版带的还是本版漂的」）
    # 两者分开报：本版跟着母版走，母版自己歪的字会被原样继承——那不叫漂。
    dcx, dmaster, dcx_before = [], [], []
    for r in wide:
        dcx.append((r["after"][0] + r["after"][2]) / 2 - EM / 2)
        if r["before"]:
            dcx_before.append((r["before"][0] + r["before"][2]) / 2 - EM / 2)
        if r["target"]:
            dmaster.append((r["target"][0] + r["target"][2]) / 2 - EM / 2)
    out["horizontal"] = {
        "center_x": bool(box_align.CENTER_X),
        "wide": len(wide),
        "dcx": percentiles(dcx),
        "dcx_before": percentiles(dcx_before),
        "dcx_master": percentiles(dmaster),
        "within_1_before": round(sum(1 for d in dcx_before if abs(d) <= CENTER_TOL)
                                 / max(1, len(dcx_before)), 4),
        "within_1": round(sum(1 for d in dcx if abs(d) <= CENTER_TOL) / max(1, len(dcx)), 4),
        "over_20": sorted((round(d, 1), r["char"]) for d, r in zip(dcx, wide) if abs(d) > TOL),
        "over_20_master": sorted((round(d, 1), r["char"])
                                 for d, r in zip(dmaster, wide) if abs(d) > TOL),
    }

    # 2. 纵向：四边差
    edges = {"top": [], "bottom": [], "left": [], "right": []}
    resid = []
    for r in rows:
        if not r["after"] or not r["target"]:
            continue
        a, t = r["after"], r["target"]
        d = {"left": a[0] - t[0], "bottom": a[1] - t[1],
             "right": a[2] - t[2], "top": a[3] - t[3]}
        for k, v in d.items():
            edges[k].append(v)
        resid.append((max(abs(v) for v in d.values()), r["char"], d))
    out["vertical"] = {
        "n": len(resid),
        "edges": {k: percentiles(v) for k, v in edges.items()},
        "over_20": sorted((round(m, 1), ch) for m, ch, _ in resid if m > TOL),
        "worst": [{"char": ch, "max": round(m, 1),
                   "edges": {k: round(v, 1) for k, v in d.items()}}
                  for m, ch, d in sorted(resid, reverse=True)[:8]],
    }

    # 3. 行框与裁切（win = 裁剪包络，必须盖住墨迹；typo 只管行距，不参与裁字）
    lows = [r["after"][1] for r in rows if r["after"]]
    highs = [r["after"][3] for r in rows if r["after"]]
    low, high = (min(lows), max(highs)) if lows else (0, 0)
    frame = {"hhea": [cjk_vf.HHEA_ASCENT, cjk_vf.HHEA_DESCENT],
             "typo": [880, -120],          # cjk_vf.setupOS2 写的值
             "win": [cjk_vf.HHEA_ASCENT, cjk_vf.HHEA_DESCENT]}
    win_bottom = -frame["win"][1]
    out["frame"] = {
        "ink": [round(low, 1), round(high, 1)],
        "hhea": frame["hhea"], "typo": frame["typo"], "win": frame["win"],
        "win_top": frame["win"][0], "win_bottom": win_bottom,
        "win_headroom_top": round(frame["win"][0] - high, 1),
        "win_headroom_bottom": round(low + win_bottom, 1),
        "typo_clips_top": high > frame["typo"][0],
        "typo_clips_bottom": low < frame["typo"][1],
    }

    # 4. 字宽
    adv = [r["advance"] for r in rows]
    out["advance"] = {"n": len(adv), "min": min(adv) if adv else 0,
                      "max": max(adv) if adv else 0,
                      "not_1000": sorted({a for a in adv if a != EM})[:12]}

    # 5. 越界
    out["outside"] = [{"char": r["char"], "why": r["outside"]} for r in rows if r["outside"]]
    return out


def verdict(r: dict) -> list[str]:
    lines, ok = [], True
    h = r["horizontal"]
    if h["wide"]:
        if h["within_1"] >= 0.999:
            lines.append(f"横向 OK：满格字 {h['wide']} 个，对齐后 |墨心−500| ≤ 1 的占 "
                         f"{h['within_1'] * 100:.1f}%，p95 {h['dcx']['p95']}")
        elif h["center_x"]:
            ok = False
            worst = h["over_20"][:5]
            lines.append(f"横向 归中已开但没归干净：|墨心−500| ≤ 1 只有 {h['within_1'] * 100:.1f}%"
                         f"（{worst}）")
        else:
            inherited = len(h["over_20_master"])
            lines.append(f"横向 跟随母版：|墨心−500| ≤ 1 占 {h['within_1'] * 100:.1f}%，"
                         f"最远 {h['dcx']['min']}/{h['dcx']['max']}；母版同名字面框本来就歪 "
                         f"{inherited}/{h['wide']} 个（> {TOL}），这是**继承不是漂移**；"
                         f"要归中设 SELFFONT_CENTER=1")
    v = r["vertical"]
    if v["n"]:
        worst = v["edges"]["top"]["p95"], v["edges"]["bottom"]["p95"]
        if not v["over_20"]:
            lines.append(f"纵向 OK：{v['n']} 字四边与母版目标差全部 ≤ {TOL}"
                         f"（上/下 p95 {worst[0]}/{worst[1]}）")
        else:
            hard = [x for x in v["over_20"] if x[0] > TOL_HARD]
            names = "、".join(ch for _, ch in v["over_20"][:6])
            if hard:
                ok = False
                lines.append(f"纵向 不过：{len(hard)} 字四边差 > {TOL_HARD}（{names}…）")
            else:
                lines.append(f"纵向 提示：{len(v['over_20'])} 字残差在 {TOL}–{TOL_HARD} 之间"
                             f"（{names}），来自 box_align 的缩放限幅，属设计内")
    f = r["frame"]
    if f["win_headroom_top"] < 0 or f["win_headroom_bottom"] < 0:
        ok = False
        lines.append(f"行框 不过：墨迹 {f['ink']} 超出 win "
                     f"[{f['win_bottom']}, {f['win_top']}]，Skia 会裁字形")
    else:
        lines.append(f"行框 OK：墨迹 {f['ink']} 落在 win [{f['win_bottom']}, {f['win_top']}] 内"
                     f"（上余 {f['win_headroom_top']}、下余 {f['win_headroom_bottom']}）")
    if f["typo_clips_top"] or f["typo_clips_bottom"]:
        lines.append(f"  提示：typo [{f['typo'][1]}, {f['typo'][0]}] 装不下墨迹——typo 只管行距，"
                     "裁字的是 win，这里不算错；但安卓换行时按它算行高")
    a = r["advance"]
    if a["not_1000"]:
        ok = False
        lines.append(f"字宽 不过：样本里出现非 1000 的 advance {a['not_1000']}")
    else:
        lines.append(f"字宽 OK：{a['n']} 字 advance 全为 1000")
    if r["outside"]:
        ok = False
        lines.append(f"越界 不过：{len(r['outside'])} 字出 {cjk_vf.FRAME}"
                     f"（{'、'.join(o['char'] for o in r['outside'][:6])}）")
    else:
        lines.append(f"越界 OK：无字出 {cjk_vf.FRAME}")
    lines.append("判定: " + ("全部通过" if ok else "有不过项，见上"))
    r["verdict"] = "pass" if ok else "fail"
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=300, help="抽样字数，0 = 全库")
    ap.add_argument("--chars", default=None, help="指定字串，优先于 --sample")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    codepoints = sample_codepoints(args.chars, args.sample)
    data = measure(codepoints)
    r = report(data)
    print(f"字库 {r['glyphs']} 字｜字面框表 {r['targets']} 字｜设计中线 {r['centre']}"
          f"｜样本 {r['sample']}")
    h = r["horizontal"]
    print(f"\n== 1. 横向定位（满格字 {h['wide']} 个，对齐后；"
          f"归中开关 {'开' if h['center_x'] else '关'}）")
    if h["wide"]:
        d, dm = h["dcx"], h["dcx_master"]
        b = h["dcx_before"]
        print(f"   对齐前墨心−500：中位 {b['median']}  p05/p95 {b['p05']}/{b['p95']}"
              f"  极值 {b['min']}/{b['max']}   |差| ≤ 1 占 {h['within_1_before'] * 100:.1f}%")
        print(f"   本版墨心−500：中位 {d['median']}  p05/p95 {d['p05']}/{d['p95']}"
              f"  极值 {d['min']}/{d['max']}")
        print(f"   母版墨心−500：中位 {dm['median']}  p05/p95 {dm['p05']}/{dm['p95']}"
              f"  极值 {dm['min']}/{dm['max']}")
        print(f"   本版 |差| ≤ 1：{h['within_1'] * 100:.1f}%   |差| > {TOL}：{len(h['over_20'])} 字"
              f"（母版同口径 {len(h['over_20_master'])} 字）"
              + ("（" + "、".join(ch for _, ch in h["over_20"][:8]) + "）" if h["over_20"] else ""))
    v = r["vertical"]
    print(f"\n== 2. 纵向定位（{v['n']} 字，对齐后 − 母版目标）")
    for k, label in (("top", "上沿"), ("bottom", "下沿"), ("left", "左沿"), ("right", "右沿")):
        e = v["edges"][k]
        print(f"   {label}：中位 {e['median']}  p05/p95 {e['p05']}/{e['p95']}"
              f"  极值 {e['min']}/{e['max']}")
    print(f"   四边差 > {TOL}：{len(v['over_20'])} 字"
          + ("（" + "、".join(ch for _, ch in v["over_20"][:8]) + "）" if v["over_20"] else ""))
    for w in v["worst"][:5]:
        print(f"   最大 {w['char']} {w['max']}：{w['edges']}")
    f = r["frame"]
    print("\n== 3. 行框与裁切")
    print(f"   墨迹包络 {f['ink'][0]} .. {f['ink'][1]}")
    print(f"   hhea {f['hhea']}  typo {f['typo']}  win [{f['win_bottom']}, {f['win_top']}]")
    print(f"   win 余量：上 {f['win_headroom_top']}  下 {f['win_headroom_bottom']}"
          f"   typo 装不下墨迹：超上沿 {f['typo_clips_top']} 超下沿 {f['typo_clips_bottom']}")
    a = r["advance"]
    print(f"\n== 4. 字宽：{a['n']} 字 advance {a['min']}..{a['max']}"
          + (f"  非 1000 的 {a['not_1000']}" if a["not_1000"] else "（全 1000）"))
    print(f"\n== 5. 越界：{len(r['outside'])} 字"
          + ("　" + "、".join(o["char"] for o in r["outside"][:8]) if r["outside"] else "（无）"))
    print()
    for line in verdict(r):
        print(line)
    if args.json:
        args.json.write_text(json.dumps(r, ensure_ascii=False, indent=1))
        print(f"\n已写 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
