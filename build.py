#!/usr/bin/env python3
"""Selffont 打包器：一个主字体 + 基础包 → KernelSU 模块 zip;--check 跑内建自检。

  pip install -r requirements.txt
  python3 build.py --check                       # 自检：无框架，assert 直跑，不下载不打包
  python3 build.py [--font X.ttf] [--base Y.zip] [--output O.zip]
                   [--build 总序号] [--day 当日序号] [--date YY.M.D] [--query-github]

版本号按全局规范的五段格式：yy.m.d.当日序号。总序号（展示不含 v），versionCode = 总序号。
日期与两个序号在仓库唯一构建工作流 Build Selffont 一处算定（--query-github 现场查运行历史，
不写死现值）；本地也可以手工传入。取不到当日序号时退化写四段 yy.m.d.总序号 并警告。

自由化：--font/--base 都收本地文件或 URL，没有平台闸门；家族名、可变轴、行度量
全部现场从字体里读。主字体必须是含 wght 轴的可变字体——配置只出新语法（supportedAxes），
静态字体没有该轴，直接拒绝，不做逐档展开的降级。

对主字体的安装副本只做三件事（都属 OFL 意义上的修改，所以安装副本整体改名）：
1. 竖直行度量对齐基础包里的 Roboto 空壳——真机验证过的角标偏低/切下沿修复；
2. 剪除映射到空白字形的码位——上游声称覆盖但字形空白，会吞掉回退链；
3. 内部家族名改成 RENAME——保留名合规（文渊的 OFL 保留 'WenYuan'/'文渊'）。
轮廓、cmap 归属、可变轴有构建期守卫，动一个字节就报错。

另外附带几枚「别名字件」（只有家族名、没有字形的极小字体，见 ALIAS_FAMILIES）：Gecko 只认
字件内部家族名，系统 fonts.xml 里的别名它看不见，网页按名调用会落到平台默认字体；有了同名
字件，Gecko 命中它、逐字回退再按模块名单落到文渊.--no-alias-fonts 可关掉。
"""
import argparse
import hashlib
import io
import json
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

# ---------------------------------------------------------------- 默认来源（哈希只是提示）
PRIMARY_URL = "https://github.com/takushun-wu/WenYuanFonts/releases/download/v1.010/WenYuanRoundedSCVF.ttf"
PRIMARY_SHA256 = "e9ebde68d6d45ad5998765505677d1fb95821318fc693982f873e73fc27a2122"
PRIMARY_NAME = "Selffont-WenYuanRoundedSCVF.ttf"  # 默认源的安装名
RENAME = "Selffont Rounded SC VF"                 # 安装副本内部家族名（OFL 保留名合规）
BASE_URL = "https://github.com/Numbersf/MakeFontsGreatAgain/releases/download/1717180003/MFGA-SELFUSE-17.0.1.08-31-alpha2.1717180003.zip"
BASE_SHA256 = "620789eab7a6e47b96cfb333bb50f44ee526abe1e2ab2f572e54c30b16a3649b"

# ---------------------------------------------------------------- 配置数据
CARRIER = "Roboto-Regular.ttf"  # 输入 fonts.xml 的默认家族必须保留的度量空壳
PRIMARY_FAMILIES = {"sans-serif", "sans-serif-condensed", "serif", "monospace",
                    "serif-monospace", "casual", "cursive", "sans-serif-smallcaps"}
METRIC_FAMILIES = {"sans-serif", "sans-serif-condensed"}
OLD_PRIMARY = {f"{weight}.ttf" for weight in range(100, 1000, 100)}  # 输入配置里的旧数字主字体
WEIGHTS = range(100, 1000, 100)
BLANK_CATEGORIES = {"Cc", "Cf", "Zs", "Zl", "Zp"}  # 合法空白字符的码位类别（空格类、控制类）
MODULE_KEYS = ("id", "name", "version", "versionCode", "author", "description")
CLOCK = timezone(timedelta(hours=8))  # 版本号里的日期按 UTC+8（否则 CI 在 UTC 下会差一天）
FONT_SUFFIXES = (".ttf", ".otf", ".ttc")
WORKFLOW = "build.yml"  # 版本取数的计数对象：仓库唯一构建工作流
DEV_VERSION = "dev"     # 仓库里的非发行默认：没盖戳就不假装有正式序号
VERSION_RE = re.compile(r"^(?P<date>\d{1,2}\.\d{1,2}\.\d{1,2})\.(?:(?P<day>\d+)\.)?(?P<build>\d+)$")

# Gecko 的名字清单只收字件内部家族名，fonts.xml 别名永远进不去。这几个别名在设备上没有
# 同名真实字件，网页按名调用（带引号的 "cursive" / "sans-serif-smallcaps" 等）会落到平台
# 默认字体；主字体 48.7MB 复制四份不值，于是给每个别名发一枚只有名字、没有字形的极小字件：
# Gecko 命中它 → 该字件画不出字 → 逐字回退按模块名单落到文渊。
# sans-serif / serif / monospace 不发：设备上有真实同名家族，泛型路径已由 pref 前置文渊。
ALIAS_FAMILIES = ("cursive", "fantasy", "casual", "serif-monospace",
                  "sans-serif-smallcaps", "sans-serif-condensed")
ALIAS_PREFIX = "Selffont-Alias-"

# 网页自带字体开关：模板默认压掉（全系统同一副面孔）；--keep-web-fonts 放开（图标字体等要它）。
# 表示法与 module/web-fonts.sh 完全一致：生效 = pref 行原样，放行 = 该行加 Selffont:keep 标记注释。
WEB_FONT_PREF = "browser.display.use_document_fonts: 0"
WEB_FONT_ACTIVE = f"  {WEB_FONT_PREF}"
WEB_FONT_KEPT = f"  # Selffont:keep {WEB_FONT_PREF}"


def apply_web_font_switch(config: str, keep: bool) -> str:
    """把配置置成目标状态（幂等）：keep 注释掉 pref 行（放行），否则还原（压掉）；找不到那一行就报错。"""
    wanted, other = (WEB_FONT_KEPT, WEB_FONT_ACTIVE) if keep else (WEB_FONT_ACTIVE, WEB_FONT_KEPT)
    if re.search(rf"^{re.escape(wanted)}$", config, re.M):
        return config
    if not re.search(rf"^{re.escape(other)}$", config, re.M):
        raise ValueError(f"模板里找不到网页字体开关行（{WEB_FONT_PREF}）：请检查 module/geckoview-config.yaml")
    return re.sub(rf"^{re.escape(other)}$", wanted, config, count=1, flags=re.M)


def warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


# ---------------------------------------------------------------- 来源（自由）

def fetch(url: str, destination: Path, expected: str | None = None) -> Path:
    """下载到 destination（已存在就复用）；expected 是默认源哈希，漂移只警告不拦截。"""
    if destination.exists():
        print(f"[缓存] {destination}")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        print(f"[下载] {url}")
        request = urllib.request.Request(url, headers={"User-Agent": "Selffont-builder"})
        with urllib.request.urlopen(request, timeout=300) as response, destination.open("wb") as out:
            shutil.copyfileobj(response, out, 1 << 20)
    if expected and digest(destination) != expected:
        warn(f"默认源内容已变：期望 sha256 {expected[:12]}…，实际 {digest(destination)[:12]}…。继续构建。")
    return destination


def source(spec: str | None, default_url: str, default_sha: str, destination: Path) -> Path:
    """来源自由：None 用默认 URL（带哈希提示），本地路径原样，URL 下载到缓存。"""
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
    """家族名与可变轴——全部现场读取，读到什么用什么。"""
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
    """一组字符的墨迹竖直包络 （min, max）；一个字形都没有时 None。"""
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
    """度量空壳：必须没有可见字形，否则它会把主字体的渲染抢走。"""
    try:
        with TTFont(io.BytesIO(data), lazy=True) as font:
            cmap = font.getBestCmap() or {}
            if any(glyph != ".notdef" and unicodedata.category(chr(codepoint)) not in BLANK_CATEGORIES
                   for codepoint, glyph in cmap.items()):
                return None
            return layout_metrics(font)
    except Exception:  # 不是字体、或结构损坏：按“没有空壳”处理，由调用方降级
        return None


def weight_ladder(axes: dict) -> list[dict]:
    """字重阶梯：走 wght/ital 轴（越界只出范围内的档，不拒绝）。

    没有 wght 轴（静态字体）直接拒绝：配置只出新语法 supportedAxes，静态字体没有可声明的轴，
    逐档展开属于已删除的降级路径。
    """
    if "wght" not in axes:
        raise ValueError("主字体没有 wght 轴：配置只出 supportedAxes 新语法，静态字体不再支持")
    low, _, high = axes["wght"]
    weights = [weight for weight in WEIGHTS if low <= weight <= high] or [min(max(400, low), high)]
    ital = axes.get("ital")
    styles = [False, True] if ital and ital[0] <= 1 <= ital[2] else [False]
    return [{"weight": weight, "italic": italic,
             "axes": ([("wght", weight)] if "wght" in axes else []) + ([("ital", 1)] if italic else [])}
            for italic in styles for weight in weights]


# ---------------------------------------------------------------- 安装副本的三处修改

def normalize_metrics(data: bytes, carrier: dict) -> bytes:
    """竖直行度量对齐 Roboto 空壳：根治角标数字偏低/切下沿（真机验证）。"""
    font = TTFont(io.BytesIO(data), recalcBBoxes=False, recalcTimestamp=False)
    head, hhea, os2 = font["head"], font["hhea"], font["OS/2"]
    upm, carrier_upm = head.unitsPerEm, carrier["unitsPerEm"]
    ascender, descender, line_gap = (round(value * upm / carrier_upm) for value in carrier["hhea"])
    if ascender <= 0 or descender >= 0:
        raise ValueError("空壳行度量不是合法的 ascent/descent")
    ink = ink_bounds(font, "0123456789")
    if ink is None:
        raise ValueError("主字体没有数字字形，无法验证归一后的行框")
    if ink[1] > ascender or ink[0] < descender:
        raise ValueError(f"归一后的行框会切数字墨迹：ink={list(ink)} box=[{descender},{ascender}]")
    hhea.ascent, hhea.descent, hhea.lineGap = ascender, descender, line_gap
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = ascender, descender, line_gap
    if carrier["useTypoMetrics"]:
        os2.version = max(os2.version, 4)
        os2.fsSelection |= 0x80
    else:
        os2.fsSelection &= ~0x80
    os2.usWinAscent = max(ascender, head.yMax, ink[1])   # 裁剪包络跟着真实墨迹，只动行度量
    os2.usWinDescent = max(-descender, -head.yMin, -ink[0])
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def glyph_signature(data: bytes) -> dict:
    """归一化不得改动的全部内容：轮廓、cmap 归属、家族名、可变轴。"""
    with TTFont(io.BytesIO(data), recalcBBoxes=False, recalcTimestamp=False) as font:
        if "glyf" in font:
            glyf = font["glyf"]
            outlines = {name: glyf[name].compile(glyf) for name in font.getGlyphOrder()}
        else:  # CFF：画笔重放（只比默认实例轮廓）
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
    """剪除映射到空白字形的码位（非空白类码位）：字形缺失却声称覆盖，会吞掉回退。

    空白类码位是合法空白，保留；字形一律不删，只剪映射。
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
            except Exception:  # 画不出来的字形不是空壳，不动它
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
    """OFL 保留名合规：修改过的安装副本整体改名（legacy/typographic 双模型都写）。"""
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

def supported_axes(ladder: list[dict]) -> str | None:
    """可变字体的 supportedAxes 值（Android 15+ 只认 wght / wght,ital）；静态字体返回 None。

    带这个属性的字件由系统在运行时按请求的字重/斜体现场实例化——一条顶掉整条静态阶梯。
    """
    tags = {tag for entry in ladder for tag, _ in entry["axes"]}
    if tags == {"wght", "ital"}:
        return "wght,ital"
    return "wght" if tags == {"wght"} else None


def replace_fonts(family: ET.Element, font_name: str, ladder: list[dict]) -> None:
    """一条 supportedAxes 字件顶掉整条阶梯（新语法，weight/style 可省）；没有可声明的轴就拒绝。"""
    for child in list(family):
        if child.tag == "font":
            family.remove(child)
    axes = supported_axes(ladder)
    if not axes:
        raise ValueError("主字体没有 wght/ital 轴：配置只出 supportedAxes，不退回逐档展开")
    node = ET.SubElement(family, "font", supportedAxes=axes)
    node.text = font_name


def configure_fonts(template: bytes, font_name: str, ladder: list[dict]) -> bytes:
    """主字体接管全部主家族；空壳留在度量家族；旧数字主字体整体替换；匿名字形回退紧随默认家族。

    输出统一是新语法（supportedAxes,Android 15+ 运行时实例化）：安装脚本只投放 font_fallback*.xml,
    库存 fonts.xml 不再替换，所以没有 legacy 展开的第二份。
    """
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
            continue  # 度量家族保留空壳：主字体走匿名回退，这里只提供行度量
        elif name in PRIMARY_FAMILIES or files & OLD_PRIMARY:
            replace_fonts(family, font_name, ladder)
    fallback = ET.Element("family")
    replace_fonts(fallback, font_name, ladder)
    root.insert(list(root).index(default) + 1, fallback)
    # 输出文件的根节点只能是不带属性的 <familyset>（AOSP font_fallback.xml 头注：
    # 「No attributes are allowed to familyset node」，官方生成器也不写任何属性）；
    # 模板从 fonts.xml 带来的 version 属性在这里去掉——带属性可能整份配置被拒。
    root.attrib.pop("version", None)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------- 版本盖戳

def default_output(prop: str) -> Path:
    """产物名跟版本走：Selffont-<版本>.zip（规范 <项目名>-<版本>）；非发行默认留在 build/Selffont.zip。"""
    stamped = re.search(r"^version=(.+)$", prop, flags=re.M)
    core = stamped.group(1) if stamped and VERSION_RE.fullmatch(stamped.group(1)) else None
    return ROOT / "build" / (f"Selffont-{core}.zip" if core else "Selffont.zip")


def version_core(date: str, day: str | None, build: str) -> str:
    """五段版本号核心：yy.m.d.当日序号。总序号；取不到当日序号时退化成四段 yy.m.d.总序号。"""
    return f"{date}.{day}.{build}" if day else f"{date}.{build}"


def check_number(value: str, label: str, minimum: int = 0) -> str:
    if not value.isdigit() or int(value) < minimum:
        raise ValueError(f"{label}必须是 ≥{minimum} 的十进制整数，收到 {value!r}")
    return value


def check_date(value: str) -> str:
    if not re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{1,2}", value):
        raise ValueError(f"日期必须是 YY.M.D（m/d 不补零），收到 {value!r}")
    return value


def stamp_version(prop: str, build: str | None, day: str | None = None,
                  date: str | None = None, now: datetime | None = None) -> str:
    """盖戳：version = yy.m.d.当日序号。总序号（展示不含 v），versionCode = 总序号（KSU 靠它比新旧）。

    没有总序号（本地直接打包且不指定）就原样返回——仓库里的 module.prop 是非发行默认，不猜数。
    没有当日序号就退化写四段 yy.m.d.总序号（规范允许，文档写明原因）；没有日期取当天 UTC+8.
    """
    if not build:
        return prop
    check_number(build, "总序号", 1)
    if day:
        check_number(day, "当日序号", 1)
    if not date:
        moment = now or datetime.now(CLOCK)
        date = f"{moment.year % 100}.{moment.month}.{moment.day}"
    check_date(date)
    prop = re.sub(r"^version=.*$", f"version={version_core(date, day, build)}", prop, flags=re.M)
    return re.sub(r"^versionCode=.*$", f"versionCode={build}", prop, flags=re.M)


def day_start(moment: datetime) -> datetime:
    """当天（Asia/Shanghai）零点，换算成 UTC，用来和 API 的 created_at 比。"""
    return moment.astimezone(CLOCK).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def count_day_runs(runs: list[dict], start: datetime) -> int:
    """当日序号：当天（Asia/Shanghai）push / workflow_dispatch 触发的运行数；PR 检查不计入。"""
    return sum(1 for run in runs
               if run.get("event") in ("push", "workflow_dispatch")
               and datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")) >= start)


def pick_total(runs: list[dict]) -> str:
    """总序号：该工作流最近一次运行的 run_number（单调递增的仓库既有计数）。"""
    if not runs:
        raise RuntimeError("该工作流没有任何运行，取不到总序号")
    return str(max(int(run["run_number"]) for run in runs))


def gh_api(path: str, jq: str) -> list[dict]:
    """调 gh api（继承当前凭据），按 jq 逐行出 JSON；失败就把原因原样抛出来，不静默编数。"""
    result = subprocess.run(["gh", "api", "--jq", jq, path], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"gh api 退出码 {result.returncode}")
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def github_version_numbers(workflow: str = WORKFLOW, now: datetime | None = None) -> tuple[str, str, str]:
    """从仓库唯一构建工作流的运行历史取数（现场查，不写死现值）：返回 （日期， 当日序号， 总序号）。

    按时间倒序翻页，翻到早于当天（Asia/Shanghai）零点的运行就停；日期也在这里一次取定。
    """
    moment = now or datetime.now(CLOCK)
    start = day_start(moment)
    runs, page = [], 1
    while page <= 10:  # 兜底上限：一天之内不可能翻 1000 条还没跨过当天零点
        batch = gh_api(f"repos/{{owner}}/{{repo}}/actions/workflows/{workflow}"
                       f"/runs?per_page=100&page={page}", ".workflow_runs[]")
        if not batch:
            break
        runs += batch
        if datetime.fromisoformat(batch[-1]["created_at"].replace("Z", "+00:00")) < start:
            break
        page += 1
    return (f"{moment.year % 100}.{moment.month}.{moment.day}",
            str(count_day_runs(runs, start)), pick_total(runs))


# ---------------------------------------------------------------- 火狐别名字件

def alias_font(family: str) -> bytes:
    """只有名字、没有字形的极小字体（.notdef/空格）：给 Gecko 一个能命中的家族名。"""
    builder = FontBuilder(1000, isTTF=True)
    order = [".notdef", "space"]
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({32: "space"})
    builder.setupGlyf({name: TTGlyphPen(None).glyph() for name in order})
    builder.setupHorizontalMetrics(dict.fromkeys(order, (500, 0)))
    builder.setupHorizontalHeader(ascent=930, descent=-250)
    builder.setupNameTable({"familyName": family, "styleName": "Regular", "uniqueFontIdentifier": family,
                            "fullName": family, "psName": family.replace(" ", "-")})
    builder.setupOS2(sTypoAscender=930, sTypoDescender=-250, usWinAscent=930, usWinDescent=250, usWeightClass=400)
    builder.setupPost()
    out = io.BytesIO()
    builder.save(out)
    return out.getvalue()


def alias_members(families=ALIAS_FAMILIES) -> dict[str, bytes]:
    """别名字件在包内的文件名 → 字体数据（不写进 fonts.xml:Minikin 不读目录，Gecko 读得到目录）。"""
    return {f"system/fonts/{ALIAS_PREFIX}{family}.ttf": alias_font(family) for family in families}


# ---------------------------------------------------------------- 基础包（只取字体资源）

def font_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members, seen = [], set()
    for entry in archive.infolist():
        path = PurePosixPath(entry.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in entry.filename:
            raise ValueError(f"基础包含不安全路径：{entry.filename}")
        if entry.filename in seen:
            raise ValueError(f"基础包含重复成员：{entry.filename}")
        seen.add(entry.filename)
        if path.parent != PurePosixPath("system/fonts") or path.suffix.lower() not in FONT_SUFFIXES:
            continue
        if stat.S_ISLNK(entry.external_attr >> 16):
            raise ValueError("基础包字体不允许符号链接")
        members.append(entry)
    return members


# ---------------------------------------------------------------- 组装

def build(base: str | None = None, font: str | None = None, output: Path | None = None,
          build_num: str | None = None, day: str | None = None, date: str | None = None,
          query: bool = False, alias: bool = True, keep_web_fonts: bool = False) -> list[str]:
    """base/font 是本地路径或 URL（None 用默认源）；返回警告列表。"""
    cache = ROOT / "build/cache"
    build_num = build_num or os.environ.get("SELFFONT_BUILD") or None
    day = day or os.environ.get("SELFFONT_DAY") or None
    date = date or os.environ.get("SELFFONT_DATE") or None
    if query and not build_num:
        try:
            date, day, build_num = github_version_numbers()
        except Exception as error:  # noqa: BLE001  取不到数不编数：退化成非发行版本并警告
            warn(f"版本取数失败，本次不打正式序号：{error}")
    prop = stamp_version((ROOT / "module/module.prop").read_text(encoding="utf-8"),
                         build_num, day=day, date=date)
    if not build_num:
        warn(f"本次构建没有总序号，按非发行版本处理（module.prop 里仍是 {DEV_VERSION}）；"
             "正式打包请传 --build 或用 --query-github 取数。")
    elif date and not day:
        warn("没有当日序号，版本号退化成四段 yy.m.d.总序号（规范允许，README 写明原因）。")
    output = Path(output) if output else default_output(prop)
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
        warnings: list[str] = []
        if f"system/fonts/{CARRIER}" not in names:
            raise ValueError(f"基础包缺少 {CARRIER} 度量空壳：没有它就不做归一，直接拒绝打包")
        carrier = carrier_metrics(archive.read(f"system/fonts/{CARRIER}"))
        if carrier is None:
            raise ValueError(f"{CARRIER} 不是可用的度量空壳（含可见字形或结构损坏），拒绝打包")
        packaged = normalize_metrics(primary, carrier)
        assert_glyphs_preserved(primary, packaged)   # 改名前先验证只动了行度量
        packaged = rename_font(packaged, RENAME)
        packaged, pruned = prune_blank_mappings(packaged)
        if pruned:
            warnings.append(f"剪除空壳映射 {pruned} 个（上游声称覆盖但字形空白），这些字落到回退链。")

        # 只出新语法（Android 15+ 的 font_fallback.xml）；库存 fonts.xml 不再替换。
        xml = configure_fonts((ROOT / "fonts.xml").read_bytes(), name, ladder)
        referenced = {(node.text or "").strip() for node in ET.fromstring(xml).iter("font")}
        bundled = [member for member in members if PurePosixPath(member.filename).name in referenced]

        # 火狐 pref 尾链：火狐的逐字回退不读 fonts.xml，逐字兜底时全清单乱序扫描，选中的字体和系统
        # 不同（花体/生僻字符两副面孔）。把补充字库的内部家族名按 fonts.xml 顺序追加到每条名单末尾，
        # 让它和系统走同一条链。火狐只认字件内部名（优先 typographic），现场从基础包读取。
        member_by_file = {PurePosixPath(m.filename).name: m for m in members}
        families, done = [], set()
        for node in ET.fromstring(xml).iter("font"):
            fname = (node.text or "").strip()
            member = member_by_file.get(fname)
            if not member or fname in (name, CARRIER) or fname in OLD_PRIMARY or fname in done:
                continue  # 设备自带（读不到内部名）或主字体/空壳：前者交给系统，后者已是名单头部
            done.add(fname)
            try:
                with TTFont(io.BytesIO(archive.read(member)), lazy=True) as font:
                    family = font["name"].getDebugName(16) or font["name"].getDebugName(1)
            except Exception:  # 坏字件跳过，不影响构建
                continue
            if family and family not in families:
                families.append(family)
        config = (ROOT / "module/geckoview-config.yaml").read_text(encoding="utf-8")
        if families:
            tail = ", ".join(families)
            config = re.sub(r'^(  font\.name-list\.[^:]+: ")([^"]*)(")$',
                            lambda match: f"{match.group(1)}{match.group(2)}, {tail}{match.group(3)}",
                            config, flags=re.M)

        aliases = alias_members() if alias else {}
        config = apply_web_font_switch(config, keep_web_fonts)
        output.parent.mkdir(parents=True, exist_ok=True)
        write_module(output, archive, bundled, name, packaged, xml, prop, config, aliases)

    version = next(line.split("=", 1)[1] for line in prop.splitlines() if line.startswith("version="))
    print(f"构建完成：{output}  版本 {version}")
    print(f"  主字体 {face['family']!r} → {RENAME}（{name},{len(ladder)} 档）")
    print(f"  补充字库 {len(bundled)} 个，fonts.xml 其余引用由设备自带（Noto/OEM，不打包）")
    print(f"  火狐别名字件 {len(aliases)} 枚（{', '.join(ALIAS_FAMILIES)}）"
          if aliases else "  火狐别名字件已关闭（--no-alias-fonts）")
    print("  网页自带字体：放行（--keep-web-fonts）" if keep_web_fonts else "  网页自带字体：压成文渊")
    for message in warnings:
        warn(message)
    return warnings


def write_module(output: Path, archive: zipfile.ZipFile, bundled: list[zipfile.ZipInfo],
                 name: str, packaged: bytes, xml: bytes, prop: str, config: str,
                 aliases: dict[str, bytes] | None = None) -> None:
    """写模块 zip：被配置引用的基础包字体 + 主字体 + 别名字件 + 原生 KSU 模块布局。

    包内只有一份字体配置 font_fallback.xml（新语法）：安装脚本把它投放到系统里存在的
    font_fallback*.xml 上；库存 fonts.xml 不替换（没有该文件的设备不支持，安装直接失败）。
    """
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as destination:
        for member in bundled:
            destination.writestr(member.filename, archive.read(member))
        destination.writestr(f"system/fonts/{name}", packaged)
        for filename, data in (aliases or {}).items():  # 不进 fonts.xml：只给 Gecko 按名命中
            destination.writestr(filename, data)
        destination.writestr("font_fallback.xml", xml)
        destination.writestr("module.prop", prop)
        destination.writestr("geckoview-config.yaml", config)  # 静态模板 + 构建期尾链
        for path in sorted((ROOT / "module").rglob("*")):
            if path.is_file() and path.name not in ("module.prop", "geckoview-config.yaml"):
                destination.write(path, path.relative_to(ROOT / "module").as_posix())
        destination.write(ROOT / "LICENSES.md", "LICENSES.md")
        if "LICENSES.md" in archive.namelist():  # 基础包归属说明，只取文本不取代码
            destination.writestr("licenses/MFGA-base-LICENSES.md", archive.read("LICENSES.md"))
        for item in destination.infolist():  # 文件属性以中央目录为准，不能带上私有 umask
            item.create_system = 3
            item.external_attr = (stat.S_IFREG | (0o755 if item.filename.endswith(".sh") else 0o644)) << 16
    with zipfile.ZipFile(output) as final:
        if final.testzip():
            raise ValueError("输出 zip 损坏")


# ================================================================ 内建自检（--check）
# 无测试框架、无夹具模块，assert 直跑；python3 build.py --check 一把跑完。

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


# ---------------------------------------------------------------- 度量归一（真机验证的角标修复）

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
    # 会切数字墨迹的归一必须被拒：空壳 ascent 700 盖不住数字墨迹 744。
    try:
        normalize_metrics(make_font(), dict(carrier, hhea=[700, -100, 0]))
        raise AssertionError("切墨迹的归一未被拒绝")
    except ValueError:
        pass
    # 空壳判定：可见字形的 Roboto 不能当空壳。
    assert carrier_metrics(make_carrier(visible=True)) is None
    assert carrier_metrics(make_carrier())["hhea"] == [930, -250, 0]
    assert carrier_metrics(b"not a font") is None


# ---------------------------------------------------------------- 字重阶梯与 fonts.xml 生成

@check
def fonts_xml():
    ladder = weight_ladder({"wght": (100, 400, 900), "ital": (0, 0, 1)})
    assert len(ladder) == 18 and all(entry["axes"] for entry in ladder), "可变字体应出 9 档 × 2 风格带轴"
    assert [entry["weight"] for entry in ladder if not entry["italic"]] == list(WEIGHTS)
    # 轴范围窄：只出范围内的档，不拒绝。
    assert [entry["weight"] for entry in weight_ladder({"wght": (200, 400, 700)}) if not entry["italic"]] \
        == [200, 300, 400, 500, 600, 700]
    # 静态字体（没有 wght 轴）直接拒绝：配置只出 supportedAxes，不退回逐档展开。
    for axes in ({}, {"ital": (0, 0, 1)}):
        try:
            weight_ladder(axes)
            raise AssertionError(f"静态字体未被拒绝：{axes}")
        except ValueError:
            pass

    template = (ROOT / "fonts.xml").read_bytes()
    root = ET.fromstring(configure_fonts(template, "V.ttf", ladder))
    assert not root.attrib, "font_fallback.xml 根节点不该带属性（AOSP：No attributes are allowed）"
    assert re.search(r"<familyset>", configure_fonts(template, "V.ttf", ladder).decode()), \
        "根节点应是不带属性的裸 <familyset>"
    default = root.find("family[@name='sans-serif']")
    assert {node.text.strip() for node in default.findall("font")} == {CARRIER}, "默认家族应保留度量空壳"
    fallback = list(root)[list(root).index(default) + 1]
    assert fallback.get("name") is None, "匿名字形回退应紧随默认家族"
    assert [(n.text.strip(), n.get("supportedAxes")) for n in fallback.findall("font")] == \
        [("V.ttf", "wght,ital")], "匿名字形回退应是单条新语法字件"
    for family in root.findall("family"):
        for node in family.findall("font"):
            assert (node.text or "").strip() not in OLD_PRIMARY, "残留旧数字主字体"
            if (node.text or "").strip() == "V.ttf":
                assert node.get("supportedAxes") == "wght,ital" and not node.findall("axis"), \
                    "主字体一律新语法：带 supportedAxes、无 axis 子节点"
                assert node.get("weight") is None and node.get("style") is None, \
                    "带 supportedAxes 的字件不该再写 weight/style"
    # 小型大写家族也接管：留在清单里的 CarroisGothicSC 会被火狐按文件名解析到。
    for name in ("sans-serif-smallcaps", "cursive", "monospace"):
        nodes = root.findall(f"family[@name='{name}']")[0].findall("font")
        assert [(n.text.strip(), n.get("supportedAxes")) for n in nodes] == [("V.ttf", "wght,ital")], name
    # 注意：模板里空壳字件自带 supportedAxes（真机 dump 就是这么写的），断言只针对主字体节点。
    def carriers_of(document):
        return sorted((n.text.strip(), n.get("supportedAxes") or "", n.get("weight") or "", n.get("style") or "")
                      for n in document.iter("font") if (n.text or "").strip() == CARRIER)

    # 模板里有 11 处空壳引用，输出少 1 处：那处随「旧数字主字体的匿名家族」整族删除（既有行为）。
    # 不变量是「留下来的空壳条目一字不改」——改了就说明生成器动了别人的条目。
    assert set(carriers_of(root)) <= set(carriers_of(ET.fromstring(template))), "空壳条目被改写"
    # supportedAxes 只认 wght / wght,ital（AOSP 校验器枚举）；其余组合没有可声明的轴，直接拒绝。
    assert supported_axes(ladder) == "wght,ital"
    assert supported_axes([{"weight": 400, "italic": False, "axes": [("wght", 400)]}]) == "wght"
    assert supported_axes([{"weight": 400, "italic": False, "axes": [("ital", 1)]}]) is None
    try:
        replace_fonts(ET.Element("family"), "V.ttf", [{"weight": 400, "italic": False, "axes": [("ital", 1)]}])
        raise AssertionError("没有 wght/ital 可声明时未被拒绝")
    except ValueError:
        pass

    # 输入防线：默认家族不是 Roboto 空壳、或不是 familyset 的输入拒绝替换。
    foreign = template.replace(b'<family name="sans-serif">', b'<family name="elsewhere">', 1)
    for bad in (foreign, b"<not-familyset/>"):
        try:
            configure_fonts(bad, "V.ttf", ladder)
            raise AssertionError("非法模板未被拒绝")
        except ValueError:
            pass


# ---------------------------------------------------------------- 空壳映射剪除

@check
def blank_prune():
    """映射到空白字形的非空白码位被剪；空格这类合法空白保留；字形集合不动。"""
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
    assert set(TTFont(io.BytesIO(pruned)).getGlyphOrder()) == set(order), "只剪映射，不删字形"


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
        base_zip(base, {"Roboto-Regular.ttf": make_carrier(),
                        "NotoSansPro.otf": make_font(family="Noto Sans Pro"),  # 真字体：验尾链要读内部家族名
                        "DeadWeight.ttf": b"dead"})
        build(base=str(base), font=str(regular), output=output, build_num="9", day="2", date="26.9.30")

        with zipfile.ZipFile(output) as archive:
            members = set(archive.namelist())
            for expected in ("module.prop", "LICENSES.md", "customize.sh",
                             "firefox.sh", "web-fonts.sh", "action.sh", "geckoview-config.yaml",
                             "font_fallback.xml", "licenses/WenYuan-OFL.txt",
                             "system/fonts/P-Regular.ttf", "system/fonts/Roboto-Regular.ttf",
                             "system/fonts/NotoSansPro.otf", "licenses/MFGA-base-LICENSES.md",
                             *alias_members()):
                assert expected in members, f"缺成员 {expected}"
            for absent in ("report.json", "system/fonts/DeadWeight.ttf",
                           "fonts.xml", "font_fallback_cjkvf.xml"):
                assert absent not in members, f"不该有的成员 {absent}"
            installed_prop = archive.read("module.prop").decode()
            assert "version=26.9.30.2.9" in installed_prop and "\nversionCode=9\n" in installed_prop, installed_prop
            # 别名字件只在系统字体目录里给 Gecko 按名命中，不进 fonts.xml（Minikin 不读目录）。
            assert not any(ALIAS_PREFIX in name for name in
                           {node.text.strip() for node in ET.fromstring(archive.read("font_fallback.xml")).iter("font")})
            assert (archive.getinfo("customize.sh").external_attr >> 16) == stat.S_IFREG | 0o755
            assert (archive.getinfo("system/fonts/P-Regular.ttf").external_attr >> 16) == stat.S_IFREG | 0o644
            packaged = archive.read("system/fonts/P-Regular.ttf")
            xml = archive.read("font_fallback.xml").decode()
            config = archive.read("geckoview-config.yaml").decode()

        # 归一 + 改名之后：轮廓/cmap/轴不动，家族名换成 RENAME,hhea 对齐空壳。
        before, after = glyph_signature(make_font()), glyph_signature(packaged)
        assert before["outlines"] == after["outlines"] and before["cmap"] == after["cmap"], "轮廓或 cmap 被改了"
        assert before["axes"] == after["axes"] and after["family"] == RENAME
        assert TTFont(io.BytesIO(packaged))["hhea"].ascent == 930, "包内字体未归一"
        assert "P-Regular.ttf" in xml
        # 单一配置、单一写法：主字体一律「一条 supportedAxes 字件」，接管家族与旧版一致。
        def ours_by_family(document):
            root = ET.fromstring(document)
            return {family.get("name"): [n for n in family.findall("font")
                                         if (n.text or "").strip() == "P-Regular.ttf"]
                    for family in root.findall("family")}

        families = {name: nodes for name, nodes in ours_by_family(xml).items() if nodes}
        assert {"serif", "monospace", "sans-serif-smallcaps"} <= set(families), "接管家族少了"
        assert all(len(nodes) == 1 and nodes[0].get("supportedAxes") == "wght,ital"
                   and not nodes[0].findall("axis") and nodes[0].get("weight") is None
                   for nodes in families.values()), "应是一条 supportedAxes 字件"
        root = ET.fromstring(xml)
        assert {node.text.strip() for node in root.find("family[@name='sans-serif']").findall("font")} == {CARRIER}
        assert "P-Regular.ttf" in {node.text.strip() for node in root.iter("font")}
        # 尾链：补充字库内部家族名按 fonts.xml 顺序拼进每条名单，前置仍是文渊。
        assert ", Noto Sans Pro\"" in config, "尾链未拼进火狐配置"
        for line in config.splitlines():
            if line.strip().startswith("font.name-list."):
                assert line.split(":", 1)[1].strip().strip('"').startswith(RENAME + ","), line

        # 关掉别名字件时包里不该有；--keep-web-fonts 时那一行应带 Selffont:keep 标记。
        build(base=str(base), font=str(regular), output=output, build_num="9", day="2", date="26.9.30",
              alias=False, keep_web_fonts=True)
        with zipfile.ZipFile(output) as archive:
            assert not any(ALIAS_PREFIX in name for name in archive.namelist()), "别名字件未关闭"
            kept = archive.read("geckoview-config.yaml").decode()
            assert re.search(rf"^{re.escape(WEB_FONT_KEPT)}$", kept, re.M), "网页字体未放行"
            assert not re.search(rf"^{re.escape(WEB_FONT_ACTIVE)}$", kept, re.M), "放行后 pref 仍生效"
            for line in kept.splitlines():  # 放行后名单本身仍完整、仍前置文渊
                if line.strip().startswith("font.name-list."):
                    assert line.split(":", 1)[1].strip().strip('"').startswith(RENAME + ","), line
        unstamped = stamp_version((ROOT / "module/module.prop").read_text(), None)
        assert default_output(unstamped).name == "Selffont.zip"
        assert default_output(stamp_version(unstamped, "9", day="2", date="26.9.30")).name == "Selffont-26.9.30.2.9.zip"

        # 自由化：主字体按自己的文件名安装，不要求固定命名；非字体后缀明确报错。
        custom = fonts_dir / "Weird-Name.ttf"
        custom.write_bytes(make_font(family="Custom Face"))
        build(base=str(base), font=str(custom), output=output)
        with zipfile.ZipFile(output) as archive:
            assert "system/fonts/Weird-Name.ttf" in archive.namelist()
            assert "Weird-Name.ttf" in archive.read("font_fallback.xml").decode()
        try:
            build(base=str(base), font=str(fonts_dir / "x.woff2"), output=output)
            raise AssertionError("非字体后缀未被拒绝")
        except ValueError:
            pass

        # 没有空壳 / 空壳不可用 → 直接拒绝打包，不静默降级（不做冗余降级）。
        base_zip(base, {"SomeFont.ttf": b"supplemental"})
        for message in ("没有它就不做归一",):
            try:
                build(base=str(base), font=str(regular), output=output)
                raise AssertionError("缺空壳未被拒绝")
            except ValueError as error:
                assert message in str(error), error
        base_zip(base, {"Roboto-Regular.ttf": make_carrier(visible=True)})  # 可见字形的 Roboto 不是空壳
        try:
            build(base=str(base), font=str(regular), output=output)
            raise AssertionError("可见字形的空壳未被拒绝")
        except ValueError as error:
            assert "度量空壳" in str(error), error
        # 静态主字体（没有 wght 轴）同样直接拒绝：配置只出 supportedAxes。
        static_font = fonts_dir / "Static.ttf"
        static_font.write_bytes(make_font(axes=False))
        base_zip(base, {"Roboto-Regular.ttf": make_carrier()})
        try:
            build(base=str(base), font=str(static_font), output=output)
            raise AssertionError("静态主字体未被拒绝")
        except ValueError as error:
            assert "wght" in str(error), error

        # 信任边界：路径穿越 / 绝对路径 / 符号链接成员拒绝，输出不许覆盖输入。
        for bad in ("system/fonts/../../evil.ttf", "/abs.ttf"):
            bad_zip = tmp / "bad.zip"
            base_zip(bad_zip, {}, licenses=False)
            with zipfile.ZipFile(bad_zip, "a") as archive:
                archive.writestr(bad, b"x")
            try:
                build(base=str(bad_zip), font=str(regular), output=output)
                raise AssertionError(f"危险成员未拒绝：{bad}")
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
    """盖戳：五段 yy.m.d.当日序号。总序号，versionCode = 总序号；没给总序号就原样不动。"""
    prop = (ROOT / "module/module.prop").read_text()
    noon = datetime(2026, 9, 30, 12, 0, tzinfo=CLOCK)
    stamped = stamp_version(prop, "42", day="3", date="26.9.30", now=noon)
    assert "version=26.9.30.3.42" in stamped and "versionCode=42" in stamped, stamped
    assert "v26" not in stamped, "展示版本不该带 v"
    # 日期缺省取当天 UTC+8；当日序号缺省退化成四段（规范允许，README 写明原因）。
    assert "version=26.9.30.3.42" in stamp_version(prop, "42", day="3", now=noon)
    degraded = stamp_version(prop, "42", now=noon)
    assert "version=26.9.30.42" in degraded and "versionCode=42" in degraded, degraded
    assert VERSION_RE.fullmatch("26.9.30.42") and VERSION_RE.fullmatch("26.9.30.3.42")
    assert not VERSION_RE.fullmatch("26.9.30") and not VERSION_RE.fullmatch("26.9.30.3.42.7")
    assert stamp_version(prop, None) == prop and stamp_version(prop, "") == prop
    for bad in ("abc", "4 2", "9.", "0"):
        try:
            stamp_version(prop, bad)
            raise AssertionError(f"非法总序号未被拒绝：{bad!r}")
        except ValueError:
            pass
    for bad in ("0", "x"):
        try:
            stamp_version(prop, "42", day=bad)
            raise AssertionError(f"非法当日序号未被拒绝：{bad!r}")
        except ValueError:
            pass
    try:
        stamp_version(prop, "42", date="26.9")
        raise AssertionError("非法日期未被拒绝")
    except ValueError:
        pass


@check
def version_numbers():
    """取数口径：总序号 = 最近运行号；当日序号只算当天 push/手动触发，PR 不计入。"""
    start = day_start(datetime(2026, 10, 5, 9, 52, tzinfo=CLOCK))
    runs = [{"run_number": 46, "event": "push", "created_at": "2026-10-05T01:52:23Z"},
            {"run_number": 45, "event": "push", "created_at": "2026-10-05T01:52:02Z"},
            {"run_number": 44, "event": "pull_request", "created_at": "2026-10-05T00:10:00Z"},
            {"run_number": 43, "event": "push", "created_at": "2026-10-04T15:00:00Z"}]  # 前一天的 23:00 UTC+8
    assert count_day_runs(runs, start) == 2, count_day_runs(runs, start)
    assert pick_total(runs) == "46"
    assert day_start(datetime(2026, 10, 5, 0, 30, tzinfo=CLOCK)) == datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc)
    try:
        pick_total([])
        raise AssertionError("空运行列表应报错，不该编数")
    except RuntimeError:
        pass


@check
def alias_fonts():
    """别名字件：家族名就是别名、除空格外没有字形、体积极小；包内文件不写进 fonts.xml。"""
    data = alias_font("sans-serif-smallcaps")
    with TTFont(io.BytesIO(data)) as font:
        assert font["name"].getDebugName(1) == "sans-serif-smallcaps"
        cmap = font.getBestCmap() or {}
        assert set(cmap) <= {32}, f"别名字件不该有可见字形：{sorted(cmap)}"
    assert len(data) < 4096, f"别名字件过大：{len(data)} 字节"
    members = alias_members()
    assert len(members) == len(ALIAS_FAMILIES)
    for family in ALIAS_FAMILIES:
        assert f"system/fonts/{ALIAS_PREFIX}{family}.ttf" in members, family


# ---------------------------------------------------------------- 火狐（Gecko）接入

@check
def firefox_bridge():
    """火狐接入：首选项只前置不清空 + install/remove 行为（PATH 上的 am 用替身）。"""
    config = (ROOT / "module/geckoview-config.yaml").read_text(encoding="utf-8")
    assert config.startswith("prefs:\n") or "\nprefs:\n" in config, "Gecko 配置必须只有 prefs 段"
    lines = [line.strip() for line in config.splitlines() if line.strip().startswith("font.name-list.")]
    assert len(lines) >= 20, f"首选项太少：{len(lines)}"
    for line in lines:  # 只前置：每条都必须以本模块家族名开头，后面原样保留 Gecko 默认回退链
        value = line.split(":", 1)[1].strip().strip('"')
        assert value.startswith(RENAME + ","), f"未前置或家族名不符：{line}"

    # 泛型缺口修复：Gecko 在 Android 只有 cursive.x-unicode/x-western 默认、fantasy 一个都没有，
    # 其余语言组解析成空字体组落到平台默认。CJK 与西文的 cursive/fantasy 必须都在位。
    keys = {line.split(":", 1)[0].strip() for line in lines}
    for generic in ("cursive", "fantasy"):
        for lang in ("x-unicode", "x-western", "zh-CN", "zh-TW", "zh-HK", "ja", "ko"):
            assert f"font.name-list.{generic}.{lang}" in keys, f"{generic}.{lang} 缺失（空字体组）"
    # 花体 Unicode（𝓐𝓑𝓒）的语言组是 x-math:Gecko 默认名单是桌面数学字体，Android 全缺。
    for key in ("serif.x-math", "sans-serif.x-math", "monospace.x-math"):
        assert f"font.name-list.{key}" in keys, f"{key} 缺失（逐字回退乱选）"
    assert config.count('"') % 2 == 0, "引号不配对"
    # 网页自带 webfont 不读系统清单：默认压掉（激进设定）；--keep-web-fonts / 管理器按钮才放行。
    assert re.search(rf"^{re.escape(WEB_FONT_ACTIVE)}$", config, re.M), "文档字体未默认压掉"
    kept = apply_web_font_switch(config, True)
    assert re.search(rf"^{re.escape(WEB_FONT_KEPT)}$", kept, re.M), "--keep-web-fonts 未生效"
    assert not re.search(rf"^{re.escape(WEB_FONT_ACTIVE)}$", kept, re.M), "放行后 pref 仍生效"
    assert apply_web_font_switch(kept, True) == kept, "置 keep 不幂等"
    assert re.search(rf"^{re.escape(WEB_FONT_ACTIVE)}$", apply_web_font_switch(kept, False), re.M), "变不回压"
    assert apply_web_font_switch(config, False) == config, "默认路径不该改动配置"
    for template in ("prefs:\n  # 开关行丢了\n", config.replace(WEB_FONT_ACTIVE, "  # 丢了标记")):
        try:  # 开关行不在时必须报错，不许静默出一个没开关的包
            apply_web_font_switch(template, True)
            raise AssertionError("开关行缺失未被拒绝")
        except ValueError:
            pass

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
        (modpath / "font_fallback.xml").write_bytes(b"<familyset modern/>")
        (modpath / "system/fonts/Any-Name.ttf").write_bytes(b"font")
        system = tmp / "sysroot"
        for directory in ("system/etc", "system_ext/etc", "product/etc", "my_product/etc"):
            (system / directory).mkdir(parents=True)
            (system / directory / "fonts.xml").write_text("<familyset>stock-legacy</familyset>")
        (system / "system/etc/font_fallback.xml").write_text("<familyset>old-modern</familyset>")
        (system / "system/etc/font_fallback_cjkvf.xml").write_text("<familyset>old-cjkvf</familyset>")
        (system / "system/etc/fonts_customization.xml").write_text("<other-schema/>")
        # 厂商分区（ColorOS 系走 my_product）也有一份：只换 /system 那份，框架读的是没换的。
        (system / "my_product/etc/font_fallback.xml").write_text("<familyset>old-oem</familyset>")
        env = {**os.environ, "MODPATH": str(modpath), "SELFFONT_SYSTEM_ROOT": str(system)}
        harness = modpath / "harness.sh"
        harness.write_text('ui_print() { echo "$@"; }\n'
                           'abort() { echo "ABORT: $*" >&2; exit 1; }\n'
                           f'. "{modpath / "customize.sh"}"\n')

        result = sh([str(harness)], env)
        assert result.returncode == 0, result.stderr
        # 只投放 font_fallback*.xml（新语法），且覆盖所有装着它的分区；
        # 库存 fonts.xml 与 fonts_customization.xml 都不碰。
        for relative in ("system/etc/font_fallback.xml", "system/etc/font_fallback_cjkvf.xml",
                         "my_product/etc/font_fallback.xml"):
            target = modpath / relative
            assert target.read_text() == "<familyset modern/>", f"{relative} 应放新语法"
        for directory in ("system/etc", "system_ext/etc", "product/etc", "my_product/etc"):
            assert not (modpath / directory / "fonts.xml").exists(), \
                f"{directory} 的库存 fonts.xml 不该被替换"
        assert not (modpath / "system/etc/fonts_customization.xml").exists(), "自选配置不该被碰"
        assert "已替换 3 份 font_fallback 配置" in result.stdout, "应报告替换数量：" + result.stdout

        # 设备没有 font_fallback*.xml（Android 15 以下）→ 中止安装，不假装成功。
        (system / "system/etc/font_fallback.xml").unlink()
        (system / "system/etc/font_fallback_cjkvf.xml").unlink()
        (system / "my_product/etc/font_fallback.xml").unlink()
        result = sh([str(harness)], env)
        assert result.returncode != 0 and "没有 font_fallback" in result.stderr, result
        system.joinpath("system/etc/font_fallback.xml").write_text("<familyset>old-modern</familyset>")
        system.joinpath("system/etc/font_fallback_cjkvf.xml").write_text("<familyset>old-cjkvf</familyset>")
        system.joinpath("my_product/etc/font_fallback.xml").write_text("<familyset>old-oem</familyset>")

        # 没有字体文件（= 直接压缩了仓库）就中止。
        (modpath / "system/fonts/Any-Name.ttf").unlink()
        result = sh([str(harness)], env)
        assert result.returncode != 0 and "ABORT" in result.stderr, result

        # 模块更新刷新火狐配置拷贝：未接入（文件不在）不碰；已接入（文件在）换新。
        (modpath / "system/fonts/Any-Name.ttf").write_bytes(b"font")
        bridge_dir = tmp / "bridge"
        bridge_dir.mkdir()
        env = {**env, "FIREFOX_DATA_DIR": str(bridge_dir)}
        result = sh([str(harness)], env)
        assert result.returncode == 0 and "已刷新火狐配置" not in result.stdout, "未接入不该刷新"
        bridge = bridge_dir / "org.mozilla.firefox-geckoview-config.yaml"
        bridge.write_text("stale\n")
        result = sh([str(harness)], env)
        assert result.returncode == 0 and "已刷新火狐配置" in result.stdout, result.stdout
        refreshed = bridge.read_text(encoding="utf-8")
        assert refreshed != "stale\n" and "font.name-list" in refreshed, "配置没换成新版"

        # 管理器按钮 / web-fonts.sh：状态文件记选择、副本立刻刷新、更新时不被覆盖。
        web, action = modpath / "web-fonts.sh", modpath / "action.sh"
        for script in (web, action):
            assert sh(["-n", str(script)], os.environ).returncode == 0, f"{script.name} 语法错误"
        state = bridge_dir / "selffont-web-fonts.state"
        assert sh([str(web), "status"], env).stdout.strip().startswith("网页自带字体 = 压成文渊")
        assert sh([str(web), "wat"], env).returncode == 2, "未知参数应报用法错"
        result = sh([str(web), "keep"], env)
        assert result.returncode == 0 and state.read_text().strip() == "keep", result
        assert re.search(rf"^{re.escape(WEB_FONT_KEPT)}$", bridge.read_text(encoding="utf-8"), re.M), \
            "keep 没写进配置副本"
        assert sh([str(web), "keep"], env).returncode == 0 and \
            state.read_text().strip() == "keep", "keep 不幂等"
        result = sh([str(action)], env)  # 管理器按钮 = toggle：keep → block
        assert result.returncode == 0 and state.read_text().strip() == "block", result
        assert re.search(rf"^{re.escape(WEB_FONT_ACTIVE)}$", bridge.read_text(encoding="utf-8"), re.M), \
            "toggle 没变回压"
        # 模块更新（customize.sh）刷新副本时按状态走：先在管理器里选 keep，再跑一次安装脚本。
        assert sh([str(action)], env).returncode == 0 and state.read_text().strip() == "keep"
        result = sh([str(harness)], env)
        assert result.returncode == 0 and "保留网页字体开关状态" in result.stdout, result.stdout
        assert re.search(rf"^{re.escape(WEB_FONT_KEPT)}$", bridge.read_text(encoding="utf-8"), re.M), \
            "模块更新把网页字体开关覆盖了"
        # 重新接入（firefox.sh install）同样按状态生成，不退回模板默认。
        assert sh([str(ROOT / "module/firefox.sh")], {**env, "PATH": os.environ["PATH"]}).returncode == 0
        assert re.search(rf"^{re.escape(WEB_FONT_KEPT)}$", bridge.read_text(encoding="utf-8"), re.M), \
            "重新接入把开关覆盖了"
        # 开关行缺失的模板必须报错，不许静默放行（把脚本放到坏模板旁边跑，MODPATH 才指向它）。
        broken = tmp / "broken"
        broken.mkdir()
        (broken / "geckoview-config.yaml").write_text("prefs:\n  # 没有开关行\n")
        shutil.copy(web, broken / "web-fonts.sh")
        result = sh([str(broken / "web-fonts.sh"), "keep"], {**env, "FIREFOX_DATA_DIR": str(broken)})
        assert result.returncode != 0 and "找不到网页字体开关行" in result.stderr, result
        (modpath / "harness.sh").unlink()


# ---------------------------------------------------------------- 仓库自身的数据与常量

@check
def repo_constants():
    """不下载任何东西：默认来源、模块字段、真实 fonts.xml 的前置条件都在位。"""
    assert PRIMARY_URL.endswith("WenYuanRoundedSCVF.ttf") and BASE_URL.endswith(".zip")
    assert len(PRIMARY_SHA256) == len(BASE_SHA256) == 64
    assert PRIMARY_NAME.endswith(".ttf") and RENAME == "Selffont Rounded SC VF"
    prop = (ROOT / "module/module.prop").read_text()
    assert all(f"{key}=" in prop for key in MODULE_KEYS), prop
    # 仓库里的 module.prop 是非发行默认（dev/0）：正式序号一律由盖戳写进去，不写死现值。
    version, code = (re.search(rf"^{key}=(.+)$", prop, re.M) for key in ("version", "versionCode"))
    assert version and code, prop
    assert version.group(1) == DEV_VERSION and code.group(1) == "0", \
        f"仓库默认应为非发行版本 {DEV_VERSION}/0，实际 {version.group(1)}/{code.group(1)}"
    # 盖戳结果必须符合规范五段格式，且 versionCode 与总序号一致。
    stamped = stamp_version(prop, "7", day="2", date="26.10.5")
    assert "version=26.10.5.2.7" in stamped and "\nversionCode=7\n" in stamped, stamped
    # configure_fonts 的前置条件：真实 fonts.xml 的默认家族必须正好是度量空壳。
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
    parser.add_argument("--check", action="store_true", help="跑内建自检：不下载、不打包")
    parser.add_argument("--base", help="基础包 ZIP：本地路径或 URL（默认下载并缓存）")
    parser.add_argument("--font", metavar="PATH|URL", help="主字体：本地文件或 URL（默认用内置来源）")
    parser.add_argument("--output", type=Path,
                        help="产物路径（默认跟版本走：build/Selffont-<版本>.zip，非发行版本用 build/Selffont.zip）")
    parser.add_argument("--build", help="总序号：盖戳进 module.prop（默认读 $SELFFONT_BUILD，没有就不盖）")
    parser.add_argument("--day", help="当日序号：五段版本号第四段（默认读 $SELFFONT_DAY，没有就退化成四段）")
    parser.add_argument("--date", help="版本日期 YY.M.D（默认读 $SELFFONT_DATE，没有取当天 UTC+8）")
    parser.add_argument("--query-github", action="store_true",
                        help="用 gh 现场查仓库唯一工作流的运行历史，取齐日期与两个序号（CI 用；失败只警告）")
    parser.add_argument("--no-alias-fonts", action="store_true", help="不打火狐别名字件")
    parser.add_argument("--keep-web-fonts", action="store_true",
                        help="放行网页自带字体（图标字体等）；默认压成文渊")
    args = parser.parse_args()
    if args.check:
        run_checks()
    else:
        build(base=args.base, font=args.font, output=args.output, build_num=args.build,
              day=args.day, date=args.date, query=args.query_github,
              alias=not args.no_alias_fonts, keep_web_fonts=args.keep_web_fonts)


if __name__ == "__main__":
    main()
