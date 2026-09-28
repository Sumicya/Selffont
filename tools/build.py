#!/usr/bin/env python3
"""Selffont 打包器:主字体 + 基础包 → 一个 KernelSU 模块 zip。

自由化:两个输入都接受任意本地文件或 URL(默认源是下面的常量),没有平台闸门;
家族名、字重、可变轴、行度量全部现场从字体里读,读到什么就用什么。

对主字体的安装副本只做三件事(都属 OFL 意义上的修改,所以安装副本整体改名):
1. 竖直行度量对齐基础包里的 Roboto 空壳——真机验证过的角标偏低/切下沿修复;
2. 剪除映射到空白字形的码位——上游声称覆盖但字形空白,会吞掉回退链;
3. 内部家族名改成 RENAME——保留名合规(文渊的 OFL 保留 'WenYuan'/'文渊')。
轮廓、cmap 归属、可变轴有构建期守卫,动一个字节就报错。
"""
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
from urllib.parse import urlparse

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]

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
MAX_DOWNLOAD = 512 * 1024 * 1024
FONT_SUFFIXES = (".ttf", ".otf", ".ttc")
# emoji 区段(U+2600 杂项符号 + U+1F000 起的主平面),用来量包内字体的 emoji 覆盖上限
EMOJI_RANGES = ((0x2600, 0x27BF), (0x1F000, 0x1FBFF))


def warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
        if destination.stat().st_size > MAX_DOWNLOAD:
            raise ValueError(f"下载超出上限 {MAX_DOWNLOAD // (1 << 20)} MiB:{url}")
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
    """家族名、声明字重、可变轴——全部现场读取。"""
    with TTFont(io.BytesIO(data), lazy=True) as font:
        return {"family": font["name"].getDebugName(1) or "",
                "weight": font["OS/2"].usWeightClass,
                "axes": font_axes(font)}


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


def emoji_ceiling(cmap: dict) -> int | None:
    """cmap 里 emoji 区段的最高码位;一个都没有就是 None。"""
    hits = [codepoint for codepoint in cmap
            if any(low <= codepoint <= high for low, high in EMOJI_RANGES)]
    return max(hits) if hits else None


def emoji_coverage(fonts: list[tuple[str, object]]) -> list[dict]:
    """(名字, 取字节的可调用对象) 逐个过 cmap,报告 emoji 覆盖上限,高的在前。

    只读 cmap 表,不碰字形;坏了就跳过,不影响构建。用途:火狐豆腐这类问题先看
    「包里到底有没有那个码位」,再谈 Gecko。给 firefox.sh 注入名单时也是这份数据。
    """
    rows = []
    for name, load in fonts:
        try:
            with TTFont(io.BytesIO(load()), lazy=True) as font:
                ceiling = emoji_ceiling(font.getBestCmap() or {})
        except Exception:  # 不是字体或结构损坏:跳过
            continue
        if ceiling:
            rows.append({"file": name, "highest": f"U+{ceiling:04X}"})
    return sorted(rows, key=lambda row: int(row["highest"][2:], 16), reverse=True)


def carrier_metrics(data: bytes) -> dict | None:
    """度量空壳:必须没有可见字形,否则它会把主字体的渲染抢走。"""
    try:
        with TTFont(io.BytesIO(data), lazy=True) as font:
            cmap = font.getBestCmap() or {}
            if any(glyph != ".notdef" and unicodedata.category(chr(codepoint)) not in BLANK_CATEGORIES
                   for codepoint, glyph in cmap.items()):
                return None
            return layout_metrics(font)
    except Exception:  # 不是字体、或结构损坏:按“没有空壳”处理,由调用方决定降级
        return None


def weight_ladder(faces: dict[str, dict]) -> list[dict]:
    """9 档 × 2 风格的阶梯。可变字体走 wght/ital 轴(越界夹取,不拒绝);静态按声明字重就近映射。"""
    if len(faces) == 1:
        name, face = next(iter(faces.items()))
        if face["axes"]:
            weights = list(WEIGHTS)
            if "wght" in face["axes"]:
                low, _, high = face["axes"]["wght"]
                weights = [weight for weight in WEIGHTS if low <= weight <= high] or [min(max(400, low), high)]

            def entry(weight: int, italic: bool) -> dict:
                axes = [("wght", weight)] if "wght" in face["axes"] else []
                if italic:
                    axes.append(("ital", 1))
                return {"weight": weight, "italic": italic, "file": name, "axes": axes}

            entries = [entry(weight, False) for weight in weights]
            ital = face["axes"].get("ital")
            if ital and ital[0] <= 1 <= ital[2]:
                entries += [entry(weight, True) for weight in weights]
            return entries
    # ponytail: 静态侧一个文件也能打包,只是粗体交给系统合成;升级:真要静态多字重就多传几个 --font。
    return [{"weight": weight, "italic": italic,
             "file": min(faces, key=lambda name: (abs(faces[name]["weight"] - weight), -faces[name]["weight"]))}
            for italic in (False, True) for weight in WEIGHTS]


# ---------------------------------------------------------------- 安装副本的三处修改

def normalize_metrics(data: bytes, carrier: dict) -> tuple[bytes, dict]:
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
    original = layout_metrics(font)
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
    return out.getvalue(), {"original": original, "normalized": layout_metrics(font), "digitInkY": list(ink)}


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

def replace_fonts(family: ET.Element, ladder: list[dict]) -> None:
    for child in list(family):
        if child.tag == "font":
            family.remove(child)
    for entry in ladder:
        node = ET.SubElement(family, "font", weight=str(entry["weight"]),
                             style="italic" if entry["italic"] else "normal")
        node.text = entry["file"]
        for tag, value in entry.get("axes", []):
            ET.SubElement(node, "axis", tag=tag, stylevalue=str(value))


def configure_fonts(template: bytes, ladder: list[dict], carrier: bool) -> bytes:
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
                replace_fonts(family, ladder)
        elif name in PRIMARY_FAMILIES or files & OLD_PRIMARY:
            replace_fonts(family, ladder)
    fallback = ET.Element("family")
    replace_fonts(fallback, ladder)
    root.insert(list(root).index(default) + 1, fallback)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


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

def build(base: str | None = None, font: list[str] | None = None,
          output: Path | None = None, revision: str | None = None) -> dict:
    """base/font 是本地路径或 URL(None 用默认源);返回并写出构建报告。"""
    cache = ROOT / "build/cache"
    output = Path(output) if output else ROOT / "build" / "Selffont.zip"
    warnings: list[str] = []

    base_path = source(base, BASE_URL, BASE_SHA256, cache / "base.zip")
    if output.resolve() == Path(base_path).resolve():
        raise ValueError("输出不能覆盖输入")

    primary: dict[str, bytes] = {}
    for spec in font or [PRIMARY_URL]:
        name = PRIMARY_NAME if font is None else basename(spec)
        if PurePosixPath(name).suffix.lower() not in FONT_SUFFIXES:
            raise ValueError(f"主字体必须是 {', '.join(FONT_SUFFIXES)}:{spec}")
        primary[name] = Path(source(spec, PRIMARY_URL, PRIMARY_SHA256, cache / name)).read_bytes()
    if len(primary) != len(font or [PRIMARY_URL]):
        raise ValueError(f"主字体安装名重复:{sorted(primary)}")
    faces = {name: font_face(data) for name, data in primary.items()}
    ladder = weight_ladder(faces)
    regular = next((name for name, face in faces.items() if face["weight"] == 400), next(iter(faces)))

    with zipfile.ZipFile(base_path) as archive:
        members = font_members(archive)
        names = {member.filename for member in members}
        carrier_name = f"system/fonts/{CARRIER}"
        carrier = carrier_metrics(archive.read(carrier_name)) if carrier_name in names else None
        if carrier is None:
            warnings.append(f"基础包没有可用的 {CARRIER} 度量空壳:跳过度量归一,角标/通知计数可能回退到修复前表现。")

        packaged: dict[str, bytes] = {}
        metrics: dict[str, dict] = {}
        for name, data in primary.items():
            if carrier:
                packaged[name], metrics[name] = normalize_metrics(data, carrier)
                assert_glyphs_preserved(data, packaged[name])   # 改名前先验证只动了行度量
            else:
                packaged[name] = data
            packaged[name] = rename_font(packaged[name], RENAME)
            packaged[name], pruned = prune_blank_mappings(packaged[name])
            if pruned:
                warnings.append(f"{name} 剪除空壳映射 {pruned} 个(上游声称覆盖但字形空白),这些字落到回退链。")

        xml = configure_fonts((ROOT / "fonts.xml").read_bytes(), ladder, carrier is not None)
        referenced = {(node.text or "").strip() for node in ET.fromstring(xml).iter("font")}
        bundled = [member for member in members if PurePosixPath(member.filename).name in referenced]
        dropped = sorted({PurePosixPath(m.filename).name for m in members} - {PurePosixPath(m.filename).name for m in bundled})
        unbundled = sorted(referenced - {PurePosixPath(m.filename).name for m in members}
                           - set(primary) - {CARRIER})
        if unbundled:
            warnings.append(f"fonts.xml 引用但基础包没有的字体(不打包):{'、'.join(unbundled)}")

        coverage = emoji_coverage(
            [(PurePosixPath(member.filename).name, lambda member=member: archive.read(member))
             for member in bundled]
            + [(name, lambda data=data: data) for name, data in packaged.items()])

        report = {
            "revision": revision or "UNSPECIFIED",
            "primary": {
                "family": faces[regular]["family"],   # 上游原家族名,读了才知道装的是谁
                "installedFamily": RENAME,
                "files": [{"name": name, "sha256": sha256(primary[name]), "normalizedSha256": sha256(packaged[name])}
                          for name in primary],
                "weightMap": {str(entry["weight"]): entry["file"] for entry in ladder if not entry["italic"]},
            },
            "metricNormalization": metrics,
            "metricCarrier": {"file": CARRIER, **carrier} if carrier else None,
            "baseArchiveSha256": digest(base_path),
            "bundledSupplementalFonts": sorted({PurePosixPath(m.filename).name for m in bundled}),
            "unreferencedFontsDropped": dropped,
            "emojiCoverage": coverage,
            "warnings": warnings,
        }

        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
            staged = Path(tmp) / output.name
            write_module(staged, archive, bundled, packaged, xml, report)
            staged.replace(output)

    print(f"\n构建完成:{output}")
    print(f"  主字体 {faces[regular]['family']!r}({len(primary)} 文件,{len(ladder)} 档)"
          f"  补充 {len(report['bundledSupplementalFonts'])} 个  丢弃 {len(dropped)} 个")
    if metrics:
        first = metrics[regular]
        print(f"  度量归一 hhea {first['original']['hhea']} → {first['normalized']['hhea']}(共 {len(metrics)} 文件)")
    else:
        print("  度量归一:跳过(无空壳)")
    if coverage:
        print(f"  emoji 覆盖上限:{coverage[0]['file']} {coverage[0]['highest']}"
              f"(共 {len(coverage)} 个字体有 emoji 段覆盖)")
    for message in warnings:
        warn(message)
    return report


def write_module(staged: Path, archive: zipfile.ZipFile, bundled: list[zipfile.ZipInfo],
                 packaged: dict[str, bytes], xml: bytes, report: dict) -> None:
    """写模块 zip:基础包里被 fonts.xml 引用的字体 + 主字体 + 原生模块布局。"""
    prop = (ROOT / "module/module.prop").read_text(encoding="utf-8")
    missing = [key for key in MODULE_KEYS if f"{key}=" not in prop]
    if missing:
        raise ValueError(f"module/module.prop 缺少字段:{missing}")
    with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as destination:
        for member in bundled:
            destination.writestr(member.filename, archive.read(member))
        for name, data in packaged.items():
            destination.writestr(f"system/fonts/{name}", data)
        destination.writestr("fonts.xml", xml)
        for path in sorted((ROOT / "module").rglob("*")):
            if path.is_file():
                destination.write(path, path.relative_to(ROOT / "module").as_posix())
        destination.write(ROOT / "LICENSES.md", "LICENSES.md")
        if "LICENSES.md" in archive.namelist():  # 基础包归属说明,只取文本不取代码
            destination.writestr("licenses/MFGA-base-LICENSES.md", archive.read("LICENSES.md"))
        destination.writestr("report.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        for item in destination.infolist():  # 文件属性以中央目录为准,不能带上私有 umask
            item.create_system = 3
            item.external_attr = (stat.S_IFREG | (0o755 if item.filename.endswith(".sh") else 0o644)) << 16
    with zipfile.ZipFile(staged) as final:
        if final.testzip():
            raise ValueError("输出 zip 损坏")
        for name, data in packaged.items():
            if sha256(final.read(f"system/fonts/{name}")) != sha256(data):
                raise ValueError(f"包内主字体与归一结果不一致:{name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="基础包 ZIP:本地路径或 URL(默认下载并缓存)")
    parser.add_argument("--font", action="append", metavar="PATH|URL",
                        help="主字体:本地文件或 URL,可重复;默认用内置来源")
    parser.add_argument("--output", type=Path, default=ROOT / "build/Selffont.zip")
    parser.add_argument("--revision", help="记入 report.json 的来源版本")
    build(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
