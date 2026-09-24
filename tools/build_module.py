#!/usr/bin/env python3
"""Assemble the KernelSU module.

Inputs are explicit: the prepared (and optionally patched) faces from
``tools/prepare_font.py`` / ``tools/edit_font.py`` and a complete MFGA base ZIP
that supplies supplemental fonts. Only font resources are read from the base --
its scripts, native binaries, Zygisk, updater and numeric primary faces are never
inherited. Nothing here touches a device.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

from font_config import METRIC_CARRIER, configure_fonts, weight_mapping
from metric_normalize import assert_glyphs_preserved, normalize_metrics
from prepare_font import MANIFEST, ROOT, verify_metric_carrier, verify_prepared_face

MODULE = json.loads((ROOT / "config/module.json").read_text())
# module.prop key order is fixed so the rendered output is deterministic.
MODULE_PROP_KEYS = ("id", "name", "version", "versionCode", "author", "description")
RUNTIME_FILES = (
    "customize.sh", "action.sh", "service.sh", "uninstall.sh", "search_dirs.sh",
    "diagnose.sh", "gms_fallback.sh", "app_fonts.sh", "collect_logs.sh", "filter_logs.awk",
)
MAX_FONT_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
FACES = tuple(MANIFEST["faces"])


def render_font_conf(faces=None, manifest=None):
    """Render the on-device font identity file (single source of truth for shell).

    The globals are resolved at call time so tests (and any future multi-face
    manifest) can substitute them without re-importing the module.
    """
    faces = FACES if faces is None else faces
    manifest = MANIFEST if manifest is None else manifest
    return "".join(
        f"SELFFONT_INSTALLED_{face['style'].upper()}={face['installedFile']}\n" for face in faces
    ) + f"SELFFONT_VISIBILITY_FILE={manifest['visibilityFile']}\n"


def render_module_prop(fields=MODULE):
    """Render module.prop from config/module.json (single source of truth)."""
    missing = [key for key in MODULE_PROP_KEYS if not fields.get(key)]
    if missing:
        raise ValueError(f"config/module.json is missing required keys: {missing}")
    for key in MODULE_PROP_KEYS:
        if "\n" in str(fields[key]):
            raise ValueError(f"module.prop field {key!r} must be single-line")
    return "".join(f"{key}={fields[key]}\n" for key in MODULE_PROP_KEYS)


def font_members(archive):
    """Yield the representable font members of a base ZIP, rejecting unsafe ones."""
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


def _prepared_faces(font_dir):
    font_dir = Path(font_dir)
    if not font_dir.is_dir():
        raise ValueError(f"Prepared font directory does not exist: {font_dir}")
    result = []
    for spec in FACES:
        path = font_dir / spec["installedFile"]
        report = verify_prepared_face(path, spec)
        data = path.read_bytes()
        if len(data) > MAX_FONT_BYTES:
            raise ValueError(f"Prepared font exceeds packaging limit: {path.name}")
        result.append((spec, path, data, report))
    return result


def build(base, font_dir, output, revision=None):
    output = Path(output)
    prepared = _prepared_faces(font_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    xml = configure_fonts((ROOT / "fonts.xml").read_bytes(), FACES)
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

            normalized = {}
            metric_reports = {}
            face_reports = []
            total_primary_bytes = 0
            for spec, path, original, report in prepared:
                if hashlib.sha256(original).hexdigest() != report["sha256"]:
                    raise ValueError(f"Prepared font changed after verification: {path.name}")
                normalized_font, metric_report = normalize_metrics(original, carrier["layoutMetrics"])
                normalized_sha = hashlib.sha256(normalized_font).hexdigest()
                metric_report["originalSha256"] = report["sha256"]
                metric_report["normalizedSha256"] = normalized_sha
                normalized[spec["installedFile"]] = normalized_font
                metric_reports[str(spec["weight"])] = metric_report
                face_report = dict(report)
                face_report["normalizedSha256"] = normalized_sha
                face_reports.append(face_report)
                total_primary_bytes += len(normalized_font)
            if total_primary_bytes > MAX_TOTAL_BYTES:
                raise ValueError("Primary font resources exceed packaging limits")

            referenced = {(node.text or "").strip() for node in ET.fromstring(xml).iter("font")}
            # fonts.xml is the whole font policy and this module overlays /system/fonts,
            # so a bundled face nobody references can never be loaded: pure dead weight.
            # The code-required faces (NotoSansPro.otf, the metrics carrier, our own)
            # are all referenced, so this never removes a build dependency.
            bundled = [
                entry for entry in entries
                if PurePosixPath(entry.filename).name in referenced
                and PurePosixPath(entry.filename).name not in normalized
            ]
            dropped = sorted(
                {PurePosixPath(entry.filename).name for entry in entries}
                - {PurePosixPath(entry.filename).name for entry in bundled}
            )
            module_report = {
                "sourceRevision": revision or "UNSPECIFIED",
                "sourceFont": {
                    "project": MANIFEST["project"],
                    "version": MANIFEST["version"],
                    "sourceFamily": MANIFEST["sourceFamily"],
                    "family": MANIFEST["family"],
                    "license": MANIFEST["license"],
                },
                "primaryFonts": face_reports,
                "staticWeightMapping": {
                    str(weight): filename for weight, filename in weight_mapping(FACES).items()
                },
                "metricNormalization": metric_reports,
                "androidMetricsCarrier": carrier,
                "baseArchiveSha256": base_digest,
                "supplementalFontCount": len(bundled),
                "unreferencedFontsDropped": dropped,
                "unbundledFontReferences": sorted(referenced - names - set(normalized)),
                "deviceInstallation": "NOT_TESTED",
                "webpageRendering": "NOT_TESTED",
            }
            for entry in bundled:
                dest.writestr(entry.filename, source.read(entry))
            for filename, data in normalized.items():
                dest.writestr("system/fonts/" + filename, data)
            dest.writestr("fonts.xml", xml)
            dest.writestr("module.prop", render_module_prop())
            # On-device single source of truth for the installed font identity.
            # customize.sh / diagnose.sh / device_state.sh source this instead of
            # hardcoding filenames, so a font swap never touches shell code.
            dest.writestr("font.conf", render_font_conf())
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
            # Generated web-side identity: diagnostics.html reads the family name from
            # here for its local() probe, so a font swap updates the page without
            # editing HTML. A static offline fallback stays in the HTML.
            dest.writestr("webroot/font.json", json.dumps(
                {"family": MANIFEST["family"], "visibilityFile": MANIFEST["visibilityFile"]},
                indent=2,
            ) + "\n")
            # Preserve base attribution, not executable content or auto-update metadata.
            if "LICENSES.md" in source.namelist():
                info = source.getinfo("LICENSES.md")
                if info.file_size > 1024 * 1024:
                    raise ValueError("Unexpected base attribution size")
                dest.writestr("licenses/MFGA-base-LICENSES.md", source.read(info))
            font_report = {
                "sourceFont": module_report["sourceFont"],
                "faces": face_reports,
                "deviceRendering": "NOT_TESTED",
            }
            dest.writestr("font-report.json", json.dumps(font_report, indent=2) + "\n")
            dest.writestr("module-report.json", json.dumps(module_report, indent=2) + "\n")
            if os.environ.get("GITHUB_ACTIONS") == "true":
                metrics = carrier["layoutMetrics"]
                print(
                    "::notice title=Android font metrics::Verified no-visible-glyph carrier; "
                    f"UPM={metrics['unitsPerEm']}; hhea={metrics['hhea']}; "
                    f"SHA256={carrier['sha256']}"
                )
                print(
                    "::notice title=Selffont Maru metric normalization::"
                    f"faces={len(prepared)}; weights="
                    + ",".join(str(face[0]["weight"]) for face in prepared)
                )
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
            for spec, _, original, _ in prepared:
                filename = spec["installedFile"]
                with final.open("system/fonts/" + filename) as stream:
                    packaged = stream.read()
                if hashlib.sha256(packaged).hexdigest() != hashlib.sha256(normalized[filename]).hexdigest():
                    raise ValueError(f"Packaged primary font SHA-256 differs: {filename}")
                # Only line metrics may differ from the prepared face: outlines, cmap,
                # family name and static weight stay as shipped by the editor.
                assert_glyphs_preserved(original, packaged)
        staged.replace(output)
    print(f"Built {output}; device installation/rendering NOT TESTED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path, help="Complete MFGA ZIP (supplemental font source)")
    parser.add_argument("--font-dir", type=Path, default=ROOT / "build/fonts-patched",
                        help="Prepared (and optionally patched) face directory")
    parser.add_argument("--output", type=Path, default=ROOT / "build/Selffont-Maru.zip")
    parser.add_argument("--revision", help="Source commit recorded in the artifact report")
    args = parser.parse_args()
    build(args.base, args.font_dir, args.output, args.revision)


if __name__ == "__main__":
    main()
