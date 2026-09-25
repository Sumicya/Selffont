#!/usr/bin/env python3
"""Extend Zen Maru with the simplified glyphs it never drew.

Zen Maru is a Japanese face: it draws 貝/頁/馬/鳥/見 and no 贝/页/马/鸟/见, and it
covers only 3378 of the 6763 hanzi in GB2312. This tool fills the rest from two
sources, in order of preference.

* **Its own contours.** A recipe recomposes a new glyph out of contours the face
  already owns, transformed by explicit matrices. Rules are a small, reviewable
  table (``RECIPES``), one entry per character::

      "赵": [("辶", all_contours, ...), ("乂", all_contours, fit(...))]

  A part is ``(source glyph, selector, shaper)``. Selectors pick contours by
  role, never by index, because each weight was drawn separately and the same
  character can have four contours in Bold and six in Light.

* **A pinned reference font.** Characters no rule can reach are imported from a
  reference declared in ``config/reference-sources.json`` -- version, bytes,
  SHA-256, licence and reserved font names included. The tool refuses a file
  that does not match the pin, and the borrowed outline is offset along its
  normals until its measured stroke thickness matches this face's, so one
  reference weight can serve all five.

What the tool refuses to do:

* it never rewrites an existing codepoint -- a character that is already drawn
  is an error, not an overwrite, and a rule always outranks the reference;
* it never removes or reorders an existing glyph;
* it never ships a guessed shape: a weight that cannot express a rule is skipped
  and reported, and an imported outline that would invert, collapse or leave the
  em box is backed off or refused;
* it verifies the result: every pre-existing glyph byte-identical, glyph order
  unchanged, the new glyph list exactly what it wrote, and the cmap gaining
  exactly the characters it added.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from fontTools.pens.areaPen import AreaPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "config/font-source.json").read_text())
FACES = {face["style"]: face for face in MANIFEST["faces"]}





# --- geometry ---


def apply(matrix, point):
    a, b, c, d, e, f = matrix
    x, y = point
    return (a * x + c * y + e, b * x + d * y + f)


# How far a derived outline may stray from the em box before it is rejected.
LIMIT = 1400


def bounds(contours):
    points = [p for contour in contours for p in contour.points() if p]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


class Contour:
    """One closed contour in font units, as pen commands."""

    def __init__(self, commands):
        self.commands = commands

    def points(self):
        for op, args in self.commands:
            if op != "closePath":
                yield from args

    def transform(self, matrix):
        return Contour([(op, tuple(apply(matrix, p) if p else p for p in args))
                        for op, args in self.commands])

    def flags(self):
        """[(point, is_on_curve)] in contour order, implied points resolved."""
        result = []
        for op, args in self.commands:
            if op in ("moveTo", "lineTo"):
                result.append((args[0], True))
            elif op == "qCurveTo":
                points = list(args)
                last = points.pop()
                if last is None:
                    raise ValueError("contour relies on an implied on-curve point")
                result.extend((point, False) for point in points)
                result.append((last, True))
        return result

    def rebuild(self, points):
        """A contour with the same on/off pattern but new point positions."""
        flags = [on for _, on in self.flags()]
        if len(points) != len(flags):
            raise ValueError(f"expected {len(flags)} points, got {len(points)}")
        commands, pending, started = [], [], False
        for point, on_curve in zip(points, flags, strict=True):
            if not on_curve:
                pending.append(point)
                continue
            if not started:
                commands.append(("moveTo", (point,)))
                started = True
            elif pending:
                commands.append(("qCurveTo", (*pending, point)))
                pending = []
            else:
                commands.append(("lineTo", (point,)))
        if pending:
            commands.append(("qCurveTo", (*pending, None)))
        commands.append(("closePath", ()))
        return Contour(commands)

    def segments(self):
        """Split the outline into runs that end at each on-curve point.

        Each record carries the run's points, whether it is a straight line, and
        the top of its bounding box -- the leg filter needs the last one.
        """
        flat = []
        for op, args in self.commands:
            if op in ("moveTo", "lineTo"):
                flat.append((args[0], True))
            elif op == "qCurveTo":
                points = list(args)
                last = points.pop()
                flat.extend((point, False) for point in points)
                if last is None:
                    raise ValueError("contour relies on an implied on-curve point")
                flat.append((last, True))
        segments, current = [], None
        for point, on_curve in flat:
            current = {"points": [point], "start": point} if current is None else current
            if current["points"][-1] is not point:
                current["points"].append(point)
            if on_curve and len(current["points"]) > 1:
                segments.append({
                    "points": current["points"],
                    "start": current["points"][0],
                    "end": point,
                    "straight": len(current["points"]) == 2,
                    "top": max(p[1] for p in current["points"]),
                })
                current = {"points": [point], "start": point}
        if current and len(current["points"]) > 1:
            segments.append({
                "points": current["points"],
                "start": current["points"][0],
                "end": segments[0]["start"],
                "straight": False,
                "top": max(p[1] for p in current["points"]),
            })
        return segments

    def reversed(self):
        """The same outline walked the other way round.

        TrueType fills by winding: an outer contour runs one way and a white slot
        runs the other. Mirroring a glyph reverses both, so a mirrored frame
        would come out with its holes filled and its outline punched out --
        门 rendered as two blobs. Reversing the copy restores the original
        orientation.
        """
        flat = []
        for op, args in self.commands:
            if op in ("moveTo", "lineTo"):
                flat.append((args[0], True))
            elif op == "qCurveTo":
                points = list(args)
                last = points.pop()
                flat.extend((point, False) for point in points)
                flat.append((last, True))
        if len(flat) > 1 and flat[-1][0] == flat[0][0]:
            flat.pop()
        flat.reverse()
        start = next(index for index, (_, on) in enumerate(flat) if on)
        flat = flat[start:] + flat[:start]
        commands = [("moveTo", (flat[0][0],))]
        index = 1
        while index < len(flat):
            if flat[index][1]:
                commands.append(("lineTo", (flat[index][0],)))
                index += 1
                continue
            controls = []
            while index < len(flat) and not flat[index][1]:
                controls.append(flat[index][0])
                index += 1
            end = flat[index][0] if index < len(flat) else flat[0][0]
            commands.append(("qCurveTo", (*controls, end)))
            index += 1
        commands.append(("closePath", ()))
        return Contour(commands)

    def clamp_below(self, floor):
        """Pull every point up to ``floor``, so a cut leaves a flat edge.

        Removing the segments below a floor leaves the walls reaching down to
        where the feet used to be; clamping makes the cut edge flat, which is what
        贝's bottom looks like.
        """
        commands = []
        for op, args in self.commands:
            if op in ("moveTo", "lineTo"):
                commands.append((op, ((args[0][0], max(args[0][1], floor)),)))
            elif op == "qCurveTo":
                commands.append((op, tuple((p[0], max(p[1], floor)) if p else None for p in args)))
            else:
                commands.append((op, args))
        return Contour(commands)

    def keep_segments(self, predicate):
        """Rebuild the outline from the runs that pass ``predicate``."""
        kept = [segment for segment in self.segments() if predicate(segment)]
        if not kept:
            raise ValueError("a filter removed every segment of a contour")
        commands = [("moveTo", (kept[0]["points"][0],))]
        for segment in kept:
            tail = tuple(segment["points"][1:])
            commands.append(("lineTo", (tail[-1],)) if segment["straight"] else ("qCurveTo", tail))
        commands.append(("closePath", ()))
        return Contour(commands)

    def draw(self, pen):
        for op, args in self.commands:
            getattr(pen, op)(*args)

    def __repr__(self):
        x0, y0, x1, y1 = bounds([self])
        return f"<Contour {len(list(self.points()))}pt {x0:.0f},{y0:.0f} {x1:.0f},{y1:.0f}>"


def contours_of(font: TTFont, glyph_name: str):
    """Every contour of a glyph, in glyph order, composites decomposed."""
    pen = DecomposingRecordingPen(font.getGlyphSet())
    font.getGlyphSet()[glyph_name].draw(pen)
    contours, current = [], []
    for op, args in pen.value:
        if op == "moveTo":
            if current:
                raise ValueError(f"{glyph_name}: contour without closePath")
            current = [(op, args)]
        elif op == "closePath":
            current.append((op, ()))
            contours.append(Contour(current))
            current = []
        else:
            current.append((op, args))
    if current:
        raise ValueError(f"{glyph_name}: unclosed contour")
    return [_resolve_implied(contour) for contour in contours]


def _resolve_implied(contour):
    commands = list(contour.commands)
    if commands and commands[-1][0] == "qCurveTo" and commands[-1][1][-1] is None:
        start = next(args[0] for op, args in commands if op == "moveTo")
        commands[-1] = ("qCurveTo", (*commands[-1][1][:-1], start))
    return Contour(commands)


# --- selectors and shapers --------------------------------------------------

# A recipe part is ``(source glyph, selector, shaper)``.
#
# *selector* picks contours out of the source glyph; it never uses a raw index,
# because each weight of a five-weight family was drawn separately and the same
# character can have four contours in Bold and six in Light. The selectors below
# describe roles (main outline, inner bars, bottom pieces), so one recipe works
# across every weight.
#
# *shaper* turns the selected contours into the contours of the new glyph.


def _glyph_contours(glyph):
    pen = DecomposingRecordingPen(None)
    glyph.draw(pen, None)
    contours, current = [], []
    for op, args in pen.value:
        if op == "moveTo":
            current = [(op, args)]
        elif op == "closePath":
            current.append((op, ()))
            contours.append(Contour(current))
            current = []
        else:
            current.append((op, args))
    return contours


# --- classification ---


def area(contour):
    x0, y0, x1, y1 = bounds([contour])
    return (x1 - x0) * (y1 - y0)


def apply_offset(contours, delta, offset_matrix_free):
    """Offset every contour, each backing off as far as its winding requires."""
    from reference_font import fill_sign

    fill = fill_sign(contours)
    shaped, backoff = [], 1.0
    for contour in contours:
        moved, scale = offset_contour(contour, delta, offset_matrix_free, fill)
        shaped.append(moved)
        backoff = min(backoff, scale)
    return shaped, backoff


def match_thickness(contours, target, delta, offset_matrix_free, steps=5, tolerance=0.5):
    """Pick the offset that makes these contours measure ``target`` thick.

    Half the width difference is the analytic guess, but ink area over outline
    length is not linear in the offset (junctions, corners and counters all
    react differently), so the guess is measured and corrected until it lands.
    """
    from reference_font import contour_thickness

    shaped, backoff = apply_offset(contours, delta, offset_matrix_free)
    for _ in range(steps - 1):
        measured = contour_thickness(shaped)
        if abs(measured - target) <= tolerance:
            break
        delta += (target - measured) / 2
        shaped, backoff = apply_offset(contours, delta, offset_matrix_free)
    return shaped, delta, backoff


def offset_contour(contour, delta, offset_matrix_free, fill=-1, steps=6):
    """Offset one contour, halving the offset until its winding survives.

    Returns the contour to draw and the fraction of the offset that was usable.
    A fraction of zero means the contour is drawn exactly as the reference has
    it, which is the honest outcome for a shape that cannot take the weight.
    """
    from reference_font import MITER_LIMIT

    if not delta:
        return contour, 1.0
    box = bounds([contour])
    slack = abs(delta) * MITER_LIMIT + 1
    area = abs(signed_area(contour))
    scale = 1.0
    for _ in range(steps):
        moved = offset_matrix_free([contour], delta * scale, fill)[0]
        # Same winding (it did not turn inside out), same extent (it did not
        # collapse to nothing), same neighbourhood (no point flew away).
        if (_winding(moved) == _winding(contour)
                and abs(signed_area(moved)) > max(1.0, area * 0.01)
                and _within(bounds([moved]), box, slack)):
            return moved, scale
        scale /= 2
    return contour, 0.0


def _within(inner, outer, slack):
    """True when ``inner`` stays inside ``outer`` grown by ``slack`` on every side."""
    return all(inner[index] >= outer[index] - slack and inner[index + 2] <= outer[index + 2] + slack
               for index in (0, 1))





def _winding(contour):
    """True when a contour runs clockwise, which is how this face marks holes."""
    return signed_area(contour) < 0


def signed_area(contour):
    points = [p for p in contour.points() if p]
    total = 0
    for index in range(len(points)):
        x0, y0 = points[index]
        x1, y1 = points[(index + 1) % len(points)]
        total += x0 * y1 - x1 * y0
    return total / 2


def classify(contours):
    """Split a glyph into (main outline, holes, strokes).

    Holes are the reversed-winding contours that carve the 目 interiors white;
    strokes are same-winding contours that are not the main outline -- in this
    family that means the 灬 feet. Winding, not size, is what decides: 貝's three
    white slots look like "bars" until you notice they are wound backwards.
    """
    main = max(contours, key=area)
    main_sign = signed_area(main) < 0
    holes = [c for c in contours if c is not main and (signed_area(c) < 0) != main_sign]
    strokes = [c for c in contours if c is not main and c not in holes]
    return main, holes, strokes


def _by_size(main, strokes, ratio):
    """Split same-winding contours into small and body-sized by bounding area."""
    body = area(main)
    small = [c for c in strokes if area(c) < ratio * body]
    return small, [c for c in strokes if c not in small]


def _feet(main, strokes):
    """Same-winding contours small enough to be 灬 feet rather than body parts.

    The size test is a guard, not the definition: in 貝/頁/馬/鳥/烏 the 目 slots
    are holes, so any remaining same-winding contour is a foot. If one of them
    were as big as the body this would be the wrong character, and the guard
    stops the derivation instead of quietly cutting a stroke off it.
    """
    small, big = _by_size(main, strokes, 0.4)
    if small and big:
        raise ValueError("mixed foot and body-sized strokes; refusing to guess")
    return small


def _floor_segment(contour):
    """The widest flat horizontal run in the lower half of an outline."""
    _, y0, _, y1 = bounds([contour])
    middle = (y0 + y1) / 2
    candidates = [
        segment for segment in contour.segments()
        if segment["straight"]
        and abs(segment["start"][1] - segment["end"][1]) < 2
        and segment["start"][1] < middle
    ]
    if not candidates:
        return None
    segment = max(candidates, key=lambda s: abs(s["end"][0] - s["start"][0]))
    return {"segment": segment, "y": (segment["start"][1] + segment["end"][1]) / 2}


# --- selectors ---


def all_contours(contours, context=None):
    return list(contours)


def main_contour(contours, context=None):
    """The outline that carries the character: the largest one."""
    return [max(contours, key=area)]


# Selectors that may legitimately come back empty say so, because the engine
# treats an empty selection as "this weight cannot prove the recipe" and reports
# a skip -- which is only correct for the selectors where empty is expected.
def _optional(selector):
    selector.optional = True
    return selector


@_optional
def everything_but_main(contours, context=None):
    """Every contour except the one carrying the character.

    Legitimately empty: a heavy weight sometimes draws a character as a single
    fused outline (飛 in Bold), and "the rest of it" is then nothing at all.
    """
    biggest = max(contours, key=area)
    return [c for c in contours if c is not biggest]


def left_half(contours, context=None):
    """Contours whose centre sits left of the glyph's own centre line.

    扌 in 持, 阝 in 陳: the radical is a separate contour, and "left of centre"
    finds it in every weight without naming an index.
    """
    boxes = [bounds([c]) for c in contours]
    axis = (min(b[0] for b in boxes) + max(b[2] for b in boxes)) / 2
    return [c for c in contours if sum(bounds([c])[:3:2]) < 2 * axis]


def right_half(contours, context=None):
    """Mirror of ``left_half``: the right component of a compound character."""
    boxes = [bounds([c]) for c in contours]
    axis = (min(b[0] for b in boxes) + max(b[2] for b in boxes)) / 2
    return [c for c in contours if sum(bounds([c])[:3:2]) >= 2 * axis]


def _radical_side(contours, side, min_height=0.6):
    """The component that reads as this character's radical.

    A radical is most of the glyph's height and flush with one side of it. The
    height test is what makes this honest: in the heavier weights a radical is
    often fused into the body, and what is left of it beside the centre line is
    a fragment of a slot (55% of the height in 陳). A fragment fails the test, the
    recipe reports a skip, and no half-drawn character ships.
    """
    whole = bounds(contours)
    height = whole[3] - whole[1]
    edge = 0.06 * (whole[2] - whole[0])
    half = left_half(contours) if side == "left" else right_half(contours)
    for contour in half:
        x0, y0, x1, y1 = bounds([contour])
        if y1 - y0 <= min_height * height:
            continue
        if (x0 <= whole[0] + edge) if side == "left" else (x1 >= whole[2] - edge):
            # A radical is not one contour: 所 draws 戶 as a body, the small top
            # bar of 尸, and the slot inside its head. Once the tall stroke proves
            # which component this is, the whole side comes with it.
            return list(half)
    return []


def left_radical(contours, context=None):
    """The left component: 阝 in 限, 扌 in 打, 戶 in 所."""
    return _radical_side(contours, "left")


def right_radical(contours, context=None):
    """The right component: 東 in 棟."""
    return _radical_side(contours, "right")


def leftmost(contours, context=None):
    """The leftmost contour that is not the body: 糸's lower-left dot.

    That dot's own slant already rises to the right, which is the shape 纟 uses
    for its third stroke, so 维 borrows the dot instead of drawing a 提. The body
    is excluded because 糸's outline reaches further left than its dot does.
    """
    biggest = max(contours, key=area)
    others = [c for c in contours if c is not biggest]
    return [min(others, key=lambda c: bounds([c])[0])] if others else []


def rightmost(contours, context=None):
    """The rightmost contour that is not the body: 小's lower-right dot.

    Mirror of ``leftmost``: used when both of a character's feet come from the
    same glyph and each has to be named by where it sits.
    """
    biggest = max(contours, key=area)
    others = [c for c in contours if c is not biggest]
    return [max(others, key=lambda c: bounds([c])[0])] if others else []


def highest(contours, context=None):
    """The topmost contour -- 戸's top bar, which 户 draws as a dot."""
    return [max(contours, key=lambda c: bounds([c])[1])]


def except_highest(contours, context=None):
    top = highest(contours)[0]
    return [c for c in contours if c is not top]


def above(y):
    return lambda contours: [c for c in contours if bounds([c])[1] >= y]


def above_main(contours, context=None):
    """Contours that sit on top of the main outline: 員's 口 over its 貝."""
    main = max(contours, key=area)
    top = bounds([main])[3]
    return [c for c in contours if c is not main and bounds([c])[1] >= top]


def below(y):
    """Contours that sit entirely below ``y``."""
    return lambda contours, context=None: [c for c in contours if bounds([c])[3] <= y]


# --- shapers ---


def translate(dx, dy):
    def shaper(contours, context):
        return [c.transform((1, 0, 0, 1, dx, dy)) for c in contours]
    return shaper


def fit(box, keep_aspect=True, align=(0.5, 0.5)):
    """Scale whatever it is given into ``box`` = (x0, y0, x1, y1).

    ``keep_aspect`` scales uniformly by the smaller ratio, so a box that was
    square in the traditional glyph stays square in the derived one.
    """
    def shaper(contours, context):
        x0, y0, x1, y1 = bounds(contours)
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            raise ValueError("degenerate source bounds")
        fx, fy = (box[2] - box[0]) / w, (box[3] - box[1]) / h
        if keep_aspect:
            fx = fy = min(fx, fy)
        ox = box[0] + (box[2] - box[0]) / 2 - align[0] * w * fx
        oy = box[1] + (box[3] - box[1]) / 2 - align[1] * h * fy
        matrix = (fx, 0, 0, fy, ox - fx * x0, oy - fy * y0)
        return [c.transform(matrix) for c in contours]
    return shaper


def flip_x():
    """Mirror a shape about its own vertical centre line.

    The face leans its dots one way (丶 leans down-right), and 东's lower-left
    foot leans the other way, so that foot is the same dot flipped instead of a
    stroke long enough to be wrong. Mirroring swaps inside and outside, so the
    copy is reversed to keep its winding.
    """
    def shaper(contours, context):
        x0, _, x1, _ = bounds(contours)
        matrix = (-1, 0, 0, 1, x0 + x1, 0)
        return [c.transform(matrix).reversed() for c in contours]
    return shaper


def frame(axis=500):
    """Build a symmetrical frame from one half of a bracket: 門 -> 门, 見 -> 见.

    Whichever half is handed over is slid inward until it meets the glyph's centre
    line, then mirrored, so the two halves join instead of keeping the gap the
    original spacing had. The white slots travel with their half, because a frame
    without its slots is a pair of solid blobs.
    """
    def shaper(contours, context):
        x0 = min(bounds([c])[0] for c in contours)
        x1 = max(bounds([c])[2] for c in contours)
        shift = (axis - x0) if (x0 + x1) / 2 > axis else (axis - x1)
        placed = [c.transform((1, 0, 0, 1, shift, 0)) for c in contours]
        mirrored = [c.transform((-1, 0, 0, 1, 2 * axis, 0)).reversed() for c in placed]
        return [*placed, *mirrored]
    return shaper


def then(*shapers):
    """Apply shapers in order; each one sees what the previous produced."""
    def shaper(contours, context):
        for step in shapers:
            contours = step(contours, context)
        return contours
    return shaper


def without_feet(contours, context=None):
    """Drop the 灬 feet, keep the box and every white slot: 貝 -> 贝.

    Light, Regular and Medium draw the feet as separate small contours; Medium,
    Bold and Black merge them into the main outline. The first case drops the
    small strokes, the second cuts the outline below its own floor. Both keep
    the holes, because a box with its slots is 贝 and a box without them is a
    black rectangle.
    """
    main, holes, strokes = classify(contours)
    feet = _feet(main, strokes)
    if feet:
        if context is not None:
            context.setdefault("notes", {})["feetBox"] = bounds(feet)
        return [main, *holes, *[c for c in strokes if c not in feet]]
    floor = _floor_segment(main)
    if floor is None:
        raise ValueError("no floor found to cut the feet from")
    shaped = main.keep_segments(
        lambda segment: segment["top"] > floor["y"] or segment is floor["segment"])
    shaped = shaped.clamp_below(floor["y"])
    if len(shaped.segments()) == len(main.segments()):
        raise ValueError("no feet were found to remove in this weight")
    if context is not None:
        x0, _, x1, _ = bounds([main])
        context.setdefault("notes", {})["feetBox"] = (x0, bounds([main])[1], x1, floor["y"])
    return [shaped, *holes, *strokes]


def body_only(contours, context=None):
    """The box and its slots, at the character's own scale: 馬 -> 马, 鳥 -> 鸟."""
    return without_feet(contours, context)


def simplified_box(count=2):
    """貝/見 -> 贝/见's box: merge the lowest white slots into one.

    貝 is 目 + 八: three white slots over two dividers. 贝 has one divider, so
    the two lowest slots merge into a single cell. The merged cell is the lowest
    slot stretched to the pair's combined box, which keeps the face's own
    rounded corner on two sides and the box's straight dividers on the other.
    """
    def shaper(contours, context=None):
        main, holes, strokes = classify(contours)
        ordered = sorted(holes, key=lambda c: bounds([c])[1])
        if len(ordered) < count:
            raise ValueError(f"this glyph has {len(ordered)} slots, fewer than the {count} to merge")
        group, rest = ordered[-count:], ordered[:-count]
        x0 = min(bounds([c])[0] for c in group)
        y0 = min(bounds([c])[1] for c in group)
        x1 = max(bounds([c])[2] for c in group)
        y1 = max(bounds([c])[3] for c in group)
        merged = fit((x0, y0, x1, y1), keep_aspect=False)([group[-1]], context)
        return [main, *rest, *merged, *strokes]
    return shaper


def without_feathers(contours, context=None):
    """飛 -> 飞: drop the four small tail feathers, keep the body.

    飛 carries a body contour bigger than half the glyph plus four small plume
    strokes; 飞 is that body. Unlike the 貝 family there is a legitimately large
    non-main contour here, so the size threshold is the whole rule.
    """
    main, holes, strokes = classify(contours)
    small, big = _by_size(main, strokes, 0.15)
    if not small:
        raise ValueError("no feathers found to remove")
    return [main, *holes, *big]


def bar_over_feet(height=0.13, overhang=0.0, level=0.45):
    """The long bottom stroke of 马/鸟/乌, placed where the feet used to be.

    Simplified 马/鸟/乌 replace the 灬 feet with one horizontal stroke, so the
    stroke is fitted into the band the feet occupied -- keeping it inside the
    character instead of below the baseline. The band is measured by
    ``without_feet`` and handed over in the context, so the bar follows the
    weight's own geometry; the bar outline itself comes from 一.
    """
    def shaper(contours, context):
        notes = (context or {}).get("notes", {})
        if "feetBox" not in notes:
            raise ValueError("the bar needs the feet band; run the feet removal first")
        _, fy0, _, fy1 = notes["feetBox"]
        built = (context or {}).get("built") or []
        if not built:
            raise ValueError("the bar needs the body to be built first")
        bx0, by0, bx1, by1 = bounds(built)
        thickness = height * (by1 - by0)
        top = fy0 + level * (fy1 - fy0)
        span = bx1 - bx0
        box = (bx0 - overhang * span, top - thickness, bx1 + overhang * span, top)
        return fit(box, keep_aspect=False)(contours, context)
    return shaper


RECIPES: dict[str, list] = {}


def recipe(char, *parts):
    """Name a new character and the existing contours that compose it."""
    RECIPES[char] = list(parts)
    return char


# Every recipe works in all five weights: selectors name roles, never indices,
# because each weight was drawn separately (貝 has six contours in Light and four
# in Bold).

# --- 貝/頁/見: the 灬 feet go, the box keeps its white slots ------------------
recipe("贝", ("貝", all_contours, then(without_feet, simplified_box())))
recipe("页", ("頁", all_contours, without_feet))
# 见: the frame is one half of 門's bracket mirrored; the legs are 儿 itself.
# 见 = 冂 + 儿: 冂 is its own character in this face, and 元's main contour is
# exactly the pair of 儿 legs, so neither part is drawn from scratch.
recipe("见", ("冂", all_contours, fit((110, 300, 890, 850))),
             ("元", main_contour, fit((130, -80, 870, 290))))
# 员: 員's 口 with its white slot, over 貝 simplified exactly the way 贝 is.
recipe("员", ("員", above_main, fit((355, 575, 645, 865))),
             ("貝", all_contours, then(without_feet, simplified_box(), fit((150, 40, 850, 520)))))

# --- 馬/鳥/烏: same feet removal, then the long bottom stroke ---------------
recipe("马", ("馬", all_contours, body_only), ("一", all_contours, bar_over_feet()))
recipe("鸟", ("鳥", all_contours, body_only), ("一", all_contours, bar_over_feet()))
recipe("乌", ("烏", all_contours, body_only), ("一", all_contours, bar_over_feet()))
# 岛 is 島 with the same feet removal and bottom stroke 鸟 gets -- the 鳥 inside
# 島 is already drawn at 島's size, so nothing is scaled to fit.
recipe("岛", ("島", all_contours, body_only), ("一", all_contours, bar_over_feet()))
recipe("飞", ("飛", all_contours, without_feathers))

# --- 門 -> 门: 门 is a plain 冂 frame with a 丶 at the top left, and this face
# draws 冂 as its own character -- so the frame is borrowed, not re-derived from
# 門's two leaves (mirroring those gave a doubled middle wall).
recipe("门", ("冂", all_contours, fit((190, -80, 870, 800))),
            ("戸", highest, fit((95, 690, 315, 830))))

# --- 东: assembled from the face's single strokes ---------------------------
# 东 is not 東 with a piece cut out of it: the box loses its right wall and its
# bars, and the feet become dots. This face draws single strokes as characters of
# their own -- 一 丨 亅 丿 丶 and the kana ニ 冫 -- so 东 is assembled from those
# strokes at their own weight rather than scaled down out of 東: a stroke scaled
# to a narrower column comes out thin, and this font keeps one weight everywhere.
recipe("东", ("一", all_contours, fit((55, 730, 945, 800), keep_aspect=False)),
             ("冫", highest, then(flip_x(), fit((330, 340, 600, 745), keep_aspect=False))),
             ("ニ", highest, fit((330, 340, 800, 400), keep_aspect=False)),
             ("亅", all_contours, fit((450, -75, 640, 800))),
             ("冫", highest, then(flip_x(), fit((140, -75, 360, 190), keep_aspect=False))),
             ("冫", highest, fit((640, -75, 860, 190), keep_aspect=False)))

# --- 走/辶/糸 compositions --------------------------------------------------
recipe("赵", ("走", all_contours, fit((20, -60, 580, 840))),
            ("乂", all_contours, fit((560, 40, 950, 780))))
recipe("进", ("辻", below(500), translate(0, 0)), ("井", all_contours, fit((380, 120, 900, 800))))
recipe("迁", ("辻", below(500), translate(0, 0)), ("千", all_contours, fit((400, 120, 880, 800))))
# 陈 = 阝 + 东, with that 东 laid out for the narrow column: same strokes, drawn
# at the column's width instead of squeezed there.
recipe("陈", ("限", left_radical, fit((60, -90, 430, 850))),
            ("ニ", highest, fit((450, 736, 960, 801))),
            ("冫", highest, then(flip_x(), fit((600, 340, 800, 740), keep_aspect=False))),
            ("-", all_contours, fit((640, 340, 890, 400), keep_aspect=False)),
            ("亅", all_contours, fit((530, -80, 720, 738), keep_aspect=False)),
            ("冫", highest, then(flip_x(), fit((455, -80, 640, 185), keep_aspect=False))),
            ("冫", highest, fit((700, -80, 885, 185), keep_aspect=False)))
# 护: 扌 from 打; 户 = 所's left component (戶: 尸 plus the bar 户 draws as a dot)
# with that bar dropped, and the dot taken from 丶 -- which leans the way 户's
# first stroke leans.
recipe("护", ("打", left_radical, fit((30, -85, 470, 850))),
            ("所", left_radical, then(except_highest, fit((490, -85, 970, 850)))),
            ("丶", all_contours, fit((500, 740, 700, 850))))
# 维: 糸's body (its own two lower dots are 纟's 撇 and 点) plus 隹.
recipe("维", ("幺", all_contours, fit((30, 170, 400, 860), keep_aspect=False)),
            ("糸", leftmost, fit((30, -70, 400, 160), keep_aspect=False)),
            ("隹", all_contours, fit((410, -50, 950, 850))))


class Face:
    """A face being extended: reads existing glyphs, adds derived ones."""

    def __init__(self, path):
        self.path = Path(path)
        self.font = TTFont(self.path)
        self.cmap = self.font.getBestCmap()
        self.original_glyphs = {
            name: self.font["glyf"][name].compile(self.font["glyf"])
            for name in self.font.getGlyphOrder()
        }
        self.added: dict[str, dict] = {}
        self.pending: list[tuple] = []

    def contours(self, char_or_name):
        name = char_or_name
        if len(char_or_name) == 1 and ord(char_or_name) in self.cmap:
            name = self.cmap[ord(char_or_name)]
        if name not in self.font.getGlyphOrder():
            raise ValueError(f"source glyph {char_or_name!r} is missing from the face")
        return contours_of(self.font, name)

    def add(self, char, parts):
        """Compose a new glyph from transformed source contours."""
        if len(char) != 1:
            raise ValueError(f"{char!r} is not a single character")
        if ord(char) in self.cmap:
            raise ValueError(f"{char!r} is already drawn by this face; a derivation must not overwrite it")
        pen = TTGlyphPen(None)
        context: dict = {"built": [], "notes": {}}
        used, detail = [], []
        for source, select, shape in parts:
            contours = select(self.contours(source))
            if not contours:
                if not getattr(select, "optional", False):
                    # A missing radical is not an empty detail, it is half a
                    # character: refuse the recipe so the weight reports a skip.
                    raise ValueError(
                        f"{char}: {source} has no contour for {select.__name__}; "
                        "this weight draws it fused, so the recipe cannot be proved")
                detail.append(f"{source}(0)")
                continue
            shaped = shape(contours, context)
            for contour in shaped:
                contour.draw(pen)
            context["built"].extend(shaped)
            used.append(source)
            detail.append(f"{source}({len(contours)}->{len(shaped)})")
        return self.register(char, pen.glyph(), detail, metrics=used)

    def register(self, char, glyph, sources, metrics=None, advance=None, vertical_advance=None):
        """Register a finished glyph: metrics, cmap, provenance, verification.

        ``sources`` is human-readable provenance for the report; ``metrics``
        names the glyphs whose advances this one inherits. An imported glyph
        passes its numbers in directly, because its source lives in another
        font.
        """
        if not glyph.numberOfContours or glyph.numberOfContours < 0:
            raise ValueError(f"{char}: the derivation produced an empty glyph")
        if len(char) != 1:
            raise ValueError(f"{char!r} is not a single character")
        if ord(char) in self.cmap:
            raise ValueError(f"{char!r} is already drawn by this face; a derivation must not overwrite it")
        name = self._glyph_name(char)
        box = bounds(_glyph_contours(glyph))
        # A CJK glyph lives inside the em box. A transform that throws a point
        # far outside it has gone wrong, and shipping the result would be worse
        # than leaving the character out and saying so.
        if not all(-LIMIT <= value <= LIMIT for value in box):
            raise ValueError(f"{char}: the outline runs to {[round(v) for v in box]}, outside the {LIMIT} unit box")
        if advance is None:
            advance, measured_vertical = self._metrics_of(metrics or sources)
            vertical_advance = measured_vertical if vertical_advance is None else vertical_advance
        # Claim the codepoint only once the glyph is known to be usable, and
        # before anything else runs: the reference pass and later recipes must
        # see this character as already drawn.
        self.cmap[ord(char)] = name
        self.pending.append((char, name, glyph, advance, vertical_advance))
        self.added[char] = {"glyph": name, "sources": sources, "advance": advance,
                            "verticalAdvance": vertical_advance,
                            "bounds": [round(v) for v in box]}
        return self.added[char]

    def import_glyph(self, char, reference, ratio, reference_name=None):
        """Draw ``char`` from a pinned reference font, matched to this weight.

        The borrowed outline is offset until its own measured stroke thickness
        matches this face's, so one reference weight serves all five. The offset
        moves each point along its normals (a miter offset); where that would
        turn a thin contour inside out -- heavy faces thicken a reference drawn
        for 400 by up to 40% -- only that contour backs off, halving until its
        winding survives, and the report records how far it had to.
        """
        from reference_font import _LengthPen, contour_thickness, offset_matrix_free

        name = reference_name or (reference.getBestCmap() or {}).get(ord(char))
        if not name:
            raise ValueError(f"{char}: the reference font has no glyph for it")
        contours = contours_of(reference, name)
        if not contours:
            raise ValueError(f"{char}: the reference font maps it to a glyph with no outline")
        glyph_set = reference.getGlyphSet()
        area_pen, length_pen = AreaPen(glyph_set), _LengthPen(glyph_set)
        glyph_set[name].draw(area_pen)
        glyph_set[name].draw(length_pen)
        thickness = abs(area_pen.value) / length_pen.length if length_pen.length else 0
        delta = thickness * (ratio - 1) / 2 if abs(thickness * (ratio - 1) / 2) >= 0.5 else 0.0
        shaped, delta, backoff = match_thickness(
            contours, thickness * ratio, delta, offset_matrix_free)
        pen = TTGlyphPen(None)
        for contour in shaped:
            contour.draw(pen)
        advance = reference["hmtx"][name][0]
        vertical = reference["vmtx"][name][0] if "vmtx" in reference else advance
        report = self.register(char, pen.glyph(), [f"reference:{name}"],
                               advance=advance, vertical_advance=vertical)
        report["origin"] = "reference"
        report["offset"] = round(delta, 1)
        report["thickness"] = [round(thickness, 1),
                              round(contour_thickness(shaped), 1)]
        report["targetThickness"] = round(thickness * ratio, 1)
        report["sourceGlyph"] = name
        if backoff < 1.0:
            report["offsetBackoff"] = round(backoff, 3)
        return report

    def thickness_of(self, glyph):
        """Ink area over outline length for a glyph that is not in the font yet."""
        from reference_font import contour_thickness

        return contour_thickness(_glyph_contours(glyph))

    def enforce_weight(self, baseline, tolerance=0.12, only=None):
        """Bring every pending glyph to this face's measured stroke thickness.

        A component scaled down to fit a box scales its strokes down with it:
        赵 came out at half the face's weight, 见 and 维 at 0.6. The face has no
        such thing as a lighter stroke -- 同字等粗 is the rule -- so every
        derived glyph is measured and, if it is off by more than ``tolerance``,
        offset along its own normals until it matches. Whatever cannot be
        brought into tolerance is returned: the caller may prefer the reference
        font for those, and a caller with no reference must report them.

        A clamped ``baseline`` of zero means the face has no measurable weight
        (a fixture); nothing is normalised in that case. ``only`` narrows the
        pass to one class of glyph (``"recipe"`` leaves imported ones alone --
        they were already matched when they were imported, and a second attempt
        on a dense glyph at Black weight would only drop it).
        """
        from reference_font import contour_thickness, offset_matrix_free

        if not baseline:
            return []
        def measure(glyph):
            # A glyph whose outline has no length at all cannot be measured;
            # that is a failure to prove, not a crash.
            try:
                return contour_thickness(_glyph_contours(glyph))
            except ValueError:
                return 0.0

        unproven = []
        for index, (char, name, glyph, advance, vertical) in enumerate(self.pending):
            if only == "recipe" and self.added[char].get("origin") == "reference":
                continue
            measured = measure(glyph)
            if not measured:
                unproven.append(char)
                continue
            if abs(measured / baseline - 1) <= tolerance:
                continue
            shaped, delta, backoff = match_thickness(
                _glyph_contours(glyph), baseline, measured * (baseline / measured - 1) / 2,
                offset_matrix_free)
            pen = TTGlyphPen(None)
            for contour in shaped:
                contour.draw(pen)
            # The pen hands over its contours exactly once: glyph() empties it,
            # so the object that gets measured has to be the object that gets
            # stored. Measuring one and storing a second empty one is how an
            # invisible glyph nearly shipped.
            normalized = pen.glyph()
            after = measure(normalized)
            info = self.added[char]
            info["weightBefore"] = round(measured / baseline, 3)
            info["offsetToFaceWeight"] = round(delta, 1)
            if backoff < 1.0:
                info["offsetBackoff"] = round(backoff, 3)
            if not normalized.numberOfContours or normalized.numberOfContours < 0:
                info["weightAfter"] = 0.0
                unproven.append(char)
                continue
            if abs(after / baseline - 1) > tolerance:
                # The offset could not reach the face's weight (a contour that
                # would invert, or a shape whose joins resist). Leave the glyph
                # as derived and let the caller decide.
                info["weightAfter"] = round(after / baseline, 3)
                unproven.append(char)
                continue
            info["weightAfter"] = round(after / baseline, 3)
            self.pending[index] = (char, name, normalized, advance, vertical)
        return unproven

    def _glyph_name(self, char):
        taken = set(self.font.getGlyphOrder()) | {entry[1] for entry in self.pending}
        base = f"uni{ord(char):04X}"
        name, suffix = base, 1
        while name in taken:
            name = f"{base}.{suffix}"
            suffix += 1
        return name

    def _metrics_of(self, used):
        """Median horizontal and vertical metrics of the source glyphs.

        A derived glyph must sit on the same advance as the strokes it borrows;
        taking the median of its sources is stable and never invents a number.
        """
        horizontal, vertical = {}, {}
        for source in used:
            name = source
            if len(name) == 1 and ord(name) in self.font.getBestCmap():
                name = self.font.getBestCmap()[ord(name)]
            horizontal.setdefault(name, self.font["hmtx"][name][0])
            if "vmtx" in self.font:
                vertical.setdefault(name, self.font["vmtx"][name][0])
        def pick(table):
            return sorted(table.values())[len(table) // 2]
        return pick(horizontal), (pick(vertical) if vertical else 1000)

    def save(self, path):
        """Materialise every pending glyph at once, then write and verify."""
        font = self.font
        self.saved_names = [entry[1] for entry in self.pending]
        font.setGlyphOrder([*font.getGlyphOrder(), *self.saved_names])
        glyf = font["glyf"]
        for char, name, glyph, advance, vertical_advance in self.pending:
            glyf.glyphs[name] = glyph
            glyph.recalcBounds(glyf)
            font["hmtx"].metrics[name] = (advance, glyph.xMin)
            if "vmtx" in font:
                # Horizontal and vertical metrics share one implementation; a
                # face with a vmtx needs the derived glyph there too or saving
                # fails on the missing entry.
                font["vmtx"].metrics[name] = (vertical_advance, glyph.yMax)
            for table in font["cmap"].tables:
                if table.isUnicode():
                    table.cmap[ord(char)] = name
            self.cmap[ord(char)] = name
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        font.save(target)
        self.pending = []
        self.verify(target)
        return target

    def verify(self, path):
        """Only the derived glyphs may be new, and nothing may have vanished."""
        after = TTFont(path, recalcBBoxes=False, recalcTimestamp=False)
        glyf = after["glyf"]
        for name, compiled in self.original_glyphs.items():
            if name not in after.getGlyphOrder():
                raise ValueError(f"{self.path.name}: glyph {name} disappeared")
            if glyf[name].compile(glyf) != compiled:
                raise ValueError(f"{self.path.name}: unrelated glyph {name} changed")
        order = after.getGlyphOrder()
        new = [name for name in order if name not in self.original_glyphs]
        if new != self.saved_names:
            raise ValueError(f"{self.path.name}: unexpected new glyphs {sorted(set(new) - set(self.saved_names))}")
        for name in self.original_glyphs:
            if order.index(name) != list(self.original_glyphs).index(name):
                raise ValueError(f"{self.path.name}: glyph order changed at {name}")
        cmap = after.getBestCmap()
        added = {ord(char) for char in self.added}
        for code in added:
            if code not in cmap:
                raise ValueError(f"{self.path.name}: derived character {chr(code)} is not mapped")
        extra = set(cmap) - self.original_cmap_codes()
        if extra != added:
            raise ValueError(f"{self.path.name}: unexpected codepoints {sorted(extra - added)}")
        return {"glyphs": len(order), "added": sorted(self.added), "cmap": len(cmap)}

    def original_cmap_codes(self):
        return set(TTFont(self.path, lazy=True).getBestCmap() or {})


def gb2312_characters():
    """The GB2312 hanzi set, generated from the codec rather than a data file."""
    characters = set()
    for lead in range(0xB0, 0xF8):
        for trail in range(0xA1, 0xFF):
            try:
                char = bytes([lead, trail]).decode("gb2312")
            except UnicodeDecodeError:
                continue
            if "\u4e00" <= char <= "\u9fff":
                characters.add(char)
    return characters


def extend_face(path, output, recipes=None, reference=None, charset=None):
    """Derive every recipe this weight can prove, then borrow what is missing.

    A weight that fuses a character's strokes into one outline cannot be
    simplified by picking contours, and inventing a cut for it would be
    guesswork. Those cases are skipped and reported per weight: a missing glyph
    falls back to the system font, which is honest, while a bad glyph would
    silently ship in the module. Characters the recipes cannot cover are
    borrowed from a pinned reference font when one is given.
    """
    recipes = RECIPES if recipes is None else recipes
    face = Face(path)
    skipped = {}
    # Measure the weight difference while the face is still untouched: a
    # character that has been claimed but not yet written has no glyph to
    # measure, and its codepoint is already in this face's map.
    import reference_font as reference_module

    face.reference_ratio = None
    # The face's own weight, measured on characters it drew itself: every
    # derived glyph -- rule or reference -- has to end up at this thickness.
    try:
        face.baseline_thickness = reference_module.stroke_width(face.font)
    except ValueError:
        # A face with too few shared probe characters has no measurable weight;
        # there is nothing to normalise against, so derivations are left alone.
        face.baseline_thickness = None
    if reference is not None:
        face.reference_ratio = reference_module.shared_stroke_ratio(face.font, reference[0])
    for char, parts in recipes.items():
        try:
            face.add(char, parts)
        except ValueError as error:
            skipped[char] = str(error)
    borrowed = 0
    if reference is not None and charset is not None:
        ref_font, _entry = reference
        ratio = face.reference_ratio
        ref_cmap = ref_font.getBestCmap() or {}
        for char in sorted(charset):
            if ord(char) in face.cmap:
                continue
            if ord(char) not in ref_cmap:
                skipped[char] = f"{char}: the reference font has no glyph for it"
                continue
            try:
                face.import_glyph(char, ref_font, ratio)
                borrowed += 1
            except ValueError as error:
                skipped[char] = str(error)
    unproven = face.enforce_weight(face.baseline_thickness, only="recipe")
    if unproven and reference is not None:
        # A rule-derived glyph that cannot reach the face's weight is replaced
        # by the reference's own drawing of that character, offset to match:
        # shipping a stroke half the weight of its neighbours is worse than
        # importing the shape, and the report says which happened.
        ref_font, _entry = reference
        for char in unproven:
            info = face.added[char]
            face.pending = [entry for entry in face.pending if entry[0] != char]
            del face.added[char]
            try:
                face.import_glyph(char, ref_font, face.reference_ratio)
                face.added[char]["replacedRecipe"] = True
                face.added[char]["reason"] = f"the rule-derived outline measured {info.get('weightBefore')} of the face's weight and could not be offset to it"
                borrowed += 1
            except ValueError as error:
                skipped[char] = str(error)
        if unproven:
            face.enforce_weight(face.baseline_thickness)
    elif unproven:
        for char in unproven:
            skipped[char] = (f"{char}: the rule-derived outline measures "
                             f"{face.added[char].get('weightAfter')} of the face's stroke weight")
    # Imported glyphs keep their shortfall in the report rather than being
    # dropped: a dense character at 0.86 of the face's weight is a far smaller
    # defect than a missing character.
    for _char, info in face.added.items():
        if info.get("origin") != "reference":
            continue
        ratio = info["thickness"][1] / info["targetThickness"] if info.get("targetThickness") else None
        if ratio is not None and abs(ratio - 1) > 0.12:
            info["weightShortfall"] = round(ratio, 3)
    if face.pending:
        face.save(output)
    return face, skipped, borrowed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, default=ROOT / "build/fonts")
    parser.add_argument("--output", type=Path, default=ROOT / "build/fonts-simplified")
    parser.add_argument("--report", type=Path, default=ROOT / "build/extend-report.json")
    parser.add_argument("--reference", default=None,
                        help="Reference font id from config/reference-sources.json")
    parser.add_argument("--reference-dir", type=Path, default=ROOT / "build/reference",
                        help="Directory holding the pinned reference file")
    parser.add_argument("--charset", default="none", choices=("none", "gb2312", "targets"),
                        help="Characters to borrow from the reference when the recipes cannot draw them")
    args = parser.parse_args()
    if not RECIPES:
        raise SystemExit("no recipes are defined yet")
    reference = None
    if args.reference:
        import reference_font as reference_module

        reference = reference_module.load(args.reference, args.reference_dir)
    charset = None
    if args.charset == "gb2312":
        charset = gb2312_characters()
    elif args.charset == "targets":
        targets = json.loads((ROOT / "config/glyph-targets.json").read_text())
        charset = set(targets["textCharacters"])
    report = []
    for style, face in FACES.items():
        source = args.prepared / face["installedFile"]
        result, skipped, borrowed = extend_face(
            source, args.output / face["installedFile"], reference=reference, charset=charset)
        faces_report = {"face": style, "source": str(source), "added": result.added,
                        "skipped": skipped, "borrowedFromReference": borrowed}
        if reference is not None:
            faces_report["reference"] = reference[1]["id"]
            faces_report["strokeRatio"] = round(result.reference_ratio, 3)
        report.append(faces_report)
        summary = f"{style}: 派生 {len(result.added)}"
        if borrowed:
            summary += f"（其中参考字体 {borrowed}）"
        if skipped:
            summary += f"，跳过 {len(skipped)}"
        print(summary)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
