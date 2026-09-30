#!/usr/bin/env python3
"""Selffont 打包器:一个主字体 + 基础包 → KernelSU 模块 zip;--check 跑内建自检。

  pip install -r requirements.txt
  python3 build.py --check                       # 自检:无框架,assert 直跑,不下载不打包
  python3 build.py [--font X.ttf] [--base Y.zip] [--output O.zip] [--build N]

自由化:--font/--base 都收本地文件或 URL,没有平台闸门;家族名、可变轴、行度量
全部现场从字体里读;静态字体也能打包(全档同文件,粗体交给系统合成)。

对主字体的安装副本只做三件事(都属 OFL 意义上的修改,所以安装副本整体改名):
1. 竖直行度量对齐基础包里的 Roboto 空壳——真机验证过的角标偏低/切下沿修复;
2. 剪除映射到空白字形的码位——上游声称覆盖但字形空白,会吞掉回退链;
3. 内部家族名改成 RENAME——保留名合规(文渊的 OFL 保留 'WenYuan'/'文渊')。
轮廓、cmap 归属、可变轴有构建期守卫,动一个字节就报错。
"""
import argparse
import hashlib
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import traceback
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------- 默认来源(哈希只是提示)
PRIMARY_URL = "https://github.com/takushun-wu/WenYuanFonts/releases/download/v1.010/WenYuanRoundedSCVF.ttf"
PRIMARY_SHA256 = "e9ebde68d6d45ad5998765505677d1fb95821318fc693982f873e73fc27a2122"
PRIMARY_NAME = "Selffont-WenYuanRoundedSCVF.ttf"  # 默认源的安装名
RENAME = "Selffont Rounded SC VF"                 # 安装副本内部家族名(OFL 保留名合规)
BASE_URL = "https://github.com/Numbersf/MakeFontsGreatAgain/releases/download/1717180003/MFGA-SELFUSE-17.0.1.08-31-alpha2.1717180003.zip"
BASE_SHA256 = "620789eab7a6e47b96cfb333bb50f44ee526abe1e2ab2f572e54c30b16a3649b"

# ---------------------------------------------------------------- 配置数据
CARRIER = "Roboto-Regular.ttf"  # 输入 fonts.xml 的默认家族必须保留的度量空壳
PRIMARY_FAMILIES = {"sans-serif", "sans-serif-condensed", "serif", "monospace",
                    "serif-monospace", "casual", "cursive"}
METRIC_FAMILIES = {"sans-serif", "sans-serif-condensed"}
OLD_PRIMARY = {f"{weight}.ttf" for weight in range(100, 1000, 100)}  # 输入配置里的旧数字主字体
WEIGHTS = range(100, 1000, 100)
BLANK_CATEGORIES = {"Cc", "Cf", "Zs", "Zl", "Zp"}  # 合法空白字符的码位类别(空格类、控制类)
MODULE_KEYS = ("id", "name", "version", "versionCode", "author", "description")
CLOCK = timezone(timedelta(hours=8))  # 版本号里的日期按 UTC+8(否则 CI 在 UTC 下会差一天)
FONT_SUFFIXES = (".ttf", ".otf", ".ttc")


def warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


# ---------------------------------------------------------------- 来源(自由)

def fetch(url: str, destination: Path, expected: str | None = None) -> Path:
    """下载到 destination(已存在就复用);expected 是默认源哈希,漂移只警告不拦截。"""
    if destination.exists():
        print(f"[缓存] {destination}")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        print(f"[下载] {url}")
        request = urllib.request.Request(url, headers={"User-Agent": "Selffont-builder"})
        with urllib.request.urlopen(request, timeout=300) as response, destination.open("wb") as out:
            shutil.copyfileobj(response, out, 1 << 20)
    if expected and digest(destination) != expected:
        warn(f"默认源内容已变:期望 sha256 {expected[:12]}…,实际 {digest(destination)[:12]}…。继续构建。")
    return destination


def source(spec: str | None, default_url: str, default_sha: str, destination: Path) -> Path:
    """来源自由:None 用默认 URL(带哈希提示),本地路径原样,URL 下载到缓存。"""
    if spec is None:
        return fetch(default_url, destination, default_sha)
    if spec.startswith(("http://", "https://")):
        return fetch(spec, destination)
    return Path(spec)


def basename(spec: str) -> str:
    return PurePosixPath(urlparse(spec).path).name


# ---------------------------------------------------------------- 现场读取字体

def font_axes(font: TTFont) -> dict:
    return {axis.axisTag: (axis.minValue, axis.defaultValue, axis.maxValue)
            for axis in font["fvar"].axes} if "fvar" in font else {}


def font_face(data: bytes) -> dict:
    """家族名与可变轴——全部现场读取,读到什么用什么。"""
    with TTFont(io.BytesIO(data), lazy=True) as font:
        return {"family": font["name"].getDebugName(1) or "", "axes": font_axes(font)}


def layout_metrics(font: TTFont) -> dict:
    head, hhea, os2 = font["head"], font["hhea"], font["OS/2"]
    return {"unitsPerEm": head.unitsPerEm,
            "hhea": [hhea.ascent, hhea.descent, hhea.lineGap],
            "typo": [os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap],
            "win": [os2.usWinAscent, os2.usWinDescent],
            "useTypoMetrics": bool(os2.fsSelection & 0x80)}


def ink_bounds(font: TTFont, characters: str) -> tuple[int, int] | None:
    """一组字符的墨迹竖直包络 (min, max);一个字形都没有时 None。"""
    glyphs, cmap = font.getGlyphSet(), font.getBestCmap() or {}
    bounds = []
    for character in characters:
        name = cmap.get(ord(character))
        if name and name in glyphs:
            pen = BoundsPen(glyphs)
            glyphs[name].draw(pen)
            if pen.bounds is not None:
                bounds.append(pen.bounds)
    return (min(b[1] for b in bounds), max(b[3] for b in bounds)) if bounds else None


def carrier_metrics(data: bytes) -> dict | None:
    """度量空壳:必须没有可见字形,否则它会把主字体的渲染抢走。"""
    try:
        with TTFont(io.BytesIO(data), lazy=True) as font:
            cmap = font.getBestCmap() or {}
            if any(glyph != ".notdef" and unicodedata.category(chr(codepoint)) not in BLANK_CATEGORIES
                   for codepoint, glyph in cmap.items()):
                return None
            return layout_metrics(font)
    except Exception:  # 不是字体、或结构损坏:按“没有空壳”处理,由调用方降级
        return None


def weight_ladder(axes: dict) -> list[dict]:
    """9 档字重阶梯:VF 走 wght/ital 轴(越界只出范围内的档,不拒绝);
    静态字体全档同文件,粗体交给系统合成。"""
    if "wght" in axes:
        low, _, high = axes["wght"]
        weights = [weight for weight in WEIGHTS if low <= weight <= high] or [min(max(400, low), high)]
    else:
        weights = list(WEIGHTS)
    ital = axes.get("ital")
    styles = [False, True] if ital and ital[0] <= 1 <= ital[2] else [False]
    return [{"weight": weight, "italic": italic,
             "axes": ([("wght", weight)] if "wght" in axes else []) + ([("ital", 1)] if italic else [])}
            for italic in styles for weight in weights]


# ---------------------------------------------------------------- 安装副本的三处修改

def normalize_metrics(data: bytes, carrier: dict) -> bytes:
    """竖直行度量对齐 Roboto 空壳:根治角标数字偏低/切下沿(真机验证)。"""
    font = TTFont(io.BytesIO(data), recalcBBoxes=False, recalcTimestamp=False)
    head, hhea, os2 = font["head"], font["hhea"], font["OS/2"]
    upm, carrier_upm = head.unitsPerEm, carrier["unitsPerEm"]
    ascender, descender, line_gap = (round(value * upm / carrier_upm) for value in carrier["hhea"])
    if ascender <= 0 or descender >= 0:
        raise ValueError("空壳行度量不是合法的 ascent/descent")
    ink = ink_bounds(font, "0123456789")
    if ink is None:
        raise ValueError("主字体没有数字字形,无法验证归一后的行框")
    if ink[1] > ascender or ink[0] < descender:
        raise ValueError(f"归一后的行框会切数字墨迹:ink={list(ink)} box=[{descender},{ascender}]")
    hhea.ascent, hhea.descent, hhea.lineGap = ascender, descender, line_gap
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = ascender, descender, line_gap
    if carrier["useTypoMetrics"]:
        os2.version = max(os2.version, 4)
        os2.fsSelection |= 0x80
    else:
        os2.fsSelection &= ~0x80
    os2.usWinAscent = max(ascender, head.yMax, ink[1])   # 裁剪包络跟着真实墨迹,只动行度量
    os2.usWinDescent = max(-descender, -head.yMin, -ink[0])
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def glyph_signature(data: bytes) -> dict:
    """归一化不得改动的全部内容:轮廓、cmap 归属、家族名、可变轴。"""
    with TTFont(io.BytesIO(data), recalcBBoxes=False, recalcTimestamp=False) as font:
        if "glyf" in font:
            glyf = font["glyf"]
            outlines = {name: glyf[name].compile(glyf) for name in font.getGlyphOrder()}
        else:  # CFF:画笔重放(只比默认实例轮廓)
            glyphs = font.getGlyphSet()
            outlines = {}
            for name in font.getGlyphOrder():
                pen = RecordingPen()
                glyphs[name].draw(pen)
                outlines[name] = repr(pen.value).encode()
        return {"outlines": outlines, "cmap": font.getBestCmap(),
                "family": font["name"].getDebugName(1), "axes": font_axes(font)}


def assert_glyphs_preserved(original: bytes, packaged: bytes) -> None:
    before, after = glyph_signature(original), glyph_signature(packaged)
    changed = [key for key in before if before[key] != after[key]]
    if changed:
        raise ValueError(f"度量归一改变了 {', '.join(changed)}")


def prune_blank_mappings(data: bytes) -> tuple[bytes, int]:
    """剪除映射到空白字形的码位(非空白类码位):字形缺失却声称覆盖,会吞掉回退。

    空白类码位是合法空白,保留;字形一律不删,只剪映射。
    """
    font = TTFont(io.BytesIO(data))
    glyphs = font.getGlyphSet()
    pruned: set[int] = set()
    for table in font["cmap"].tables:
        kept = {}
        for codepoint, glyph_name in table.cmap.items():
            pen = BoundsPen(glyphs)
            try:
                glyphs[glyph_name].draw(pen)
            except Exception:  # 画不出来的字形不是空壳,不动它
                kept[codepoint] = glyph_name
                continue
            if pen.bounds is None and unicodedata.category(chr(codepoint)) not in BLANK_CATEGORIES:
                pruned.add(codepoint)
            else:
                kept[codepoint] = glyph_name
        table.cmap = kept
    out = io.BytesIO()
    font.save(out)
    return out.getvalue(), len(pruned)


def rename_font(data: bytes, family: str) -> bytes:
    """OFL 保留名合规:修改过的安装副本整体改名(legacy/typographic 双模型都写)。"""
    font = TTFont(io.BytesIO(data))
    name, os2 = font["name"], font["OS/2"]
    style = "Bold" if os2.fsSelection & 0x20 else "Regular"
    legacy_family = family if style == "Regular" else f"{family} {style}"
    full = f"{legacy_family} {style}"
    postscript = family.replace(" ", "-") + ("" if style == "Regular" else f"-{style}")
    for record in list(name.names):
        if record.nameID in (1, 3, 4, 6, 16, 17):
            name.removeNames(record.nameID, record.platformID, record.platEncID, record.langID)
    for platform, encoding, language in ((3, 1, 0x409), (1, 0, 0)):
        name.setName(legacy_family, 1, platform, encoding, language)
        name.setName(style, 2, platform, encoding, language)
        name.setName(full, 4, platform, encoding, language)
        name.setName(postscript, 6, platform, encoding, language)
        name.setName(f"{family}; metric-normalized, see OFL.txt; {full}", 3, platform, encoding, language)
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- fonts.xml 生成

def replace_fonts(family: ET.Element, font_name: str, ladder: list[dict]) -> None:
    for child in list(family):
        if child.tag == "font":
            family.remove(child)
    for entry in ladder:
        node = ET.SubElement(family, "font", weight=str(entry["weight"]),
                             style="italic" if entry["italic"] else "normal")
        node.text = font_name
        for tag, value in entry["axes"]:
            ET.SubElement(node, "axis", tag=tag, stylevalue=str(value))


def configure_fonts(template: bytes, font_name: str, ladder: list[dict], carrier: bool) -> bytes:
    """主字体接管全部主家族;空壳留在度量家族;旧数字主字体整体替换;匿名字形回退紧随默认家族。"""
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.fromstring(template, parser=parser)
    if root.tag != "familyset":
        raise ValueError("输入 fonts.xml 必须是 familyset")
    default = root.find("family[@name='sans-serif']")
    if default is None or {(node.text or "").strip() for node in default.findall("font")} != {CARRIER}:
        raise ValueError(f"输入 fonts.xml 的默认家族必须保留 {CARRIER} 度量空壳")
    for family in list(root.findall("family")):
        name = family.get("name")
        files = {(node.text or "").strip() for node in family.findall("font")}
        if not name and files and files <= OLD_PRIMARY | {CARRIER}:
            root.remove(family)
        elif name in METRIC_FAMILIES and files == {CARRIER}:
            if not carrier:  # 没有空壳文件:度量隔离让位,主字体直接进默认家族(不拒绝构建)
                replace_fonts(family, font_name, ladder)
        elif name in PRIMARY_FAMILIES or files & OLD_PRIMARY:
            replace_fonts(family, font_name, ladder)
    fallback = ET.Element("family")
    replace_fonts(fallback, font_name, ladder)
    root.insert(list(root).index(default) + 1, fallback)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------- 版本盖戳

def stamp_version(prop: str, build: str | None, now: datetime | None = None) -> str:
    """CI 盖戳:version = vYY.M.D.<总构建数>,versionCode = <总构建数>(KSU 靠它比新旧)。

    没有构建数(本地直接打包)就原样返回——仓库里的 module.prop 就是本地默认值,不猜数。
    """
    if not build:
        return prop
    if not build.isdigit():
        raise ValueError(f"构建数必须是纯数字,收到 {build!r}")
    day = now or datetime.now(CLOCK)
    prop = re.sub(r"^version=.*$", f"version=v{day.year % 100}.{day.month}.{day.day}.{build}", prop, flags=re.M)
    return re.sub(r"^versionCode=.*$", f"versionCode={build}", prop, flags=re.M)


# ---------------------------------------------------------------- 基础包(只取字体资源)

def font_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members, seen = [], set()
    for entry in archive.infolist():
        path = PurePosixPath(entry.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in entry.filename:
            raise ValueError(f"基础包含不安全路径:{entry.filename}")
        if entry.filename in seen:
            raise ValueError(f"基础包含重复成员:{entry.filename}")
        seen.add(entry.filename)
        if path.parent != PurePosixPath("system/fonts") or path.suffix.lower() not in FONT_SUFFIXES:
            continue
        if stat.S_ISLNK(entry.external_attr >> 16):
            raise ValueError("基础包字体不允许符号链接")
        members.append(entry)
    return members


# ---------------------------------------------------------------- 组装

def build(base: str | None = None, font: str | None = None, output: Path | None = None,
          build_num: str | None = None) -> list[str]:
    """base/font 是本地路径或 URL(None 用默认源);返回警告列表。"""
    cache = ROOT / "build/cache"
    output = Path(output) if output else ROOT / "build/Selffont.zip"
    build_num = build_num or os.environ.get("SELFFONT_BUILD") or None
    prop = stamp_version((ROOT / "module/module.prop").read_text(encoding="utf-8"), build_num)
    base_path = source(base, BASE_URL, BASE_SHA256, cache / "base.zip")
    if output.resolve() == Path(base_path).resolve():
        raise ValueError("输出不能覆盖输入")

    name = PRIMARY_NAME if font is None else basename(font)
    if PurePosixPath(name).suffix.lower() not in FONT_SUFFIXES:
        raise ValueError(f"主字体必须是 {', '.join(FONT_SUFFIXES)}:{font}")
    primary = Path(source(font, PRIMARY_URL, PRIMARY_SHA256, cache / name)).read_bytes()
    face = font_face(primary)
    ladder = weight_ladder(face["axes"])

    with zipfile.ZipFile(base_path) as archive:
        members = font_members(archive)
        names = {member.filename for member in members}
        carrier = carrier_metrics(archive.read(f"system/fonts/{CARRIER}")) if f"system/fonts/{CARRIER}" in names else None
        warnings: list[str] = []
        if carrier is None:
            warnings.append(f"基础包没有可用的 {CARRIER} 度量空壳:跳过度量归一,角标/通知计数可能回退到修复前表现。")
            packaged = primary
        else:
            packaged = normalize_metrics(primary, carrier)
            assert_glyphs_preserved(primary, packaged)   # 改名前先验证只动了行度量
        packaged = rename_font(packaged, RENAME)
        packaged, pruned = prune_blank_mappings(packaged)
        if pruned:
            warnings.append(f"剪除空壳映射 {pruned} 个(上游声称覆盖但字形空白),这些字落到回退链。")

        xml = configure_fonts((ROOT / "fonts.xml").read_bytes(), name, ladder, carrier is not None)
        referenced = {(node.text or "").strip() for node in ET.fromstring(xml).iter("font")}
        bundled = [member for member in members if PurePosixPath(member.filename).name in referenced]

        output.parent.mkdir(parents=True, exist_ok=True)
        write_module(output, archive, bundled, name, packaged, xml, prop)

    version = next(line.split("=", 1)[1] for line in prop.splitlines() if line.startswith("version="))
    print(f"构建完成:{output}  版本 {version}")
    print(f"  主字体 {face['family']!r} → {RENAME}({name},{len(ladder)} 档)")
    print(f"  补充字库 {len(bundled)} 个,fonts.xml 其余引用由设备自带(Noto/OEM,不打包)")
    for message in warnings:
        warn(message)
    return warnings


def write_module(output: Path, archive: zipfile.ZipFile, bundled: list[zipfile.ZipInfo],
                 name: str, packaged: bytes, xml: bytes, prop: str) -> None:
    """写模块 zip:被 fonts.xml 引用的基础包字体 + 主字体 + 原生 KSU 模块布局。"""
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as destination:
        for member in bundled:
            destination.writestr(member.filename, archive.read(member))
        destination.writestr(f"system/fonts/{name}", packaged)
        destination.writestr("fonts.xml", xml)
        destination.writestr("module.prop", prop)
        for path in sorted((ROOT / "module").rglob("*")):
            if path.is_file() and path.name != "module.prop":  # 已按盖戳结果写入
                destination.write(path, path.relative_to(ROOT / "module").as_posix())
        destination.write(ROOT / "LICENSES.md", "LICENSES.md")
        if "LICENSES.md" in archive.namelist():  # 基础包归属说明,只取文本不取代码
            destination.writestr("licenses/MFGA-base-LICENSES.md", archive.read("LICENSES.md"))
        for item in destination.infolist():  # 文件属性以中央目录为准,不能带上私有 umask
            item.create_system = 3
            item.external_attr = (stat.S_IFREG | (0o755 if item.filename.endswith(".sh") else 0o644)) << 16
    with zipfile.ZipFile(output) as final:
        if final.testzip():
            raise ValueError("输出 zip 损坏")


# ================================================================ 内建自检(--check)
# 无测试框架、无夹具模块,assert 直跑;python3 build.py --check 一把跑完。

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def box(x0, y0, x1, y1):
    pen = TTGlyphPen(None)
    pen.moveTo((x0, y0)), pen.lineTo((x0, y1)), pen.lineTo((x1, y1)), pen.lineTo((x1, y0))
    pen.closePath()
    return pen.glyph()


def make_font(family="Test Primary", upm=1000, axes=True):
    order = [".notdef", "space", *"0123456789", "A"]
    b = FontBuilder(upm, isTTF=True)
    b.setupGlyphOrder(order)
    b.setupCharacterMap({32: "space", 65: "A", **{ord(d): d for d in "0123456789"}})
    glyphs = {".notdef": box(0, 0, 500, 700), "space": TTGlyphPen(None).glyph()}
    for digit in "0123456789":
        glyphs[digit] = box(40, -10, 460, 744)
    glyphs["A"] = box(20, 0, 480, 700)
    b.setupGlyf(glyphs)
    b.setupHorizontalMetrics(dict.fromkeys(order, (500, 0)))
    b.setupHorizontalHeader(ascent=1160, descent=-288)
    b.setupNameTable({"familyName": family, "styleName": "Regular",
                      "uniqueFontIdentifier": family, "fullName": family, "psName": family})
    b.setupOS2(sTypoAscender=880, sTypoDescender=-120, usWinAscent=1160, usWinDescent=288, usWeightClass=400)
    b.setupPost()
    if axes:
        b.setupFvar(axes=[("wght", 100, 400, 900, "Weight"), ("ital", 0, 0, 1, "Italic")], instances=[])
    out = io.BytesIO()
    b.save(out)
    return out.getvalue()


def make_carrier(visible=False):
    order = [".notdef", "space"] + (["A"] if visible else [])
    b = FontBuilder(1000, isTTF=True)
    b.setupGlyphOrder(order)
    b.setupCharacterMap({32: "space", **({65: "A"} if visible else {})})
    b.setupGlyf({name: TTGlyphPen(None).glyph() for name in order})
    b.setupHorizontalMetrics(dict.fromkeys(order, (500, 0)))
    b.setupHorizontalHeader(ascent=930, descent=-250)
    b.setupNameTable({"familyName": "Carrier", "styleName": "Regular", "uniqueFontIdentifier": "Carrier",
                      "fullName": "Carrier", "psName": "Carrier"})
    b.setupOS2(sTypoAscender=930, sTypoDescender=-250, usWinAscent=930, usWinDescent=250, usWeightClass=400)
    b.setupPost()
    out = io.BytesIO()
    b.save(out)
    return out.getvalue()


def base_zip(path, fonts, licenses=True):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in fonts.items():
            archive.writestr("system/fonts/" + name, data)
        if licenses:
            archive.writestr("LICENSES.md", "base attribution\n")


def sh(args, env):
    return subprocess.run(["sh", *args], env=env, capture_output=True, text=True)


# ---------------------------------------------------------------- 度量归一(真机验证的角标修复)

@check
def metric_normalization():
    carrier = layout_metrics(TTFont(io.BytesIO(make_carrier())))
    data = make_font()
    normalized = normalize_metrics(data, carrier)
    result = TTFont(io.BytesIO(normalized))
    assert (result["hhea"].ascent, result["hhea"].descent) == (930, -250), "hhea 未对齐空壳"
    assert (result["OS/2"].sTypoAscender, result["OS/2"].sTypoDescender) == (930, -250), "typo 未对齐"
    assert_glyphs_preserved(data, normalized)  # 轮廓/cmap/家族/轴必须逐字节不变
    scaled = TTFont(io.BytesIO(normalize_metrics(make_font(upm=2048), carrier)))
    assert scaled["hhea"].ascent == round(930 * 2048 / 1000), "upm 缩放错误"
    # 会切数字墨迹的归一必须被拒:空壳 ascent 700 盖不住数字墨迹 744。
    try:
        normalize_metrics(make_font(), dict(carrier, hhea=[700, -100, 0]))
        raise AssertionError("切墨迹的归一未被拒绝")
    except ValueError:
        pass
    # 空壳判定:可见字形的 Roboto 不能当空壳。
    assert carrier_metrics(make_carrier(visible=True)) is None
    assert carrier_metrics(make_carrier())["hhea"] == [930, -250, 0]
    assert carrier_metrics(b"not a font") is None


# ---------------------------------------------------------------- 字重阶梯与 fonts.xml 生成

@check
def fonts_xml():
    ladder = weight_ladder({"wght": (100, 400, 900), "ital": (0, 0, 1)})
    assert len(ladder) == 18 and all(entry["axes"] for entry in ladder), "可变字体应出 9 档 × 2 风格带轴"
    assert [entry["weight"] for entry in ladder if not entry["italic"]] == list(WEIGHTS)
    # 轴范围窄:只出范围内的档,不拒绝。
    assert [entry["weight"] for entry in weight_ladder({"wght": (200, 400, 700)}) if not entry["italic"]] \
        == [200, 300, 400, 500, 600, 700]
    # 静态:无轴也能打包,全档同文件。
    static = weight_ladder({})
    assert len(static) == 9 and not any(entry["axes"] for entry in static)

    template = (ROOT / "fonts.xml").read_bytes()
    root = ET.fromstring(configure_fonts(template, "V.ttf", ladder, True))
    default = root.find("family[@name='sans-serif']")
    assert {node.text.strip() for node in default.findall("font")} == {CARRIER}, "默认家族应保留度量空壳"
    fallback = list(root)[list(root).index(default) + 1]
    assert fallback.get("name") is None and len(fallback.findall("font")) == 18, "匿名字形回退应紧随默认家族"
    assert {node.text.strip() for node in fallback.findall("font")} == {"V.ttf"}
    for family in root.findall("family"):
        for node in family.findall("font"):
            assert (node.text or "").strip() not in OLD_PRIMARY, "残留旧数字主字体"
    # 静态主字体不生成 axis;可变主字体生成 axis。
    static_root = ET.fromstring(configure_fonts(template, "S.ttf", static, True))
    ours = [node for family in static_root.findall("family") for node in family.findall("font")
            if (node.text or "").strip() == "S.ttf"]
    assert ours and not any(node.findall("axis") for node in ours), "静态主字体不该生成 axis"

    # 自由化:没有空壳时,度量家族也指向主字体(放弃度量隔离,不拒绝构建)。
    no_carrier = ET.fromstring(configure_fonts(template, "V.ttf", ladder, False))
    for name in ("sans-serif", "sans-serif-condensed"):
        got = no_carrier.findall(f"family[@name='{name}']")[0].findall("font")
        assert {node.text.strip() for node in got} == {"V.ttf"}, name
    assert not [node for family in no_carrier.findall("family") for node in family.findall("font")
                if (node.text or "").strip() == CARRIER], "无空壳时仍引用 Roboto"

    # 输入防线:默认家族不是 Roboto 空壳、或不是 familyset 的输入拒绝替换。
    foreign = template.replace(b'<family name="sans-serif">', b'<family name="elsewhere">', 1)
    for bad in (foreign, b"<not-familyset/>"):
        try:
            configure_fonts(bad, "V.ttf", ladder, True)
            raise AssertionError("非法模板未被拒绝")
        except ValueError:
            pass


# ---------------------------------------------------------------- 空壳映射剪除

@check
def blank_prune():
    """映射到空白字形的非空白码位被剪;空格这类合法空白保留;字形集合不动。"""
    b = FontBuilder(1000, isTTF=True)
    order = [".notdef", "space", "A", "B"]
    b.setupGlyphOrder(order)
    b.setupCharacterMap({0x20: "space", 0x41: "A", 0x42: "B"})
    b.setupGlyf({"A": box(0, 0, 100, 100), "B": TTGlyphPen(None).glyph(),
                 "space": TTGlyphPen(None).glyph(), ".notdef": TTGlyphPen(None).glyph()})
    b.setupHorizontalMetrics({name: (500, 0) for name in order})
    b.setupHorizontalHeader(ascent=930, descent=-250)
    b.setupNameTable({"familyName": "T", "styleName": "Regular"})
    b.setupOS2(usWeightClass=400)
    b.setupPost()
    out = io.BytesIO()
    b.save(out)
    pruned, count = prune_blank_mappings(out.getvalue())
    assert count == 1, count  # format4/format12 同码位只算一个
    cmap = TTFont(io.BytesIO(pruned)).getBestCmap()
    assert 0x20 in cmap and 0x41 in cmap and 0x42 not in cmap, cmap
    assert set(TTFont(io.BytesIO(pruned)).getGlyphOrder()) == set(order), "只剪映射,不删字形"


# ---------------------------------------------------------------- 端到端构建 + 自由化 + 信任边界

@check
def build_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fonts_dir = tmp / "fonts"
        fonts_dir.mkdir()
        regular = fonts_dir / "P-Regular.ttf"
        regular.write_bytes(make_font())
        base, output = tmp / "base.zip", tmp / "out" / "Selffont.zip"
        base_zip(base, {"Roboto-Regular.ttf": make_carrier(), "NotoSansPro.otf": b"supplemental",
                        "DeadWeight.ttf": b"dead"})
        build(base=str(base), font=str(regular), output=output, build_num="9")

        with zipfile.ZipFile(output) as archive:
            members = set(archive.namelist())
            for expected in ("module.prop", "fonts.xml", "LICENSES.md", "customize.sh",
                             "firefox.sh", "geckoview-config.yaml", "licenses/WenYuan-OFL.txt",
                             "system/fonts/P-Regular.ttf", "system/fonts/Roboto-Regular.ttf",
                             "system/fonts/NotoSansPro.otf", "licenses/MFGA-base-LICENSES.md"):
                assert expected in members, f"缺成员 {expected}"
            for absent in ("report.json", "action.sh", "system/fonts/DeadWeight.ttf"):
                assert absent not in members, f"不该有的成员 {absent}"
            installed_prop = archive.read("module.prop").decode()
            assert "version=v26." in installed_prop and "\nversionCode=9\n" in installed_prop, installed_prop
            assert (archive.getinfo("customize.sh").external_attr >> 16) == stat.S_IFREG | 0o755
            assert (archive.getinfo("system/fonts/P-Regular.ttf").external_attr >> 16) == stat.S_IFREG | 0o644
            packaged = archive.read("system/fonts/P-Regular.ttf")
            xml = archive.read("fonts.xml").decode()

        # 归一 + 改名之后:轮廓/cmap/轴不动,家族名换成 RENAME,hhea 对齐空壳。
        before, after = glyph_signature(make_font()), glyph_signature(packaged)
        assert before["outlines"] == after["outlines"] and before["cmap"] == after["cmap"], "轮廓或 cmap 被改了"
        assert before["axes"] == after["axes"] and after["family"] == RENAME
        assert TTFont(io.BytesIO(packaged))["hhea"].ascent == 930, "包内字体未归一"
        assert "P-Regular.ttf" in xml

        # 自由化:主字体按自己的文件名安装,不要求固定命名;非字体后缀明确报错。
        custom = fonts_dir / "Weird-Name.ttf"
        custom.write_bytes(make_font(family="Custom Face"))
        build(base=str(base), font=str(custom), output=output)
        with zipfile.ZipFile(output) as archive:
            assert "system/fonts/Weird-Name.ttf" in archive.namelist()
            assert "Weird-Name.ttf" in archive.read("fonts.xml").decode()
        try:
            build(base=str(base), font=str(fonts_dir / "x.woff2"), output=output)
            raise AssertionError("非字体后缀未被拒绝")
        except ValueError:
            pass

        # 没有空壳 → 跳过归一并警告,构建继续(自由化)。
        base_zip(base, {"SomeFont.ttf": b"supplemental"})
        warnings = build(base=str(base), font=str(regular), output=output)
        assert any("Roboto" in message for message in warnings)
        with zipfile.ZipFile(output) as archive:
            root = ET.fromstring(archive.read("fonts.xml"))
        assert {node.text.strip() for node in root.find("family[@name='sans-serif']").findall("font")} == {"P-Regular.ttf"}

        # 信任边界:路径穿越 / 绝对路径 / 符号链接成员拒绝,输出不许覆盖输入。
        for bad in ("system/fonts/../../evil.ttf", "/abs.ttf"):
            bad_zip = tmp / "bad.zip"
            base_zip(bad_zip, {}, licenses=False)
            with zipfile.ZipFile(bad_zip, "a") as archive:
                archive.writestr(bad, b"x")
            try:
                build(base=str(bad_zip), font=str(regular), output=output)
                raise AssertionError(f"危险成员未拒绝:{bad}")
            except ValueError:
                pass
        link_zip = tmp / "link.zip"
        base_zip(link_zip, {}, licenses=False)
        with zipfile.ZipFile(link_zip, "a") as archive:
            info = zipfile.ZipInfo("system/fonts/Link.ttf")
            info.external_attr = (stat.S_IFLNK | 0o644) << 16
            archive.writestr(info, "/etc/passwd")
        try:
            build(base=str(link_zip), font=str(regular), output=output)
            raise AssertionError("符号链接字体未被拒绝")
        except ValueError:
            pass
        try:
            build(base=str(base), font=str(regular), output=base)
            raise AssertionError("输出覆盖了输入")
        except ValueError:
            pass


# ---------------------------------------------------------------- 版本盖戳

@check
def version_stamp():
    """CI 盖戳:version = vYY.M.D.<构建数>,versionCode = <构建数>;没给构建数就原样不动。"""
    prop = (ROOT / "module/module.prop").read_text()
    stamped = stamp_version(prop, "42", now=datetime(2026, 9, 30, 12, 0, tzinfo=CLOCK))
    assert "version=v26.9.30.42" in stamped and "versionCode=42" in stamped, stamped
    assert stamp_version(prop, None) == prop and stamp_version(prop, "") == prop
    for bad in ("abc", "4 2", "9."):
        try:
            stamp_version(prop, bad)
            raise AssertionError(f"非数字构建数未被拒绝:{bad!r}")
        except ValueError:
            pass


# ---------------------------------------------------------------- 火狐(Gecko)接入

@check
def firefox_bridge():
    """火狐接入:首选项只前置不清空 + install/remove 行为(PATH 上的 am 用替身)。"""
    config = (ROOT / "module/geckoview-config.yaml").read_text(encoding="utf-8")
    assert config.startswith("prefs:\n") or "\nprefs:\n" in config, "Gecko 配置必须只有 prefs 段"
    lines = [line.strip() for line in config.splitlines() if line.strip().startswith("font.name-list.")]
    assert len(lines) >= 20, f"首选项太少:{len(lines)}"
    for line in lines:  # 只前置:每条都必须以本模块家族名开头,后面原样保留 Gecko 默认回退链
        value = line.split(":", 1)[1].strip().strip('"')
        assert value.startswith(RENAME + ","), f"未前置或家族名不符:{line}"
    assert config.count('"') % 2 == 0, "引号不配对"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shim, calls = tmp / "bin", tmp / "calls"
        shim.mkdir()
        (shim / "am").write_text(f'#!/bin/sh\necho "am $*" >> {calls}\n')
        (shim / "am").chmod(0o755)
        data = tmp / "local/tmp"
        env = {**os.environ, "PATH": f"{shim}:{os.environ['PATH']}",
               "FIREFOX_DATA_DIR": str(data), "FIREFOX_PACKAGE": "org.mozilla.firefox"}

        result = sh([str(ROOT / "module/firefox.sh")], env)
        assert result.returncode == 0, result.stderr
        target = data / "org.mozilla.firefox-geckoview-config.yaml"
        assert target.read_bytes() == (ROOT / "module/geckoview-config.yaml").read_bytes(), "配置没原样落地"
        assert "am set-debug-app --persistent org.mozilla.firefox" in calls.read_text()

        result = sh([str(ROOT / "module/firefox.sh"), "remove"], env)
        assert result.returncode == 0 and not target.exists(), result
        assert "am clear-debug-app" in calls.read_text()

        assert sh([str(ROOT / "module/firefox.sh"), "wat"], env).returncode == 2, "未知参数应报用法错"


# ---------------------------------------------------------------- 模块安装脚本

@check
def runtime_scripts():
    assert sh(["-n", str(ROOT / "module/customize.sh")], os.environ).returncode == 0, "customize.sh 语法错误"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        modpath = tmp / "module"
        (modpath / "system/fonts").mkdir(parents=True)
        for path in sorted((ROOT / "module").iterdir()):  # 模块目录照打包后的样子铺开
            if path.is_file():
                shutil.copy(path, modpath / path.name)
        (modpath / "fonts.xml").write_bytes(b"<familyset/>")
        (modpath / "system/fonts/Any-Name.ttf").write_bytes(b"font")
        system = tmp / "sysroot"
        for directory in ("etc", "system_ext/etc", "product/etc"):
            (system / directory).mkdir(parents=True)
            (system / directory / "font.xml").write_text("<familyset>old</familyset>")
        (system / "etc/fonts_customization.xml").write_text("<other-schema/>")
        env = {**os.environ, "MODPATH": str(modpath), "SELFFONT_SYSTEM_ROOT": str(system)}
        harness = modpath / "harness.sh"
        harness.write_text('ui_print() { echo "$@"; }\n'
                           'abort() { echo "ABORT: $*" >&2; exit 1; }\n'
                           f'. "{modpath / "customize.sh"}"\n')

        result = sh([str(harness)], env)
        assert result.returncode == 0, result.stderr
        for directory in ("etc", "system_ext/etc", "product/etc"):
            assert (modpath / system.relative_to("/") / directory / "font.xml").read_text() == "<familyset/>", directory
        assert not (modpath / "system/etc/fonts_customization.xml").exists(), "自选配置不该被碰"
        assert "已替换 3 份" in result.stdout, "应报告替换数量:" + result.stdout

        # 没有字体文件(= 直接压缩了仓库)就中止。
        (modpath / "system/fonts/Any-Name.ttf").unlink()
        result = sh([str(harness)], env)
        assert result.returncode != 0 and "ABORT" in result.stderr, result


# ---------------------------------------------------------------- 仓库自身的数据与常量

@check
def repo_constants():
    """不下载任何东西:默认来源、模块字段、真实 fonts.xml 的前置条件都在位。"""
    assert PRIMARY_URL.endswith("WenYuanRoundedSCVF.ttf") and BASE_URL.endswith(".zip")
    assert len(PRIMARY_SHA256) == len(BASE_SHA256) == 64
    assert PRIMARY_NAME.endswith(".ttf") and RENAME == "Selffont Rounded SC VF"
    prop = (ROOT / "module/module.prop").read_text()
    assert all(f"{key}=" in prop for key in MODULE_KEYS), prop
    # 版本号 = vYY.M.D.<总构建数>,versionCode = <总构建数>;两处的构建数必须一致(发布前抓错)。
    version, code = (re.search(rf"^{key}=(.+)$", prop, re.M) for key in ("version", "versionCode"))
    assert version and code, prop
    stamp = re.fullmatch(r"v\d{1,2}\.\d{1,2}\.\d{1,2}\.(\d+)", version.group(1))
    assert stamp, f"版本号应为 vYY.M.D.<总构建数>,实际 {version.group(1)!r}"
    assert code.group(1) == stamp.group(1), f"versionCode 与版本号里的构建数不一致:{version.group(1)} / {code.group(1)}"
    # configure_fonts 的前置条件:真实 fonts.xml 的默认家族必须正好是度量空壳。
    root = ET.fromstring((ROOT / "fonts.xml").read_bytes())
    assert {node.text.strip() for node in root.find("family[@name='sans-serif']").findall("font")} == {CARRIER}
    # 真实模板引用的字体名与基础包目录约定一致。
    assert all(not name.startswith("/") and ".." not in name
               for name in {node.text.strip() for node in root.iter("font")})


def run_checks() -> None:
    failed = 0
    for fn in CHECKS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as error:  # noqa: BLE001
            failed += 1
            traceback.print_exc()
            print(f"FAIL {fn.__name__}: {error}")
    if failed:
        print(f"{failed} 个检查失败")
        sys.exit(1)
    print(f"{len(CHECKS)} 项全部通过")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="跑内建自检:不下载、不打包")
    parser.add_argument("--base", help="基础包 ZIP:本地路径或 URL(默认下载并缓存)")
    parser.add_argument("--font", metavar="PATH|URL", help="主字体:本地文件或 URL(默认用内置来源)")
    parser.add_argument("--output", type=Path, default=ROOT / "build/Selffont.zip")
    parser.add_argument("--build", help="总构建数:盖戳进 module.prop(默认读 $SELFFONT_BUILD,没有就不盖)")
    args = parser.parse_args()
    if args.check:
        run_checks()
    else:
        build(base=args.base, font=args.font, output=args.output, build_num=args.build)


if __name__ == "__main__":
    main()
