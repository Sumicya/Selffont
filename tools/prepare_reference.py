#!/usr/bin/env python3
"""Fetch and verify the pinned reference font.

No reference binary is kept in Git. This tool takes every entry of
``config/reference-sources.json`` -- the released archive first, then a mirror of
the same file -- verifies the result against the pinned size and SHA-256, and
only then writes it to ``build/reference/``. A file that fails verification is
deleted again: nothing reaches the build directory that does not match the pin.

    python3 tools/prepare_reference.py                       # every declared reference
    python3 tools/prepare_reference.py --reference chillroundm
    python3 tools/prepare_reference.py --file ./ChillRoundM.ttf   # offline, same check
"""
import argparse
import hashlib
import io
import json
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "config/reference-sources.json").read_text())
DEFAULT_OUTPUT = ROOT / "build/reference"
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024


def _fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "selffont-build"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"{url}: larger than {MAX_DOWNLOAD_BYTES} bytes")
    return data


def sources(entry):
    """Every place the pinned file may come from, in order of preference."""
    urls = []
    if entry.get("releaseAsset"):
        urls.append(entry["releaseAsset"])
    urls.extend(entry.get("mirrors", []))
    return urls


def extract(data, filename):
    """The font inside ``data``: either the file itself or a zip holding it."""
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            matches = [name for name in archive.namelist() if Path(name).name == filename]
            if not matches:
                raise ValueError(f"the archive has no {filename}")
            return archive.read(matches[0])
    return data


def verify(data, entry):
    """Return the font bytes, or raise if they are not the pinned ones."""
    font = extract(data, Path(entry["file"]).name)
    if len(font) != entry["bytes"]:
        raise ValueError(f"got {len(font)} bytes, the pin says {entry['bytes']}")
    digest = hashlib.sha256(font).hexdigest()
    if digest != entry["sha256"]:
        raise ValueError(f"got SHA-256 {digest}, the pin says {entry['sha256']}")
    return font


def prepare(output, reference_id=None, local_file=None):
    """Verify every requested reference and write it to ``output``."""
    entries = MANIFEST["references"]
    if reference_id:
        entries = [entry for entry in entries if entry["id"] == reference_id]
        if not entries:
            raise SystemExit(f"{reference_id!r} is not declared in config/reference-sources.json")
    output.mkdir(parents=True, exist_ok=True)
    written = []
    for entry in entries:
        target = output / Path(entry["file"]).name
        if local_file:
            font = verify(Path(local_file).read_bytes(), entry)
        else:
            errors = []
            font = None
            for url in sources(entry):
                try:
                    font = verify(_fetch(url), entry)
                    break
                except (OSError, ValueError, urllib.error.URLError, zipfile.BadZipFile) as error:
                    errors.append(f"{url}: {error}")
            if font is None:
                raise SystemExit(
                    f"could not obtain {entry['file']} for {entry['id']}; "
                    f"pass --file with a local copy. " + "; ".join(errors))
        target.write_bytes(font)
        written.append((entry, target))
        print(f"{entry['id']}: {target} ({len(font)} bytes, SHA-256 verified, {entry['license']})")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default=None, help="Only this reference id")
    parser.add_argument("--file", type=Path, default=None,
                        help="Use this local copy instead of downloading (still verified)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    prepare(args.output, args.reference, args.file)


if __name__ == "__main__":
    main()
