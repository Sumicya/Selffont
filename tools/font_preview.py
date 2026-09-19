#!/usr/bin/env python3
"""Preview server: original vs edited font side by side.

Serves a comparison page plus the two font files under the same host,
so the page works when proxied (relative URLs only).

Loading strategy (deliberate, do not "simplify" back to @font-face):
each pane shows a download progress bar and NOTHING else until its font
is fully downloaded, parsed and installed via the FontFace API. No
fallback face is ever rendered — the old font-display:swap approach
showed the system default font during the ~48MB download, which was
repeatedly mistaken for a real render. Freshness: ?v=<mtime> URLs +
fetch({cache:'no-store'}) + no-store responses, so a stale in-browser
face is impossible. The version line shows mtime + md5 + per-pane state.

Usage: tools/font_preview.py [port]   (default 8321)
"""
import hashlib
import http.server
import json
import os
import sys

from font_config import SOURCE_FONT_PATH

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, "build")
PREVIEW_DIR = os.path.join(FONT_DIR, "preview")

# (url, path, mime)
FILES = {
    "/font/orig.woff2": (os.path.join(PREVIEW_DIR, "font-orig-subset.woff2"), "font/woff2"),
    "/font/edit.woff2": (os.path.join(PREVIEW_DIR, "font-edit-subset.woff2"), "font/woff2"),
    "/font/orig.ttf": (os.path.join(PREVIEW_DIR, "font-orig-subset.ttf"), "font/ttf"),
    "/font/edit.ttf": (os.path.join(PREVIEW_DIR, "font-edit-subset.ttf"), "font/ttf"),
    "/font/orig-full.ttf": (str(SOURCE_FONT_PATH), "font/ttf"),
    "/font/edit-full.ttf": (os.path.join(FONT_DIR, "font-edited.ttf"), "font/ttf"),
}


def _meta(path):
    if not os.path.exists(path):
        return None
    st = os.stat(path)
    with open(path, "rb") as f:
        md5 = hashlib.md5(f.read()).hexdigest()[:8]
    return {"mtime": st.st_mtime, "size": st.st_size, "md5": md5}


def _font_file(name):
    for ext in (".woff2", ".ttf"):
        url = f"/font/{name}{ext}"
        if url in FILES and os.path.exists(FILES[url][0]):
            return url, FILES[url][0]
    return f"/font/{name}-full.ttf", FILES[f"/font/{name}-full.ttf"][0]


def _font_url(name):
    url, path = _font_file(name)
    m = _meta(path)
    if not m:
        return f"{url}?v=0"
    return f"{url}?v={int(m['mtime'])}"


SRC_URL = _font_url("orig")
EDIT_URL = _font_url("edit")

PAGE = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Selffont \u9884\u89c8 \u2014 \u6587\u6e90\u5706\u6da6</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
         margin: 0; background: #f4f4f0; color: #222; }
  header { padding: 12px 20px; background: #fff; border-bottom: 1px solid #ddd;
           display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
  header b { font-size: 15px; }
  header .meta { font-size: 12px; color: #888; margin-left: auto; }
  input[type=text] { width: min(560px, 100%); font-size: 16px; padding: 9px 12px;
                     border: 1px solid #ccc; border-radius: 8px; background: #fff; }
  .ctl { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #555; }
  .finfo { font-size: 12px; color: #555; font-family: ui-monospace, monospace;
           padding: 6px 20px; background: #fafaf7; border-bottom: 1px solid #e5e5df; }
  .finfo .ok { color: #1a7f37; font-weight: 600; }
  .finfo .warn { color: #b35900; font-weight: 600; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; padding: 14px; }
  @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
  .pane { background: #fff; border-radius: 10px; padding: 16px 18px;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  .pane h2 { margin: 0 0 12px; font-size: 13px; color: #888; font-weight: 600;
             letter-spacing: .04em; }
  .pane h2 .tag { background: #eee; border-radius: 4px; padding: 1px 6px;
                  font-size: 11px; margin-left: 6px; color: #666; }
  .veil { padding: 30px 10px; text-align: center; color: #888; font-size: 14px; }
  .bar { height: 8px; background: #e8e8e2; border-radius: 4px;
         margin: 12px auto 8px; max-width: 420px; overflow: hidden; }
  .bar > div { height: 100%; width: 0%; background: #1a7f37; border-radius: 4px;
               transition: width .15s; }
  .vpct { font-family: ui-monospace, monospace; font-size: 12px; }
  .veil.err .vpct { color: #b35900; }
  .sample { font-size: var(--size, 84px); line-height: 1.42;
            white-space: pre-wrap; word-break: break-all; min-height: 1.4em;
            visibility: hidden; }
  .pane.ready .sample { visibility: visible; }
  .pane.ready .veil { display: none; }
  .src .sample { font-family: "OrigFont"; }
  .edit .sample { font-family: "EditFont"; }
</style>
</head>
<body>
<header>
  <b>Selffont \u9884\u89c8</b>
  <span class="meta">\u6587\u6e90\u5706\u6da6\u7b80\u4f53 VF \u00b7 \u5de6/\u4e0a \u539f\u59cb\uff0c\u53f3/\u4e0b \u5e73\u6ed1\u7248</span>
  <input type="text" id="t" value="\u9898\u5154\u514d\u63d0\u5317\u6253\u627e\u6307\u738b\u5929\u4e38\u4e5d\u5200\u4e70\u5356\u536f\u5458\u54ed" spellcheck="false">
  <label class="ctl">\u5927\u5c0f <input type="range" id="sz" min="28" max="220" value="84">
  <span id="szv">84</span>px</label>
</header>
<div class="finfo" id="finfo">\u5b57\u4f53\u7248\u672c\u4fe1\u606f\u52a0\u8f7d\u4e2d\u2026</div>
<div class="grid">
  <div class="pane src" id="p1"><h2>\u539f\u59cb<span class="tag">src</span></h2>
    <div class="veil" id="v1"><div>\u539f\u59cb\u5b57\u4f53\u4e0b\u8f7d\u4e2d\u2026</div><div class="bar"><div id="b1"></div></div><div class="vpct" id="n1">0%</div></div>
    <div class="sample" id="s1"></div></div>
  <div class="pane edit" id="p2"><h2>\u5e73\u6ed1\u7248<span class="tag">edited</span></h2>
    <div class="veil" id="v2"><div>\u5e73\u6ed1\u7248\u5b57\u4f53\u4e0b\u8f7d\u4e2d\u2026</div><div class="bar"><div id="b2"></div></div><div class="vpct" id="n2">0%</div></div>
    <div class="sample" id="s2"></div></div>
</div>
<script>
const URLO = "__SRC__", URLE = "__EDIT__";
const t = document.getElementById('t'),
      sz = document.getElementById('sz'),
      szv = document.getElementById('szv'),
      s1 = document.getElementById('s1'),
      s2 = document.getElementById('s2');
function up() {
  const v = t.value || '\u9898\u5154\u514d\u63d0\u5317\u6253\u627e\u6307';
  s1.textContent = v;
  s2.textContent = v;
  szv.textContent = sz.value;
  document.documentElement.style.setProperty('--size', sz.value + 'px');
}
t.addEventListener('input', up);
sz.addEventListener('input', up);
up();

// version line state
let metaO = null, metaE = null, okO = false, okE = false;
const fm = ts => new Date(ts * 1000).toLocaleTimeString('zh-CN', {hour12: false});
function paintMeta() {
  const line = (name, m, ok) => m
    ? `${name}: ${fm(m.mtime)} \u00b7 md5 ${m.md5} \u00b7 ${(m.size/1048576).toFixed(1)}MB ${ok ? '<span class="ok">\u2713 \u5df2\u52a0\u8f7d</span>' : '<span class="warn">\u23f3 \u52a0\u8f7d\u4e2d\u2026</span>'}`
    : `${name}: \u6587\u4ef6\u7f3a\u5931`;
  document.getElementById('finfo').innerHTML =
    line('\u539f\u59cb', metaO, okO) + ' &nbsp;|\u00a0 ' + line('\u5e73\u6ed1\u7248', metaE, okE);
}

// full-download + FontFace install with progress; the pane stays veiled
// (no fallback glyphs, ever) until the real face is ready
async function loadOne(family, url, bar, num, veil, pane, markOk) {
  veil.classList.remove('err');
  veil.onclick = null;
  try {
    const res = await fetch(url, {cache: 'no-store'});
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const total = parseInt(res.headers.get('Content-Length') || '0', 10);
    const rd = res.body.getReader();
    const chunks = [];
    let n = 0;
    for (;;) {
      const {done, value} = await rd.read();
      if (done) break;
      chunks.push(value);
      n += value.length;
      const p = total ? Math.min(99, Math.round(n / total * 100)) : 0;
      bar.style.width = p + '%';
      num.textContent = total
        ? (n / 1048576).toFixed(1) + ' / ' + (total / 1048576).toFixed(1) + 'MB \u00b7 ' + p + '%'
        : (n / 1048576).toFixed(1) + 'MB';
    }
    bar.style.width = '100%';
    num.textContent = '\u89e3\u6790\u4e2d\u2026';
    const ab = await (new Blob(chunks)).arrayBuffer();
    const face = new FontFace(family, ab);
    await face.load();
    document.fonts.add(face);
    pane.classList.add('ready');
    markOk();
  } catch (e) {
    num.textContent = '\u52a0\u8f7d\u5931\u8d25: ' + e.message + ' \u2014 \u70b9\u51fb\u91cd\u8bd5';
    veil.classList.add('err');
    veil.style.cursor = 'pointer';
    veil.onclick = () => loadOne(family, url, bar, num, veil, pane, markOk);
  }
}

fetch('/api/info').then(r => r.json()).then(info => {
  metaO = info.orig;
  metaE = info.edit;
  paintMeta();
  loadOne('OrigFont', URLO,
    document.getElementById('b1'), document.getElementById('n1'),
    document.getElementById('v1'), document.getElementById('p1'),
    () => { okO = true; paintMeta(); });
  loadOne('EditFont', URLE,
    document.getElementById('b2'), document.getElementById('n2'),
    document.getElementById('v2'), document.getElementById('p2'),
    () => { okE = true; paintMeta(); });
}).catch(() => {
  document.getElementById('finfo').textContent = '\u5b57\u4f53\u7248\u672c\u4fe1\u606f\u83b7\u53d6\u5931\u8d25';
});
</script>
</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self._is_head = True
        self.do_GET()
        self._is_head = False

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            body = PAGE.replace("__SRC__", _font_url("orig")).replace(
                "__EDIT__", _font_url("edit")).encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)
        elif path == "/api/info":
            _, orig_path = _font_file("orig")
            _, edit_path = _font_file("edit")
            body = json.dumps({
                "orig": _meta(orig_path),
                "edit": _meta(edit_path),
                "srcLoaded": False, "editLoaded": False,
            }).encode("utf-8")
            self._send(200, "application/json", body)
        elif path in FILES:
            fpath, mime = FILES[path]
            if not os.path.exists(fpath):
                self._send(404, "text/plain", b"missing")
                return
            with open(fpath, "rb") as f:
                self._send(200, mime, f.read())
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, code, ctype, data):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # never serve a stale font face from disk cache
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not getattr(self, "_is_head", False):
            self.wfile.write(data)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[HTTP] {fmt % args}\n")
        sys.stderr.flush()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8321
    print(f"font preview on 0.0.0.0:{port}", flush=True)
    http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
