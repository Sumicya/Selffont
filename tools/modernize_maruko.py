"""把 Maruko 做成"干净现代化"字形的流水线：无钩 → 笔画合并 → 曲线重拟合。

三步的顺序是有原因的，换顺序就白做：

1. **无钩**：候选点对由 `hook_cut.find_hooks()` 在原始轮廓上判（点序还在，钩环的几何
   特征才读得出来），但**切的时候切在墨迹上**——把闸门之间围出的环从掩膜里挖掉。
   直接在轮廓上换圆弧的做法会把内腔翻实、把长弧腰斩，实测 252 字里 192 个被弄坏，
   详见 `hook_erase.py` 的说明。
2. **笔画合并**：光栅化按真实墨迹取形状，再沿墨迹边界描线。并集自然干掉了"相交笔画
   各自独立轮廓、靠非零环绕叠在一起"的隐藏重叠。必须**直接描 mask**（保形）；拿
   "骨架 × 常数半径"当重建源会把原设计整个丢掉——转角削圆、收笔变圆头、`日` 这类
   窄空腔直接被两侧笔画堵死（实测 `春` IoU 0.698、缺墨 22%）。
3. **曲线重拟合**（`curve_simplify.py`）：第 2 步描出来的是折线（每字上万点），
   必须重拟合回二次贝塞尔。描线前对掩膜做 1 px 高斯平滑，让 marching squares 取到
   亚像素边界；不平滑的话二值台阶是 ±0.5 px 的方波，拟合器只能把每个折点都留下
   （实测「街」精简后仍剩 1598 点，平滑后 490 点）。

用法：
    python3 tools/modernize_maruko.py --font MarukoSC-Regular.ttf --chars-file chars.txt \
        --out ModernSC-Regular.ttf --px 2000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_cut import detect_hook_plan, split_contours  # noqa: E402
from hook_erase import (  # noqa: E402
    MAX_ERASE_FRACTION,
    MIN_IOU_AFTER_CUT,
    compare_glyphs,
    erase_loops,
)
from stroke_width_normalize_prototype import glyph_from_mask, raster_mask  # noqa: E402


def _contours_of(font, gname):
    glyph = font["glyf"][gname]
    coords, ends, flags = glyph.getCoordinates(font["glyf"])
    return split_contours(coords, ends, flags)


def rebuild_merged(font, chars, cmap, px, margin_frac, smooth_px=1.0, plan=None,
                   guard=True):
    """保形并集 + 墨迹级无钩。"""
    glyf = font["glyf"]
    done, failed, cut_report, rejected = [], [], {}, []
    for ch in chars:
        if ord(ch) not in cmap:
            continue
        gname = cmap[ord(ch)]
        if glyf[gname].isComposite():
            failed.append((ch, "composite"))
            continue
        try:
            mask, transform = raster_mask(font, gname, px, margin_frac)
            basemask = mask
            applied = 0
            if plan and gname in plan:
                contours = _contours_of(font, gname)
                contour_index = dict(enumerate(contours))
                candidate, applied, fraction = erase_loops(
                    mask, transform, contour_index, plan[gname])
                if fraction > MAX_ERASE_FRACTION:
                    rejected.append((ch, f"erase {fraction*100:.1f}%"))
                    applied = 0
                else:
                    basemask = candidate
            original = glyf[gname]
            glyph = glyph_from_mask(basemask, font, transform, smooth_px)
            if guard and applied:
                iou, ink = compare_glyphs(original, glyph, glyf)
                if iou < MIN_IOU_AFTER_CUT or ink < -MAX_ERASE_FRACTION:
                    rejected.append((ch, f"iou {iou:.2f} ink {ink*100:+.1f}%"))
                    applied = 0
                    glyph = glyph_from_mask(mask, font, transform, smooth_px)
            glyf[gname] = glyph
            # 重描后 xMin 会动（细尖被光栅吃掉一点），hmtx 的 lsb 必须跟着走，
            # 否则任何走 getGlyphSet() 的下游工具都会把整个字平移 lsb-xMin。
            glyph.recalcBounds(glyf)
            advance = font["hmtx"][gname][0]
            font["hmtx"][gname] = (advance, glyph.xMin)
            if applied:
                cut_report[ch] = applied
            done.append(ch)
        except Exception as exc:  # noqa: BLE001
            failed.append((ch, str(exc)[:60]))
    return done, failed, cut_report, rejected


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--font", required=True, help="Maruko 静态字重 TTF")
    ap.add_argument("--chars-file", required=True, help="要处理的字符（一行，去重后使用）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--px", type=int, default=2000)
    ap.add_argument("--margin-frac", type=float, default=0.08)
    ap.add_argument("--smooth-px", type=float, default=1.0,
                    help="描线前的高斯平滑 sigma（像素），抹掉二值掩膜的台阶")
    ap.add_argument("--skip-hooks", action="store_true")
    args = ap.parse_args()

    chars = list(dict.fromkeys(open(args.chars_file, encoding="utf-8").read().strip()))
    font = TTFont(args.font)
    cmap = font.getBestCmap()
    chars = [c for c in chars if ord(c) in cmap]
    print(f"输入 {len(chars)} 个字", flush=True)

    plan = None
    if not args.skip_hooks:
        order = [cmap[ord(ch)] for ch in chars]
        plan = detect_hook_plan(font["glyf"], order)
        print(f"[1/3] 无钩：{len(plan)} 个字形、{sum(len(v) for v in plan.values())} 处候选钩",
              flush=True)
    else:
        print("[1/3] 无钩：跳过", flush=True)

    print("[2/3] 笔画合并（保形并集）", flush=True)
    done, failed, cut_report, rejected = rebuild_merged(
        font, chars, cmap, args.px, args.margin_frac, args.smooth_px, plan)
    print(f"      重建 {len(done)} 字，失败 {len(failed)}", flush=True)
    print(f"      实际切钩 {sum(cut_report.values())} 处，覆盖 {len(cut_report)} 字；"
          f"闸门拦下 {len(rejected)} 处", flush=True)
    if rejected[:8]:
        print("      拦下样例:", rejected[:8], flush=True)
    if failed[:5]:
        print("      失败样例:", failed[:5], flush=True)

    font.save(args.out)
    print(f"[3/3] 已保存 {args.out}（曲线重拟合请另跑 curve_simplify.py）", flush=True)


if __name__ == "__main__":
    sys.exit(main())
