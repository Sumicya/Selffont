#!/usr/bin/env python3
"""Create a research-only Tsukushi A D/400 hook-end preview.

Only the eight previously selected hook cuts in the 63-entry sample are changed.
All corner, short-turn, stroke-width, frame, and production-font processing is omitted.
The source and output TTFs must stay outside the repository.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates

import hook_cut


CHARS_63 = (
    "一二三十口日回国了乙人入八木林森永心必水走建进这远道你好中国"
    "语言文字书写规范长美丽颜色锦绣风雨雪龙马鸟虫鱼电子已己巳也包囚暖田"
)
HOOK_CANDIDATES = "乙也了包子己已电"
EXPECTED_HOOKS = 8
EXPECTED_CHANGED_GLYPHS = 7


def signature(glyph, glyf_table):
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    return (
        tuple((int(x), int(y)) for x, y in coords),
        tuple(int(end) for end in ends),
        tuple(bool(flag) for flag in flags),
    )


def round_cap(contour, n, i, j):
    """Replace the selected hook loop with two G1-joined quadratic cap arcs."""
    ax, ay = contour[i][0], contour[i][1]
    bx, by = contour[j][0], contour[j][1]
    prev = contour[(i - 1) % n]
    next_point = contour[(j + 1) % n]
    dx, dy = ax - prev[0], ay - prev[1]
    dlen = math.hypot(dx, dy) or 1.0
    incoming = (dx / dlen, dy / dlen)
    ox, oy = next_point[0] - bx, next_point[1] - by
    olen = math.hypot(ox, oy) or 1.0
    outgoing = (ox / olen, oy / olen)
    gx, gy = bx - ax, by - ay
    glen = math.hypot(gx, gy) or 1.0
    gate = (gx / glen, gy / glen)
    normal = (-gate[1], gate[0])
    if incoming[0] * normal[0] + incoming[1] * normal[1] < 0:
        normal = (-normal[0], -normal[1])

    # Match the existing contour tangents at both cap ends. Equal-length controls
    # place the join halfway between them, where the two quadratic arcs are G1.
    r = glen * 0.5
    q1 = (ax + incoming[0] * r, ay + incoming[1] * r)
    q2 = (bx - outgoing[0] * r, by - outgoing[1] * r)
    apex = ((q1[0] + q2[0]) * 0.5, (q1[1] + q2[1]) * 0.5)
    gate_mid = ((ax + bx) * 0.5, (ay + by) * 0.5)
    outward = ((apex[0] - gate_mid[0]) * normal[0]
               + (apex[1] - gate_mid[1]) * normal[1])

    # The cap must bulge out from the gate, match both endpoint tangents, and
    # meet with a common tangent at the apex; otherwise the candidate is unsafe.
    left = (apex[0] - q1[0], apex[1] - q1[1])
    right = (q2[0] - apex[0], q2[1] - apex[1])
    cross = left[0] * right[1] - left[1] * right[0]
    dot = left[0] * right[0] + left[1] * right[1]
    if outward <= 0 or abs(cross) > 1e-8 or dot <= 0:
        raise AssertionError("Rounded cap is inward-facing or not G1-continuous")
    for vector, tangent in (
        ((q1[0] - ax, q1[1] - ay), incoming),
        ((bx - q2[0], by - q2[1]), outgoing),
    ):
        end_cross = vector[0] * tangent[1] - vector[1] * tangent[0]
        end_dot = vector[0] * tangent[0] + vector[1] * tangent[1]
        if abs(end_cross) > 1e-8 or end_dot <= 0:
            raise AssertionError("Rounded cap does not match an endpoint tangent")
    return [(ax, ay, True), (q1[0], q1[1], False),
            (apex[0], apex[1], True), (q2[0], q2[1], False), (bx, by, True)]


def apply_round_cuts(glyph, glyf_table, hooks):
    """Apply only the local research cap; leave the shared production helper untouched."""
    if not hooks:
        return 0
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    contours = hook_cut.split_contours(coords, ends, flags)
    by_contour = {h[0]: h for h in hooks}
    new_contours = []
    made = 0
    for ci, contour in enumerate(contours):
        if ci not in by_contour:
            new_contours.append(contour)
            continue
        _, i, j, *_ = by_contour[ci]
        n = len(contour)
        replacement = round_cap(contour, n, i, j)
        out = [contour[i], *replacement[1:]]
        k = (j + 1) % n
        while k != i:
            out.append(contour[k])
            k = (k + 1) % n
        new_contours.append(out)
        made += 1

    flat, new_ends = [], []
    for contour in new_contours:
        flat.extend(contour)
        new_ends.append(len(flat) - 1)
    glyph.coordinates = GlyphCoordinates(
        [(int(round(x)), int(round(y))) for x, y, _ in flat]
    )
    glyph.flags = [bool(on) for _, _, on in flat]
    glyph.endPtsOfContours = new_ends
    glyph.recalcBounds(glyf_table)
    return made


def simplify(font: TTFont) -> tuple[TTFont, list[tuple[str, list[tuple[int, int, int]]]]]:
    if "glyf" not in font or "fvar" in font:
        raise ValueError("Expected a static TrueType font with glyf outlines.")
    if font["OS/2"].usWeightClass != 400:
        raise ValueError(f"Expected usWeightClass=400, got {font['OS/2'].usWeightClass}.")
    cmap = font.getBestCmap()
    missing = [ch for ch in CHARS_63 if ord(ch) not in cmap]
    if missing:
        raise ValueError(f"Missing sample characters: {''.join(missing)}")
    if len(CHARS_63) != 63 or len(set(CHARS_63)) != 62:
        raise AssertionError("The audit sample must remain 63 entries / 62 unique characters.")

    glyf = font["glyf"]
    names = set(cmap[ord(ch)] for ch in CHARS_63)
    before = {name: signature(glyf[name], glyf) for name in names}
    reports = []
    for ch in HOOK_CANDIDATES:
        name = cmap[ord(ch)]
        glyph = glyf[name]
        if glyph.isComposite():
            raise ValueError(f"{ch} ({name}) is composite; refusing implicit outline expansion.")
        coords, ends, flags = glyph.getCoordinates(glyf)
        contours = hook_cut.split_contours(coords, ends, flags)
        hooks = hook_cut.find_hooks(contours)
        gates = [(item[0], item[1], item[2]) for item in hooks]
        if hooks:
            count = apply_round_cuts(glyph, glyf, hooks)
            if count != len(hooks):
                raise AssertionError(f"{ch}: applied {count} of {len(hooks)} detected cuts")
            reports.append((ch, gates))
            print(f"{ch} ({name}): {count} G1 round-cap cut(s), gates={gates}")
        else:
            print(f"{ch} ({name}): no hook detected; unchanged")

    after = {name: signature(glyf[name], glyf) for name in names}
    changed = {name for name in names if before[name] != after[name]}
    expected_names = {cmap[ord(ch)] for ch, _ in reports}
    if changed != expected_names:
        raise AssertionError(f"Unexpected changed glyph set: {sorted(changed ^ expected_names)}")
    hook_count = sum(len(gates) for _, gates in reports)
    if hook_count != EXPECTED_HOOKS or len(changed) != EXPECTED_CHANGED_GLYPHS:
        raise AssertionError(
            f"Expected {EXPECTED_HOOKS} cuts on {EXPECTED_CHANGED_GLYPHS} glyphs; "
            f"got {hook_count} cuts on {len(changed)} glyphs."
        )
    print(f"sample={len(CHARS_63)} entries / {len(names)} unique glyphs")
    print(f"proposal={hook_count} G1 round-cap cuts on {len(changed)} glyphs")
    print("No corner, short-turn, stroke-width, frame, or production processing was run.")
    return font, reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", required=True, help="Static Tsukushi A D/400 source TTF")
    parser.add_argument("--output", required=True, help="Temporary research-preview TTF")
    args = parser.parse_args()
    font, _ = simplify(TTFont(args.font))
    font.recalcTimestamp = False
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    font.save(output)
    print("saved research preview ->", output)


if __name__ == "__main__":
    main()
