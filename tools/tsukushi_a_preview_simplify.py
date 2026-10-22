#!/usr/bin/env python3
"""Create a research-only Tsukushi A D/400 hook-end preview.

Only the eight selected hook cuts in the 63-entry sample are changed. A shared bisector
axis keeps each two-arc cap balanced; candidates that cannot meet the tangent/bulge limits
are rejected. All corner, short-turn, stroke-width, frame, and production processing is
omitted. Source and output TTFs must stay outside the repository.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates

if __package__:
    from . import hook_cut
else:
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
    """Replace one hook loop with a balanced, two-arc round cap.

    A single bisector axis is shared by both quadratic arcs, avoiding the visibly
    uneven crown produced when each side independently follows a different tangent.
    The cap is accepted only when that axis is close enough to the gate normal and
    both original endpoint tangents; rejected geometry is never silently reshaped.
    """
    ax, ay = contour[i][0], contour[i][1]
    bx, by = contour[j][0], contour[j][1]
    prev = contour[(i - 1) % n]
    next_point = contour[(j + 1) % n]
    dx, dy = ax - prev[0], ay - prev[1]
    dlen = math.hypot(dx, dy)
    ox, oy = next_point[0] - bx, next_point[1] - by
    olen = math.hypot(ox, oy)
    if dlen <= 1e-9 or olen <= 1e-9:
        raise AssertionError("Cannot construct a cap from a zero-length tangent")
    incoming = (dx / dlen, dy / dlen)
    outgoing = (ox / olen, oy / olen)

    gx, gy = bx - ax, by - ay
    glen = math.hypot(gx, gy)
    if glen <= 1e-9:
        raise AssertionError("Cannot construct a cap across a zero-length gate")
    gate = (gx / glen, gy / glen)
    normal = (-gate[1], gate[0])
    if incoming[0] * normal[0] + incoming[1] * normal[1] < 0:
        normal = (-normal[0], -normal[1])

    # Bisect the two cap-facing contour tangents: incoming and reverse(outgoing).
    dx, dy = incoming[0] - outgoing[0], incoming[1] - outgoing[1]
    axis_len = math.hypot(dx, dy)
    if axis_len <= 1e-9:
        raise AssertionError("Endpoint tangents do not define a cap axis")
    axis = (dx / axis_len, dy / axis_len)
    outward_alignment = axis[0] * normal[0] + axis[1] * normal[1]
    if outward_alignment < math.cos(math.radians(25)):
        raise AssertionError("Balanced cap axis is too skewed from the outward gate normal")

    tangent_error = max(
        math.degrees(math.acos(max(-1.0, min(1.0,
            incoming[0] * axis[0] + incoming[1] * axis[1])))),
        math.degrees(math.acos(max(-1.0, min(1.0,
            -outgoing[0] * axis[0] - outgoing[1] * axis[1])))),
    )
    if tangent_error > 15:
        raise AssertionError(
            f"Balanced cap endpoint tangent mismatch is too large: {tangent_error:.2f}°"
        )

    # A shared direction and half-gate radius make the two quadratic arcs meet
    # symmetrically at their apex. The join is G1; endpoint mismatch is bounded above.
    r = glen * 0.5
    q1 = (ax + axis[0] * r, ay + axis[1] * r)
    apex = ((ax + bx) * 0.5 + axis[0] * r,
            (ay + by) * 0.5 + axis[1] * r)
    q2 = (bx + axis[0] * r, by + axis[1] * r)
    return [(ax, ay, True), (q1[0], q1[1], False),
            (apex[0], apex[1], True), (q2[0], q2[1], False),
            (bx, by, True)]


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
            print(f"{ch} ({name}): {count} balanced round-cap cut(s), gates={gates}")
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
    print(f"proposal={hook_count} balanced two-arc round-cap cuts on {len(changed)} glyphs")
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
