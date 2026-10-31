"""高清对照图：1× 输出、不做任何像素放大。

上一版的局部图是「96 px 渲染 + 4× 最近邻」，放大不会多出信息，端头看着发方有一半是
像素化造成的。这一份按「渲染多少 px 就是多少 px」出图：

- `--em` 是每个字的身高像素（1000 单位 = 1 em）。默认 512，篱 的墨迹高 0.944 em = 483 px。
- 出图后断言：宽 ≤ 1200；整字图里每个字的墨迹高 ≥ 400 px；没有重采样（只贴不缩放）。
- `--crop x0,y0,x1,y1` 给字体单位的裁切框，两个字体用**同一个框**，尺寸一模一样，
  可以直接上下对看。

用法：

    # 整字：母版 / 本版 并排
    .venv/bin/python tools/hires_render.py --char 篱 --em 512 \
        --font 母版.ttf --font 本版.ttf --out docs/evidence/xxx.png

    # 竹头裁切：同一框、上下两行
    .venv/bin/python tools/hires_render.py --char 篱 --em 1024 --crop 58,-90,954,855 \
        --font 母版.ttf --font 本版.ttf --out docs/evidence/xxx-crop.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def render(font_path: Path, ch: str, em: int, pad: int = 6) -> Image.Image:
    """渲染一个字的整幅（白底黑字），裁到墨迹四周 pad（像素）。"""
    font = ImageFont.truetype(str(font_path), em)
    side = int(em * 2.2)
    canvas = Image.new("L", (side, side), 255)
    ImageDraw.Draw(canvas).text((side // 2, side // 2), ch, font=font, fill=0, anchor="mm")
    ink = np.asarray(canvas) < 128
    ys, xs = np.where(ink)
    if len(ys) == 0:
        raise SystemExit(f"{font_path} 里没有 {ch} 的墨迹")
    box = (max(int(xs.min()) - pad, 0), max(int(ys.min()) - pad, 0),
           min(int(xs.max()) + pad + 1, side), min(int(ys.max()) + pad + 1, side))
    return canvas.crop(box)


def render_crop(font_path: Path, ch: str, em: int, crop) -> Image.Image:
    """按字体单位裁切：两个字体给同一个框，输出的像素尺寸完全一致。"""
    font = ImageFont.truetype(str(font_path), em)
    side = int(em * 2.2)
    origin = (int(em * 0.5), int(em * 1.7))      # 左对齐 + 基线
    canvas = Image.new("L", (side, side), 255)
    ImageDraw.Draw(canvas).text(origin, ch, font=font, fill=0, anchor="ls")
    s = em / 1000.0
    x0, y0, x1, y1 = crop
    return canvas.crop((int(origin[0] + x0 * s), int(origin[1] - y1 * s),
                        int(origin[0] + x1 * s), int(origin[1] - y0 * s)))


def stack(tiles, labels, pad=8, label_w=34):
    w = max(t.width for t in tiles) + label_w
    h = sum(t.height for t in tiles) + pad * (len(tiles) - 1)
    out = Image.new("L", (w, h), 255)
    pen = ImageDraw.Draw(out)
    y = 0
    tag_font = ImageFont.truetype(str(labels[0][1]), 22)
    for (tag, _font), tile in zip(labels, tiles):
        pen.text((2, y + 2), tag, font=tag_font, fill=0)
        out.paste(tile, (label_w, y))
        y += tile.height + pad
    return out


def side_by_side(tiles, labels):
    w = sum(t.width for t in tiles) + 10 * (len(tiles) - 1)
    h = max(t.height for t in tiles) + 26
    out = Image.new("L", (w, h), 255)
    pen = ImageDraw.Draw(out)
    tag_font = ImageFont.truetype(str(labels[0][1]), 22)
    x = 0
    for (tag, _font), tile in zip(labels, tiles):
        box = pen.textbbox((0, 0), tag, font=tag_font)
        pen.text((x + (tile.width - (box[2] - box[0])) // 2, 2), tag, font=tag_font, fill=0)
        out.paste(tile, (x, 26))
        x += tile.width + 10
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="1× 高清对照图（不放大）")
    ap.add_argument("--char", default="篱")
    ap.add_argument("--em", type=int, default=512)
    ap.add_argument("--font", type=Path, action="append", required=True, help="可给多次，按顺序出图")
    ap.add_argument("--label", action="append", default=None)
    ap.add_argument("--crop", default=None, help="字体单位裁切框 x0,y0,x1,y1（给同一个框）")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-width", type=int, default=1200)
    ap.add_argument("--min-ink", type=int, default=400)
    args = ap.parse_args()

    labels = args.label or ["母版", "本版"]
    assert len(labels) == len(args.font), "标签数与字体数要对上"

    if args.crop:
        crop = tuple(float(v) for v in args.crop.split(","))
        tiles = [render_crop(f, args.char, args.em, crop) for f in args.font]
        img = stack(tiles, list(zip(labels, args.font)))
    else:
        tiles = [render(f, args.char, args.em) for f in args.font]
        img = side_by_side(tiles, list(zip(labels, args.font)))

    ink_h = [int((np.asarray(t) < 128).sum(axis=1).nonzero()[0].size) for t in tiles]
    if not args.crop:
        assert min(ink_h) >= args.min_ink, f"墨迹高 {ink_h} 不到 {args.min_ink} px：把 --em 调大"
    assert img.width <= args.max_width, f"图宽 {img.width} 超过 {args.max_width}"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"{args.out}  {img.width}×{img.height}  em={args.em}  "
          f"每字墨迹高 {[t.height for t in tiles]} px（裁边后），1× 无放大")


if __name__ == "__main__":
    main()
