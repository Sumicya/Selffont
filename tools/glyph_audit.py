#!/usr/bin/env python3
"""Check the author's target characters against the prepared faces.

Replaces the old whole-charset Unicode audit. The input is the small, owned list
in ``config/glyph-targets.json``; the output says, per character, which faces can
already render it and which cannot.

A character that no face covers needs a *designed* glyph (a new outline), which is
not something a point patch can do. Keeping that distinction visible is the whole
point of this tool: it stops "apply the handwriting conventions" from quietly
turning into "invent a Chinese font".

    python3 tools/glyph_audit.py                     # human-readable table
    python3 tools/glyph_audit.py --json out.json     # machine-readable report
"""
import argparse
import json
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "config/font-source.json").read_text())
TARGETS = json.loads((ROOT / "config/glyph-targets.json").read_text())


def face_coverage(font_dir: Path):
    result = {}
    for face in MANIFEST["faces"]:
        path = Path(font_dir) / face["installedFile"]
        if not path.is_file():
            raise SystemExit(f"missing prepared face: {path} (run tools/prepare_font.py)")
        with TTFont(path, lazy=True) as font:
            result[face["style"]] = set(font.getBestCmap() or {})
    return result


def audit(font_dir: Path, targets: dict) -> dict:
    """Split the target list into 'a point patch can rework this' and 'not drawn yet'."""
    coverage = face_coverage(font_dir)
    characters = []
    for char in dict.fromkeys(targets["textCharacters"]):
        present = [style for style, cmap in coverage.items() if ord(char) in cmap]
        characters.append(
            {
                "char": char,
                "codepoint": f"U+{ord(char):04X}",
                "faces": present,
                "status": "editable" if present else "needs-new-glyph",
            }
        )
    characters.sort(key=lambda row: (row["status"], row["codepoint"]))
    studies = []
    for char in dict.fromkeys(targets["radicalStudies"]):
        present = [style for style, cmap in coverage.items() if ord(char) in cmap]
        studies.append({"char": char, "codepoint": f"U+{ord(char):04X}", "faces": present})
    return {
        "family": MANIFEST["family"],
        "sourceFamily": MANIFEST["sourceFamily"],
        "faces": [face["style"] for face in MANIFEST["faces"]],
        "editable": [row["char"] for row in characters if row["status"] == "editable"],
        "needsNewGlyph": [row["char"] for row in characters if row["status"] == "needs-new-glyph"],
        "characters": characters,
        "radicalStudies": studies,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-dir", type=Path, default=ROOT / "build/fonts")
    parser.add_argument("--targets", type=Path, default=ROOT / "config/glyph-targets.json")
    parser.add_argument("--json", type=Path, help="Write the full report here")
    args = parser.parse_args()
    report = audit(args.font_dir, json.loads(Path(args.targets).read_text()))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"{report['family']} (from {report['sourceFamily']}) vs {len(report['characters'])} text targets")
    for row in report["characters"]:
        mark = "edit " if row["status"] == "editable" else " NEW "
        print(f"  {mark} {row['char']} {row['codepoint']}  {','.join(row['faces']) or '-'}")
    print(
        f"editable={len(report['editable'])} "
        f"needsNewGlyph={len(report['needsNewGlyph'])} "
        f"({''.join(report['needsNewGlyph']) or '-'})"
    )
    print(
        "radical studies (stroke reference, not text): "
        + " ".join(row["char"] for row in report["radicalStudies"])
    )
    sys.stdout.flush()


if __name__ == "__main__":
    main()
