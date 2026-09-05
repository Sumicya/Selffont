#!/usr/bin/env python3
"""Assemble a KSU-only module using an explicit MFGA base ZIP for supplemental fonts.

Only font resources are read from the base. Its scripts, binaries, zygisk, updater,
font edits and boot hooks are never inherited. No system/device writes occur here.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET

from font_config import configure_fonts, METRIC_CARRIER
from prepare_font import MANIFEST, ROOT, verify_font, verify_metric_carrier

RUNTIME_FILES = ("customize.sh", "action.sh", "service.sh", "uninstall.sh", "search_dirs.sh",
                   "diagnose.sh", "gms_fallback.sh", "app_fonts.sh", "collect_logs.sh", "filter_logs.awk")
MAX_FONT_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024


def font_members(archive):
    total = 0
    names = set()
    for entry in archive.infolist():
        path = PurePosixPath(entry.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in entry.filename:
            raise ValueError("Unsafe base ZIP member")
        if not entry.is_dir() and entry.filename != path.as_posix():
            raise ValueError("Noncanonical base ZIP member")
        if entry.filename in names:
            raise ValueError("Duplicate base ZIP member")
        names.add(entry.filename)
        if path.parent != PurePosixPath("system/fonts") or path.suffix.lower() not in (".ttf", ".otf", ".ttc"):
            continue
        if re.fullmatch(r"[1-9]00\.ttf", path.name) or path.name == "NotoColorEmoji-fallback.ttf":
            continue
        if stat.S_ISLNK(entry.external_attr >> 16):
            raise ValueError("Font symlinks in base ZIP are not supported")
        total += entry.file_size
        if entry.file_size > MAX_FONT_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("Base font resources exceed packaging limits")
        yield entry


def build(base, font, output, revision=None):
    report = verify_font(font)
    output = Path(output)
    if output.resolve() in (Path(base).resolve(), Path(font).resolve()):
        raise ValueError("Output must not overwrite an input")
    output.parent.mkdir(parents=True, exist_ok=True)
    xml = configure_fonts((ROOT / "fonts.xml").read_bytes(), MANIFEST["installedFile"])
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        staged = Path(tmp) / "module.zip"
        with zipfile.ZipFile(base) as source, zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as dest:
            entries = list(font_members(source))
            names = {PurePosixPath(entry.filename).name for entry in entries}
            if "NotoSansPro.otf" not in names:
                raise ValueError("Missing NotoSansPro.otf supplemental font")
            if METRIC_CARRIER not in names:
                raise ValueError("Missing inherited Roboto metrics carrier")
            carrier = verify_metric_carrier(source.read("system/fonts/" + METRIC_CARRIER))
            with Path(base).open("rb") as stream:
                base_digest = hashlib.file_digest(stream, "sha256").hexdigest()
            referenced = {(node.text or "").strip() for node in ET.fromstring(xml).iter("font")}
            module_report = {
                "sourceRevision": revision or "UNSPECIFIED",
                "primaryFont": report,
                "androidMetricsCarrier": carrier,
                "baseArchiveSha256": base_digest,
                "supplementalFontCount": len(entries),
                "unbundledFontReferences": sorted(referenced - names - {MANIFEST["installedFile"]}),
                "deviceInstallation": "NOT_TESTED",
                "webpageRendering": "NOT_TESTED",
            }
            for entry in entries:
                if PurePosixPath(entry.filename).name != MANIFEST["installedFile"]:
                    dest.writestr(entry.filename, source.read(entry))
            dest.write(font, "system/fonts/" + MANIFEST["installedFile"])
            dest.writestr("fonts.xml", xml)
            dest.writestr("module.prop", "id=MFGA\nname=Selffont · WenYuan\nversion=1.4-phase1.1\n"
                          "versionCode=1717180005\nauthor=Selffont contributors\n"
                          "description=Android 16 / Oplus / KSU. Gecko adapter requires device validation.\n")
            for name in RUNTIME_FILES:
                dest.write(ROOT / "script" / name, name)
            for directory in ("lang", "webroot", "licenses"):
                for path in sorted((ROOT / directory).rglob("*")):
                    if path.is_file():
                        dest.write(path, path.relative_to(ROOT).as_posix())
            for name in ("fonts_list.yaml", "LICENSES.md"):
                dest.write(ROOT / name, name)
            for path in (ROOT / "fonts").glob("LICENSE-*"):
                dest.write(path, "licenses/" + path.name)
            # Preserve base attribution, not executable content or auto-update metadata.
            if "LICENSES.md" in source.namelist():
                info = source.getinfo("LICENSES.md")
                if info.file_size > 1024 * 1024:
                    raise ValueError("Unexpected base attribution size")
                dest.writestr("licenses/MFGA-base-LICENSES.md", source.read(info))
            dest.writestr("font-report.json", json.dumps(report, indent=2) + "\n")
            dest.writestr("module-report.json", json.dumps(module_report, indent=2) + "\n")
            if os.environ.get("GITHUB_ACTIONS") == "true":
                metrics = carrier["layoutMetrics"]
                # Public resource diagnostics, readable through the checks API too.
                print("::notice title=Android font metrics::Verified no-visible-glyph carrier; "
                      f"UPM={metrics['unitsPerEm']}; hhea={metrics['hhea']}; "
                      f"SHA256={carrier['sha256']}")
            # Do not inherit a private download umask (0600) for system font files.
            # Central-directory attributes are authoritative for Unix ZIP extraction.
            for info in dest.infolist():
                info.create_system = 3
                mode = 0o755 if info.filename.endswith(".sh") else 0o644
                info.external_attr = (stat.S_IFREG | mode) << 16
        with zipfile.ZipFile(staged) as final:
            corrupt = final.testzip()
            if corrupt:
                raise ValueError(f"Corrupt output archive member: {corrupt}")
            with final.open("system/fonts/" + MANIFEST["installedFile"]) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != report["sha256"]:
                    raise ValueError("Packaged primary font SHA-256 differs from verified input")
        staged.replace(output)
    print(f"Built {output}; device installation/rendering NOT TESTED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path, help="Complete MFGA ZIP (supplemental font source)")
    parser.add_argument("--font", type=Path, default=ROOT / "build/font" / MANIFEST["file"])
    parser.add_argument("--output", type=Path, default=ROOT / "build/Selffont-phase1.zip")
    parser.add_argument("--revision", help="Source commit recorded in the artifact report")
    args = parser.parse_args()
    build(args.base, args.font, args.output, args.revision)


if __name__ == "__main__":
    main()
