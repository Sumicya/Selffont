#!/usr/bin/env python3
"""Selffont 打包器:任意主字体 + 扩展字库 + 任意基础包 ZIP → 一个 KSU 模块。

自由化:config/sources.json 里的哈希和版本只是默认下载源的提示,不是闸门。
主字体/扩展/基础包都接受本地路径或 URL;家族名、字重、行度量全部现场从字体读取。
唯一硬性要求:主字体能被 fontTools 解析。度量归一(真机验证的角标修复)在基础包
里找不到 Roboto 空壳载体时自动跳过并警告,而不是拒绝构建。

原字体字形、cmap、家族名、可变轴逐字节保留;只改主字体安装副本的竖直行度量。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
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

INPUT_CARRIER = "Roboto-Regular.ttf"                   # 输入 fonts.xml 引用的度量空壳
PRIMARY_NAMES = {"sans-serif", "sans-serif-condensed", "serif", "monospace",
                 "serif-monospace", "casual", "cursive"}
METRIC_FAMILIES = {"sans-serif", "sans-serif-condensed"}
OLD_PRIMARY = {f"{weight}.ttf" for weight in range(100, 1000, 100)}
MAX_FONT_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
DOWNLOAD_CAP = 512 * 1024 * 1024
WEIGHTS = range(100, 1000, 100)


def warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- 资源获取(自由)

def fetch(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Selffont-builder"})
    with urllib.request.urlopen(request, timeout=300) as response, destination.open("wb") as out:
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
        # ponytail: 默认源哈希只警告不拦截——来源自由是特性;升级:想要严格模式再加 --strict。
        digest = hashlib.file_digest(cache.open("rb"), "sha256").hexdigest()
        if digest != default["sha256"]:
            warn(f"默认源 {kind} 哈希变化:期望 {default['sha256'][:12]}…,实际 {digest[:12]}…。继续构建。")
    return cache


def resolve_font_file(entry: dict, cache: Path, refresh: bool) -> Path:
    """主字体/扩展的单个文件:本地路径(相对路径按仓库根)或 URL,按 installed 名缓存。"""
    dest = cache / entry["installed"]
    url = entry.get("url")
    if url is None:
        raise ValueError(f"{entry['installed']} 无 url:主字体请用 --font 提供生成产物(见 README 生成步骤)")
    if not url.startswith(("http://", "https://")):
        path = Path(url)
        return path if path.is_absolute() else ROOT / path
    if dest.exists() and not refresh:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if entry.get("archive") == "7z":
        import py7zr  # 只在真用到 7z 源时导入
        archive_path = cache / (entry["installed"] + ".7z")
        if not archive_path.exists() or refresh:
            print(f"[extra] 下载 {entry['url']}")
            fetch(entry["url"], archive_path)
        with py7zr.SevenZipFile(archive_path) as archive:
            matches = [n for n in archive.getnames() if n.endswith(entry["pick"])]
        if len(matches) != 1:
            raise ValueError(f"7z 包里 {entry['pick']!r} 匹配到 {len(matches)} 个文件")
        with py7zr.SevenZipFile(archive_path) as archive:
            archive.extract(targets=matches, path=dest.parent)
        extracted = dest.parent / matches[0]
        shutil.move(extracted, dest)
    else:
        print(f"[font] 下载 {entry['url']}")
        fetch(entry["url"], dest)
    return dest


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
    """家族名、字重、轴、覆盖全部现场读取;解析失败才失败。"""
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
            "weight": font["OS/2"].usWeightClass,
            "axes": axes,
            "mappedCodepoints": len(cmap),
            "layoutMetrics": layout_metrics(font),
            "digitInkY": digits,
        }


def map_weights(files: list[dict]) -> list[dict]:
    """静态多字重:100..900 每档映射到最近声明字重(并列取较重)。"""
    if not files:
        return []
    return [
        {"weight": weight, "italic": italic, "file": min(
            files, key=lambda f: (abs(f["weight"] - weight), -f["weight"]))["installed"]}
        for italic in (False, True) for weight in WEIGHTS
    ]


def ladder_for(primary: dict, axes: dict | None = None) -> list[dict]:
    """主字体阶梯。vf=True 走可变轴(单文件);否则静态多文件映射。"""
    if primary.get("vf"):
        # ponytail: 轴越界值夹取不拒绝;升级:需要字体审计模式时改为报错。
        filename = primary["files"][0]["installed"]
        weights = list(WEIGHTS)
        if axes and "wght" in axes:
            lo, _, hi = axes["wght"]
            weights = [w for w in WEIGHTS if lo <= w <= hi] or [round(min(max(400, lo), hi))]
        upright = [{"weight": w, "italic": False, "file": filename,
                    "axes": [("wght", w)]} for w in weights]
        ital = axes.get("ital") if axes else None
        if ital and ital[0] <= 1 <= ital[2]:
            upright += [{"weight": w, "italic": True, "file": filename,
                         "axes": [("wght", w), ("ital", 1)]} for w in weights]
        return upright
    return map_weights(primary["files"])


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

def family_fonts(family: ET.Element, ladder: list[dict]) -> None:
    for child in list(family):
        if child.tag == "font":
            family.remove(child)
    for entry in ladder:
        node = ET.SubElement(family, "font", weight=str(entry["weight"]),
                             style="italic" if entry["italic"] else "normal")
        node.text = entry["file"]
        for tag, value in entry.get("axes", []):
            ET.SubElement(node, "axis", tag=tag, stylevalue=str(value))


def configure_fonts(source: bytes, primary_ladder: list[dict],
                    extra_ladder: list[dict], carrier: str | None) -> bytes:
    """主字体接管全部主家族;空壳度量家族保留原位;旧数字主字体整体替换。"""
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
                family_fonts(family, primary_ladder)
        elif name in PRIMARY_NAMES or files & OLD_PRIMARY:
            family_fonts(family, primary_ladder)
    fallback = ET.Element("family")
    family_fonts(fallback, primary_ladder + extra_ladder)
    # 匿名字形回退:主字体在前,扩展字库随后,再往后是输入配置里的其他补充家族。
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

def build(base: Path, output: Path, revision: str | None = None,
          font_override: Path | None = None, refresh: bool = False) -> dict:
    base, output = Path(base), Path(output)
    if output.resolve() == base.resolve():
        raise ValueError("输出不能覆盖输入")
    cache = ROOT / "build/cache"
    primary = SOURCES["primary"]
    warnings: list[str] = []

    # 主字体文件:现场读取家族/字重/轴;vf 单文件或静态多文件。
    if font_override is None and any("url" not in f for f in primary["files"]):
        raise ValueError("主字体未配置 url:先按 README 生成 Selffont Round 字库,再用 --font <目录> 构建")
    primary_data: dict[str, bytes] = {}
    for entry in primary["files"]:
        path = font_override / entry["installed"] if font_override else resolve_font_file(entry, cache, refresh)
        primary_data[entry["installed"]] = Path(path).read_bytes()
    regular_name = next((f["installed"] for f in primary["files"] if f["weight"] == 400),
                        primary["files"][0]["installed"])
    regular_info = read_font(primary_data[regular_name])
    primary_ladder = ladder_for(primary, regular_info.get("axes"))
    extra_ladder = map_weights(SOURCES["extras"])
    if regular_info["family"] != primary["family"]:
        warnings.append(f"主字体实际家族名 {regular_info['family']!r} 与配置 {primary['family']!r} 不同;"
                        "Gecko/Firefox 适配需同步修改 xposed 的 Policy.kt。")
    if any(read_font(data)["axes"] for data in primary_data.values()):
        warnings.append("主字体含 fvar 但配置为静态多字重;如需可变轴请设 primary.vf=true。")

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

        # 扩展字库:解析到实际字节;缺源警告不拦截。
        extras_data: dict[str, bytes] = {}
        for entry in SOURCES["extras"]:
            try:
                path = resolve_font_file(entry, cache, refresh)
                extras_data[entry["installed"]] = Path(path).read_bytes()
            except (OSError, ValueError) as error:
                warnings.append(f"扩展字库 {entry['installed']} 获取失败,跳过:{error}")
        extra_ladder = [e for e in extra_ladder
                        if e["file"] in extras_data or e["file"] in primary_data]
        xml = configure_fonts((FONTS_XML).read_bytes(), primary_ladder, extra_ladder,
                              INPUT_CARRIER if carrier else None)

        referenced = {(node.text or "").strip() for node in ET.fromstring(xml).iter("font")}
        bundled = [e for e in members if PurePosixPath(e.filename).name in referenced]
        dropped = sorted({PurePosixPath(e.filename).name for e in members} - {PurePosixPath(e.filename).name for e in bundled})
        unbundled = sorted(referenced - names - set(primary_data) - set(extras_data) - (set() if carrier else {INPUT_CARRIER}))
        if unbundled:
            warnings.append(f"fonts.xml 引用但基础包没有的字体(不打包):{', '.join(unbundled)}")

        # 主字体逐文件度量归一 + 字形守卫;扩展字库不归一(只兜生僻字,不进紧凑槽)。
        normalized: dict[str, bytes] = {}
        metric_reports = {}
        if carrier:
            for name, data in primary_data.items():
                normalized[name], metric_reports[name] = normalize_metrics(data, carrier["layoutMetrics"])
                assert_glyphs_preserved(data, normalized[name])
        else:
            normalized = primary_data

        with Path(base).open("rb") as base_stream:
            base_sha256 = hashlib.file_digest(base_stream, "sha256").hexdigest()
        report = {
            "revision": revision or "UNSPECIFIED",
            "primary": {
                "family": regular_info["family"],
                "configuredFamily": primary["family"],
                "files": [{"installed": name, "sha256": sha256(primary_data[name]),
                           "normalizedSha256": sha256(normalized[name]),
                           **{k: v for k, v in read_font(primary_data[name]).items()
                              if k in ("family", "weight", "mappedCodepoints")}}
                          for name in primary_data],
                "weightMap": {str(w): [e["file"] for e in primary_ladder
                                       if e["weight"] == w and not e["italic"]][0] for w in WEIGHTS},
            },
            "extras": [{"installed": name, "sha256": sha256(data),
                        **{k: v for k, v in read_font(data).items() if k in ("family", "weight")}}
                       for name, data in extras_data.items()],
            "metricNormalization": metric_reports,
            "androidMetricsCarrier": carrier,
            "baseArchiveSha256": base_sha256,
            "bundledSupplementalFonts": sorted({PurePosixPath(e.filename).name for e in bundled}),
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
                    dest.writestr(entry.filename, source.read(entry))
                for name, data in normalized.items():
                    dest.writestr(f"system/fonts/{name}", data)
                for name, data in extras_data.items():
                    dest.writestr(f"system/fonts/{name}", data)
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
                for name, data in normalized.items():
                    if sha256(final.read(f"system/fonts/{name}")) != sha256(data):
                        raise ValueError(f"包内主字体与归一结果不一致:{name}")
            staged.replace(output)
    print(f"\n构建完成:{output}")
    print(f"  主字体 {regular_info['family']!r}({len(primary_data)} 文件)  扩展 {len(extras_data)} 文件  "
          f"补充 {len(report['bundledSupplementalFonts'])} 个")
    if metric_reports:
        first = next(iter(metric_reports.values()))
        print(f"  度量归一 hhea {first['original']['hhea']} → {first['normalized']['hhea']}(共 {len(metric_reports)} 文件)")
    else:
        print("  度量归一:跳过(无载体)")
    for message in warnings:
        warn(message)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="基础包 ZIP:本地路径或 URL(默认按 sources.json 下载并缓存)")
    parser.add_argument("--font", type=Path, help="主字体目录:按 sources.json 的 installed 名提供文件,跳过下载")
    parser.add_argument("--output", type=Path, default=ROOT / "build/Selffont.zip")
    parser.add_argument("--revision", help="记入 report.json 的来源版本")
    parser.add_argument("--refresh", action="store_true", help="忽略缓存重新下载默认源")
    args = parser.parse_args()
    build(resolve(args.base, "base", ROOT / "build/cache/base.zip", args.refresh),
          args.output, args.revision, args.font, args.refresh)


if __name__ == "__main__":
    main()
