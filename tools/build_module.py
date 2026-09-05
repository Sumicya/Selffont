#!/usr/bin/env python3
"""Assemble a KSU-only module using an explicit MFGA base ZIP for supplemental fonts.

Only font resources are read from the base. Its scripts, binaries, zygisk, updater,
font edits and boot hooks are never inherited. No system/device writes occur here.
"""
import argparse
import json
import re
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from font_config import configure_fonts
from prepare_font import MANIFEST, ROOT, verify_font

RUNTIME_SCRIPTS = ("customize.sh", "action.sh", "service.sh", "uninstall.sh", "search_dirs.sh",
                   "diagnose.sh", "gms_fallback.sh", "app_fonts.sh")
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


def build(base, font, output):
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
            if not entries:
                raise ValueError("No supplemental fonts found in the base ZIP")
            for entry in entries:
                if PurePosixPath(entry.filename).name != MANIFEST["installedFile"]:
                    dest.writestr(entry.filename, source.read(entry))
            dest.write(font, "system/fonts/" + MANIFEST["installedFile"])
            dest.writestr("fonts.xml", xml)
            dest.writestr("module.prop", "id=MFGA\nname=Selffont · WenYuan\nversion=1.4-phase1\n"
                          "versionCode=1717180004\nauthor=Selffont contributors\n"
                          "description=Android 16 / Oplus / KSU. Gecko adapter requires device validation.\n")
            for name in RUNTIME_SCRIPTS:
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
            # Do not inherit a private download umask (0600) for system font files.
            # Central-directory attributes are authoritative for Unix ZIP extraction.
            for info in dest.infolist():
                info.create_system = 3
                mode = 0o755 if info.filename.endswith(".sh") else 0o644
                info.external_attr = (stat.S_IFREG | mode) << 16
        staged.replace(output)
    print(f"Built {output}; device installation/rendering NOT TESTED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path, help="Complete MFGA ZIP (supplemental font source)")
    parser.add_argument("--font", type=Path, default=ROOT / "build/font" / MANIFEST["file"])
    parser.add_argument("--output", type=Path, default=ROOT / "build/Selffont-phase1.zip")
    args = parser.parse_args()
    build(args.base, args.font, args.output)


if __name__ == "__main__":
    main()
