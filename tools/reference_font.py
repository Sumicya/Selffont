#!/usr/bin/env python3
"""Borrow outlines from a pinned, licensed reference font.

Zen Maru is a Japanese face: it never drew about half of the GB2312 simplified
set. Those glyphs are imported from a reference font instead of being invented,
and the reference is declared in ``config/reference-sources.json`` with its
project, commit, SHA-256, licence and Reserved Font Names. Nothing is borrowed
from a font that has not been pinned and licensed here, and every borrowed glyph
is recorded with its provenance in the build report.

Two things make an import usable rather than merely legal:

``stroke_width``  measures a face's effective stroke thickness as ink area over
                  outline length. Zen Maru's five weights measure roughly
                  20/35/50/64/79 units, so a glyph borrowed from a single
                  reference weight would look wrong in four of the five faces.
``offset``        thickens or thins a contour by moving it along its own normals
                  (a miter offset, with self-intersections left to the non-zero
                  fill rule). One reference weight therefore serves all five
                  faces, with the offset measured per face and per glyph.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "config/reference-sources.json").read_text())
REFERENCES = {entry["id"]: entry for entry in MANIFEST["references"]}

# Characters every CJK face draws, used to measure a face's stroke thickness.
# They have to be present in both the face and the reference for the comparison
# to mean anything, so callers intersect this with the two cmaps.
PROBE = "一丁七万丈三上下不与丐丑且世丘丙业东丝专严丧世丘"

# How far a corner may stretch a miter before the offset falls back to moving the
# point along the corner's bisector instead. Without a limit, a nearly straight
# (or doubled-back) segment pair divides by a number close to zero and throws the
# point across the canvas -- which is how a single borrowed glyph ended up five
# ems wide.
MITER_LIMIT = 4.0


class UnpinnedReference(ValueError):
    """The reference font on disk is not the pinned one."""


def load(reference_id: str, directory: Path) -> tuple[TTFont, dict]:
    """Open a pinned reference font, refusing anything that does not match."""
    if reference_id not in REFERENCES:
        raise UnpinnedReference(f"{reference_id!r} is not a declared reference")
    entry = REFERENCES[reference_id]
    path = Path(directory) / Path(entry["file"]).name
    if not path.is_file():
        raise UnpinnedReference(f"{path} is missing")
    data = path.read_bytes()
    if len(data) != entry["bytes"]:
        raise UnpinnedReference(f"{path} is {len(data)} bytes, expected {entry['bytes']}")
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry["sha256"]:
        raise UnpinnedReference(f"{path} has SHA-256 {digest}, expected {entry['sha256']}")
    return TTFont(path), entry


class _LengthPen(BasePen):
    """Total outline length, used with AreaPen to estimate stroke thickness.

    The glyph set must be passed in: CJK faces build many glyphs as composites,
    and a pen without one cannot expand a component into its contours.
    """

    def __init__(self, glyph_set=None):
        super().__init__(glyph_set)
        self.length = 0.0

    def _moveTo(self, pt):
        self.last = pt

    def _lineTo(self, pt):
        self.length += math.dist(pt, self.last)
        self.last = pt

    def _curveToOne(self, p1, p2, p3):
        self._lineTo(p3)

    def _qCurveToOne(self, p1, p2):
        self._lineTo(p2)


def outline_length(glyph_set, glyph_name):
    pen = _LengthPen(glyph_set)
    glyph_set[glyph_name].draw(pen)
    return pen.length


def stroke_width(font: TTFont, probe=PROBE, minimum_samples=6):
    """Effective stroke thickness of a face: total ink area over total length.

    A stroke of width ``w`` and length ``L`` covers about ``w * L`` units, so
    area/length is a thickness estimate in font units that needs no rendering.
    ``minimum_samples`` guards against reporting a number from two glyphs.
    """
    from fontTools.pens.areaPen import AreaPen

    glyphs, cmap = font.getGlyphSet(), font.getBestCmap() or {}
    area = length = 0.0
    samples = 0
    for char in probe:
        name = cmap.get(ord(char))
        if not name:
            continue
        samples += 1
        pen = AreaPen(glyphs)
        glyphs[name].draw(pen)
        area += abs(pen.value)
        length += outline_length(glyphs, name)
    if samples < minimum_samples or length <= 0:
        raise ValueError(f"only {samples} probe glyphs available; cannot measure a stroke width")
    return area / length


def shared_stroke_ratio(face: TTFont, reference: TTFont, probe=PROBE, minimum_samples=6):
    """How much thicker ``face`` draws the same characters than ``reference``.

    Measuring the two faces on the characters they share keeps design
    differences out of the number: only the stroke weight differs. Values above
    one mean the face is heavier than the reference.
    """
    face_glyphs, face_cmap = face.getGlyphSet(), face.getBestCmap() or {}
    ref_glyphs, ref_cmap = reference.getGlyphSet(), reference.getBestCmap() or {}
    from fontTools.pens.areaPen import AreaPen

    def measure(glyphs, cmap, chars):
        area = length = 0.0
        for char in chars:
            name = cmap[ord(char)]
            pen = AreaPen(glyphs)
            glyphs[name].draw(pen)
            area += abs(pen.value)
            length += outline_length(glyphs, name)
        return area / length

    shared = [char for char in probe if ord(char) in face_cmap and ord(char) in ref_cmap]
    if len(shared) < minimum_samples:
        raise ValueError(f"only {len(shared)} characters are shared; cannot compare weights")
    return measure(face_glyphs, face_cmap, shared) / measure(ref_glyphs, ref_cmap, shared)


def contour_thickness(contours):
    """Ink area over outline length for contours that are not in a font yet."""
    from fontTools.pens.areaPen import AreaPen

    area, length = AreaPen(None), _LengthPen(None)
    for contour in contours:
        contour.draw(area)
        contour.draw(length)
    if not length.length:
        raise ValueError("these contours enclose no outline")
    return abs(area.value) / length.length


def _normals(points, closed=True):
    """Outward unit normal of every segment of a point ring."""
    result = []
    for index in range(len(points)):
        nxt = points[(index + 1) % len(points)]
        if not closed and index == len(points) - 1:
            break
        dx, dy = nxt[0] - points[index][0], nxt[1] - points[index][1]
        length = math.hypot(dx, dy)
        result.append((dy / length, -dx / length) if length else (0.0, 0.0))
    return result


def fill_sign(contours):
    """+1 or -1: which normal direction means "more ink" for these contours.

    A glyph mixes solid contours with counters, and they wind opposite ways, so
    the sign cannot be decided per contour: a counter offset by its own winding
    would grow while the stroke around it thickens, which is exactly the bug
    that made heavy weights come out thinner than the reference. The largest
    contour is always a solid, so its winding settles the direction for the
    whole glyph.
    """
    largest = max(contours, key=lambda contour: abs(_signed_area([p for p in contour.points() if p])))
    return -1 if _signed_area([p for p in largest.points() if p]) < 0 else 1


def offset_matrix_free(contours, delta, fill=None):
    """Move every point of every contour along its normals by ``delta``.

    A miter offset: a point between two segments moves by
    ``delta * (n1 + n2) / (1 + n1 . n2)``, which lands corners exactly where a
    true offset would (a right angle moves diagonally by ``delta * sqrt(2)``).
    Self-intersections at joins are left alone -- the non-zero fill rule handles
    them, which is why a naive offset is usable here at all.

    Positive ``delta`` always means "more ink" for the glyph as a whole: solids
    grow and counters shrink together, because ``fill`` fixes one direction for
    the whole glyph (see :func:`fill_sign`).
    """
    if fill is None:
        fill = fill_sign(contours)
    result = []
    for contour in contours:
        points = [p for p in contour.points() if p is not None]
        if len(points) < 3:
            result.append(contour)
            continue
        normals = _normals(points)
        moved = []
        for index, point in enumerate(points):
            first = normals[(index - 1) % len(points)]
            second = normals[index]
            dot = first[0] * second[0] + first[1] * second[1]
            bx, by = first[0] + second[0], first[1] + second[1]
            bisector = math.hypot(bx, by)
            if bisector > 2 / MITER_LIMIT:
                # |n1 + n2| = 2 cos(half angle), so this keeps the miter's reach
                # within MITER_LIMIT * |delta| of the original point.
                scale = delta * fill / (1 + dot)
                move = (scale * bx, scale * by)
            elif bisector > 1e-6:
                move = (delta * fill * bx / bisector, delta * fill * by / bisector)
            else:
                move = (0.0, 0.0)
            moved.append((point[0] + move[0], point[1] + move[1]))
        result.append(contour.rebuild(moved))
    return result


def _signed_area(points):
    total = 0.0
    for index in range(len(points)):
        x0, y0 = points[index]
        x1, y1 = points[(index + 1) % len(points)]
        total += x0 * y1 - x1 * y0
    return total / 2
