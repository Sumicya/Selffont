#!/usr/bin/env python3
"""Selffont 打包器:任意主字体 + 任意基础包 ZIP → 一个 KSU 模块。

自由化:config/sources.json 里的哈希和版本只是默认下载源的提示,不是闸门。
--font / --base 接受本地文件或 URL;家族名、可变轴、行度量全部现场从字体读取。
唯一硬性要求:主字体必须能被 fontTools 解析。度量归一(真机验证过的角标修复)
在基础包里找不到 Roboto 空壳载体时自动跳过并警告,而不是拒绝构建。

原字体字形、cmap、家族名、可变轴逐字节保留;只改安装副本的竖直行度量。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import stat
import sys
import tempfile
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
SOURCES = json.loads((ROOT / "config/sources.json").read_text())
FONTS_XML = ROOT / "fonts.xml"
MODULE_DIR = ROOT / "module"

INSTALLED_FILE = SOURCES["font"]["installedFile"]      # zip 内的主字体安装名
DEFAULT_FAMILY = SOURCES["font"]["family"]             # Xposed Policy.kt 内置的 Gecko 家族名
INPUT_CARRIER = "Roboto-Regular.ttf"                   # 输入 fonts.xml 引用的度量空壳
PRIMARY_NAMES = {"sans-serif", "sans-serif-condensed", "serif", "monospace",
                 "serif-monospace", "casual", "cursive"}
METRIC_FAMILIES = {"sans-serif", "sans-serif-condensed"}
OLD_PRIMARY = {f"{weight}.ttf" for weight in range(100, 1000, 100)}
MAX_FONT_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
DOWNLOAD_CAP = 512 * 1024 * 1024


def warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- 资源获取(自由)

def fetch(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Selffont-builder"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as out:
        remaining = DOWNLOAD_CAP
        while remaining:
            chunk = response.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            out.write(chunk)
            remaining -= len(chunk)


def resolve(spec: str | None, kind: str, cache: Path, refresh: bool) -> Path:
    """本地路径原样使用;URL 下载到缓存;缺省用 sources.json 的默认 URL。"""
    default = SOURCES[kind]
    if spec is None:
        if cache.exists() and not refresh:
            print(f"[{kind}] 复用缓存 {cache}")
            return cache
        spec = default["url"]
    if not spec.startswith(("http://", "https://")):
        return Path(spec)
    cache.parent.mkdir(parents=True, exist_ok=True)
    print(f"[{kind}] 下载 {spec}")
    fetch(spec, cache)
    if spec == default["url"] and default.get("sha256"):
        digest = hashlib.file_digest(cache.open("rb"), "sha256").hexdigest()
        if digest != default["sha256"]:
            # ponytail: 默认源哈希只警告不拦截——来源自由是特性;升级:想要严格模式再加 --strict。
            warn(f"默认源 {kind} 哈希变化:期望 {default['sha256'][:12]}…,实际 {digest[:12]}…。继续构建。")
    return cache


# ---------------------------------------------------------------- 字体读取(现场检测)

def layout_metrics(font: TTFont) -> dict:
    head, hhea, os2 = font["head"], font["hhea"], font["OS/2"]
    return {
        "unitsPerEm": head.unitsPerEm,
        "hhea": [hhea.ascent, hhea.descent, hhea.lineGap],
        "typo": [os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap],
        "win": [os2.usWinAscent, os2.usWinDescent],
        "useTypoMetrics": bool(os2.fsSelection & 0x80),
    }


def read_font(data: bytes) -> dict:
    """家族名、轴、覆盖全部现场读取;解析失败才失败。"""
    with TTFont(io.BytesIO(data)) as font:
        axes = {a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in font["fvar"].axes} if "fvar" in font else {}
        cmap = font.getBestCmap() or {}
        glyphs = font.getGlyphSet()
        digits = {}
        for character in "0123456789":
            name = cmap.get(ord(character))
            if name and name in glyphs:
                pen = BoundsPen(glyphs)
                glyphs[name].draw(pen)
                if pen.bounds is not None:
                    digits[character] = pen.bounds
        return {
            "family": font["name"].getDebugName(1) or "",
            "axes": axes,
            "mappedCodepoints": len(cmap),
            "layoutMetrics": layout_metrics(font),
            "digitInkY": digits,
        }


def weight_ladder(axes: dict) -> list[dict]:
    """把字体实际支持的轴翻译成 fonts.xml 的字重阶梯;越界值夹取,不报错。"""
    wght, ital = axes.get("wght"), axes.get("ital")
    if not wght:
        # 静态字体:同一文件声明全字重,粗体/斜体由系统合成。
        return [{"weight": w, "italic": False, "axes": []} for w in range(100, 1000, 100)]
    lo, _, hi = wght
    # ponytail: 轴越界值夹取不拒绝;升级:需要字体审计模式时改为报错。
    weights = [w for w in range(100, 1000, 100) if lo <= w <= hi] or [round(min(max(400, lo), hi))]
    ladder = [{"weight": w, "italic": False, "axes": [("wght", w)]} for w in weights]
    if ital and ital[0] <= 1 <= ital[2]:
        ladder += [{"weight": w, "italic": True, "axes": [("wght", w), ("ital", 1)]} for w in weights]
    return ladder


# ---------------------------------------------------------------- 度量归一(真机验证,保留)

def _ink_envelope(font: TTFont, characters: str) -> tuple[int, int] | None:
    glyphs, cmap = font.getGlyphSet(), font.getBestCmap() or {}
    bounds = []
    for character in characters:
        name = cmap.get(ord(character))
        if name and name in glyphs:
            pen = BoundsPen(glyphs)
            glyphs[name].draw(pen)
            if pen.bounds is not None:
                bounds.append(pen.bounds)
    if not bounds:
        return None
    return min(b[1] for b in bounds), max(b[3] for b in bounds)


def carrier_info(data: bytes) -> dict | None:
    """度量空壳:必须没有可见字形,否则会抢走主字体的渲染。"""
    try:
        with TTFont(io.BytesIO(data)) as font:
            cmap = font.getBestCmap() or {}
            if any(glyph != ".notdef" and unicodedata.category(chr(cp)) not in {"Cc", "Cf", "Zs", "Zl", "Zp"}
                   for cp, glyph in cmap.items()):
                return None
            return {"sha256": sha256(data), "family": font["name"].getDebugName(1),
                    "layoutMetrics": layout_metrics(font)}
    except Exception:
        return None


def normalize_metrics(font_data: bytes, carrier: dict) -> tuple[bytes, dict]:
    """主字体的 hhea/typo 对齐载体名义度量,根治角标数字偏低/切下沿。"""
    font = TTFont(io.BytesIO(font_data), recalcBBoxes=False, recalcTimestamp=False)
    head, hhea, os2 = font["head"], font["hhea"], font["OS/2"]
    upm, carrier_upm = head.unitsPerEm, carrier["unitsPerEm"]

    def scale(value):
        return round(value * upm / carrier_upm)

    asc, desc, gap = (scale(v) for v in carrier["hhea"])
    if asc <= 0 or desc >= 0:
        raise ValueError("载体行度量不是合法的 ascent/descent")
    ink = _ink_envelope(font, "0123456789")
    if ink is None:
        raise ValueError("主字体没有数字字形,无法验证归一后的行框")
    ink_min, ink_max = ink
    if ink_max > asc or ink_min < desc:
        raise ValueError(f"归一后行框会切数字墨迹:ink=[{ink_min},{ink_max}] box=[{desc},{asc}]")
    original = {"unitsPerEm": upm, "hhea": [hhea.ascent, hhea.descent, hhea.lineGap],
                "typo": [os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap],
                "win": [os2.usWinAscent, os2.usWinDescent],
                "useTypoMetrics": bool(os2.fsSelection & 0x80)}
    hhea.ascent, hhea.descent, hhea.lineGap = asc, desc, gap
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = asc, desc, gap
    if carrier.get("useTypoMetrics"):
        os2.version = max(os2.version, 4)
        os2.fsSelection |= 0x80
    else:
        os2.fsSelection &= ~0x80
    # 裁剪包络保持覆盖真实墨迹,只动行度量。
    os2.usWinAscent = max(asc, head.yMax, ink_max)
    os2.usWinDescent = max(-desc, -head.yMin, -ink_min)
    out = io.BytesIO()
    font.save(out)
    return out.getvalue(), {
        "carrierUnitsPerEm": carrier_upm, "original": original,
        "normalized": {"hhea": [asc, desc, gap], "typo": [asc, desc, gap],
                       "win": [os2.usWinAscent, os2.usWinDescent],
                       "useTypoMetrics": bool(os2.fsSelection & 0x80)},
        "digitInkY": [ink_min, ink_max],
    }


def _glyph_signature(data: bytes) -> dict:
    font = TTFont(io.BytesIO(data), recalcBBoxes=False, recalcTimestamp=False)
    glyf = font["glyf"]
    return {
        "order": font.getGlyphOrder(),
        "glyphs": {name: glyf[name].compile(glyf) for name in font.getGlyphOrder()},
        "cmap": font.getBestCmap(),
        "family": font["name"].getDebugName(1),
        "axes": {a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in font["fvar"].axes}
                if "fvar" in font else {},
    }


def assert_glyphs_preserved(original: bytes, packaged: bytes) -> None:
    """除行度量外一切必须逐字节不变:轮廓、cmap、家族名、轴。"""
    before, after = _glyph_signature(original), _glyph_signature(packaged)
    for key in ("order", "glyphs", "cmap", "family", "axes"):
        if before[key] != after[key]:
            raise ValueError(f"度量归一改变了 {key}")


# ---------------------------------------------------------------- fonts.xml 生成

def primary_fonts(family: ET.Element, filename: str, ladder: list[dict]) -> None:
    for child in list(family):
        if child.tag == "font":
            family.remove(child)
    for entry in ladder:
        node = ET.SubElement(family, "font", weight=str(entry["weight"]),
                             style="italic" if entry["italic"] else "normal")
        node.text = filename
        for tag, value in entry["axes"]:
            ET.SubElement(node, "axis", tag=tag, stylevalue=str(value))


def configure_fonts(source: bytes, filename: str, ladder: list[dict], carrier: str | None) -> bytes:
    """把主字体注入全部主家族;空壳度量家族保留原位;旧数字主字体整体替换。"""
    if "/" in filename or "\\" in filename:
        raise ValueError("安装文件名必须是纯文件名")
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.fromstring(source, parser=parser)
    if root.tag != "familyset":
        raise ValueError("输入 fonts.xml 必须是 familyset")
    default = root.find("family[@name='sans-serif']")
    if default is None or {(node.text or "").strip() for node in default.findall("font")} != {INPUT_CARRIER}:
        raise ValueError("输入 fonts.xml 的默认家族必须保留 Roboto 度量空壳")
    for family in list(root.findall("family")):
        name, files = family.get("name"), {(f.text or "").strip() for f in family.findall("font")}
        if not name and files and files <= OLD_PRIMARY | {INPUT_CARRIER}:
            root.remove(family)
        elif name in METRIC_FAMILIES and files == {INPUT_CARRIER}:
            if carrier is None:
                primary_fonts(family, filename, ladder)
        elif name in PRIMARY_NAMES or files & OLD_PRIMARY:
            primary_fonts(family, filename, ladder)
    fallback = ET.Element("family")
    primary_fonts(fallback, filename, ladder)
    root.insert(list(root).index(default) + 1, fallback)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------- 基础包(只取字体资源)

def font_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    total, seen = 0, set()
    members = []
    for entry in archive.infolist():
        path = PurePosixPath(entry.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in entry.filename:
            raise ValueError(f"基础包含不安全路径:{entry.filename}")
        if entry.filename in seen:
            raise ValueError(f"基础包含重复成员:{entry.filename}")
        seen.add(entry.filename)
        if path.parent != PurePosixPath("system/fonts") or path.suffix.lower() not in (".ttf", ".otf", ".ttc"):
            continue
        if stat.S_ISLNK(entry.external_attr >> 16):
            raise ValueError("基础包字体不允许符号链接")
        total += entry.file_size
        if entry.file_size > MAX_FONT_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("基础包字体超出打包上限")
        members.append(entry)
    return members


def render_module_prop(fields: dict) -> str:
    keys = ("id", "name", "version", "versionCode", "author", "description")
    missing = [key for key in keys if not fields.get(key)]
    if missing:
        raise ValueError(f"config/sources.json 的 module 缺少字段:{missing}")
    return "".join(f"{key}={fields[key]}\n" for key in keys)


# ---------------------------------------------------------------- 组装

def build(font: Path, base: Path, output: Path, revision: str | None = None, refresh: bool = False) -> dict:
    font, output = Path(font), Path(output)
    if output.resolve() in (font.resolve(), Path(base).resolve()):
        raise ValueError("输出不能覆盖输入")
    original_data = font.read_bytes()
    info = read_font(original_data)
    warnings: list[str] = []
    if not info["axes"]:
        warnings.append("主字体不是可变字体:按静态字体打包,全部字重指向同一文件,由系统合成。")
    if info["family"] != DEFAULT_FAMILY:
        warnings.append(f"家族名 {info['family']!r} 与 Xposed 模块内置的 {DEFAULT_FAMILY!r} 不同;"
                        "Gecko/Firefox 适配需同步修改 xposed 的 Policy.kt。")
    ladder = weight_ladder(info["axes"])

    with Path(base).open("rb") as base_stream:
        base_sha256 = hashlib.file_digest(base_stream, "sha256").hexdigest()
    with zipfile.ZipFile(base) as source:
        members = font_members(source)
        names = {PurePosixPath(e.filename).name for e in members}
        carrier = None
        if INPUT_CARRIER in names:
            carrier = carrier_info(source.read("system/fonts/" + INPUT_CARRIER))
            if carrier is None:
                warnings.append("基础包的 Roboto 含可见字形,不作为度量载体。")
        else:
            warnings.append("基础包没有 Roboto 度量空壳;跳过度量归一,角标/通知计数可能回退到修复前表现。")

        if carrier:
            font_data, metric_report = normalize_metrics(original_data, carrier["layoutMetrics"])
            assert_glyphs_preserved(original_data, font_data)
        else:
            font_data, metric_report = original_data, None
        xml = configure_fonts(FONTS_XML.read_bytes(), INSTALLED_FILE, ladder, INPUT_CARRIER if carrier else None)

        referenced = {(node.text or "").strip() for node in ET.fromstring(xml).iter("font")}
        bundled = [e for e in members
                   if PurePosixPath(e.filename).name in referenced or PurePosixPath(e.filename).name == INSTALLED_FILE]
        dropped = sorted({PurePosixPath(e.filename).name for e in members} - {PurePosixPath(e.filename).name for e in bundled})
        unbundled = sorted(referenced - names - {INSTALLED_FILE} - (set() if carrier else {INPUT_CARRIER}))
        if unbundled:
            warnings.append(f"fonts.xml 引用但基础包没有的字体(不打包):{', '.join(unbundled)}")

        report = {
            "revision": revision or "UNSPECIFIED",
            "font": {**{k: v for k, v in info.items() if k != "digitInkY"},
                     "sha256": sha256(original_data),
                     "normalizedSha256": sha256(font_data)},
            "metricNormalization": metric_report,
            "androidMetricsCarrier": carrier,
            "baseArchiveSha256": base_sha256,
            "weightLadder": [entry["weight"] for entry in ladder if not entry["italic"]],
            "bundledSupplementalFonts": sorted({PurePosixPath(e.filename).name for e in bundled} - {INSTALLED_FILE}),
            "unreferencedFontsDropped": dropped,
            "unbundledFontReferences": unbundled,
            "warnings": warnings,
            "deviceInstallation": "NOT_TESTED",
        }

        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
            staged = Path(tmp) / "module.zip"
            with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as dest:
                for entry in bundled:
                    if PurePosixPath(entry.filename).name != INSTALLED_FILE:
                        dest.writestr(entry.filename, source.read(entry))
                dest.writestr(f"system/fonts/{INSTALLED_FILE}", font_data)
                dest.writestr("fonts.xml", xml)
                dest.writestr("module.prop", render_module_prop(SOURCES["module"]))
                for path in sorted(MODULE_DIR.rglob("*")):
                    if path.is_file():
                        dest.write(path, path.relative_to(MODULE_DIR).as_posix())
                dest.write(ROOT / "LICENSES.md", "LICENSES.md")
                if "LICENSES.md" in source.namelist():  # 基础包归属说明,只取文本不取代码
                    dest.writestr("licenses/MFGA-base-LICENSES.md", source.read("LICENSES.md"))
                dest.writestr("report.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n")
                # 系统字体文件不能继承私有 umask;Unix 属性以中央目录为准。
                for item in dest.infolist():
                    item.create_system = 3
                    mode = 0o755 if item.filename.endswith(".sh") else 0o644
                    item.external_attr = (stat.S_IFREG | mode) << 16
            with zipfile.ZipFile(staged) as final:
                if final.testzip():
                    raise ValueError("输出 zip 损坏")
                if sha256(final.read(f"system/fonts/{INSTALLED_FILE}")) != sha256(font_data):
                    raise ValueError("包内主字体与归一结果不一致")
            staged.replace(output)
    print(f"\n构建完成:{output}")
    print(f"  家族 {info['family']!r}  字重 {report['weightLadder']}  补充字体 {len(report['bundledSupplementalFonts'])} 个")
    if metric_report:
        print(f"  度量归一 hhea {metric_report['original']['hhea']} → {metric_report['normalized']['hhea']}")
    else:
        print("  度量归一:跳过(无载体)")
    for message in warnings:
        warn(message)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", help="主字体 TTF/OTF:本地路径或 URL(默认按 sources.json 下载并缓存)")
    parser.add_argument("--base", help="基础包 ZIP:本地路径或 URL(默认按 sources.json 下载并缓存)")
    parser.add_argument("--output", type=Path, default=ROOT / "build/Selffont.zip")
    parser.add_argument("--revision", help="记入 report.json 的来源版本")
    parser.add_argument("--refresh", action="store_true", help="忽略缓存重新下载默认源")
    args = parser.parse_args()
    font = resolve(args.font, "font", ROOT / "build/cache/font.ttf", args.refresh)
    base = resolve(args.base, "base", ROOT / "build/cache/base.zip", args.refresh)
    build(font, base, args.output, args.revision, args.refresh)


if __name__ == "__main__":
    main()
