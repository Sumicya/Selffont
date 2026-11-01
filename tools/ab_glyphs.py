"""整字 A/B：同一批字、两个字体，逐字报像素差与点数/轮廓数，并出两个尺度的图。

为什么必须做这一步（2026-11-01 踩的坑）：端头那一轮我只截了 10× 的端头，放大后端点
本身那 6% 的胖看得清清楚楚，可旁边被一并改坏的字一个也没进画面——`永` 的点变成三角楔、
`字` 的 `子` 出白洞加发丝、`地` 的 `乚` 出白缝，XOR 到 21–31%，两张局部图全都「通过」。
**局部放大能证明局部对了，证明不了整个字没坏。**

所以改轮廓构造的提交，一律要跑这个脚本：

- 尺度一：整字 1×（每字按给定 em 渲染，不放大），A/B 并排 + 差异图；
- 尺度二：放大 ≥6× 的局部（`--zoom x0,y0,x1,y1` 给字体单位框），同一框两张对比；
- 数字：逐字 XOR px ÷ 并集 px 排序（贴前几名）、轮廓数、点数、每字是否变点。

用法：

    .venv/bin/python tools/ab_glyphs.py --a build/metrics/revert/preview.ttf \\
        --b build/metrics/quads/preview.ttf --chars 永字法地 --out build/metrics/ab

    # 只出数字不出图
    .venv/bin/python tools/ab_glyphs.py --a A.ttf --b B.ttf --chars 永字法地 --no-figure
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


# ---------------------------------------------------------------- 取轮廓

def contours(font_path: Path, ch: str):
    """返回 [(点列, on/off 标志)]，矢量取，不经栅格。"""
    from fontTools.pens.recordingPen import RecordingPen
    from fontTools.ttLib import TTFont
    font = TTFont(str(font_path))
    cmap = font.getBestCmap()
    if ord(ch) not in cmap:
        raise KeyError(ch)
    glyph = font.getGlyphSet()[cmap[ord(ch)]]
    pen = RecordingPen()
    glyph.draw(pen)
    rings, flags, cur, curf = [], [], [], []
    for op, args in pen.value:
        if op == "moveTo":
            cur, curf = [args[0]], [1]
        elif op == "lineTo":
            cur.append(args[0]); curf.append(1)
        elif op == "qCurveTo":
            pts = [a for a in args if a is not None]
            for a in pts[:-1]:
                cur.append(a); curf.append(0)
            cur.append(pts[-1]); curf.append(1)
        elif op in ("closePath", "endPath"):
            if cur:
                rings.append(cur); flags.append(curf)
                cur, curf = [], []
    return rings, flags


def render(font_path: Path, ch: str, em: int, box=None, center: str = "origin"):
    """整字栅格。`center` 决定摆法，而摆法会改数——必须显式写出来。

    - `origin`（默认，正确）：固定原点 + `anchor="ls"`，两个字体落在同一坐标系里。
    - `bbox`（旧，已知会凭空加位移）：各自按墨迹框居中。
    - `bbox-topleft`（旧）：各自把墨迹框左上角钉在 (em·0.028, em·0.028)。
      后两种留着只为复现 2026-11-01 报出的四个数，**不要拿它们做验收**：

      | 摆法 | em | 字 | 永 | 地 | 法 |
      | --- | --- | --- | --- | --- | --- |
      | origin | 1024 | 16.4% | 13.4% | 7.6% | 0.8% |
      | bbox | 360 | 21.6% | 18.2% | 7.6% | 18.7% |
      | bbox-topleft | 360 | 30.8% | 22.5% | 10.5% | 13.0% |

      同一对字体三个结果——「摆放差」能压过「字形差」，所以口径不写清楚，数就没意义。
    """
    box = box or int(em * 1.6)
    font = ImageFont.truetype(str(font_path), em)
    img = Image.new("L", (box, box), 255)
    d = ImageDraw.Draw(img)
    if center == "bbox":
        bb = d.textbbox((0, 0), ch, font=font)
        d.text(((box - bb[2] - bb[0]) // 2, (box - bb[3] - bb[1]) // 2), ch, font=font, fill=0)
    elif center == "bbox-topleft":
        bb = d.textbbox((0, 0), ch, font=font)
        pad = int(em * 0.028)
        d.text((pad - bb[0], pad - bb[1]), ch, font=font, fill=0)
    else:
        d.text((int(em * 0.3), int(em * 1.2)), ch, font=font, fill=0, anchor="ls")
    return np.asarray(img) < 128


# ---------------------------------------------------------------- 量

def compare(font_a: Path, font_b: Path, chars: str, em: int, center: str = "origin"):
    rows = []
    for ch in chars:
        ma = render(font_a, ch, em, center=center)
        mb = render(font_b, ch, em, center=center)
        xor = int((ma ^ mb).sum())
        union = int((ma | mb).sum()) or 1
        ra, fa = contours(font_a, ch)
        rb, fb = contours(font_b, ch)
        na, nb = len(ra), len(rb)
        pa = sum(len(r) for r in ra)
        pb = sum(len(r) for r in rb)
        rows.append({
            "字": ch,
            "XOR": xor,
            "并集": union,
            "XOR占比": round(xor / union, 4),
            "新增": int((ma & ~mb).sum()),
            "删去": int((mb & ~ma).sum()),
            "轮廓A": na, "轮廓B": nb,
            "点数A": pa, "点数B": pb,
            "点变": (na != nb) or (pa != pb),
            "闭合段数A": sum(f.count(0) for f in fa),
            "闭合段数B": sum(f.count(0) for f in fb),
        })
    rows.sort(key=lambda r: -r["XOR占比"])
    return rows


# ---------------------------------------------------------------- 出图

def fig_whole(font_a: Path, font_b: Path, chars: str, em: int, out: Path):
    tiles = []
    for ch in chars:
        ma = render(font_a, ch, em)
        mb = render(font_b, ch, em)
        img = np.full(ma.shape + (3,), 255, np.uint8)
        img[ma & mb] = (30, 30, 30)
        img[ma & ~mb] = (0, 90, 210)          # 只 A = 蓝
        img[mb & ~ma] = (210, 0, 0)           # 只 B = 红
        tiles.append(Image.fromarray(img))
    pad, label = 8, 16
    w = sum(t.width for t in tiles) + pad * (len(tiles) + 1)
    h = max(t.height for t in tiles) + label + pad * 2
    out_img = Image.new("RGB", (w, h), "white")
    pen = ImageDraw.Draw(out_img)
    f = ImageFont.load_default()
    x = pad
    for ch, t in zip(chars, tiles):
        out_img.paste(t, (x, pad + label))
        pen.text((x + 2, pad + 2), f"{ch} blue=A only red=B only", font=f, fill=(0, 0, 0))
        x += t.width + pad
    out_img.save(out)


def fig_zoom(font_a: Path, font_b: Path, ch: str, em: int, crop, out: Path):
    """放大裁剪：同一字体单位框，A 与 B 并排，倍数 = em/1000。"""
    def tile(path):
        font = ImageFont.truetype(str(path), em)
        side = int(em * 2.2)
        origin = (int(em * 0.5), int(em * 1.7))
        img = Image.new("L", (side, side), 255)
        ImageDraw.Draw(img).text(origin, ch, font=font, fill=0, anchor="ls")
        s = em / 1000.0
        x0, y0, x1, y1 = crop
        return img.crop((int(origin[0] + x0 * s), int(origin[1] - y1 * s),
                         int(origin[0] + x1 * s), int(origin[1] - y0 * s)))
    ta, tb = tile(font_a), tile(font_b)
    w = ta.width + tb.width + 24
    h = max(ta.height, tb.height) + 20
    out_img = Image.new("RGB", (w, h), "white")
    out_img.paste(ta.convert("RGB"), (8, 20))
    out_img.paste(tb.convert("RGB"), (ta.width + 16, 20))
    pen = ImageDraw.Draw(out_img)
    f = ImageFont.load_default()
    pen.text((8, 3), "A", font=f, fill=(0, 0, 0))
    pen.text((ta.width + 16, 3), "B", font=f, fill=(0, 0, 0))
    out_img.save(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="整字 A/B：像素差 + 点数/轮廓数 + 两个尺度的图")
    ap.add_argument("--a", type=Path, required=True)
    ap.add_argument("--b", type=Path, required=True)
    ap.add_argument("--chars", required=True)
    ap.add_argument("--em", type=int, default=1024, help="渲染字号（验收口径 1024）")
    ap.add_argument("--center", choices=("origin", "bbox", "bbox-topleft"), default="origin",
                    help="摆法：origin = 固定原点（正确）；bbox = 各自墨迹框居中（会加位移，只用于复现旧数）")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--zoom", default=None, help="放大框 x0,y0,x1,y1（字体单位），配合 --zoom-char")
    ap.add_argument("--zoom-char", default=None)
    ap.add_argument("--zoom-em", type=int, default=6000, help="放大用的 em（6000 = 6×）")
    ap.add_argument("--no-figure", action="store_true")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    rows = compare(args.a, args.b, args.chars, args.em, args.center)
    print(f"{'字':>2} {'XOR%':>6} {'XOR':>7} {'新增':>6} {'删去':>6} "
          f"{'轮廓':>7} {'点数':>11} {'点变':>4}")
    for r in rows:
        print(f"{r['字']:>2} {r['XOR占比'] * 100:>5.1f}% {r['XOR']:>7} {r['新增']:>6} {r['删去']:>6} "
              f"{r['轮廓A']:>3}→{r['轮廓B']:<3} {r['点数A']:>4}→{r['点数B']:<6} "
              f"{'是' if r['点变'] else '否':>3}")
    changed = sum(1 for r in rows if r['点变'])
    worst = [r for r in rows if r['XOR占比'] > 0.01]
    print(f"口径：em={args.em}，摆法={args.center}")
    print(f"\n{len(rows)} 字：点数/轮廓数变化 {changed} 字；XOR >1% 的 {len(worst)} 字"
          + (f"（最差 {worst[0]['字']} {worst[0]['XOR占比'] * 100:.1f}%）" if worst else ""))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    if not args.no_figure:
        out = args.out or Path("build/metrics/ab")
        out.mkdir(parents=True, exist_ok=True)
        fig_whole(args.a, args.b, args.chars, args.em, out / "whole.png")
        print(f"整字图 → {out / 'whole.png'}")
        if args.zoom and args.zoom_char:
            crop = tuple(float(v) for v in args.zoom.split(","))
            fig_zoom(args.a, args.b, args.zoom_char, args.zoom_em, crop, out / f"zoom-{args.zoom_char}.png")
            print(f"放大图 → {out / f'zoom-{args.zoom_char}.png'}")


if __name__ == "__main__":
    main()
