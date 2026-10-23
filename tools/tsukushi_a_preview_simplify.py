#!/usr/bin/env python3
"""Create a research-only, sketch-referenced Tsukushi A D/400 form preview.

V7 processes all 63 sample entries: manually reviewed hook caps are combined with
terminal-only tip/free-end rounding, sketch-guided whole-glyph proportions for 鸟/也,
modest last-stroke extensions to 己/已, and symmetric compression of 电's four internal
openings. This is a reversible, single-weight study, not a production-font edit; source
and output TTFs must stay outside the repository.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates

if __package__:
    from . import hook_cut
    from . import round as round_tools
else:
    import hook_cut
    import round as round_tools


CHARS_63 = (
    "一二三十口日回国了乙人入八木林森永心必水走建进这远道你好中国"
    "语言文字书写规范长美丽颜色锦绣风雨雪龙马鸟虫鱼电子已己巳也包囚暖田"
)
SAMPLE_CHARS = tuple(dict.fromkeys(CHARS_63))

# Manually reviewed sample-wide hook map: tuples are (contour, gate_i, gate_j).
# The geometric detector also sees dots, diagonals and ordinary turns; those false
# positives are not rounded. Every listed entry is checked against the D/400 source.
HOOK_CUT_PLAN = {
    "了": ((0, 8, 20),),
    "永": ((0, 6, 20),),
    "水": ((0, 41, 53),),
    "好": ((1, 8, 18),),
    "字": ((0, 9, 20),),
    "书": ((0, 39, 51),),
    "规": ((3, 25, 1),),
    "范": ((4, 2, 16),),
    "色": ((0, 11, 23),),
    "绣": ((0, 23, 29),),
    "风": ((0, 14, 24),),
    "龙": ((0, 77, 85),),
    "马": ((0, 35, 47),),
    "鸟": ((0, 56, 68),),
    "电": ((0, 32, 42),),
    "子": ((0, 8, 18),),
    "已": ((0, 35, 48),),
    "己": ((0, 40, 52),),
    "巳": ((0, 9, 22),),
    "也": ((0, 8, 20),),
    "包": ((0, 12, 24), (1, 10, 20)),
}
EXPECTED_HOOKS = 22
# Only 走 is allowlisted: a full round_tips pass caused single-contour self-intersections
# in seven other glyphs, so those glyph-level edits are intentionally excluded.
TIP_ROUND_ALLOWLIST = frozenset({"走"})
EXPECTED_ROUND_TIPS = 1
EXPECTED_ROUND_CAPS = 11
EXPECTED_TERMINAL_ROUNDS = EXPECTED_ROUND_TIPS + EXPECTED_ROUND_CAPS
EXPECTED_CHANGED_GLYPHS = 26

# Extension is measured in gate widths. 己/已 follow the recalled design direction;
# 电's short extension compensates the round cap's inward reach so its original ink
# width and rightmost exterior extent remain unchanged.
CAP_EXTENSION_RATIOS = {"己": 1.0, "已": 1.5, "电": 0.41}

# Whole-glyph scales use the user's 鸟/也 sketches only as proportion/style references;
# no points are traced. They are deliberately modest so the hand-drawn ratios inform
# the outline without forcing every irregularity of a freehand sketch into the font.
SKETCH_PROPORTION_SCALES = {"鸟": (1.06, 0.92), "也": (1.0, 1.06)}

# Narrow the four interior openings by the same horizontal amount from the center
# side. Their outer-side edges, the exterior contour, and the frame centerline stay put.
ELECTRIC_FRAME_CONTOURS = (1, 2, 3, 4)
ELECTRIC_FRAME_SHRINK_FRACTION = 0.10


def signature(glyph, glyf_table):
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    return (
        tuple((int(x), int(y)) for x, y in coords),
        tuple(int(end) for end in ends),
        tuple(bool(flag) for flag in flags),
    )


def scale_outline_points(points, scale_x, scale_y, anchor_x, anchor_y):
    """Apply a whole-outline scale around a fixed lower-left anchor."""
    if (
        not math.isfinite(scale_x) or scale_x <= 0
        or not math.isfinite(scale_y) or scale_y <= 0
    ):
        raise ValueError("Whole-glyph scale factors must be finite and positive")
    return [
        (
            int(round(anchor_x + (x - anchor_x) * scale_x)),
            int(round(anchor_y + (y - anchor_y) * scale_y)),
            bool(on_curve),
        )
        for x, y, on_curve in points
    ]


def apply_whole_glyph_scale(glyph, glyf_table, scale_x, scale_y):
    """Scale one complete outline while preserving its lower-left placement anchor."""
    coords, _ends, flags = glyph.getCoordinates(glyf_table)
    if not coords:
        raise ValueError("Cannot scale an empty glyph outline")
    anchor_x = min(x for x, _y in coords)
    anchor_y = min(y for _x, y in coords)
    points = [(x, y, flag) for (x, y), flag in zip(coords, flags)]
    scaled = scale_outline_points(points, scale_x, scale_y, anchor_x, anchor_y)
    glyph.coordinates = GlyphCoordinates([(x, y) for x, y, _on in scaled])
    glyph.flags = [on for _x, _y, on in scaled]
    glyph.recalcBounds(glyf_table)


def round_cap(contour, n, i, j, extension=0.0):
    """Replace one hook loop with a balanced, two-arc round cap.

    A single bisector axis is shared by both quadratic arcs, avoiding the visibly
    uneven crown produced when each side independently follows a different tangent.
    The cap is accepted only when that axis is close enough to the gate normal and
    both original endpoint tangents are bounded by the validation checks below.

    ``extension`` adds a straight, tangent-continuous run before the round cap. The
    original gate points remain in place, so the extension lengthens the terminal
    without changing the rest of the glyph or flattening the end.
    """
    if not math.isfinite(extension) or extension < 0:
        raise ValueError("Cap extension must be a finite, non-negative distance")

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

    # Translate the arc gates together along their shared axis. A straight run joins
    # each original gate to its translated gate; both joins have the same G1 tangent.
    start = (ax + axis[0] * extension, ay + axis[1] * extension)
    end = (bx + axis[0] * extension, by + axis[1] * extension)
    r = glen * 0.5
    q1 = (start[0] + axis[0] * r, start[1] + axis[1] * r)
    apex = ((start[0] + end[0]) * 0.5 + axis[0] * r,
            (start[1] + end[1]) * 0.5 + axis[1] * r)
    q2 = (end[0] + axis[0] * r, end[1] + axis[1] * r)

    cap = [(ax, ay, True)]
    if extension > 1e-9:
        cap.append((start[0], start[1], True))
    cap.extend([
        (q1[0], q1[1], False),
        (apex[0], apex[1], True),
        (q2[0], q2[1], False),
    ])
    if extension > 1e-9:
        cap.append((end[0], end[1], True))
    cap.append((bx, by, True))
    return cap


def apply_round_cuts(glyph, glyf_table, hooks, extension_ratio=0.0):
    """Apply local research caps; leave the shared production helper untouched."""
    if not hooks:
        return 0
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    contours = hook_cut.split_contours(coords, ends, flags)
    by_contour = {h[0]: h for h in hooks}
    if len(by_contour) != len(hooks):
        raise ValueError(
            "Multiple hook cuts in one contour require manual ordering; refusing overwrite"
        )
    new_contours = []
    made = 0
    for ci, contour in enumerate(contours):
        if ci not in by_contour:
            new_contours.append(contour)
            continue
        _, i, j, *_ = by_contour[ci]
        n = len(contour)
        gate_length = math.hypot(
            contour[j][0] - contour[i][0], contour[j][1] - contour[i][1]
        )
        replacement = round_cap(
            contour, n, i, j, extension=gate_length * extension_ratio
        )
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


def compress_electric_frame_contours(contours, shrink_fraction):
    """Narrow 电's inner openings toward its center while preserving outer side edges.

    The left and right openings move by the same absolute distance, preserving the
    centerline of the divider. Their outer-side boundaries stay fixed, so the exterior
    side strokes do not gain thickness; only the inner frame is reshaped.
    """
    if not math.isfinite(shrink_fraction) or not 0 <= shrink_fraction < 1:
        raise ValueError("Frame shrink fraction must be in the interval [0, 1)")
    if len(contours) != 5:
        raise ValueError(
            f"Expected one outer contour and four inner openings; got {len(contours)}"
        )
    result = list(contours)
    left = (1, 2)
    right = (3, 4)
    left_widths = []
    right_widths = []
    for ci in left:
        xs = [p[0] for p in contours[ci]]
        left_widths.append(max(xs) - min(xs))
    for ci in right:
        xs = [p[0] for p in contours[ci]]
        right_widths.append(max(xs) - min(xs))
    reference_width = min(left_widths + right_widths)
    shift = reference_width * shrink_fraction

    for ci in left:
        contour = contours[ci]
        outer_x = min(p[0] for p in contour)
        inner_x = max(p[0] for p in contour)
        width = inner_x - outer_x
        if width <= 1e-9:
            raise ValueError(f"Electric frame contour {ci} has zero horizontal width")
        scale = (width - shift) / width
        result[ci] = [
            (outer_x + (x - outer_x) * scale, y, on)
            for x, y, on in contour
        ]

    for ci in right:
        contour = contours[ci]
        outer_x = max(p[0] for p in contour)
        inner_x = min(p[0] for p in contour)
        width = outer_x - inner_x
        if width <= 1e-9:
            raise ValueError(f"Electric frame contour {ci} has zero horizontal width")
        scale = (width - shift) / width
        result[ci] = [
            (outer_x - (outer_x - x) * scale, y, on)
            for x, y, on in contour
        ]
    return result


def apply_electric_frame_compression(glyph, glyf_table):
    """Narrow 电's four internal 田 openings without moving its exterior outline."""
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    contours = hook_cut.split_contours(coords, ends, flags)
    compressed = compress_electric_frame_contours(
        contours, ELECTRIC_FRAME_SHRINK_FRACTION
    )
    flat, new_ends = [], []
    for contour in compressed:
        flat.extend(contour)
        new_ends.append(len(flat) - 1)
    glyph.coordinates = GlyphCoordinates(
        [(int(round(x)), int(round(y))) for x, y, _ in flat]
    )
    glyph.flags = [bool(on) for _, _, on in flat]
    glyph.endPtsOfContours = new_ends
    glyph.recalcBounds(glyf_table)
    return len(ELECTRIC_FRAME_CONTOURS)


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
    expected_names = set()
    for ch, gate_specs in HOOK_CUT_PLAN.items():
        name = cmap[ord(ch)]
        glyph = glyf[name]
        if glyph.isComposite():
            raise ValueError(f"{ch} ({name}) is composite; refusing implicit outline expansion.")
        coords, ends, flags = glyph.getCoordinates(glyf)
        contours = hook_cut.split_contours(coords, ends, flags)
        detected = hook_cut.find_hooks(contours)
        hooks = []
        for spec in gate_specs:
            matches = [item for item in detected if item[:3] == spec]
            if len(matches) != 1:
                raise AssertionError(f"{ch}: curated hook gate {spec} is not unique in source")
            item = matches[0]
            ci, i, j, *_ = item
            gate_length = math.hypot(
                contours[ci][j][0] - contours[ci][i][0],
                contours[ci][j][1] - contours[ci][i][1],
            )
            round_cap(
                contours[ci], len(contours[ci]), i, j,
                extension=gate_length * CAP_EXTENSION_RATIOS.get(ch, 0.0),
            )
            hooks.append(item)
        count = apply_round_cuts(
            glyph, glyf, hooks, extension_ratio=CAP_EXTENSION_RATIOS.get(ch, 0.0)
        )
        if count != len(gate_specs):
            raise AssertionError(f"{ch}: applied {count} of {len(gate_specs)} curated cuts")
        gates = [(item[0], item[1], item[2]) for item in hooks]
        reports.append((ch, gates))
        expected_names.add(name)
        extension_ratio = CAP_EXTENSION_RATIOS.get(ch, 0.0)
        extension_text = (
            f", terminal extension={extension_ratio:.2f}× gate width"
            if extension_ratio else ""
        )
        print(
            f"{ch} ({name}): {count} manually reviewed balanced round-cap cut(s), "
            f"gates={gates}{extension_text}"
        )

    tip_count = cap_count = 0
    for ch in SAMPLE_CHARS:
        name = cmap[ord(ch)]
        glyph = glyf[name]
        if glyph.isComposite():
            raise ValueError(f"{ch} ({name}) is composite; refusing implicit outline expansion.")
        tips = (
            round_tools.round_tips(glyph, glyf)
            if ch in TIP_ROUND_ALLOWLIST else 0
        )
        caps = round_tools.round_glyph(glyph, glyf)
        if tips or caps:
            tip_count += tips
            cap_count += caps
            expected_names.add(name)
            print(f"{ch} ({name}): rounded {tips} exposed tip(s), {caps} flat free-end cap(s)")

    n = apply_electric_frame_compression(glyf[cmap[ord("电")]], glyf)
    expected_names.add(cmap[ord("电")])
    print(
        f"电 ({cmap[ord('电')]}): narrowed {n} inner 田 openings symmetrically; "
        f"each inner edge moves by {ELECTRIC_FRAME_SHRINK_FRACTION:.0%} "
        "of the narrowest opening width; outer edges and centerline stay fixed"
    )

    for ch, (scale_x, scale_y) in SKETCH_PROPORTION_SCALES.items():
        name = cmap[ord(ch)]
        glyph = glyf[name]
        if glyph.isComposite():
            raise ValueError(f"{ch} ({name}) is composite; refusing implicit outline expansion.")
        before_bbox = (glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax)
        apply_whole_glyph_scale(glyph, glyf, scale_x, scale_y)
        after_bbox = (glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax)
        if after_bbox == before_bbox:
            raise AssertionError(f"{ch}: sketch-proportioned whole-glyph scale made no change")
        expected_names.add(name)
        print(
            f"{ch} ({name}): applied whole-glyph proportion scale "
            f"x={scale_x:.2f}, y={scale_y:.2f}; bbox {before_bbox} -> {after_bbox}"
        )

    after = {name: signature(glyf[name], glyf) for name in names}
    changed = {name for name in names if before[name] != after[name]}
    if changed != expected_names:
        raise AssertionError(f"Unexpected changed glyph set: {sorted(changed ^ expected_names)}")
    hook_count = sum(len(gates) for _, gates in reports)
    if (
        hook_count != EXPECTED_HOOKS
        or tip_count != EXPECTED_ROUND_TIPS
        or cap_count != EXPECTED_ROUND_CAPS
        or len(changed) != EXPECTED_CHANGED_GLYPHS
    ):
        raise AssertionError(
            "Unexpected sample-wide treatment counts: "
            f"hooks={hook_count}, tips={tip_count}, caps={cap_count}, "
            f"changed glyphs={len(changed)}"
        )
    print(f"sample={len(CHARS_63)} entries / {len(names)} unique glyphs")
    print(
        f"proposal={hook_count} manually reviewed hook caps + {tip_count} tip rounds + "
        f"{cap_count} flat-end rounds; {len(changed)} glyphs changed"
    )
    print("No general corner, short-turn, stroke-width, or production processing was run.")
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
