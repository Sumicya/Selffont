#!/usr/bin/env python3
"""Build the host-side A/B preview for glyph edits.

Subsets the original and edited fonts to GB2312 + ASCII (keeps the VF
axes + gvar of untouched glyphs), converts to woff2 when brotli is
available, and copies the preview page into build/preview/.

Usage: .venv/bin/python tools/make_preview.py
"""

from __future__ import annotations

import json
import string
import sys
import time
from pathlib import Path

from fontTools.subset import Subsetter, Options

from font_config import SOURCE_FONT_PATH

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "build" / "preview"

ORIG = SOURCE_FONT_PATH
EDITED = REPO / "build" / "font-edited.ttf"
PAGE = REPO / "tools" / "font-preview.html"


def charset() -> str:
    chars = list(string.printable)
    for b1 in range(0xB0, 0xD8):
        for b2 in range(0xA1, 0xFF):
            try:
                chars.append(bytes([b1, b2]).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    # CJK radicals (丨 丶 丿 乙 ...): the demo characters live here and
    # GB2312 does not cover them
    for cp in range(0x2F00, 0x2FDF + 1):
        chars.append(chr(cp))
    # radical characters that are regular CJK codepoints outside the block
    for cp in (0x5B80, 0x5196, 0x4E01, 0x4E59):  # 宀 冖 亠 乙
        chars.append(chr(cp))
    return "".join(dict.fromkeys(chars))


def build_subset(font_path: Path, out_stem: str) -> list[str]:
    from fontTools.ttLib import TTFont

    out: list[str] = []
    font = TTFont(font_path)
    options = Options()
    options.layout_features = []
    options.name_IDs = ["*"]
    options.notdef_outline = True
    options.symbol_cmap = False
    options.glyph_names = False
    options.legacy_kern = False
    options.retain_gids = False
    sub = Subsetter(options)
    sub.populate(text=charset())
    sub.subset(font)

    ttf = OUT / f"{out_stem}.ttf"
    font.save(ttf)
    out.append(str(ttf))
    try:
        font.flavor = "woff2"
        w2 = OUT / f"{out_stem}.woff2"
        font.save(w2)
        out.append(str(w2))
    except Exception as e:  # brotli missing etc.
        print(f"    (no woff2: {e})", file=sys.stderr)
    return out


def main() -> int:
    if not ORIG.exists():
        print(f"missing {ORIG}; run tools/prepare_font.py first", file=sys.stderr)
        return 1
    if not EDITED.exists():
        print(f"missing {EDITED}; run tools/edit_font.py first", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_bytes(PAGE.read_bytes())
    # Cache-bust the font URLs: mobile browsers cache font files hard, and a
    # URL that never changes keeps serving a stale (possibly broken) subset.
    ver = int(time.time())
    html = (OUT / "index.html").read_text()
    for name in ("font-orig-subset", "font-edit-subset"):
        for ext in (".woff2", ".ttf"):
            html = html.replace(f"url('{name}{ext}')",
                                f"url('{name}{ext}?v={ver}')")
    (OUT / "index.html").write_text(html)
    report_path = REPO / "build" / "edit-report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text())
        chars = set()
        for op in ("roof-dot-to-stem", "round-terminals"):
            block = report.get(op, {})
            chars.update(block.get("changed", {}))
        (OUT / "changed.json").write_text(
            json.dumps({"chars": sorted(chars)}, ensure_ascii=False))
        print(f"changed.json: {len(chars)} chars")
    print("orig:  ", *build_subset(ORIG, "font-orig-subset"))
    print("edited:", *build_subset(EDITED, "font-edit-subset"))
    print(f"preview: {OUT / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
