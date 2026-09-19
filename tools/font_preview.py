#!/usr/bin/env python3
"""Preview server: original vs edited font side by side.

Serves a comparison page plus the two font files under the same host,
so the page works when proxied (relative URLs only).

Cache-busting: the @font-face URLs carry ?v=<file mtime>, so after a
rebuild the browser is forced to re-download (same URL made it reuse
the in-memory font face from the previous build). The page also shows
each font's mtime + md5 fingerprint and a load-state indicator.

Usage: tools/font_preview.py [port]   (default 8321)
"""
import hashlib
import http.server
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, "build")

# (url, path, mime)
FILES = {
    "/font/orig.ttf": (os.path.join(FONT_DIR, "font", "WenYuanRoundedSCVF.ttf"), "font/ttf"),
    "/font/edit.ttf": (os.path.join(FONT_DIR, "font-edited.ttf"), "font/ttf"),
}


def _meta(path):
    if not os.path.exists(path):
        return None
    st = os.stat(path)
    with open(path, "rb") as f:
        md5 = hashlib.md5(f.read()).hexdigest()[:8]
    return {"mtime": st.st_mtime, "size": st.st_size, "md5": md5}


def _font_url(name):
    path = FILES[f"/font/{name}.ttf"][0]
    m = _meta(path)
    if not m:
        return f"/font/{name}.ttf?v=0"
    return f"/font/{name}.ttf?v={int(m['mtime'])}"


SRC_URL = _font_url("orig")
EDIT_URL = _font_url("edit")

PAGE = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Selffont 预览 — 文源圆润</title>
<style>
  @font-face { font-family: "OrigFont"; src: url("__SRC__") format("truetype"); font-display: swap; }
  @font-face { font-family: "EditFont"; src: url("__EDIT__") format("truetype"); font-display: swap; }
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
  .sample { font-size: var(--size, 84px); line-height: 1.42;
            white-space: pre-wrap; word-break: break-all; min-height: 1.4em; }
  .src .sample { font-family: "OrigFont", serif; }
  .edit .sample { font-family: "EditFont", serif; }
</style>
</head>
<body>
<header>
  <b>Selffont 预览</b>
  <span class="meta">文源圆润简体 VF · 左/上 原始，右/下 平滑版</span>
  <input type="text" id="t" value="题兔免提北打找指
王天丸九刀买卖卯员哭" spellcheck="false">
  <label class="ctl">大小 <input type="range" id="sz" min="28" max="220" value="84">
  <span id="szv">84</span>px</label>
</header>
<div class="finfo" id="finfo">字体版本信息加载中…</div>
<div class="grid">
  <div class="pane src"><h2>原始<span class="tag">src</span></h2>
    <div class="sample" id="s1"></div></div>
  <div class="pane edit"><h2>平滑版<span class="tag">edited</span></h2>
    <div class="sample" id="s2"></div></div>
</div>
<script>
const t = document.getElementById('t'),
      sz = document.getElementById('sz'),
      szv = document.getElementById('szv'),
      s1 = document.getElementById('s1'),
      s2 = document.getElementById('s2');
function up() {
  const v = t.value || '题兔免提北打找指';
  s1.textContent = v;
  s2.textContent = v;
  szv.textContent = sz.value;
  document.documentElement.style.setProperty('--size', sz.value + 'px');
}
t.addEventListener('input', up);
sz.addEventListener('input', up);
up();

// font version + load state
fetch('/api/info').then(r => r.json()).then(info => {
  const fm = ts => new Date(ts * 1000).toLocaleTimeString('zh-CN', {hour12: false});
  const line = (name, m, ok) => m
    ? `${name}: ${fm(m.mtime)} · md5 ${m.md5} · ${(m.size/1048576).toFixed(1)}MB ${ok ? '<span class="ok">✓ 已加载</span>' : '<span class="warn">⏳ 加载中…</span>'}`
    : `${name}: 文件缺失`;
  let html = line('原始', info.orig, info.srcLoaded) + ' &nbsp;|&nbsp; ' +
             line('平滑版', info.edit, info.editLoaded);
  document.getElementById('finfo').innerHTML = html;
  // re-check load state once fonts settle
  if (document.fonts) {
    Promise.all([
      document.fonts.load('96px OrigFont', '题兔免提'),
      document.fonts.load('96px EditFont', '题兔免提'),
    ]).then(() => document.fonts.ready).then(() => {
      fetch('/api/info').then(r => r.json()).then(i2 => {
        document.getElementById('finfo').innerHTML =
          line('原始', i2.orig, true) + ' &nbsp;|&nbsp; ' + line('平滑版', i2.edit, true);
      });
    });
  }
}).catch(() => {
  document.getElementById('finfo').textContent = '字体版本信息获取失败';
});
</script>
</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            body = PAGE.replace("__SRC__", _font_url("orig")).replace(
                "__EDIT__", _font_url("edit")).encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)
        elif path == "/api/info":
            body = json.dumps({
                "orig": _meta(FILES["/font/orig.ttf"][0]),
                "edit": _meta(FILES["/font/edit.ttf"][0]),
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
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # keep the log quiet
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8321
    print(f"font preview on 0.0.0.0:{port}", flush=True)
    http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
