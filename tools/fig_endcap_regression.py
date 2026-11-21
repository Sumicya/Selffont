"""出两张图：整字 1× 的 A/B，与放大 6× 的坏点特写。

A = 回滚后的字体（`/tmp/base/preview.ttf`），B = 回归版（`a92a9bd`，`/tmp/reg/preview.ttf`）。

尺度一是「整字 1×」：证明坏的是整个字，不是某个角的裁切；
尺度二是「放大 6×」：证明最坏的连通块长什么样。
只给放大图会被端点那 6% 的胖骗过去——那是 2026-11-01 的教训。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi

A_FONT = Path("/tmp/base/preview.ttf")
B_FONT = Path("/tmp/reg/preview.ttf")
LABEL = Path("/tmp/lab/preview.ttf")
CHARS = "永字法地"
OUT = Path("docs/evidence")
EM = 320            # 整字 1×：只改字号，不做任何放大


def render(font: Path, ch: str, em: int = EM, box: int | None = None):
    box = box or int(em * 1.7)
    f = ImageFont.truetype(str(font), em)
    img = Image.new("L", (box, box), 255)
    ImageDraw.Draw(img).text((int(em * 0.3), int(em * 1.25)), ch, font=f, fill=0, anchor="ls")
    return np.asarray(img) < 128


def label(text: str, max_width: int, size: int = 26) -> Image.Image:
    """标签按列宽自适应：超宽就缩字号。不裁字——上一版 label 比列宽还宽，
    被下一列的图盖掉了半句（"A 回滚后" 显示成 "A 后"）。"""
    while size > 10:
        f = ImageFont.truetype(str(LABEL), size)
        bb = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=f)
        if bb[2] - bb[0] <= max_width - 8:
            break
        size -= 2
    f = ImageFont.truetype(str(LABEL), size)
    bb = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=f)
    img = Image.new("RGB", (max(bb[2] - bb[0] + 8, 1), max(bb[3] - bb[1] + 8, 1)), "white")
    ImageDraw.Draw(img).text((4 - bb[0], 4 - bb[1]), text, font=f, fill=(0, 0, 0))
    return img


def fig_whole(path: Path):
    """每字三栏：A（灰）、B（黑）、差异（红=只 B，蓝=只 A）。"""
    rows = []
    for ch in CHARS:
        ma, mb = render(A_FONT, ch), render(B_FONT, ch)
        # 裁到两者并集外框
        ys, xs = np.nonzero(ma | mb)
        pad = 10
        sl = (slice(max(ys.min() - pad, 0), ys.max() + pad), slice(max(xs.min() - pad, 0), xs.max() + pad))
        ma, mb = ma[sl], mb[sl]

        t1 = np.full(ma.shape + (3,), 255, np.uint8)
        t1[ma] = (150, 150, 150)
        t2 = np.full(ma.shape + (3,), 255, np.uint8)
        t2[mb] = (0, 0, 0)
        t3 = np.full(ma.shape + (3,), 255, np.uint8)
        t3[ma & mb] = (185, 185, 185)
        t3[mb & ~ma] = (205, 0, 0)
        t3[ma & ~mb] = (0, 80, 200)
        rows.append((ch, [Image.fromarray(x) for x in (t1, t2, t3)]))

    tw = max(t.width for _, ts in rows for t in ts)
    th = max(t.height for _, ts in rows for t in ts)
    gap, lab_h = 12, 32
    W = gap + (tw + gap) * 3
    H = gap + len(rows) * (th + lab_h + gap)
    out = Image.new("RGB", (W, H), "white")

    heads = ["A 回滚后", "B 回归版", "差异 红B 蓝A"]
    for i, h in enumerate(heads):
        out.paste(label(h, tw), (gap + i * (tw + gap), 2))

    y = gap + lab_h
    for ch, tiles in rows:
        x = gap
        for t in tiles:
            out.paste(t, (x, y + lab_h - 18))
            x += tw + gap
        out.paste(label(ch, tw), (gap, y - 6))
        y += th + lab_h + gap
    out.save(path)
    print(f"{path}  {out.size}")


def fig_zoom(path: Path):
    """每字取最大差异连通块，6× 放大，A / B / 差异 三栏。"""
    scale = 6
    base_em = 260
    tiles = []
    for ch in CHARS:
        ma = render(A_FONT, ch, em=base_em)
        mb = render(B_FONT, ch, em=base_em)
        d = ma ^ mb
        lab, n = ndi.label(ndi.binary_dilation(d, iterations=2))
        if n == 0:
            continue
        sizes = ndi.sum(d, lab, range(1, n + 1))
        k = int(np.argmax(sizes)) + 1
        ys, xs = np.nonzero(lab == k)
        cy, cx = int(np.mean(ys)), int(np.mean(xs))
        half_y = int((ys.max() - ys.min()) * 0.75 + 8)
        half_x = int((xs.max() - xs.min()) * 0.75 + 8)
        half = max(half_y, half_x, 24)
        sl = (slice(max(cy - half, 0), cy + half + 1), slice(max(cx - half, 0), cx + half + 1))
        a, b = ma[sl], mb[sl]
        t1 = np.full(a.shape + (3,), 255, np.uint8); t1[a] = (150, 150, 150)
        t2 = np.full(a.shape + (3,), 255, np.uint8); t2[b] = (0, 0, 0)
        t3 = np.full(a.shape + (3,), 255, np.uint8)
        t3[a & b] = (190, 190, 190)
        t3[b & ~a] = (205, 0, 0)
        t3[a & ~b] = (0, 80, 200)
        trio = [Image.fromarray(x).resize((a.shape[1] * scale, a.shape[0] * scale), Image.NEAREST)
                for x in (t1, t2, t3)]
        tiles.append((ch, trio))

    if not tiles:
        return
    tw = max(t.width for _, ts in tiles for t in ts)
    th = max(t.height for _, ts in tiles for t in ts)
    gap, lab_h = 14, 34
    W = gap + (tw + gap) * 3
    H = gap + len(tiles) * (th + lab_h + gap)
    out = Image.new("RGB", (W, H), "white")
    for i, h in enumerate(["A 回滚后", "B 回归版", "差异  红=只B  蓝=只A"]):
        out.paste(label(h, tw), (gap + i * (tw + gap), 2))
    y = gap + lab_h
    for ch, trio in tiles:
        out.paste(label(f"{ch}", tw), (gap, y - 8))
        x = gap
        for t in trio:
            out.paste(t, (x, y + lab_h - 20))
            x += tw + gap
        y += th + lab_h + gap
    out.save(path)
    print(f"{path}  {out.size}")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_whole(OUT / "2026-11-01-endcap-ab-whole-1024.png")
    fig_zoom(OUT / "2026-11-01-endcap-ab-zoom6x.png")
