#!/usr/bin/env python3
"""Create the V9 geometry base for a research-only Tsukushi A D/400 preview.

All 63 sample entries are reviewed. Manually selected hooks receive semicircular
endings; safe terminal rounds and modest 己/已 extensions remain glyph-specific.
Sketches for 鸟 and 也 are qualitative shape references, never point maps or global
bbox targets. Stroke-width regularization and the measured 电 frame adjustment run in
the separate, optional research builder. Source and output TTFs stay outside the repo.
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
    "也": ((0, 8, 20),),
    "包": ((0, 12, 24), (1, 10, 20)),
}
EXPECTED_HOOKS = 21
# Only 走 is allowlisted: a full round_tips pass caused single-contour self-intersections
# in seven other glyphs, so those glyph-level edits are intentionally excluded.
TIP_ROUND_ALLOWLIST = frozenset({"走"})
EXPECTED_ROUND_TIPS = 1
EXPECTED_ROUND_CAPS = 11
EXPECTED_TERMINAL_ROUNDS = EXPECTED_ROUND_TIPS + EXPECTED_ROUND_CAPS
# Small rigid contour-group translations open only the two negative-space collisions
# found in the 74-FU reconstruction; they do not alter component outlines or weight.
COMPONENT_SPACING_TRANSLATIONS_FU = {
    "颜": {0: (0, -15), 1: (4, 5), 5: (0, -21)},
    "暖": {0: (0, -8), 2: (0, 8), 5: (0, -8)},
}
EXPECTED_SPACING_GLYPHS = 2
EXPECTED_CHANGED_GLYPHS = 27

# 电 retains a small explicit extension so the rounded lower terminal does not change
# its exterior constraints. For the identified long-sweep terminals, derive the cap run
# from the actual quadratic path instead of guessing a gate multiplier: 色/也/龙 retain
# their source extreme, and 己/已 extend 8 FU beyond their actual source tips before width rebuilding.
# 巳's native terminal is already rounded, so its outline is not cut. This avoids deleting
# visible glyph length and does not copy any external outline.
CAP_EXTENSION_RATIOS = {"电": 0.41}
CAP_PRESERVE_EXTENT_EXTRA_FU = {
    "色": 0.0,
    "龙": 0.0,
    "也": 0.0,
    "己": 8.0,
    "已": 8.0,
}

def signature(glyph, glyf_table):
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    return (
        tuple((int(x), int(y)) for x, y in coords),
        tuple(int(end) for end in ends),
        tuple(bool(flag) for flag in flags),
    )


def _round_cap_axis(contour, n, i, j):
    """Return the balanced outward cap axis and the gate width after validating tangents."""
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
    return axis, glen


def _quadratic_segment_samples(start, controls, end, steps=24):
    """Sample one TrueType quadratic segment, including implied off-curve midpoints."""
    if not controls:
        return [end]
    samples = []
    current = start
    for index, control in enumerate(controls):
        if index + 1 < len(controls):
            following = controls[index + 1]
            target = ((control[0] + following[0]) * 0.5,
                      (control[1] + following[1]) * 0.5)
        else:
            target = end
        for step in range(1, steps + 1):
            t = step / steps
            one_minus_t = 1.0 - t
            samples.append((
                one_minus_t * one_minus_t * current[0]
                + 2.0 * one_minus_t * t * control[0]
                + t * t * target[0],
                one_minus_t * one_minus_t * current[1]
                + 2.0 * one_minus_t * t * control[1]
                + t * t * target[1],
            ))
        current = target
    return samples


def _contour_segment_samples(contour, i, j, steps=24):
    """Sample the actual on-curve path from anchor i to anchor j (not control points)."""
    n = len(contour)
    current = (contour[i][0], contour[i][1])
    samples = [current]
    controls = []
    k = (i + 1) % n
    while True:
        point = contour[k]
        if point[2]:
            endpoint = (point[0], point[1])
            samples.extend(_quadratic_segment_samples(current, controls, endpoint, steps))
            current = endpoint
            controls = []
            if k == j:
                return samples
        else:
            controls.append((point[0], point[1]))
        k = (k + 1) % n


def cap_extension_to_preserve_extent(contour, n, i, j, extra=0.0):
    """Extend a round cap to the source path's furthest point along its cap axis.

    The removed hook segment is sampled as its actual quadratic outline, so off-curve
    control points do not overstate the target extent. ``extra`` is an optional modest
    continuation beyond the original tip, in font units.
    """
    if not math.isfinite(extra) or extra < 0:
        raise ValueError("Extent-preserving cap extra must be finite and non-negative")
    axis, gate_width = _round_cap_axis(contour, n, i, j)
    ax, ay = contour[i][0], contour[i][1]
    bx, by = contour[j][0], contour[j][1]
    midpoint = ((ax + bx) * 0.5, (ay + by) * 0.5)
    projections = [
        (x - midpoint[0]) * axis[0] + (y - midpoint[1]) * axis[1]
        for x, y in _contour_segment_samples(contour, i, j)
    ]
    required = max(projections, default=0.0) - gate_width * 0.5 + extra
    return max(0.0, required)


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
    axis, glen = _round_cap_axis(contour, n, i, j)

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


def apply_round_cuts(
    glyph, glyf_table, hooks, extension_ratio=0.0, extension_by_contour=None
):
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
        extension = (
            extension_by_contour.get(ci, gate_length * extension_ratio)
            if extension_by_contour is not None
            else gate_length * extension_ratio
        )
        replacement = round_cap(contour, n, i, j, extension=extension)
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


def apply_component_spacing_translations(font: TTFont) -> set[str]:
    """Open reviewed near-collisions by translating complete contours rigidly.

    The offsets are limited to the two glyphs whose shared 74-FU radius would make
    distinct source components touch. Whole component contours (and their counters)
    move together; no stroke is scaled, thickened, or copied from the reference font.
    """
    cmap = font.getBestCmap()
    changed_names = set()
    expected_contour_counts = {"颜": 8, "暖": 7}
    for ch, offsets in COMPONENT_SPACING_TRANSLATIONS_FU.items():
        glyph_name = cmap.get(ord(ch))
        if glyph_name is None:
            raise ValueError(f"Cannot space-adjust missing sample {ch!r}")
        glyph = font["glyf"][glyph_name]
        if glyph.isComposite():
            raise ValueError(f"{ch} ({glyph_name}) is composite; refusing implicit expansion")
        coords, ends, flags = glyph.getCoordinates(font["glyf"])
        if len(ends) != expected_contour_counts[ch]:
            raise ValueError(
                f"{ch}: expected {expected_contour_counts[ch]} contours before spacing edit, "
                f"got {len(ends)}"
            )
        shifted = []
        start = 0
        for contour_index, end in enumerate(ends):
            dx, dy = offsets.get(contour_index, (0, 0))
            for point_index in range(start, end + 1):
                x, y = coords[point_index]
                shifted.append((int(x) + dx, int(y) + dy))
            start = end + 1
        glyph.coordinates = GlyphCoordinates(shifted)
        glyph.flags = [bool(flag) for flag in flags]
        glyph.endPtsOfContours = list(ends)
        glyph.recalcBounds(font["glyf"])
        changed_names.add(glyph_name)
    return changed_names


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
        extension_by_contour = {}
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
            extension = gate_length * CAP_EXTENSION_RATIOS.get(ch, 0.0)
            if ch in CAP_PRESERVE_EXTENT_EXTRA_FU:
                extension = cap_extension_to_preserve_extent(
                    contours[ci], len(contours[ci]), i, j,
                    extra=CAP_PRESERVE_EXTENT_EXTRA_FU[ch],
                )
            if ci in extension_by_contour:
                raise ValueError(f"{ch}: multiple cap edits in contour {ci} are unsupported")
            round_cap(
                contours[ci], len(contours[ci]), i, j, extension=extension
            )
            extension_by_contour[ci] = extension
            hooks.append(item)
        count = apply_round_cuts(
            glyph, glyf, hooks,
            extension_ratio=CAP_EXTENSION_RATIOS.get(ch, 0.0),
            extension_by_contour=extension_by_contour,
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

    spacing_changed = apply_component_spacing_translations(font)
    expected_names.update(spacing_changed)
    if len(spacing_changed) != EXPECTED_SPACING_GLYPHS:
        raise AssertionError(
            f"Expected {EXPECTED_SPACING_GLYPHS} spacing-repair glyphs, "
            f"got {len(spacing_changed)}"
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
        f"{cap_count} flat-end rounds + {len(spacing_changed)} rigid spacing repairs; "
        f"{len(changed)} glyphs changed"
    )
    print(
        "Geometry base only: shared stroke-width reconstruction and the measured 电 frame "
        "spacing transform run in build_tsukushi_a_v9.py; no production font was changed."
    )
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
