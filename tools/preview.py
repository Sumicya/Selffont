#!/usr/bin/env python3
"""Render and review the target characters in the real prepared faces.

Two jobs, both small:

``--render``  rasterise a PNG sheet per face using FreeType (the same outline
              rasteriser Android uses), so a review never depends on the
              reviewer's desktop font stack;
``--serve``   serve an HTML review page plus the actual TTF files, so the browser
              renders the real faces and the author can look at a phone-sized
              page without installing anything. When a patch report exists the
              page also shows each changed character before/after, using the
              unpatched faces from ``--baseline-dir``.

The page shows three things: the target characters in each face, the audit split
between "a point patch can rework this" and "this character does not exist in the
face yet", and the stroke conventions the sheets practise.
"""
import argparse
import contextlib
import html
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import find_spec
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from glyph_audit import MANIFEST, TARGETS, audit

FACES = {face["style"]: face for face in MANIFEST["faces"]}
SAMPLE = "你好中国圆体 0123456789 Abc"


def _load_faces(directory: Path):
    directory = Path(directory)
    result = {}
    for style, face in FACES.items():
        path = directory / face["installedFile"]
        if path.is_file():
            result[style] = path
    if not result:
        raise SystemExit(f"no prepared faces in {directory} (run tools/prepare_font.py)")
    return result


def render_sheet(face_path: Path, characters: str, output: Path, size: int = 96) -> None:
    """Rasterise one row of characters through FreeType into a PNG."""
    if find_spec("freetype") is None or find_spec("PIL") is None:
        raise SystemExit("--render needs freetype-py and Pillow (tools/requirements-dev.txt)")
    import freetype
    from PIL import Image, ImageDraw

    face = freetype.Face(str(face_path))
    face.set_char_size(size * 64)
    margin, baseline, line = 14, int(size * 0.86), int(size * 1.35)
    advance_total = 0
    widths = []
    for char in characters:
        face.load_char(char, freetype.FT_LOAD_RENDER)
        widths.append(face.glyph.advance.x >> 6)
        advance_total += widths[-1]
    image = Image.new("L", (advance_total + margin * 2, line * 2 + margin), 255)
    draw = ImageDraw.Draw(image)
    x = margin
    for char, width in zip(characters, widths, strict=True):
        face.load_char(char, freetype.FT_LOAD_RENDER)
        bitmap = face.glyph.bitmap
        if bitmap.rows and bitmap.width:
            glyph = Image.frombytes("L", (bitmap.width, bitmap.rows), bytes(bitmap.buffer))
            image.paste(0, (x + face.glyph.bitmap_left, baseline - face.glyph.bitmap_top), glyph)
        x += width
    draw.line((0, baseline + 2, image.width, baseline + 2), fill=200)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def _face_css(name: str, url: str, weight: int) -> str:
    return f'@font-face{{font-family:"{name}";src:url("{url}");font-weight:{weight};}}'


def _patched_styles(faces: dict, patch_report: list | None) -> dict[str, str]:
    """{style: comma separated characters actually changed} from the patch report."""
    changed: dict[str, str] = {}
    for entry in patch_report or []:
        glyphs = entry.get("changedGlyphs") or {}
        if glyphs:
            changed[entry["face"]] = "".join(glyphs)
    return {style: chars for style, chars in changed.items() if style in faces}


def _page(report: dict, faces: dict, size: int, baseline_faces: dict | None = None,
          patch_report: list | None = None) -> str:
    editable = "".join(row["char"] for row in report["characters"] if row["status"] == "editable")
    missing = "".join(row["char"] for row in report["characters"] if row["status"] == "needs-new-glyph")
    styles, rows = [], []
    for face, path in faces.items():
        weight = FACES[face]["weight"]
        styles.append(_face_css(face, f"/fonts/{path.name}", weight))
        rows.append(
            f'<p class="face"><b>{face}</b> weight {weight}</p>'
            f'<p class="sample" style="font-family:{face};font-weight:{weight}">{html.escape(SAMPLE)}</p>'
            f'<p class="targets" style="font-family:{face};font-weight:{weight}">{html.escape(editable)}</p>'
        )
    patched = _patched_styles(faces, patch_report)
    comparison = []
    for style, chars in patched.items():
        before = baseline_faces.get(style) if baseline_faces else None
        if before is None:
            continue
        styles.append(_face_css(f"before-{style}", f"/baseline/{before.name}", FACES[style]["weight"]))
        comparison.append(
            f'<p class="face"><b>{style}</b> 改动 {html.escape(chars)}：'
            f'<span class="pair" style="font-family:before-{style};font-weight:{FACES[style]["weight"]}">改前</span>'
            f'<span class="pair" style="font-family:{style};font-weight:{FACES[style]["weight"]}">改后</span></p>'
        )
    comparison_html = ""
    if comparison:
        comparison_html = (
            '<h2>本面已应用的逐点改动（草稿）</h2>' + "".join(comparison) +
            '<p class="meta">左为未改动的基准面，右为 patch 后的面；下面每个 face 行显示的也是改后的面。</p>'
        )
    radicals = "".join(html.escape(char) for char in TARGETS["radicalStudies"])
    rules = "".join(f"<li>{html.escape(rule)}</li>" for rule in TARGETS["strokeRules"])
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Selffont Maru 笔画审阅</title><style>
{''.join(styles)}
body{{font:16px/1.6 system-ui,sans-serif;margin:0;background:#faf8f5;color:#222}}
main{{max-width:60rem;margin:0 auto;padding:1.5rem 1rem 4rem}}
h1{{font-size:1.4rem;margin:.2rem 0 .1rem}} h2{{font-size:1.05rem;margin:2rem 0 .4rem}}
p.meta{{color:#666;margin:.2rem 0 1rem}}
.face{{margin:.6rem 0 .1rem;color:#444}} .sample{{margin:.1rem 0 .2rem;font-size:{size}px;line-height:1.5}}
.targets{{margin:.1rem 0 1.2rem;font-size:{max(28, size // 2)}px;line-height:1.7;word-break:break-all;color:#333}}
.pair{{font-size:{size}px;margin:0 .4rem}}
.chip{{display:inline-block;min-width:2.4rem;text-align:center;margin:.15rem;padding:.15rem .35rem;
border:1px solid #d6cec4;border-radius:.4rem;background:#fff;font-size:1.5rem}}
.chip.new{{border-style:dashed;color:#999;background:#f4f1ee}}
.rules li{{margin:.15rem 0}} code{{background:#efeae3;padding:.05rem .3rem;border-radius:.25rem}}
</style></head><body><main>
<h1>Selffont Maru 笔画审阅</h1>
<p class="meta">基准 {html.escape(MANIFEST['sourceFamily'])} @ {html.escape(MANIFEST['version'])}
· 派生家族 {html.escape(MANIFEST['family'])} · 五个静态 face，斜体由平台合成</p>
{comparison_html}
<h2>实际 face 渲染（浏览器直接加载已备好的 TTF）</h2>
{''.join(rows)}
<h2>你的练习字：可改（已有字形，可用逐点 patch 改笔画）</h2>
<p class="targets">{editable}</p>
<p class="meta">上面每个 face 行里的第二行就是这些字，用的就是该 face 的真实轮廓。</p>
<h2>你的练习字：缺字（{html.escape(MANIFEST['sourceFamily'])} 里没有，需另行造形）</h2>
<p class="targets">{missing}</p>
<p class="meta">这些是简体专用形，日文基准字体没有；不改的话手机上会回退到系统字体。</p>
<h2>部首练习（笔法参考，不是独立文本目标）</h2>
<p style="font-size:1.6rem">{radicals}</p>
<h2>手写笔画约定（当前审阅标准）</h2>
<ul class="rules">{rules}</ul>
<h2>怎么改</h2>
<p>每个面一个 <code>config/glyph-patches/&lt;Style&gt;.json</code>，只写明确点号与位移，
然后 <code>tools/edit_font.py</code> 校验并发布到 <code>build/fonts-patched</code>，
本页刷新即可看到。审计数字由 <code>tools/glyph_audit.py</code> 生成。</p>
</main></body></html>"""


def serve(faces: dict, report: dict, host: str, port: int, size: int,
          baseline_faces: dict | None = None, patch_report: list | None = None) -> None:
    page = _page(report, faces, size, baseline_faces, patch_report).encode()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status, content_type, payload):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head=False):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", b"" if head else page)
                return
            if path == "/api/audit":
                self._send(200, "application/json", json.dumps(report, ensure_ascii=False, indent=2).encode())
                return
            for prefix, sources in (("/fonts/", faces), ("/baseline/", baseline_faces or {})):
                if path.startswith(prefix):
                    name = path.rsplit("/", 1)[-1]
                    for candidate in sources.values():
                        if candidate.name == name:
                            self._send(200, "font/ttf", b"" if head else candidate.read_bytes())
                            return
            self._send(404, "text/plain; charset=utf-8", b"not found\n")

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"review page on http://{host}:{port} (faces: {', '.join(faces)})", flush=True)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-dir", type=Path, default=ROOT / "build/fonts-patched")
    parser.add_argument("--baseline-dir", type=Path, default=ROOT / "build/fonts",
                        help="Unpatched faces, served as /baseline for the before/after row")
    parser.add_argument("--patch-report", type=Path, default=ROOT / "build/glyph-patch-report.json",
                        help="tools/edit_font.py --report output; absent means nothing was patched yet")
    parser.add_argument("--render", type=Path, nargs="?", const=ROOT / "build/preview", default=None,
                        help="Write PNG sheets for the target characters and exit")
    parser.add_argument("--serve", action="store_true", help="Serve the review page")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--size", type=int, default=96)
    args = parser.parse_args()
    if not args.font_dir.is_dir():
        args.font_dir = ROOT / "build/fonts"
    faces = _load_faces(args.font_dir)
    baseline = {}
    if args.baseline_dir.is_dir():
        with contextlib.suppress(SystemExit):
            baseline = _load_faces(args.baseline_dir)
    patch_report = None
    if args.patch_report.is_file():
        patch_report = json.loads(args.patch_report.read_text())
    report = audit(args.font_dir, TARGETS)
    if args.render:
        for style, path in faces.items():
            render_sheet(path, "".join(row["char"] for row in report["characters"]),
                         Path(args.render) / f"{style}.png", size=max(48, args.size // 2))
            print(f"wrote {Path(args.render) / (style + '.png')}")
    if args.serve or not args.render:
        serve(faces, report, args.host, args.port, args.size, baseline, patch_report)


if __name__ == "__main__":
    main()
