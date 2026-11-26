#!/usr/bin/env python3
"""罚篇三十/三十一一轮的三张证据图渲染器（可复算来源）。

为什么存在：主人两轮指出「没图」。本轮三件事各配一张图，且渲染代码进仓库：
  1. roster-20.png      碎块名单三方对照（生产侧 scan / 验收侧名单 / 点数变化）
  2. insert-before-after.png   skia.sh 插入前后 sans-serif 族首对照
  3. choose-0-100.png   核心判据选择层 0% → 100% 对照

名单对照的纪律（罚篇三十一）：汉字集合**一律从数据生成**（scan 输出解析、
点数变化实测、yaml 里码位字面量 eval），不许手写汉字字面量——手写在编辑与
脚本里三次漏字（䐴 㬵 㮣 挀 甆 与验证脚本里的 㮣  饦），代价是三次 CI failure
加一轮假读数。

用法：
    python tools/draw_round30_proof.py <母版.ttf> <清理版.ttf> <插入前配置> <插入后配置> <本包字件.ttf>
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yaml  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def cjk_font(size: int):
    import os
    # 渲染用字体必须含 CJK：系统没有 Noto CJK 时退到 load_default 会画出全豆腐图
    # （本轮第一版即如此：数据全对、字全豆腐，图作为证据失效）。母版本身含 2 万汉字，
    # 由 main() 经 SELFFONT_RENDER_FONT 传入，复算命令里因此必须带母版路径。
    cands = ([os.environ["SELFFONT_RENDER_FONT"]] if os.environ.get("SELFFONT_RENDER_FONT") else []) + [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    for p in cands:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def roster(mother: Path, cleaned: Path) -> Image.Image:
    out = subprocess.run([sys.executable, str(ROOT / "tools/drop_stray_ring.py"),
                          str(mother), "-o", "/tmp/_roster.ttf", "--scan"],
                         capture_output=True, text=True).stdout
    scan = {ln.strip()[0] for ln in out.splitlines() if ln.startswith("  ") and "U+" in ln}
    src = [s for s in yaml.safe_load((ROOT / ".github/workflows/build.yml").read_text())
           ["jobs"]["build"]["steps"] if "验收" in s.get("name", "")][0]["run"]
    approved = eval(re.search(r"STRAY_DROPPED = (\{chr\(c\) for c in \([\s\S]*?\)\})", src).group(1))
    gb, ga = TTFont(mother, lazy=False), TTFont(cleaned, lazy=False)
    cb, hb, ha = gb.getBestCmap(), gb["glyf"], ga["glyf"]
    changed = {chr(cp): (len(hb[gn].coordinates), len(ha[gn].coordinates))
               for cp, gn in cb.items()
               if gn in ha.glyphs and hb[gn].numberOfContours > 0
               and len(hb[gn].coordinates) != len(ha[gn].coordinates)}
    chars = sorted(scan | approved | set(changed))
    cols, cell = 5, 190
    rows = (len(chars) + cols - 1) // cols
    img = Image.new("RGB", (cols * cell, rows * cell + 30), "white")
    dr = ImageDraw.Draw(img)
    f1, f2 = cjk_font(64), cjk_font(15)
    for k, ch in enumerate(chars):
        ox, oy = (k % cols) * cell + 8, (k // cols) * cell + 26
        ok = ch in scan and ch in approved and ch in changed
        nb, na = changed.get(ch, (0, 0))
        dr.rectangle([ox, oy, ox + cell - 16, oy + cell - 16],
                     outline=(0, 150, 0) if ok else (200, 0, 0))
        dr.text((ox + 55, oy + 8), ch, font=f1, fill="black")
        dr.text((ox + 6, oy + 86), f"scan{'✓' if ch in scan else '✗'} 名单"
                f"{'✓' if ch in approved else '✗'} 点{nb}->{na}", font=f2,
                fill=(0, 120, 0) if ok else (200, 0, 0))
    dr.text((8, 4), f"碎块名单三方对照：scan {len(scan)} / 名单 {len(approved)} / "
            f"点数变化 {len(changed)}；三方相等={scan == approved == set(changed)}",
            font=cjk_font(16), fill="blue")
    return img


def insert_diff(before_cfg: Path, after_cfg: Path) -> Image.Image:
    def head(p):
        txt = p.read_text(encoding="utf-8").splitlines()
        i = next(n for n, l in enumerate(txt) if 'name="sans-serif"' in l)
        return txt[i:i + 6]
    b, a = head(before_cfg), head(after_cfg)
    img = Image.new("RGB", (1180, 260), "white")
    dr = ImageDraw.Draw(img)
    f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 15) \
        if Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf").exists() else cjk_font(15)
    dr.text((10, 6), "插入前（设备原配置 sans-serif 族首）", font=cjk_font(16), fill="blue")
    dr.text((600, 6), "插入后（skia.sh apply 产物族首）", font=cjk_font(16), fill="blue")
    for n, ln in enumerate(b):
        dr.text((10, 32 + n * 20), ln.strip()[:62], font=f, fill="black")
    for n, ln in enumerate(a):
        col = (200, 0, 0) if "Selffont" in ln else "black"
        dr.text((600, 32 + n * 20), ln.strip()[:62], font=f, fill=col)
    return img


def bars(pct_before: float, pct_after: float) -> Image.Image:
    img = Image.new("RGB", (900, 200), "white")
    dr = ImageDraw.Draw(img)
    f = cjk_font(18)
    for n, (label, pct) in enumerate((("设备原配置：本包画", pct_before),
                                      ("投放后配置：本包画", pct_after))):
        y = 40 + n * 70
        dr.text((10, y - 24), label, font=f, fill="black")
        dr.rectangle([10, y, 10 + 800, y + 34], outline=(150, 150, 150))
        dr.rectangle([10, y, 10 + 800 * pct / 100, y + 34], fill=(0, 130, 0))
        dr.text((820, y + 6), f"{pct:.2f}%", font=f, fill="black")
    return img


def pct_drawn(cfg: Path, ours: Path) -> float:
    """本包码位里由本包画的百分比——实跑 skia_paths，不硬编码。"""
    import skia_paths as S
    cmaps = {ours.name: set(TTFont(ours, lazy=True).getBestCmap())}
    fam = S.parse_families(cfg)
    probe = sorted(next(iter(cmaps.values())))
    return 100 * sum(1 for cp in probe if S.choose(fam, cmaps, cp) == ours.name) / max(len(probe), 1)


def main() -> int:
    mother, cleaned, before_cfg, after_cfg, ours = map(Path, sys.argv[1:6])
    import os
    os.environ["SELFFONT_RENDER_FONT"] = str(mother)
    # 规范 §15：图放 docs/evidence/，且「图不内联等于没有图」。
    # 于是内联语法由本脚本打印——把内联焊在渲染动作上，不靠我记得贴。
    out = ROOT / "docs/evidence"
    date = os.environ.get("SELFFONT_EVIDENCE_DATE", "2026-11-26")
    pb, pa = pct_drawn(before_cfg, ours), pct_drawn(after_cfg, ours)
    for img, stem in ((roster(mother, cleaned), "roster-20"),
                      (insert_diff(before_cfg, after_cfg), "insert-before-after"),
                      (bars(pb, pa), "choose-0-100")):
        p = out / f"{date}-{stem}.png"
        img.save(p)
        blob = p.read_bytes()
        rel = p.relative_to(ROOT)
        print(f"{rel}  {len(blob)} B  sha256 {hashlib.sha256(blob).hexdigest()}")
        print(f"![{stem}](/{rel})")
    del ours
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
