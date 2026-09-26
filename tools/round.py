#!/usr/bin/env python3
"""Selffont Round:把 Noto Sans SC(思源黑体同源)的笔画自由端头圆角化。

只圆「自由端头」:两个直角拐点夹一段短直线封口,且两侧长边近乎平行(T 形接口、
L 形拐角不是自由端头,一律不动)。端头替换为半圆弧;接口、字形骨架、字重不变。
这就是与资源圆体一类「逢角必圆」流派的差别:接口处永不产生凸起。

用法:python3 round.py <in.otf> <out.ttf> [--render out.png]
"""
import argparse
import math
import os
import sys

from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates

MIN_CAP = 18      # 端头封口最短(单位/1000upm),太短是衬线残迹
MAX_CAP = 115     # 太长不是笔画端头
NEIGHBOR = 2.5    # 两侧长边至少是封口长的倍数
COS_LIMIT = 0.20  # 端点须近垂直(θ≥78°):关节角(如 A 顶点 ~71°)不在此列
PARALLEL = -0.55  # 两长边平行:dot(d_in, d_out) 须小于此


def otf_to_glyf(font: TTFont, max_err: float = 1.0) -> None:
    """CFF → glyf(quadratic),经典 otf2ttf 流程。"""
    assert font.sfntVersion == "OTTO" and "CFF " in font
    glyph_order = font.getGlyphOrder()
    font["loca"] = newTable("loca")
    font["glyf"] = glyf = newTable("glyf")
    glyf.glyphOrder = glyph_order
    glyf.glyphs = {}
    glyph_set = font.getGlyphSet()
    for name in glyph_order:
        pen = TTGlyphPen(glyph_set)
        glyph_set[name].draw(Cu2QuPen(pen, max_err, reverse_direction=True))
        glyf.glyphs[name] = pen.glyph()
    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]
    hmtx = font["hmtx"]
    for name, glyph in glyf.glyphs.items():
        if hasattr(glyph, "xMin"):
            hmtx[name] = (hmtx[name][0], glyph.xMin)
    maxp = font["maxp"]
    maxp.tableVersion = 0x00010000
    for attr in ("maxPoints", "maxContours", "maxCompositePoints", "maxCompositeContours",
                 "maxZones", "maxTwilightPoints", "maxStorage", "maxFunctionDefs",
                 "maxInstructionDefs", "maxStackElements", "maxSizeOfInstructions",
                 "maxComponentElements", "maxComponentDepth"):
        setattr(maxp, attr, 0)
    maxp.maxZones = 1
    font.sfntVersion = "\x00\x01\x00\x00"


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length else (0.0, 0.0), length


def round_glyph(glyph, glyf_table) -> int:
    """原位圆角一个简单字形,返回圆掉的端头数。"""
    if glyph.isComposite() or glyph.numberOfContours <= 0:
        return 0
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    points = [(float(x), float(y), bool(on)) for (x, y), on in zip(coords, flags)]
    made = 0
    offset = 0
    new_points_all = []
    for c in range(len(ends)):
        start = 0 if c == 0 else ends[c - 1] + 1
        end = ends[c] + 1
        contour = points[start:end]
        n = len(contour)
        if os.environ.get("SF_DEBUG"):
            print(f"  contour {c}: [{start}:{end}] n={n} anchors={[i for i in range(n) if contour[i][1]]}")
        if n < 4:
            new_points_all.append(contour)
            continue
        # 锚点与其在循环里的相邻关系
        anchors = [i for i in range(n) if contour[i][2]]
        if len(anchors) < 3:
            new_points_all.append(contour)
            continue
        straight = {}
        for k, i in enumerate(anchors):
            j = anchors[(k + 1) % len(anchors)]
            straight[(i, j)] = _is_straight_wrap(contour, i, j, n)
        # 分段:每个锚点到下一锚点为一段;检测到的端头段替换为半圆弧,其余原样。
        segs = []
        for k in range(len(anchors)):
            i = anchors[k]
            j = anchors[(k + 1) % len(anchors)]
            interior = (list(range(i + 1, j)) if i < j
                        else list(range(i + 1, n)) + list(range(0, j)))
            segs.append({"a": i, "interior": interior, "cap": None})
        for k, i in enumerate(anchors):
            j = anchors[(k + 1) % len(anchors)]
            if not straight.get((i, j)):
                continue
            _, cap_len = _unit(contour[i], contour[j])
            if not (MIN_CAP <= cap_len <= MAX_CAP):
                continue
            prev_i = anchors[(k - 1) % len(anchors)]
            next_j = anchors[(k + 2) % len(anchors)]
            if not straight.get((prev_i, i)) or not straight.get((j, next_j)):
                continue
            d_in, prev_len = _unit(contour[i], contour[prev_i])     # 指向端头
            d_out, next_len = _unit(contour[next_j], contour[j])
            if prev_len < NEIGHBOR * cap_len or next_len < NEIGHBOR * cap_len:
                continue
            d_cap = _unit(contour[i], contour[j])[0]
            d_in_fwd = (-d_in[0], -d_in[1])                 # 行进方向(越过端头)
            if abs(d_in_fwd[0] * d_cap[0] + d_in_fwd[1] * d_cap[1]) > COS_LIMIT:
                continue
            if abs(d_out[0] * d_cap[0] + d_out[1] * d_cap[1]) > COS_LIMIT:
                continue
            # 两侧长边平行:它们都指向封口,平行时互为反向,点积 ≈ -1。
            if (d_in[0] * d_out[0] + d_in[1] * d_out[1]) > PARALLEL:
                continue
            if os.environ.get("SF_DEBUG"):
                print(f"    CAP seg {k}: {contour[i][:2]}→{contour[j][:2]} len={cap_len:.1f} "
                      f"v1={abs(d_in_fwd[0] * d_cap[0] + d_in_fwd[1] * d_cap[1]):.3f} "
                      f"v2={abs(d_out[0] * d_cap[0] + d_out[1] * d_cap[1]):.3f} "
                      f"par={d_in[0] * d_out[0] + d_in[1] * d_out[1]:.2f}")
            segs[k]["cap"] = (cap_len, d_in_fwd)
        if not any(s["cap"] for s in segs):
            new_points_all.append(contour)
            continue
        out = []
        skip_anchor = False
        for seg in segs:
            if seg["cap"] is not None:
                cap_len, d = seg["cap"]
                ax, ay = contour[seg["a"]][0], contour[seg["a"]][1]
                b = (seg["a"] + 1 + len(seg["interior"])) % n
                bx, by = contour[b][0], contour[b][1]
                # 真半圆头(禅丸式):两段 90° 二次弧,控制点在切线交点 A+r·d / B+r·d。
                # 单段抛物线肩部外鼓 55% 成方肩;两段弧肩部误差 <7%,肉眼即圆。
                r = cap_len * 0.5
                mx, my = (ax + bx) / 2, (ay + by) / 2
                apex = (mx + d[0] * r, my + d[1] * r)
                q1 = (ax + d[0] * r, ay + d[1] * r)
                q2 = (bx + d[0] * r, by + d[1] * r)
                out.append((q1[0], q1[1], False))
                out.append((apex[0], apex[1], True))
                out.append((q2[0], q2[1], False))
                skip_anchor = True  # 端头另一侧锚点被弧替代
                made += 1
                continue
            if not skip_anchor:
                out.append(contour[seg["a"]])
            skip_anchor = False
            out.extend(contour[t] for t in seg["interior"])
        new_points_all.append(out)
    # 写回
    flat, ends_out = [], []
    for contour in new_points_all:
        for x, y, on in contour:
            flat.append((x, y, on))
        ends_out.append(len(flat) - 1)
    glyph.coordinates = GlyphCoordinates([(int(round(x)), int(round(y))) for x, y, on in flat])
    glyph.flags = [bool(on) for _, _, on in flat]
    glyph.endPtsOfContours = ends_out
    glyph.recalcBounds(glyf_table)
    return made


def _is_straight_wrap(contour, i, j, n):
    """锚点 i→j 的循环直线判断。"""
    if i < j:
        return all(not contour[k][2] for k in range(i + 1, j))
    return all(not contour[k][2] for k in list(range(i + 1, n)) + list(range(0, j)))


WEIGHT_STYLE = {100: "Thin", 300: "Light", 400: "Regular", 500: "Medium",
                600: "SemiBold", 700: "Bold", 900: "Heavy"}


def rename_family(font: TTFont, family: str) -> None:
    """OFL 保留名合规:衍生字库整体改名,legacy/typographic 双模型都写。"""
    name = font["name"]
    weight = font["OS/2"].usWeightClass
    style = WEIGHT_STYLE.get(weight, str(weight))
    if style in ("Regular", "Bold"):
        legacy_family, legacy_style = family, style
    else:
        legacy_family, legacy_style = f"{family} {style}", "Regular"
    ps = legacy_family.replace(" ", "") + ("" if legacy_style == "Regular" else "-" + style)
    full = f"{legacy_family} {legacy_style}"
    for record in list(name.names):
        if record.nameID in (1, 3, 4, 6, 16, 17):
            name.removeNames(record.nameID, record.platformID, record.platEncID, record.langID)
    for pid, eid, lid in ((3, 1, 0x409), (1, 0, 0)):
        name.setName(legacy_family, 1, pid, eid, lid)
        name.setName(legacy_style, 2, pid, eid, lid)
        name.setName(full, 4, pid, eid, lid)
        name.setName(ps, 6, pid, eid, lid)
        name.setName(f"Selffont Round; derived from Noto Sans SC (OFL); {full}", 3, pid, eid, lid)
        if style not in ("Regular", "Bold"):
            name.setName(family, 16, pid, eid, lid)
            name.setName(style, 17, pid, eid, lid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--render", help="同时渲染样张 PNG(需 pillow)")
    parser.add_argument("--only-round", action="store_true", help="跳过 CFF 转换,直接圆角已转换的 TTF")
    parser.add_argument("--family", help="改名:衍生物家族名(OFL 保留名合规)")
    args = parser.parse_args()

    font = TTFont(args.input)
    if not args.only_round:
        otf_to_glyf(font)
    glyf = font["glyf"]
    total = rounded_glyphs = 0
    for name in font.getGlyphOrder():
        glyph = glyf[name]
        made = round_glyph(glyph, glyf)
        if made:
            rounded_glyphs += 1
            total += made
    if args.family:
        rename_family(font, args.family)
    font.save(args.output)
    print(f"rounded {total} caps in {rounded_glyphs} glyphs"
          + (f"; renamed to {args.family!r}" if args.family else ""))

    if args.render:
        from PIL import Image, ImageDraw, ImageFont
        text = "永国圆禅龘鬱饕Aa123 自圆角"
        rows = []
        for label, path in [("rounded", args.output),
                            ("source", args.input)]:
            try:
                face = ImageFont.truetype(path, 88)
                box = face.getbbox(text)
                img = Image.new("RGB", (box[2] - box[0] + 40, box[3] - box[1] + 30), "white")
                ImageDraw.Draw(img).text((20 - box[0], 15 - box[1]), text, font=face, fill="black")
                rows.append(img)
            except Exception as error:
                print(f"render {label} failed: {error}")
        width = max(img.width for img in rows)
        height = sum(img.height for img in rows)
        sheet = Image.new("RGB", (width, height), "white")
        y = 0
        for img in rows:
            sheet.paste(img, (0, y))
            y += img.height
        sheet.save(args.render)
        print(f"rendered {args.render}")


if __name__ == "__main__":
    main()
