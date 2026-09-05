#!/usr/bin/env python3
"""Prepare the exact MFGA supplemental-resource archive. Never execute its code."""
import argparse
import hashlib
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "config/base-source.json").read_text())


def verify_base(path, manifest=None):
    manifest = MANIFEST if manifest is None else manifest
    path = Path(path)
    if path.stat().st_size != manifest["bytes"]:
        raise ValueError("Base archive size differs from the pinned release")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != manifest["sha256"]:
        raise ValueError("Base archive SHA-256 differs from the pinned release")
    with zipfile.ZipFile(path) as archive:
        prop = archive.getinfo("module.prop")
        if prop.file_size > 65536:
            raise ValueError("Unexpected module.prop size")
        fields = dict(line.split("=", 1) for line in archive.read(prop).decode("utf-8-sig").splitlines()
                      if "=" in line and not line.startswith("#"))
        if fields.get("id") != "MFGA" or fields.get("versionCode") != manifest["version"]:
            raise ValueError("Base module identity differs from the pinned release")
        if archive.getinfo("system/fonts/NotoSansPro.otf").file_size == 0:
            raise ValueError("Missing core supplemental font")
    return {"sha256": digest, "bytes": path.stat().st_size, "versionCode": fields["versionCode"]}


def prepare(source, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        staged = Path(temp) / "base.zip"
        if source:
            shutil.copyfile(source, staged)
        else:
            request = urllib.request.Request(MANIFEST["url"], headers={"User-Agent": "Selffont-base-preparer"})
            with urllib.request.urlopen(request, timeout=90) as response, staged.open("wb") as stream:
                remaining = MANIFEST["bytes"] + 1
                while remaining:
                    data = response.read(min(1024 * 1024, remaining))
                    if not data:
                        break
                    stream.write(data)
                    remaining -= len(data)
        report = verify_base(staged)
        staged.replace(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, help="Verify a local copy instead of downloading")
    parser.add_argument("--output", type=Path, default=ROOT / "build/base/MFGA-base.zip")
    args = parser.parse_args()
    print(json.dumps(prepare(args.base, args.output), indent=2))


if __name__ == "__main__":
    main()
