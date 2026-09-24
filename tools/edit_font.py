#!/usr/bin/env python3
"""Apply explicitly authored point patches to a prepared face.

This is the only glyph editor in the project, and it is deliberately narrow. It
does not infer strokes from a photo, does not smooth or round anything by itself,
does not take a character range and has no ``--all`` mode. A patch names the
exact glyph and the exact point indices to move; everything else is untouched.

Patch file (one per face, ``config/glyph-patches/<Style>.json``)::

    {
      "faceSha256": "<source face SHA-256 from config/font-source.json>",
      "glyphs": {
        "马": {"points": [{"index": 17, "dx": -6, "dy": 3}]}
      }
    }

``dx``/``dy`` are relative moves, ``x``/``y`` absolute replacements; mixing the
two forms in one point is an error. Coordinates are font units in the face's own
grid.

Refused on purpose:

* composite glyphs (editing a reference would silently change every user);
* glyphs carrying hinting bytecode (instructions address the old outline -- a
  point move would leave them lying about the contour);
* empty point lists, duplicate indices, out-of-range indices;
* variable faces with a damaged ``gvar`` topology.

The glyph set is applied all-or-nothing, and the result is verified before it
replaces anything: glyph order, cmap, family, weight and every *other* glyph must
be byte-identical to the input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

MANIFEST = json.loads((ROOT / "config/font-source.json").read_text())
FACES = {face["style"]: face for face in MANIFEST["faces"]}
PATCH_DIR = ROOT / "config/glyph-patches"


class PatchError(ValueError):
    """A patch is unsafe, malformed, or does not match the face it names."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _simple_glyph(font: TTFont, char: str):
    cmap = font.getBestCmap() or {}
    glyph_name = cmap.get(ord(char))
    if not glyph_name:
        raise PatchError(f"{char!r}: no cmap entry in this face")
    glyph = font["glyf"][glyph_name]
    if glyph.numberOfContours < 0:
        raise PatchError(f"{char!r}: composite glyphs are not editable")
    glyph.expand(font["glyf"])
    if glyph.program.getBytecode():
        raise PatchError(f"{char!r}: glyph is hinted; a point move would stale its instructions")
    return glyph_name, glyph


def _outline_digest(glyph) -> str:
    """Digest point topology and coordinates, not the compiled font table."""
    payload = {
        "contours": list(glyph.endPtsOfContours or []),
        "coordinates": [(int(x), int(y)) for x, y in glyph.coordinates],
        "flags": [int(flag) for flag in glyph.flags],
    }
    return hashlib.sha256(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def _validate_variations(font: TTFont, glyph_name: str, point_count: int) -> int:
    """If the face carries variation data, the edited glyph's records must fit it."""
    gvar = font.get("gvar")
    if gvar is None:
        return 0
    variations = gvar.variations.get(glyph_name)
    if not variations:
        raise PatchError(f"{glyph_name}: no gvar record for the edited glyph")
    expected = point_count + 4  # four phantom points in a gvar record
    for variation in variations:
        if len(variation.coordinates) != expected:
            raise PatchError(f"{glyph_name}: gvar point topology mismatch")
    return len(variations)


def _validate_point_edit(edit: dict[str, Any], point_count: int, char: str):
    if not isinstance(edit, dict):
        raise PatchError(f"{char!r}: every point edit must be an object")
    index = edit.get("index")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < point_count:
        raise PatchError(f"{char!r}: point index {index!r} is outside the outline")
    relative = "dx" in edit or "dy" in edit
    absolute = "x" in edit or "y" in edit
    if relative and absolute:
        raise PatchError(f"{char!r} point {index}: cannot mix relative and absolute coordinates")
    if not relative and not absolute:
        raise PatchError(f"{char!r} point {index}: expected dx/dy or x/y")
    values = (edit.get("dx", 0), edit.get("dy", 0)) if relative else (edit.get("x"), edit.get("y"))
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise PatchError(f"{char!r} point {index}: coordinates must be integers")
    return index, values[0], values[1], relative


def load_patch(path: Path, face: dict[str, Any]) -> dict[str, Any]:
    try:
        patch = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise PatchError(f"cannot read patch {path}: {error}") from error
    if not isinstance(patch, dict):
        raise PatchError("patch root must be an object")
    if patch.get("faceSha256") != face["sha256"]:
        raise PatchError(
            f"{path}: faceSha256 does not match the pinned {face['file']} source face"
        )
    glyphs = patch.get("glyphs")
    if not isinstance(glyphs, dict) or not glyphs:
        raise PatchError("patch glyphs must be a non-empty object")
    return patch


def apply_glyphs(font: TTFont, glyphs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Apply a validated glyph map; return an auditable per-character report."""
    changed: dict[str, dict[str, Any]] = {}
    named: set[str] = set()
    # Plan every edit first: a patch that fails anywhere changes nothing.
    plan = []
    for char, spec in glyphs.items():
        if not isinstance(char, str) or len(char) != 1:
            raise PatchError(f"invalid glyph key {char!r}")
        if not isinstance(spec, dict) or not isinstance(spec.get("points"), list):
            raise PatchError(f"{char!r}: expected a points list")
        if not spec["points"]:
            raise PatchError(f"{char!r}: an empty point list is not a change")
        glyph_name, glyph = _simple_glyph(font, char)
        if glyph_name in named:
            raise PatchError(f"{char!r}: glyph is already named by another character")
        named.add(glyph_name)
        point_count = len(glyph.coordinates)
        variation_count = _validate_variations(font, glyph_name, point_count)
        seen: set[int] = set()
        edits = []
        for edit in spec["points"]:
            index, first, second, relative = _validate_point_edit(edit, point_count, char)
            if index in seen:
                raise PatchError(f"{char!r}: point {index} is listed more than once")
            seen.add(index)
            edits.append((index, first, second, relative))
        plan.append((char, glyph_name, glyph, point_count, variation_count, edits))

    for char, glyph_name, glyph, point_count, variation_count, edits in plan:
        before = _outline_digest(glyph)
        for index, first, second, relative in edits:
            x, y = glyph.coordinates[index]
            glyph.coordinates[index] = (x + first, y + second) if relative else (first, second)
        after = _outline_digest(glyph)
        if after == before:
            raise PatchError(f"{char!r}: patch does not change the outline")
        changed[char] = {
            "glyph": glyph_name,
            "pointsMoved": len(edits),
            "pointCount": point_count,
            "variationRecords": variation_count,
            "before": before,
            "after": after,
        }
    return changed


def component_users(font: TTFont, glyph_names) -> dict[str, list[str]]:
    """Report composites that reference a patched glyph.

    Editing a component silently changes every composite that borrows it, so the
    report names them instead of hiding the side effect. The author decides
    whether that is acceptable; nothing is refused automatically.
    """
    glyf = font["glyf"]
    wanted = set(glyph_names)
    users: dict[str, list[str]] = {}
    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if not glyph.isComposite():
            continue
        for component in glyph.components:
            if component.glyphName in wanted:
                users.setdefault(component.glyphName, []).append(name)
    return users


def characters_for(font: TTFont, glyph_names) -> dict[str, str]:
    """{glyph name: characters mapping to it} for a human-readable report."""
    reverse: dict[str, list[int]] = {}
    for code, name in (font.getBestCmap() or {}).items():
        reverse.setdefault(name, []).append(code)
    return {name: "".join(chr(code) for code in sorted(reverse.get(name, []))) for name in glyph_names}


def _font_signature(font_bytes: bytes) -> dict[str, Any]:
    font = TTFont(__import__("io").BytesIO(font_bytes), recalcBBoxes=False, recalcTimestamp=False)
    glyf = font["glyf"]
    return {
        "glyphOrder": font.getGlyphOrder(),
        "glyphs": {name: glyf[name].compile(glyf) for name in font.getGlyphOrder()},
        "cmap": font.getBestCmap(),
        "family": font["name"].getDebugName(1),
        "weight": font["OS/2"].usWeightClass,
    }


def verify_only_targets_changed(before: bytes, after: bytes, chars: list[str]):
    """The shipped promise: only the named glyphs differ; everything else is identical."""
    previous, current = _font_signature(before), _font_signature(after)
    if previous["glyphOrder"] != current["glyphOrder"]:
        raise PatchError("glyph order changed during a point patch")
    if previous["cmap"] != current["cmap"]:
        raise PatchError("cmap changed during a point patch")
    if previous["family"] != current["family"] or previous["weight"] != current["weight"]:
        raise PatchError("family or weight changed during a point patch")
    font = TTFont(__import__("io").BytesIO(after), recalcBBoxes=False, recalcTimestamp=False)
    cmap = font.getBestCmap() or {}
    expected = {cmap[ord(char)] for char in chars if ord(char) in cmap}
    unexpected = [
        name for name in previous["glyphs"]
        if name not in expected and previous["glyphs"][name] != current["glyphs"][name]
    ]
    if unexpected:
        raise PatchError(f"glyphs outside the patch changed: {unexpected[:8]}")


def apply_patch(source: Path, patch_path: Path, output: Path, face: dict[str, Any],
                report_path: Path | None = None) -> dict[str, Any]:
    source = Path(source)
    patch = load_patch(patch_path, face)
    before = source.read_bytes()
    font = TTFont(source)
    changed = apply_glyphs(font, patch["glyphs"])
    users = component_users(font, [entry["glyph"] for entry in changed.values()])
    if users:
        labels = characters_for(font, [name for names in users.values() for name in names])
        for glyph_name, composites in users.items():
            described = ", ".join(f"{name} ({labels[name] or 'no cmap entry'})" for name in composites)
            print(f"[notice] {face['style']}: {glyph_name} is also a component of {described}", file=sys.stderr)

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".ttf", delete=False) as temporary:
        staged = Path(temporary.name)
    try:
        font.save(staged)
        after = staged.read_bytes()
        verify_only_targets_changed(before, after, list(changed))
        staged.replace(output)
    finally:
        staged.unlink(missing_ok=True)

    result = {
        "face": face["style"],
        "sourceFile": source.name,
        "sourceSha256": sha256(source),
        "outputFile": output.name,
        "outputSha256": sha256(output),
        "changedGlyphs": changed,
        "componentUsers": {name: characters_for(font, names) for name, names in users.items()},
        "policy": "explicit point edits only; contours, point counts and variation records preserved",
    }
    if report_path:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result


def _warn_if_derived(source: Path, face: dict[str, Any]) -> None:
    """Say out loud when a patch meets a derived face instead of the pinned one.

    Patches address points by index in the *pinned* source face. The simplified
    extension runs before the patches, so the face being edited is usually a
    derived one: that is fine for characters whose glyph was not derived, and
    wrong for characters that were. The tool cannot tell which is which, so it
    prints the mismatch rather than staying quiet about it.
    """
    digest = sha256(source)
    if digest != face["sha256"]:
        print(f"[notice] {face['style']}: editing a derived face ({digest[:12]}), not the "
              f"pinned {face['file']} ({face['sha256'][:12]}); point indices must match "
              "the glyph this face actually draws", file=sys.stderr)


def apply_patch_dir(prepared: Path, patched: Path, patch_dir: Path, report_path: Path | None = None) -> list[dict[str, Any]]:
    """Apply every ``<Style>.json`` patch found for a prepared face directory."""
    prepared, patched = Path(prepared), Path(patched)
    patched.mkdir(parents=True, exist_ok=True)
    results = []
    for style, face in FACES.items():
        source = prepared / face["installedFile"]
        if not source.is_file():
            raise PatchError(f"prepared face is missing: {source}")
        patch_path = Path(patch_dir) / f"{style}.json"
        destination = patched / face["installedFile"]
        if patch_path.is_file():
            _warn_if_derived(source, face)
            results.append(apply_patch(source, patch_path, destination, face))
        else:
            destination.write_bytes(source.read_bytes())
    if report_path:
        Path(report_path).write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, default=ROOT / "build/fonts-simplified",
                        help="Directory from tools/prepare_font.py, extended by "
                             "tools/extend_font.py; falls back to build/fonts when the "
                             "extension has not run")
    parser.add_argument("--patches", type=Path, default=PATCH_DIR,
                        help="Directory of <Style>.json point patches")
    parser.add_argument("--output", type=Path, default=ROOT / "build/fonts-patched")
    parser.add_argument("--report", type=Path, default=ROOT / "build/glyph-patch-report.json")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.prepared.is_dir():
        fallback = ROOT / "build/fonts"
        if fallback.is_dir():
            print(f"[notice] {args.prepared} does not exist; using {fallback} "
                  "(run tools/extend_font.py to include the simplified glyphs)", file=sys.stderr)
            args.prepared = fallback
        else:
            raise SystemExit(f"no prepared faces in {args.prepared} or {fallback}; "
                             "run tools/prepare_font.py first")
    results = apply_patch_dir(args.prepared, args.output, args.patches, args.report)
    print(json.dumps([{r["face"]: sorted(r["changedGlyphs"])} for r in results], ensure_ascii=False))


if __name__ == "__main__":
    main()
