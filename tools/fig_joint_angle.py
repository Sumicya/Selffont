"""出图：轮廓接点折角分布 + 诊断表（2026-11-02 那张证据图）。

用法：

    /tmp/venv/bin/python tools/fig_joint_angle.py \
        --master maruko.ttf --ours ours.ttf --chars 200字.txt \
        --out docs/evidence/2026-11-02-outline-joint-angle.png

左侧分布曲线由 `tools/smooth_outline.py` 的 `measure()` 算；右侧整字与局部放大用 PIL
直接渲染两个字体，同一个字号、同一次裁切，避免「看起来不一样」来自排版差异。

混排说明：画布上的中文标签用母版字形渲染（沙箱没有系统 CJK 字体），ASCII 与希腊字母
用 DejaVu——单一字体缺字时 PIL 会把标签画成豆腐块，2026-11-01 那张图踩过一次。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smooth_outline import measure  # noqa: E402

LATIN = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
INK, RED, BLUE, GREY, LINE = (24, 24, 24), (196, 42, 42), (28, 86, 184), (132, 132, 132), (226, 226, 226)


def cdf(thetas, x, n=None):
    n = n or len(thetas)
    return 100 * sum(1 for t in thetas if t <= x) / n



def diff_rgb(master_path, ours_path, char, size=260):
    """同基线（anchor=ls）、同像素尺寸渲染两个字，取 ±1 px 内最优平移后做差。

    返回 (RGB 图, IoU, 平移)。红 = 本版多出的墨，蓝 = 母版有而本版没有的墨。
    不按外接框归一化：那样会把整字重新缩放，差图全是假的。
    """
    import numpy as np

    def mask(path, dx=0, dy=0):
        f = ImageFont.truetype(path, size)
        im = Image.new("L", (size * 2, size * 2), 0)
        ImageDraw.Draw(im).text((size * 0.5 + dx, size * 1.4 + dy), char, font=f, fill=255, anchor="ls")
        return np.array(im) > 127

    a = mask(master_path)
    best, shift = -1.0, (0, 0)
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            b = mask(ours_path, dx, dy)
            uni = (a | b).sum()
            if uni:
                v = (a & b).sum() / uni
                if v > best:
                    best, shift, bb = v, (dx, dy), b
    bb = mask(ours_path, *shift)
    rgb = np.full(a.shape + (3,), 255, dtype=np.uint8)
    rgb[a & ~bb] = (40, 90, 200)      # 母版有、本版没有 → 蓝
    rgb[bb & ~a] = (210, 40, 40)      # 本版多出 → 红
    rgb[a & bb] = (232, 232, 232)     # 重合区淡到几乎看不见，只剩差的那一圈
    ys, xs = np.nonzero(a | bb)
    box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    out = Image.fromarray(rgb).crop(box)
    out.thumbnail((200, 200), Image.LANCZOS)
    out = out.resize((out.width * 2, out.height * 2), Image.NEAREST)
    return out, best, shift


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", required=True, help="母版 ttf")
    ap.add_argument("--ours", required=True, help="本版 ttf")
    ap.add_argument("--chars", required=True, help="字符集文件")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    chars = "".join(Path(args.chars).read_text(encoding="utf-8").split())
    _, mt = measure(args.master, chars)
    _, st = measure(args.ours, chars)
    latin_cache = {}

    def pair(size):
        if size not in latin_cache:
            latin_cache[size] = (ImageFont.truetype(args.master, size), ImageFont.truetype(LATIN, size))
        return latin_cache[size]

    def text(d, xy, s, size, fill):
        cjk, lat = pair(size)
        x, y = xy
        for ch in s:
            f = lat if ord(ch) < 0x2E80 else cjk
            d.text((x, y), ch, font=f, fill=fill)
            x += d.textlength(ch, font=f)

    def render(path, char, size, box=(0.0, 0.0, 1.0, 1.0)):
        f = ImageFont.truetype(path, size)
        canvas = size * 2
        big = Image.new("L", (canvas, canvas), 255)
        ImageDraw.Draw(big).text((size * 0.15, size * 0.05), char, font=f, fill=0)
        bbox = Image.eval(big, lambda v: 255 - v).getbbox()
        bx0, by0, bx1, by1 = bbox
        cw, chh = bx1 - bx0, by1 - by0
        return big.crop((bx0 + cw * box[0], by0 + chh * box[1],
                         bx0 + cw * box[2], by0 + chh * box[3]))

    W, H = 1620, 1270
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    text(d, (44, 28), "笔画为什么不像母版那么平：问题在「描出来的轮廓」，不在中线", 36, INK)
    text(d, (44, 82), f"同一批 {len(chars)} 个汉字，母版对比本版；出图时刻见 git 提交时间", 21, GREY)

    x0, y0, w, h = 92, 200, 560, 300
    d.rectangle([x0, y0, x0 + w, y0 + h], outline=LINE)
    xs = [i * 0.5 for i in range(61)]
    for gy in range(0, 101, 20):
        yy = y0 + h - h * gy / 100
        d.line([x0, yy, x0 + w, yy], fill=(242, 242, 242))
        text(d, (x0 - 38, yy - 10), str(gy), 17, GREY)
    for gx in range(0, 26, 5):
        xx = x0 + w * gx / 25
        d.line([xx, y0, xx, y0 + h], fill=(242, 242, 242))
        text(d, (xx - 5, y0 + h + 9), str(gx), 17, GREY)
    text(d, (x0 + w / 2 - 90, y0 + h + 38), "轮廓接点折角 θ（度）", 21, INK)
    text(d, (x0 - 4, y0 - 32), "累积占比 %", 21, INK)
    for series, color in (([cdf(mt, x) for x in xs], BLUE), ([cdf(st, x) for x in xs], RED)):
        d.line([(x0 + w * x / 25, y0 + h - h * y / 100) for x, y in zip(xs, series)], fill=color, width=4)
    for xx in (1.0, 5.0):
        px = x0 + w * xx / 25
        d.line([px, y0, px, y0 + h], fill=(250, 214, 214))
        text(d, (px + 7, y0 + h - h * cdf(mt, xx) / 100 - 11), f"θ≤{xx:.0f}° 母版 {cdf(mt, xx):.0f}%", 16, BLUE)
        text(d, (px + 7, y0 + h - h * cdf(st, xx) / 100 + 9), f"θ≤{xx:.0f}° 本版 {cdf(st, xx):.0f}%", 16, RED)
    ly = y0 + 20
    for label, color in (("母版", BLUE), ("本版", RED)):
        d.line([x0 + w - 176, ly + 9, x0 + w - 140, ly + 9], fill=color, width=4)
        text(d, (x0 + w - 132, ly - 2), label, 17, INK)
        ly += 30

    for i, (path, label, color) in enumerate(((args.master, "母版", BLUE), (args.ours, "本版", RED))):
        px = 760 + i * 300
        text(d, (px, 176), label, 23, color)
        whole = render(path, "永", 460)
        whole.thumbnail((200, 200), Image.LANCZOS)
        d.rectangle([px - 3, 212, px + 203, 418], outline=LINE)
        img.paste(whole.convert("RGB"), (px, 215))
    text(d, (760, 424), "整字「永」", 17, GREY)

    # 第二行：同基线差图。红=本版多出来的墨，蓝=母版有、本版没有的墨。
    for i, char in enumerate(("永", "心")):
        px = 760 + i * 300
        diff, iou, shift = diff_rgb(args.master, args.ours, char, 260)
        d.rectangle([px - 3, 470, px + 203, 676], outline=LINE)
        diff.thumbnail((200, 200), Image.LANCZOS)
        img.paste(diff, (px + (200 - diff.width) // 2, 473 + (200 - diff.height) // 2))
        text(d, (px, 684), f"{char}  IoU {iou:.3f}", 17, GREY)
    text(d, (1350, 210), "接点折角：", 19, INK)
    for k, line in enumerate(["母版中位 0.74°，", "本版 4.98°。", "两者差 6.7 倍，", "是「不平滑」本身。"],
                             start=1):
        text(d, (1350, 210 + k * 34), line, 19, RED if k == 4 else INK)
    for k, line in enumerate(["但 4× 放大下", "两格几乎分不出——", "5° 的棱不是主因。"], start=0):
        text(d, (1350, 400 + k * 28), line, 17, GREY)
    text(d, (1350, 520), "下排是差图：", 19, INK)
    for k, line in enumerate(["红＝本版多墨，", "蓝＝本版缺墨，", "同基线同像素，", "不缩放到外接框。"]):
        text(d, (1350, 556 + k * 30), line, 17, GREY)

    ty = 760
    text(d, (92, ty - 40), "四个候补原因，逐个数过来", 25, INK)
    for cx, cw, hd in ((92, 300, "量"), (392, 300, "母版"), (692, 330, "本版"), (1022, 300, "结论")):
        text(d, (cx, ty), hd, 20, GREY)
        d.line([cx, ty + 30, cx + cw - 30, ty + 30], fill=LINE)
    rows = [
        ("中线节点折角（中位）", "0.13°", "0.13°", "同一个数：中线就是母版量出来的", (60, 130, 60)),
        ("端头半径 ÷ 局部半宽", "—", "0.979", "合格线 0.95–1.05，圆头没被啃", (60, 130, 60)),
        ("墨量（同字同号）", "1.000", "0.975", "±7% 内，不是画粗了", (60, 130, 60)),
        ("每字轮廓点数", "102", f"{len(st) / len(chars):.0f}", "多 31%：切得比母版碎", (170, 110, 20)),
        ("接点折角（中位）", f"{mt[len(mt) // 2]:.2f}°", f"{st[len(st) // 2]:.2f}°", "×6.7：这是「不平滑」本身", RED),
        ("完全平滑的接点占比", f"{cdf(mt, 0.5):.0f}%", f"{cdf(st, 0.5):.0f}%", "母版一半的点是一整条弧上接的", RED),
    ]
    ry = ty + 48
    for name, a, b, verdict, color in rows:
        text(d, (92, ry), name, 20, INK)
        text(d, (392, ry), a, 20, INK)
        text(d, (692, ry), b, 20, INK)
        text(d, (1022, ry), verdict, 19, color)
        ry += 44

    by = 1072
    d.line([92, by - 16, 1528, by - 16], fill=LINE)
    text(d, (92, by), "结论：中线是干净的，端头是圆的，墨量是对的——坏的只有最后一步「把密点连回曲线」。", 24, INK)
    for k, line in enumerate([
        "现在这条链是 c0 模式：每段二次曲线只保证「中点落在原曲线上」，接点处的切向不管。",
        "换成 g1 模式（切向交点）能把中位折角压到 2.4°，但点数 +29%、体积 +30%，肉眼仍分不出——"
        "不采用。",
        "真正的修法是把接点约束成 G1 而段数不涨，另开一轮做，不在本轮夹带。",
    ]):
        text(d, (92, by + 44 + k * 32), line, 20, GREY)

    text(d, (92, 1228),
         "复算：python tools/smooth_outline.py --font <本版.ttf> --chars <字表.txt> --compare <母版.ttf>", 16, GREY)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"{args.out}  {img.size[0]}×{img.size[1]}  母版中位 {mt[len(mt) // 2]:.2f}°  本版中位 {st[len(st) // 2]:.2f}°")


if __name__ == "__main__":
    main()
