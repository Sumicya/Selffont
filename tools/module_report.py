#!/usr/bin/env python3
"""Summarise a built module by reading the report it carries.

The module zip is the artifact; ``module-report.json`` inside it is the record of
what went in -- face hashes, the static weight mapping, metric normalisation and
what the device has *not* been asked to prove yet. This tool extracts that report
next to the archive so CI can upload it as a text artifact and a human can read
it without unzipping anything.

    python3 tools/module_report.py --module build/Selffont-Maru.zip
"""
import argparse
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def summarise(archive_path: Path, output=None):
    """Write the module's own report next to it and return it as a dict."""
    with zipfile.ZipFile(archive_path) as archive:
        report = json.loads(archive.read("module-report.json"))
    output = output or archive_path.with_name("module-report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", type=Path, default=ROOT / "build/Selffont-Maru.zip")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = summarise(args.module, args.output)
    faces = report.get("primaryFonts", [])
    print(f"{args.module.name}: {len(faces)} primary faces, "
          f"{report.get('supplementalFontCount', 0)} supplemental fonts")
    for face in faces:
        print(f"  {face.get('style', '?'):8s} {face.get('installedFile', '?'):32s} "
              f"{face.get('normalizedSha256', face.get('sha256', ''))[:16]}…")
    print(f"  base archive: {report.get('baseArchiveSha256', '')[:16]}…")
    print(f"  device installation: {report.get('deviceInstallation', 'NOT_TESTED')}")
    print(f"  webpage rendering:   {report.get('webpageRendering', 'NOT_TESTED')}")
    unbundled = report.get("unbundledFontReferences") or []
    if unbundled:
        print(f"  unbundled configuration references: {len(unbundled)}")


if __name__ == "__main__":
    main()
