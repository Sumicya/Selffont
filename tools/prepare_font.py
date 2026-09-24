#!/usr/bin/env python3
"""Fetch, verify and rename the pinned OFL source faces.

No font binary is kept in Git. Each face is verified against the pinned size and
SHA-256 in ``config/font-source.json``, then given the project family name. That
rename is the only derivative step here: outlines, cmap, hinting and layout
tables are byte-identical (asserted before the result is accepted).

    python3 tools/prepare_font.py                     # download from the pinned revision
    python3 tools/prepare_font.py --font-dir ./faces  # offline, same verification
"""
import argparse
import base64
import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "config/font-source.json").read_text())
FACES = tuple(MANIFEST["faces"])
BASELINE_CHARACTERS = MANIFEST["baselineCharacters"]
MAX_DOWNLOAD_BYTES = 16 * 1024 * 1024


def layout_metrics(font):
    head, hhea, os2 = font["head"], font["hhea"], font["OS/2"]
    return {
        "unitsPerEm": head.unitsPerEm,
        "fontBBoxY": [head.yMin, head.yMax],
        "hhea": [hhea.ascent, hhea.descent, hhea.lineGap],
        "typo": [os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap],
        "win": [os2.usWinAscent, os2.usWinDescent],
        "useTypoMetrics": bool(os2.fsSelection & 0x80),
    }


def digit_bounds(font):
    glyphs, cmap = font.getGlyphSet(), font.getBestCmap() or {}
    result = {}
    for character in "0123456789":
        if ord(character) in cmap:
            pen = BoundsPen(glyphs)
            glyphs[cmap[ord(character)]].draw(pen)
            result[character] = pen.bounds
    return result


def verify_metric_carrier(data):
    """Reject a full Roboto: it would steal visible glyphs from the primary faces."""
    with TTFont(io.BytesIO(data)) as font:
        cmap = font.getBestCmap() or {}
        visible = [
            cp for cp, glyph in cmap.items()
            if glyph != ".notdef"
            and unicodedata.category(chr(cp)) not in {"Cc", "Cf", "Zs", "Zl", "Zp"}
        ]
        if visible:
            raise ValueError("Roboto metrics carrier has visible character coverage")
        metrics = layout_metrics(font)
        if metrics["unitsPerEm"] <= 0 or metrics["hhea"][0] <= 0:
            raise ValueError("Roboto metrics carrier has invalid layout metrics")
        return {
            "file": "Roboto-Regular.ttf",
            "sha256": hashlib.sha256(data).hexdigest(),
            "family": font["name"].getDebugName(1),
            "visibleCodepoints": 0,
            "nonInkCodepoints": sorted(cmap),
            "layoutMetrics": metrics,
        }


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _assert_digest(data, spec):
    if len(data) != spec["bytes"]:
        raise ValueError(
            f"{spec['file']} size differs from the pinned source: "
            f"expected {spec['bytes']}, got {len(data)}"
        )
    if _sha256(data) != spec["sha256"]:
        raise ValueError(f"{spec['file']} SHA-256 differs from the pinned source")


def _name_values(font, ids):
    values = set()
    for record in font["name"].names:
        if record.nameID in ids:
            with contextlib.suppress(UnicodeError):
                values.add(record.toUnicode())
    return values


def _read_font(data):
    return TTFont(io.BytesIO(data), recalcBBoxes=False, recalcTimestamp=False)


def _shape_signature(font):
    """Outlines, glyph order and cmap -- everything the rename must not touch."""
    glyf = font["glyf"]
    return (
        font.getGlyphOrder(),
        {name: glyf[name].compile(glyf) for name in font.getGlyphOrder()},
        font.getBestCmap(),
    )


def _font_report(font, spec, *, sha256, source_sha256, derived=False):
    if "fvar" in font:
        raise ValueError(f"{spec['file']} is variable; static source faces are required")
    cmap = font.getBestCmap() or {}
    missing = [character for character in BASELINE_CHARACTERS if ord(character) not in cmap]
    if missing:
        raise ValueError(f"{spec['file']} is missing baseline characters: {missing}")
    if font["OS/2"].usWeightClass != spec["weight"]:
        raise ValueError(
            f"{spec['file']} declares weight {font['OS/2'].usWeightClass}, "
            f"expected {spec['weight']}"
        )
    return {
        "sourceFile": spec["file"],
        "installedFile": spec["installedFile"],
        "weight": spec["weight"],
        "style": spec["style"],
        "sourceSha256": source_sha256,
        "sha256": sha256,
        "family": font["name"].getDebugName(1),
        "mappedCodepoints": len(cmap),
        "layoutMetrics": layout_metrics(font),
        "digitBounds": digit_bounds(font),
        "derived": derived,
    }


def verify_source_bytes(data, spec, manifest=None):
    """Verify one upstream face before any derivative transformation."""
    manifest = MANIFEST if manifest is None else manifest
    _assert_digest(data, spec)
    with _read_font(data) as font:
        names = _name_values(font, {1, 16})
        if not any(manifest["sourceFamily"] in value for value in names):
            raise ValueError(
                f"{spec['file']} family {sorted(names)!r} is not from "
                f"{manifest['sourceFamily']!r}"
            )
        report = _font_report(font, spec, sha256=_sha256(data), source_sha256=_sha256(data))
        report["sourceFamilyNames"] = sorted(names)
        return report


def _set_name_table(font, family, style):
    """Give the OFL derivative its own family name and stable subfamily names."""
    name = font["name"]
    replaced = {1, 2, 4, 6, 16, 17}
    name.names = [record for record in name.names if record.nameID not in replaced]
    values = {
        1: family,
        2: style,
        4: f"{family} {style}",
        6: f"{family.replace(' ', '')}-{style}",
        16: family,
        17: style,
    }
    for name_id, value in values.items():
        name.setName(value, name_id, 3, 1, 0x409)
        name.setName(value, name_id, 1, 0, 0)


def derive_face(data, spec, manifest=None):
    """Rename one verified source face without touching its outlines or cmap."""
    manifest = MANIFEST if manifest is None else manifest
    verify_source_bytes(data, spec, manifest)
    with _read_font(data) as font:
        original_shape = _shape_signature(font)
        _set_name_table(font, manifest["family"], spec["style"])
        out = io.BytesIO()
        font.save(out)
    derived = out.getvalue()
    with _read_font(derived) as font:
        if _shape_signature(font) != original_shape:
            raise ValueError(f"{spec['file']} outlines or cmap changed during rename")
        if font["name"].getDebugName(1) != manifest["family"]:
            raise ValueError(f"Failed to rename {spec['file']} to {manifest['family']}")
        report = _font_report(
            font, spec, sha256=_sha256(derived), source_sha256=_sha256(data), derived=True
        )
        report["sourceFamily"] = manifest["sourceFamily"]
        return derived, report


def verify_prepared_face(path, spec, manifest=None):
    """Verify one prepared (renamed, optionally patched) face before packaging."""
    manifest = MANIFEST if manifest is None else manifest
    data = Path(path).read_bytes()
    with _read_font(data) as font:
        if font["name"].getDebugName(1) != manifest["family"]:
            raise ValueError(f"{path} does not use the prepared family name")
        report = _font_report(
            font, spec, sha256=_sha256(data), source_sha256=spec["sha256"], derived=True
        )
        report["sourceFamily"] = manifest["sourceFamily"]
        return report


def _revision():
    return MANIFEST["version"].split("@", 1)[-1]


def _fetch(url, *, accept=None):
    headers = {"User-Agent": "Selffont-font-preparer"}
    if accept:
        headers["Accept"] = accept
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise ValueError("font download exceeds the inspection limit")
        content_type = response.headers.get("Content-Type", "")
    if "json" in content_type or data[:1] in (b"{", b"["):
        payload = json.loads(data)
        if not isinstance(payload, dict) or payload.get("encoding") != "base64":
            raise ValueError("GitHub font response is not a base64 blob")
        return base64.b64decode("".join(payload["content"].split()))
    return data


def download(spec):
    """Fetch one face from the pinned revision, raw first then the API fallback."""
    revision = _revision()
    sources = (
        (f"https://github.com/{MANIFEST['project']}/raw/{revision}/fonts/ttf/{spec['file']}", None),
        (
            f"https://api.github.com/repos/{MANIFEST['project']}/contents/"
            f"fonts/ttf/{spec['file']}?ref={revision}",
            "application/vnd.github.object+json",
        ),
    )
    errors = []
    for url, accept in sources:
        try:
            data = _fetch(url, accept=accept)
            _assert_digest(data, spec)
            return data
        except (OSError, ValueError, urllib.error.URLError) as error:
            errors.append(f"{url}: {error}")
    raise RuntimeError(
        f"Download failed for {spec['file']}; provide a local --font-dir. " + "; ".join(errors)
    )


def prepare(output, font_dir=None):
    """Produce build-ready faces plus their report, atomically."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    local = Path(font_dir) if font_dir else None
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        staged = Path(temp) / "fonts"
        staged.mkdir()
        reports = []
        for spec in FACES:
            source = local / spec["file"] if local else None
            data = source.read_bytes() if source else download(spec)
            source_report = verify_source_bytes(data, spec)
            derived, report = derive_face(data, spec)
            report["sourceLayoutMetrics"] = source_report["layoutMetrics"]
            (staged / spec["installedFile"]).write_bytes(derived)
            reports.append(report)
        shutil.copyfile(ROOT / "licenses" / MANIFEST["licenseFile"], staged / "OFL.txt")
        (staged / "report.json").write_text(
            json.dumps(
                {
                    "project": MANIFEST["project"],
                    "version": MANIFEST["version"],
                    "sourceFamily": MANIFEST["sourceFamily"],
                    "family": MANIFEST["family"],
                    "license": MANIFEST["license"],
                    "faces": reports,
                    "deviceRendering": "NOT_TESTED",
                },
                indent=2,
            )
            + "\n"
        )
        if output.exists():
            if output.is_dir() and not output.is_symlink():
                shutil.rmtree(output)
            else:
                output.unlink()
        staged.replace(output)
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-dir", type=Path, help="Local source faces instead of downloading")
    parser.add_argument("--output", type=Path, default=ROOT / "build/fonts")
    args = parser.parse_args()
    reports = prepare(args.output, args.font_dir)
    print(json.dumps({face["installedFile"]: face["sha256"] for face in reports}, indent=2))


if __name__ == "__main__":
    main()
