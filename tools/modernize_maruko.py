"""把 Maruko 做成"干净现代化"字形的流水线：笔画合并 → 曲线重拟合。

本步只做两件事，都是可量化、已验证的：

1. **笔画合并（保形并集）**：光栅化后**直接描合并后的墨迹**，不做骨架重造。
   并集自然干掉了"相交笔画各自独立轮廓、靠非零环绕叠在一起"的隐藏重叠，形状本身不动。
   拿"骨架 × 常数半径"当重建源会把原设计整个丢掉——转角削圆、收笔变圆头、`日` 这类
   窄空腔直接被两侧笔画堵死（实测 `春` IoU 0.698、缺墨 22.4%，不是调参能救的）。
2. **曲线重拟合**（`curve_simplify.py`，另跑）：第 1 步写出来的是折线（每字上万点），
   必须重拟合回二次贝塞尔。描线前对掩膜做 1 px 高斯平滑，让 marching squares 取到
   亚像素边界；不平滑的话二值台阶是 ±0.5 px 的方波，拟合器只能把每个折点都留下
   （实测「街」精简后仍剩 1598 点，平滑后 185 点）。

**无钩默认关闭**（`--hooks` 打开）。原因见 `hook_erase.py`：墨迹级切法的两条判据
（交叉点短刺、笔尖 2.2W 内转角）能抓住 `乙`/`了`/`子`/`电`/`也`/`九`/`巴`/`包`/`必`，
但分不开"钩"和"点"——`广` 上面那个点的笔尖转角 44°，比 `乙` 的 26°、`了` 的 19°
都高，结构上它挂在横的中间、只形成 1 长 1 短两条边，而 `乙` 的钩根是 1 长 2 短、
`了` 是 2 长 1 短。单纯数边数仍会误剪，所以这一步先不放进正式产出。

用法：
    python3 tools/modernize_maruko.py --font MarukoSC-Regular.ttf --chars-file chars.txt \
        --out ModernSC-Regular.ttf --px 2000
    python3 tools/curve_simplify.py ModernSC-Regular.ttf ModernSC-Regular.ttf.simplified \
        --chars "$(cat chars.txt)" --tolerance 2.5 --seg-len 1.0
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_erase import compare_glyphs, trim_hooks  # noqa: E402
from stroke_width_normalize_prototype import glyph_from_mask, raster_mask  # noqa: E402


def _contours_of(font, gname):
    glyph = font["glyf"][gname]
    coords, ends, flags = glyph.getCoordinates(font["glyf"])
    return split_contours(coords, ends, flags)


def rebuild_merged(font, chars, cmap, px, margin_frac, smooth_px=1.0, hooks=True,
                   guard_iou=0.90):
    """无钩（墨迹级）→ 保形并集，一步出形状。

    ``trim_hooks`` 作用在掩膜上，改完直接描线，轮廓的点数/点序/绕向全部重新生成，
    不存在"把内腔翻成实心"这类轮廓手术的副作用。切完与原文比对，IoU 低于
    ``guard_iou`` 就回退到未切的掩膜——闸门只兜底，不参与设计。
    """
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
            applied = 0
            basemask = mask
            if hooks:
                trimmed, applied = trim_hooks(mask)
                if applied:
                    basemask = trimmed
            original = glyf[gname]
            glyph = glyph_from_mask(basemask, font, transform, smooth_px)
            if hooks and applied:
                iou, _ = compare_glyphs(original, glyph, glyf)
                if iou < guard_iou:
                    rejected.append((ch, f"iou {iou:.2f}"))
                    applied = 0
                    glyph = glyph_from_mask(mask, font, transform, smooth_px)
            glyf[gname] = glyph
            # 重描后 xMin 会动，hmtx 的 lsb 必须跟着走，否则走 getGlyphSet() 的
            # 下游工具会把整字平移 lsb-xMin（实测「个」被移 20 单位、IoU 0.98→0.63）。
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
    ap.add_argument("--hooks", action="store_true",
                    help="尝试无钩。默认关闭：当前检测会误剪「点」等独立短笔画")
    args = ap.parse_args()

    chars = list(dict.fromkeys(open(args.chars_file, encoding="utf-8").read().strip()))
    font = TTFont(args.font)
    cmap = font.getBestCmap()
    chars = [c for c in chars if ord(c) in cmap]
    print(f"输入 {len(chars)} 个字", flush=True)

    print("[1/2] 笔画合并（保形并集）" + (" + 无钩" if args.hooks else ""), flush=True)
    hooks = bool(args.hooks)
    done, failed, cut_report, rejected = rebuild_merged(
        font, chars, cmap, args.px, args.margin_frac, args.smooth_px, hooks=hooks)
    print(f"      重建 {len(done)} 字，失败 {len(failed)}", flush=True)
    print(f"      实际切钩 {sum(cut_report.values())} 处，覆盖 {len(cut_report)} 字；"
          f"闸门拦下 {len(rejected)} 处", flush=True)
    if rejected[:8]:
        print("      拦下样例:", rejected[:8], flush=True)
    if failed[:5]:
        print("      失败样例:", failed[:5], flush=True)

    font.save(args.out)
    print(f"[2/2] 已保存 {args.out}（曲线重拟合请另跑 curve_simplify.py）", flush=True)


if __name__ == "__main__":
    sys.exit(main())
