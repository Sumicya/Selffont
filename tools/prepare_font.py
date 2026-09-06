#!/usr/bin/env python3
"""Fetch/verify the pinned, unmodified font. Large inputs and outputs stay outside Git."""
import argparse
import hashlib
import io
import unicodedata
import json
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from fontTools.ttLib import TTFont

from fontTools.pens.boundsPen import BoundsPen
from font_config import METRIC_CARRIER

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "config/font-source.json").read_text())


def layout_metrics(font):
    head, hhea, os2 = font['head'], font['hhea'], font['OS/2']
    return {
        'unitsPerEm': head.unitsPerEm,
        'fontBBoxY': [head.yMin, head.yMax],
        'hhea': [hhea.ascent, hhea.descent, hhea.lineGap],
        'typo': [os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap],
        'win': [os2.usWinAscent, os2.usWinDescent],
        'useTypoMetrics': bool(os2.fsSelection & 0x80),
    }


def digit_bounds(font):
    glyphs, cmap = font.getGlyphSet(), font.getBestCmap() or {}
    result = {}
    for character in '0123456789':
        if ord(character) in cmap:
            pen = BoundsPen(glyphs)
            glyphs[cmap[ord(character)]].draw(pen)
            result[character] = pen.bounds
    return result


def verify_metric_carrier(data):
    """Reject a full Roboto: it would steal visible glyphs from WenYuan."""
    with TTFont(io.BytesIO(data)) as font:
        cmap = font.getBestCmap() or {}
        visible = [cp for cp, glyph in cmap.items()
                   if glyph != '.notdef' and
                   unicodedata.category(chr(cp)) not in {'Cc', 'Cf', 'Zs', 'Zl', 'Zp'}]
        if visible:
            raise ValueError('Roboto metrics carrier has visible character coverage')
        metrics = layout_metrics(font)
        if metrics['unitsPerEm'] <= 0 or metrics['hhea'][0] <= 0:
            raise ValueError('Roboto metrics carrier has invalid layout metrics')
        return {
            'file': METRIC_CARRIER,
            'sha256': hashlib.sha256(data).hexdigest(),
            'family': font['name'].getDebugName(1),
            'visibleCodepoints': 0,
            'nonInkCodepoints': sorted(cmap),
            'layoutMetrics': metrics,
        }


def verify_font(path, manifest=None):
    manifest = MANIFEST if manifest is None else manifest
    path = Path(path)
    if path.stat().st_size != manifest["bytes"]:
        raise ValueError("Font size differs from the pinned source")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != manifest["sha256"]:
        raise ValueError("Font SHA-256 differs from the pinned source")
    with TTFont(path) as font:
        if font["name"].getDebugName(1) != manifest["family"]:
            raise ValueError("Gecko family name does not match the font")
        axes = {a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in font["fvar"].axes}
        if axes.get("wght") != (100, 400, 900) or axes.get("ital") != (0, 0, 1):
            raise ValueError("Expected wght=100..900 and ital=0..1")
        cmap = font.getBestCmap()
        missing = [c for c in "你好中国圆体Abc0123456789" if ord(c) not in cmap]
        if missing:
            raise ValueError(f"Missing baseline characters: {missing}")
        return {"sha256": digest, "family": manifest["family"], "axes": axes,
                "mappedCodepoints": len(cmap), "layoutMetrics": layout_metrics(font),
                "digitBounds": digit_bounds(font), "deviceRendering": "NOT_TESTED"}


def download(destination):
    errors = []
    for url in (MANIFEST["url"], MANIFEST["apiUrl"]):
        try:
            request = urllib.request.Request(url, headers={
                "Accept": "application/vnd.github.raw+json", "User-Agent": "Selffont-font-preparer"})
            with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as out:
                # Bounded even if a server ignores the requested resource or lies about its size.
                remaining = MANIFEST["bytes"] + 1
                while remaining:
                    data = response.read(min(1024 * 1024, remaining))
                    if not data:
                        break
                    out.write(data)
                    remaining -= len(data)
            verify_font(destination)
            return
        except (OSError, ValueError, urllib.error.URLError) as error:
            errors.append(str(error))
    raise RuntimeError("Download failed; supply --font from the pinned release. " + "; ".join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, help="Verify a local copy instead of downloading")
    parser.add_argument("--output", type=Path, default=ROOT / "build/font")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output) as temp:
        staged = Path(temp) / MANIFEST["file"]
        if args.font:
            shutil.copyfile(args.font, staged)
        else:
            download(staged)
        report = verify_font(staged)
        staged.replace(args.output / MANIFEST["file"])
    shutil.copyfile(ROOT / "licenses/WenYuan-OFL.txt", args.output / "OFL.txt")
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
