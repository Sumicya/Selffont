#!/usr/bin/env python3
"""Selffont 打包器：一个主字体 + 基础包 + 固定许可补充字体 → KernelSU 模块 zip;--check 跑内建自检。

  pip install -r requirements.txt
  python3 build.py --check                       # 自检：无框架，assert 直跑，不下载不打包
  python3 build.py [--font X.ttf] [--base Y.zip] [--output O.zip]
                   [--build 总序号] [--day 当日序号] [--date YY.M.D] [--query-ci]

版本号按全局规范：yy.m.d.当日序号.总序号（五段，展示不含 v），versionCode = 总序号。号源只有
一处：CI 运行数。总序号 = `build.yml` 本次运行的 `run_number` 原值，不做基线相减；当日序号
（当日 = `run_started_at` 转 UTC+8）用差值锚定法算：取当日现存 `build.yml` 运行的最小
`run_number`，与当日现存产物 `Selffont-yy.m.d.d0.r0` 反推出的 `r0 - d0 + 1`，两者取小作当日
首条运行号 `R_first`（都没有就取当前 `run_number`），当日序号 = 当前 `run_number - R_first + 1`。
失败运行同样占号，`pull_request` 运行永不计入。`--query-ci` 用 `gh api` 现场读数并打印 head
SHA、run_id、run_number、R_first、当日序号与最终版本；取不到数直接抛错，不编数、不留降级。
本地手工打包仍可传 --date/--day/--build（不传 --day 按四段处理，这是手工覆盖专用的简化
路径，跟 CI 的自动取数退化是两回事）。

自由化：--font/--base 都收本地文件或 URL，没有平台闸门；家族名、可变轴、行度量
全部现场从字体里读。主字体必须是含 wght 轴的可变字体——配置只出新语法（supportedAxes），
静态字体没有该轴，直接拒绝，不做逐档展开的降级。

对主字体的安装副本只做三件事（都属 OFL 意义上的修改，所以安装副本整体改名）：
1. 竖直行度量对齐基础包里的 Roboto 空壳——真机验证过的角标偏低/切下沿修复；
2. 剪除映射到空白字形的码位——上游声称覆盖但字形空白，会吞掉回退链；
3. 内部家族名改成 RENAME——保留名合规（文渊的 OFL 保留 'WenYuan'/'文渊'）。
轮廓、cmap 归属、可变轴有构建期守卫，动一个字节就报错。

不做「别名字件」：2026-10-05 真机实测（OnePlus / ColorOS 16），Gecko 的字体清单不含未写进
系统配置的字件，别名字件在网页里解析不到（20 个空格宽度 = 默认链，别名值 0.5em 未出现）；
而 Gecko 每条回退链都由本模块前置文渊，命中与不命中最终都渲染文渊——既不可见也无收益，删。
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
from datetime import date, datetime, timedelta, timezone
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

# MFGA 17.0.1 删除了不可再分发的 Symbola-13.otf。Google Fonts 的 Noto Music（OFL-1.1）
# 在 U+1D100..U+1D1FF 补回约 200 个原先仅由 Symbola 提供的可见音符字形。使用不可变 Git blob
# URL 与 SHA-256，字体和对应许可证只在构建时下载、随模块打包，不把 TTF/OTF 放进仓库。
NOTO_MUSIC_SOURCE = {
    "filename": "NotoMusic-Regular.ttf",
    "url": "https://api.github.com/repos/google/fonts/git/blobs/7f1d616dd5efee190bb631231cf5f35fa8b8ab95",
    "sha256": "aeb2998c380f5807cda77e1d94e4ac596429cb74d4fffb8da279d4f3144c0eae",
    "accept": "application/vnd.github.raw",
    "family": "Noto Music",
    "license_filename": "NotoMusic-OFL.txt",
    "license_url": "https://api.github.com/repos/google/fonts/git/blobs/b6cd8a88e3c1ed12552e242d6428fd6bd8f292b1",
    "license_sha256": "1679cb60544990b4c2445320c6d5298e4bb0c08ff00dbb5a526f3793fdaa1e6f",
    "license_accept": "application/vnd.github.raw",
    "license_marker": "SIL OPEN FONT LICENSE Version 1.1",
    "coverage_range": (0x1D100, 0x1D1FF),
    "minimum_outline_mappings": 200,
}
# 覆盖补齐走上游（MakeFontsGreatAgain）的路子：不自己画字，把公开字库按 Unicode 版本
# 分件投放，由 fonts.xml 补字区按顺序兜底。主字体是文渊，基底停在 Unicode 14 之前，
# 下面这些码位在文渊里 0 覆盖（2026-10-26 实测），必须靠这一支。
#
# 许可证一律沿用各自的 OFL：New Unicode Replenish 与 Unicodia 用 MFGA 的 fonts/LICENSE-OFL
# （同一份文本同时注明 Noto 作者与 Mercury13），Noto 系用 Google Fonts 的 OFL。
NEW_UNICODE_LICENSE = {
    "license_url": "https://api.github.com/repos/Numbersf/MakeFontsGreatAgain/git/blobs/2db76e6951b37fca03fbb33815e2076611b3ffe0",
    "license_filename": "NewUnicode-OFL.txt",
    "license_sha256": "0e54191f2800d4c915f27d693dcbeaff085523c07c5115809c85a743b8b0d459",
    "license_accept": "application/vnd.github.raw",
    "license_marker": "SIL OPEN FONT LICENSE",
}

NEW_UNICODE_18 = {
    "filename": "Unicode18-new.ttf",
    "url": "https://api.github.com/repos/Numbersf/MakeFontsGreatAgain/git/blobs/4314ad3d17e7f4f4e8f242c3ca31521c24c0ec13",
    "sha256": "2d7e87acf5acd2dcff66ae12f6febc904b82f4c2ed3bab1ba7373a93904ccd81",
    "accept": "application/vnd.github.raw",
    "family": "New Unicode Replenish",
    "coverage_range": (0xA7E2, 0x1FAFA),
    "minimum_outline_mappings": 150,
    **NEW_UNICODE_LICENSE,
}
NEW_UNICODE_17 = {
    "filename": "Unicode17-new.ttf",
    "url": "https://api.github.com/repos/Numbersf/MakeFontsGreatAgain/git/blobs/e8779062e40dd911eee2998495164a4caaf29171",
    "sha256": "1b36637b45107d2cf550e36b58572d646b5ec0f35972a36e5f8077dc2dbf3cff",
    "accept": "application/vnd.github.raw",
    "family": "New Unicode Replenish",
    "coverage_range": (0x1095A, 0x1CEF0),
    "minimum_outline_mappings": 25,
    **NEW_UNICODE_LICENSE,
}
# 楔形文字标点（U+12470..U+12474）：MFGA 的补字区用 NotoSansPro.otf 提供。
NOTO_SANS_PRO_SOURCE = {
    "filename": "NotoSansPro.otf",
    "url": "https://api.github.com/repos/Numbersf/MakeFontsGreatAgain/git/blobs/a37c8e3bac787be941f7577127e3e6dbea1e19ef",
    "sha256": "729c16402587bf8f565230d3676d8508340f7e1ad0ecf7848a3fbdbb151b1e62",
    "accept": "application/vnd.github.raw",
    "family": "Noto Sans Pro",
    "coverage_range": (0x12470, 0x12474),
    "minimum_outline_mappings": 5,
    **NEW_UNICODE_LICENSE,
}
# 拉丁扩展与修饰符号的小缺口（U+208F、U+2E60..U+2E63、U+A7DD）：MFGA 补字区用 UnicodiaFunky。
UNICODIA_FUNKY_SOURCE = {
    "filename": "UnicodiaFunky.ttf",
    "url": "https://api.github.com/repos/Mercury13/unicodia/git/blobs/8b63b24c77cd4a0a1531b5c71d00ba2289da69bc",
    "sha256": "6ae19735dee1a7e64616de44a35e27e8329f80dff14171296173057e77bea18c",
    "accept": "application/vnd.github.raw",
    "family": "UnicodiaFunky",
    "coverage_range": (0x208F, 0xA7DD),
    "minimum_outline_mappings": 6,
    **NEW_UNICODE_LICENSE,
}
# 单色轮廓 emoji：文本风格，兼容面最广，先落它。
NOTO_EMOJI_SOURCE = {
    "filename": "NotoEmoji.ttf",
    "url": "https://api.github.com/repos/google/fonts/git/blobs/c2c26ab612a88a8610ff9cfbb89299bf2aea6c7a",
    "sha256": "de6c18832938afc99caf132b39d6a30a19bac7f2e812e28db2535b4608d27551",
    "accept": "application/vnd.github.raw",
    "family": "Noto Emoji",
    "license_filename": "NotoEmoji-OFL.txt",
    "license_url": "https://api.github.com/repos/google/fonts/git/blobs/d09d3d0e09169f6747754e6b25faf5ba5ef6402d",
    "license_sha256": "500bb1ccf43df7bbb522112f9133a52b16e1c35e809632f5d8609b179152de5b",
    "license_accept": "application/vnd.github.raw",
    "license_marker": "SIL OPEN FONT LICENSE Version 1.1",
    "coverage_range": (0x1FA90, 0x1FAF8),
    "minimum_outline_mappings": 80,
}
# 彩色 emoji（COLRv1）：补单色版没有的 U+1FA8E 起那批；老系统不支持 COLRv1 时自动落上一支。
NOTO_COLR_EMOJI_SOURCE = {
    "filename": "Noto-COLRv1.ttf",
    "url": "https://api.github.com/repos/googlefonts/noto-emoji/git/blobs/d1c82373d26e6949d81bbaefa4323f1e19f77262",
    "sha256": "b8e25ea68db82f9e4d0aee921f4420be2be39887bd5c893a2ad98710531f9d0c",
    "accept": "application/vnd.github.raw",
    "family": "Noto Color Emoji",
    "license_filename": "NotoColorEmoji-OFL.txt",
    "license_url": "https://api.github.com/repos/google/fonts/git/blobs/d09d3d0e09169f6747754e6b25faf5ba5ef6402d",
    "license_sha256": "500bb1ccf43df7bbb522112f9133a52b16e1c35e809632f5d8609b179152de5b",
    "license_accept": "application/vnd.github.raw",
    "license_marker": "SIL OPEN FONT LICENSE Version 1.1",
    "coverage_range": (0x1FA8E, 0x1FAF8),
    "minimum_outline_mappings": 10,
}
SUPPLEMENTAL_FONT_SOURCES = (NOTO_MUSIC_SOURCE, NEW_UNICODE_18, NEW_UNICODE_17,
                             NOTO_SANS_PRO_SOURCE, UNICODIA_FUNKY_SOURCE,
                             NOTO_EMOJI_SOURCE, NOTO_COLR_EMOJI_SOURCE)

# 二创汉字字库：数据在 tools/design_cjk.bin（Maruko 骨架量出来的中线，SIL OFL 1.1），
# 构建时描边成轮廓、编成一份独立的 OTF，作为**单独的 family** 排在主字体之前。
# 单独成族是硬要求：configure_fonts 的注释里记着真机结论——同一个 family 里混
# supportedAxes 可变字体与静态字体会让 ColorOS 16 开机卡第一屏。
CJK_DATA = ROOT / "tools" / "design_cjk.bin"
CJK_FONT_NAME = "SelfroundsCJK-VF.ttf"   # 可变字体（wght 300–500），一份顶三档；正式发布带版本
CJK_FAMILY = "Selfrounds CJK"

# 命名跟版本号同一套规矩（主人 2026-10-30）：迭代快，**展示名不带日期**；
# 正式发布带 yy.m.d.当日序号.总序号。两处一致——文件名与家族名要么同时带、要么同时不带，
# 否则「装的是哪一版」看名字说不清。
CJK_RELEASE_VERSION: str | None = None


def cjk_naming(version: str | None = None) -> tuple[str, str]:
    """（家族名, 字体文件名）。version 为空 = 迭代版，只留稳定的名字。"""
    tag = version if version and version != DEV_VERSION else None
    family = CJK_FAMILY if tag is None else f"{CJK_FAMILY} {tag}"
    name = CJK_FONT_NAME if tag is None else f"SelfroundsCJK-VF-{tag}.ttf"
    return family, name
CJK_AXES = "wght"                      # 可变轴：安装配置里写成 supportedAxes
CJK_LICENSE = ROOT / "LICENSES" / "MarukoGothic-OFL.txt"
CJK_LICENSE_NAME = "MarukoGothic-OFL.txt"

# ---------------------------------------------------------------- 配置数据
CARRIER = "Roboto-Regular.ttf"  # 输入 fonts.xml 的默认家族必须保留的度量空壳
PRIMARY_FAMILIES = {"sans-serif", "sans-serif-condensed", "serif"}
METRIC_FAMILIES = {"sans-serif", "sans-serif-condensed"}
# 主字体接管的命名家族只剩 serif：它本来放旧数字主字件（100.ttf…900.ttf），那些字件不打包，不换就
# 是一族指不到东西的引用。sans-serif / sans-serif-condensed 走 METRIC_FAMILIES 留度量空壳。
# monospace / serif-monospace / casual / cursive / sans-serif-smallcaps 本来各有自己的字体
# （DroidSansMono / CutiveMono / ComingSoon / DancingScript / CarroisGothicSC，五个字件 2026-10-07
# 真机确认都在 /system/fonts）——本来是什么字体就保持什么字体，整族换成文渊是本模块自己改的，
# 不是恢复谁。这五族本来就没有中文，缺字照旧往语言区 / 默认区的文渊落，覆盖不靠接管它们。
# 火狐名单同一规则（见 NATIVE_FIRST），两边一致。
OLD_PRIMARY = {f"{weight}.ttf" for weight in range(100, 1000, 100)}  # 输入配置里的旧数字主字体
CJK_LANGS = {"zh", "ja", "ko"}  # 语言区里主字体要接管的 BCP-47 主语言子标签
# 主人 2026-10-06 明确：不喜欢 MiSans。配置里连引用一起清掉，中文缺字不再落到它上面；
# 那些字继续往默认区的补充字库（天珩 / Unicode 新平面等）落，覆盖不靠厂商字体。
UNWANTED_FONTS = re.compile(r"misans", re.I)
# 火狐名单里谁排最前，按这个泛型在系统里本来是什么字体（fonts.xml 的命名家族）定：
# monospace=DroidSansMono.ttf / cursive=DancingScript-Regular.ttf / casual=ComingSoon.ttf
# （Android 的 fantasy 对应 casual）。本来是什么字体就保持什么字体，文渊只紧随其后兜 CJK。
# 不在表里的泛型（sans-serif / serif / emoji）系统里本来就是主字体，文渊排最前是恢复火狐的篡改。
NATIVE_FIRST = {"monospace": "Droid Sans Mono", "cursive": "Dancing Script", "fantasy": "Coming Soon"}
WEIGHTS = range(100, 1000, 100)
BLANK_CATEGORIES = {"Cc", "Cf", "Zs", "Zl", "Zp"}  # 合法空白字符的码位类别（空格类、控制类）
MODULE_KEYS = ("id", "name", "version", "versionCode", "author", "description")
CLOCK = timezone(timedelta(hours=8))  # 版本号里的日期按 UTC+8（否则 CI 在 UTC 下会差一天）
FONT_SUFFIXES = (".ttf", ".otf", ".ttc")
PROJECT = "Selffont"  # 产物名与 artifact 名的项目段：<项目名>-<版本>
DEV_VERSION = "dev"     # 仓库里的非发行默认：没盖戳就不假装有正式序号
# 规范 2026-10-31 定的版本串：yy.m.d 两位年、月/日/序号一律不补零、序号 ≥1。
DATE_RE = r"\d{2}\.(1[0-2]|[1-9])\.(3[01]|[12][0-9]|[1-9])"
VERSION_RE = re.compile(rf"^{DATE_RE}\.([1-9]\d*)\.([1-9]\d*)$")       # 五段：日期.当日序号.总序号
VERSION_RE4 = re.compile(rf"^{DATE_RE}\.([1-9]\d*)$")                   # 四段：本地手工省略 --day 时用（CI 自动取数不走这条路径）

# 网页自带字体开关：模板默认压掉（全系统同一副面孔）；--keep-web-fonts 放开（图标字体等要它）。
# 表示法与 module/web-fonts.sh 完全一致：生效 = pref 行原样，放行 = 该行加 Selffont:keep 标记注释。
WEB_FONT_PREF = "browser.display.use_document_fonts: 0"
WEB_FONT_ACTIVE = f"  {WEB_FONT_PREF}"
WEB_FONT_KEPT = f"  # Selffont:keep {WEB_FONT_PREF}"


def name_list_ok(line: str) -> None:
    """一条 font.name-list 首选项的校验：开头由 NATIVE_FIRST 定，文渊紧随其后且只出现一次。

    本来是什么字体就保持什么字体（monospace / cursive / fantasy），火狐篡改掉的才恢复（其余泛型
    系统里本来就是主字体，文渊排最前）。构建期尾链只往名单末尾追加，文渊不该被追加第二遍。
    """
    key, raw = (part.strip() for part in line.split(":", 1))
    names = [item.strip() for item in raw.strip('"').split(",")]
    parts = key.split(".")
    native = NATIVE_FIRST.get(parts[2] if len(parts) > 2 else "")
    head = [native, RENAME] if native else [RENAME]
    assert names[:len(head)] == head, f"{key} 名单开头应是 {head}：{line}"
    assert names.count(RENAME) == 1, f"{key} 文渊只该出现一次：{line}"
    assert not UNWANTED_FONTS.search(raw), f"名单里不该有不要的厂商字体：{line}"


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

def fetch(url: str, destination: Path, expected: str | None = None,
          accept: str | None = None, strict: bool = False) -> Path:
    """下载到 destination（已存在就复用）；默认哈希漂移告警，固定许可资源可要求严格匹配。"""
    if destination.exists():
        print(f"[缓存] {destination}")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        print(f"[下载] {url}")
        headers = {"User-Agent": "Selffont-builder"}
        if accept:
            headers["Accept"] = accept
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=300) as response, destination.open("wb") as out:
            shutil.copyfileobj(response, out, 1 << 20)
    actual = digest(destination)
    if expected and actual != expected:
        message = f"来源 sha256 不匹配：期望 {expected}，实际 {actual}。"
        if strict:
            raise ValueError(message)
        warn(f"默认源内容已变：期望 sha256 {expected[:12]}…，实际 {actual[:12]}…。继续构建。")
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


def pinned_artifact(spec: str, destination: Path, expected: str, accept: str | None = None) -> Path:
    """读取固定哈希的外部资源；支持不可变 URL，也支持测试用的本地文件。"""
    if spec.startswith(("http://", "https://")):
        return fetch(spec, destination, expected, accept=accept, strict=True)
    path = Path(spec)
    if not path.is_file():
        raise FileNotFoundError(f"补充字体来源不存在：{path}")
    actual = digest(path)
    if actual != expected:
        raise ValueError(f"补充字体来源 sha256 不匹配：{path} 期望 {expected}，实际 {actual}。")
    return path


def load_supplemental_fonts(sources: tuple[dict, ...], cache: Path) -> list[dict]:
    """下载并验证许可明确的补充字体；只读源文件，不把二进制写进仓库。"""
    loaded, filenames = [], set()
    for spec in sources:
        filename = spec["filename"]
        license_filename = spec["license_filename"]
        if PurePosixPath(filename).name != filename or PurePosixPath(filename).suffix.lower() not in FONT_SUFFIXES:
            raise ValueError(f"补充字体文件名不安全：{filename!r}")
        if PurePosixPath(license_filename).name != license_filename:
            raise ValueError(f"补充字体许可证文件名不安全：{license_filename!r}")
        if filename in filenames:
            raise ValueError(f"补充字体文件名重复：{filename}")
        filenames.add(filename)

        font_path = pinned_artifact(spec["url"], cache / filename, spec["sha256"], spec.get("accept"))
        data = font_path.read_bytes()
        try:
            with TTFont(io.BytesIO(data), lazy=True) as font:
                family = font["name"].getDebugName(1) or ""
                cmap = font.getBestCmap() or {}
                glyphs = font.getGlyphSet()
                start, end = spec["coverage_range"]
                # 彩色字体（COLR/COLRv1/CBDT/sbix）的基字形通常没有轮廓，墨在图层或位图里，
                # 用 BoundsPen 数会把整支判成空。这类字件按「cmap 里有这个码位」计数。
                color = any(tag in font for tag in ("COLR", "CBDT", "sbix"))
                visible = set()
                for codepoint, glyph_name in cmap.items():
                    if not start <= codepoint <= end:
                        continue
                    if color:
                        visible.add(codepoint)
                        continue
                    pen = BoundsPen(glyphs)
                    glyphs[glyph_name].draw(pen)
                    if pen.bounds is not None:
                        visible.add(codepoint)
        except Exception as error:
            raise ValueError(f"补充字体无法解析：{filename}: {error}") from error
        if family != spec["family"]:
            raise ValueError(f"补充字体家族名漂移：{filename} 期望 {spec['family']!r}，实际 {family!r}")
        minimum = spec["minimum_outline_mappings"]
        if len(visible) < minimum:
            raise ValueError(f"补充字体覆盖不足：{filename} 在 U+{start:04X}..U+{end:04X} "
                             f"只有 {len(visible)} 个非空轮廓，至少需要 {minimum} 个")

        license_path = pinned_artifact(spec["license_url"], cache / license_filename,
                                       spec["license_sha256"], spec.get("license_accept"))
        license_data = license_path.read_bytes()
        marker = spec["license_marker"].encode("utf-8")
        if marker not in license_data:
            raise ValueError(f"补充字体许可证不符合预期：{license_filename} 缺少 {spec['license_marker']!r}")
        loaded.append({"filename": filename, "data": data, "sha256": spec["sha256"], "family": family,
                       "license_filename": license_filename, "license_data": license_data,
                       "outline_mappings": len(visible)})
    return loaded


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

# 汉字的码位范围。**只放汉字**：早先这里还带着 (0x2A80, 0x2FDF)（康熙部首/IDS）和
# (0x3000, 0x312F)（汉字标点、假名、注音），于是 `〱` `〲`（竖排假名叠点，墨迹顶到 937）
# 被当成汉字去卡 930 的行框，整个构建被判「行框会切墨迹」。它们不是汉字，它们该由
# `usWinAscent`（跟真实墨迹走）管，不是由汉字的行框管。
HAN_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x2FA1F))


def han_envelope(font: TTFont) -> tuple[int, int] | None:
    """汉字的墨迹竖直包络：行框存在的意义就是装汉字，字母的下伸部不算。"""
    if "glyf" not in font:
        return None
    glyf, cmap = font["glyf"], font.getBestCmap() or {}
    low, high = None, None
    for codepoint, name in cmap.items():
        if not any(start <= codepoint <= end for start, end in HAN_RANGES):
            continue
        glyph = glyf[name]
        glyph.expand(glyf)
        if glyph.numberOfContours == 0:
            continue
        low = glyph.yMin if low is None else min(low, glyph.yMin)
        high = glyph.yMax if high is None else max(high, glyph.yMax)
    return None if low is None else (low, high)


def ink_envelope(font: TTFont) -> tuple[int, int] | None:
    """整字库的墨迹竖直包络（所有非空字形）。没字形的字件返回 None。"""
    if "glyf" not in font:
        return None
    glyf = font["glyf"]
    low, high = None, None
    for name in font.getGlyphOrder():
        glyph = glyf[name]
        # 必须先 expand：没解包的字形 numberOfContours 一律读成 0，
        # 照那个判断会把整库都当成空格子（自检里就炸在「没有可用的墨迹」）。
        glyph.expand(glyf)
        if glyph.numberOfContours == 0:
            continue
        low = glyph.yMin if low is None else min(low, glyph.yMin)
        high = glyph.yMax if high is None else max(high, glyph.yMax)
    return None if low is None else (low, high)


def normalize_metrics(data: bytes, carrier: dict, characters: str = "0123456789") -> bytes:
    """竖直行度量对齐 Roboto 空壳：根治角标数字偏低/切下沿（真机验证）。

    自研汉字字件也走这一条（2026-10-28「做和文渊一样的高度重校准」）：它没有拉丁数字，
    `characters` 传空串就退到**汉字**的墨迹包络来判「行框切不切墨」（字母的下伸部不算，
    那是 `usWin` 的事），判据不变。
    """
    font = TTFont(io.BytesIO(data), recalcBBoxes=False, recalcTimestamp=False)
    head, hhea, os2 = font["head"], font["hhea"], font["OS/2"]
    upm, carrier_upm = head.unitsPerEm, carrier["unitsPerEm"]
    ascender, descender, line_gap = (round(value * upm / carrier_upm) for value in carrier["hhea"])
    if ascender <= 0 or descender >= 0:
        raise ValueError("空壳行度量不是合法的 ascent/descent")
    envelope = ink_envelope(font)          # 整字库：裁剪包络要盖住它，一个都不能切
    ink = ink_bounds(font, characters) if characters else None
    if ink is None and not characters:
        ink = han_envelope(font)           # 汉字字件：行框只需装得下汉字
    if ink is None:
        raise ValueError("字件没有可用的墨迹，无法验证归一后的行框")
    if ink[1] > ascender or ink[0] < descender:
        raise ValueError(f"归一后的行框会切墨迹：ink={list(ink)} box=[{descender},{ascender}]")
    hhea.ascent, hhea.descent, hhea.lineGap = ascender, descender, line_gap
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = ascender, descender, line_gap
    if carrier["useTypoMetrics"]:
        os2.version = max(os2.version, 4)
        os2.fsSelection |= 0x80
    else:
        os2.fsSelection &= ~0x80
    # 裁剪包络跟着真实墨迹（整字库，含字母下伸部），只动行度量。
    top = max([ascender, head.yMax] + ([envelope[1]] if envelope else []))
    bottom = max([-descender, -head.yMin] + ([-envelope[0]] if envelope else []))
    os2.usWinAscent, os2.usWinDescent = top, bottom
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

def cjk_glyphs() -> dict[int, dict]:
    """读二创汉字数据（码位 → 半宽 + 笔画中线）；文件不在就返回空，构建退回纯宿主。"""
    if not CJK_DATA.exists():
        return {}
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "tools"))
    import design_cjk
    return design_cjk.load()


def build_cjk_font(glyphs: dict[int, dict], carrier: dict | None = None) -> bytes:
    """中线 → 轮廓 → 一份**可变**字体（glyf + gvar，wght 300–500，默认 400）。

    为什么是可变而不是三份静态：主人 2026-10-28 定「可变」。可变唯一的硬前提是
    **同一字形在三档下轮廓点数逐一相同**，所以描边不能让 pathops 按粗细重新求并集
    （它的点数会随粗细变，实测 88~90、116~117），必须走固定拓扑构造
    （`design_cjk.stroke_contours`：中线等参数采样 + 法向偏移 + 固定段数半圆）。
    `tools/cjk_vf.py` 里逐字断言点数一致，不一致直接抛错，不许「差不多」混过去。
    """
    import sys as _sys

    _sys.path.insert(0, str(ROOT / "tools"))
    import cjk_vf
    data = cjk_vf.build_vf(glyphs, family=cjk_naming(CJK_RELEASE_VERSION)[0], style="Regular",
                           ps_name="SelfroundsCJK-VF", version=CJK_RELEASE_VERSION)
    rejected = list(cjk_vf.REJECTS)
    if rejected:
        print(f"  越出字身框未收 {len(rejected)} 字（例 {', '.join(chr(cp) for cp, _ in rejected[:6])}）")
    if carrier is None:
        return data
    # 和主字体（文渊）走同一个函数、同一个空壳：行框同一套数字，混排不会跳行。
    calibrated = normalize_metrics(data, carrier, characters="")
    assert_glyphs_preserved(data, calibrated)
    return calibrated


def supported_axes(ladder: list[dict]) -> str | None:
    """可变字体的 supportedAxes 值（Android 15+ 只认 wght / wght,ital）；静态字体返回 None。

    带这个属性的字件由系统在运行时按请求的字重/斜体现场实例化——一条顶掉整条静态阶梯。
    """
    tags = {tag for entry in ladder for tag, _ in entry["axes"]}
    if tags == {"wght", "ital"}:
        return "wght,ital"
    return "wght" if tags == {"wght"} else None


def primary_node(font_name: str, ladder: list[dict]) -> ET.Element:
    """主字体在配置里的唯一写法：一条 supportedAxes 字件（运行时实例化）；没有可声明的轴就拒绝。"""
    axes = supported_axes(ladder)
    if not axes:
        raise ValueError("主字体没有 wght/ital 轴：配置只出 supportedAxes，不退回逐档展开")
    node = ET.Element("font", supportedAxes=axes)
    node.text = font_name
    return node


def replace_fonts(family: ET.Element, font_name: str, ladder: list[dict]) -> None:
    """一条 supportedAxes 字件顶掉整条阶梯（新语法，weight/style 可省）；family 的属性原样保留。"""
    for child in list(family):
        if child.tag == "font":
            family.remove(child)
    family.append(primary_node(font_name, ladder))


def swap_fonts(family: ET.Element, font_name: str, ladder: list[dict]) -> None:
    """CJK 语言区：删掉旧主字体与度量空壳；清空了的族换成主字体单字件，还有别的字件的族一个不动。

    真机实测（ColorOS 16，26.10.7.4.98）：把主字体（supportedAxes）前置进 NotoSansCJK 的 .ttc 族、
    Hentaigana 族，也就是同一族里混 supportedAxes 字件与带 index/weight 的字件，开机卡第一屏重启；
    去掉这三处前置后正常开机。所以语言区族只能是纯主字体，或原样不动，不许混。
    不丢覆盖：单字件族在文件里排在 Noto 同语言族之前，同语言缺字仍先落主字体。
    """
    for node in list(family.findall("font")):
        if (node.text or "").strip() in OLD_PRIMARY | {CARRIER}:
            family.remove(node)
    if not family.findall("font"):
        family.append(primary_node(font_name, ladder))


def is_cjk_locale(tag: str | None) -> bool:
    """lang 属性里有中日韩标签就算 CJK 语言区（zh / zh-Hans / zh-Hant,zh-Bopo / ja / ko…）。

    依据 AOSP font_fallback.xml 头注：除默认家族、命名家族外还有 locale fallback family，
    缺字时按「完整 BCP-47 标签（含 script）→ 仅语言 → 顺序」匹配，语言区优先于默认区顺序。
    非 CJK 的语言区（und-Arab 之类）与 emoji 区一律不碰。
    """
    return any(part.split("-")[0].strip().lower() in CJK_LANGS
               for part in (tag or "").split(",") if part.strip())


def configure_fonts(template: bytes, font_name: str, ladder: list[dict],
                    cjk: bool = False) -> bytes:
    """主字体接管全部主家族、CJK 语言区与默认区；空壳留在度量家族；匿名字形回退紧随默认家族。

    输出统一是新语法（supportedAxes,Android 15+ 运行时实例化）：安装脚本只投放 font_fallback*.xml,
    库存 fonts.xml 不再替换，所以没有 legacy 展开的第二份。

    缺字回退分两个区（AOSP font_fallback.xml 头注）：语言区（带 lang/variant 的 locale fallback
    family）按「完整 BCP-47 标签 → 仅语言」优先匹配，默认区才按文件顺序。所以 CJK 语言区不能整族
    删掉：原来只放旧主字体 / MiSans 的族换成主字体单字件；带 Noto CJK 等其他字件的族不动
    （不往里混主字体，真机会卡开机），它们排在单字件族之后，同语言缺字仍先落主字体。
    """
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.fromstring(template, parser=parser)
    if root.tag != "familyset":
        raise ValueError("输入 fonts.xml 必须是 familyset")
    default = root.find("family[@name='sans-serif']")
    if default is None or {(node.text or "").strip() for node in default.findall("font")} != {CARRIER}:
        raise ValueError(f"输入 fonts.xml 的默认家族必须保留 {CARRIER} 度量空壳")
    for family in list(root.findall("family")):  # 不要的厂商字体：整条引用清掉（含 postScriptName 那类属性）
        for node in list(family.findall("font")):
            if UNWANTED_FONTS.search((node.text or "").strip()):
                family.remove(node)
    for node in list(root):  # 标注它的那条注释也删，免得产物里留一句指不到东西的说明
        if callable(node.tag) and UNWANTED_FONTS.search(node.text or ""):
            root.remove(node)
    for family in list(root.findall("family")):
        name = family.get("name")
        lang, variant = family.get("lang"), family.get("variant")
        locale = bool(lang or variant)
        files = {(node.text or "").strip() for node in family.findall("font")}
        if not name and not locale and files and files <= OLD_PRIMARY | {CARRIER}:
            root.remove(family)  # 默认区的旧主字体匿名家族：由紧随默认家族的新匿名家族顶替
        elif name in METRIC_FAMILIES and files == {CARRIER}:
            continue  # 度量家族保留空壳：主字体走匿名回退，这里只提供行度量
        elif locale and is_cjk_locale(lang) and not variant:
            swap_fonts(family, font_name, ladder)  # CJK 语言区：清空的族换主字体单字件，混有其他字件的族不动
        elif name in PRIMARY_FAMILIES or files & OLD_PRIMARY:
            replace_fonts(family, font_name, ladder)  # 语言区只换字件，lang/variant 属性原样保留
    # 二创汉字族：单独一个 family，排在主字体之前，让它覆盖到的码位先落这里。
    # 它是可变字体，字件节点必须带 supportedAxes；混写静态字件会让 ColorOS 卡第一屏。
    # 不混进任何已有族（混 supportedAxes 与静态字件会卡开机），也不带 lang 属性
    # （CJK 语言区族只能是纯主字体族，见 swap_fonts 的注释）。
    index = list(root).index(default) + 1
    if cjk:
        own = ET.Element("family")
        # 可变字件：写 supportedAxes，不写 weight（运行时按 wght 实例化）。
        node = ET.SubElement(own, "font", style="normal", supportedAxes=CJK_AXES)
        node.text = cjk_naming(CJK_RELEASE_VERSION)[1]
        root.insert(index, own)
        index += 1
    fallback = ET.Element("family")
    replace_fonts(fallback, font_name, ladder)
    root.insert(index, fallback)
    for family in list(root.findall("family")):  # 清完不要的字体后空掉的家族：空节点没有意义，删
        if not family.findall("font"):
            root.remove(family)
    # 输出文件的根节点只能是不带属性的 <familyset>（AOSP font_fallback.xml 头注：
    # 「No attributes are allowed to familyset node」，官方生成器也不写任何属性）；
    # 模板从 fonts.xml 带来的 version 属性在这里去掉——带属性可能整份配置被拒。
    root.attrib.pop("version", None)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------- 版本盖戳

def default_output(prop: str) -> Path:
    """产物名跟版本走：Selffont-<版本>.zip（规范 <项目名>-<版本>）；五段或退化四段都认，别的不出包。"""
    stamped = re.search(r"^version=(.+)$", prop, flags=re.M)
    core = stamped.group(1) if stamped else ""
    if not (VERSION_RE.fullmatch(core) or VERSION_RE4.fullmatch(core)):
        raise ValueError(f"产物名需要规范版本号（五段，本地手工省略 --day 时退化四段），实际 version={core!r}："
                         "先 --query-ci 取数，或显式传 --date/--day/--build")
    return ROOT / "build" / f"{PROJECT}-{core}.zip"


def version_core(date: str, build: str, day: str | None = None) -> str:
    """版本号核心：五段 yy.m.d.当日序号.总序号；day 为 None（本地手工省略 --day）时退化四段 yy.m.d.总序号。"""
    return f"{date}.{day}.{build}" if day else f"{date}.{build}"


def check_number(value: str, label: str, minimum: int = 0) -> str:
    if not value.isdigit() or int(value) < minimum:
        raise ValueError(f"{label}必须是 ≥{minimum} 的十进制整数，收到 {value!r}")
    return value


def check_date(value: str) -> str:
    if not re.fullmatch(DATE_RE, value):
        raise ValueError(f"日期必须是 YY.M.D（两位年，月/日不补零，例 26.11.1），收到 {value!r}")
    return value


def stamp_version(prop: str, build: str | None, day: str | None = None, date: str | None = None) -> str:
    """盖戳：version = yy.m.d.[当日序号.]总序号（展示不含 v），versionCode = 总序号（KSU 靠它比新旧）。

    总序号、日期必填，缺一就抛错停在这里，调用方（build / CI）不出包、不上传——不编数，也不
    静默产半成品。`--query-ci` 现场取数时当日序号恒 ≥1（当日第几条 `build.yml` 运行），不会是 None；
    四段退化只在本地手工省略 `--day` 时才会发生。
    """
    missing = [label for label, value in (("总序号", build), ("日期", date)) if not value]
    if missing:
        raise ValueError(f"版本号缺少{'、'.join(missing)}：用 --query-ci 现场取数，"
                         "或显式传 --build/--date（这两段不可豁免，不出非发行包）")
    check_number(build, "总序号", 1)
    if day is not None:
        check_number(day, "当日序号", 1)
    check_date(date)
    prop = re.sub(r"^version=.*$", f"version={version_core(date, build, day)}", prop, flags=re.M)
    return re.sub(r"^versionCode=.*$", f"versionCode={build}", prop, flags=re.M)


def gh_json(endpoint: str, key: str) -> list[dict]:
    """`gh api --paginate` 读一个分页端点，按 id 去重后返回列表。

    翻页期间若有新对象插队，同一对象会在两页里各出现一次；按 id 去重避免它被当成两条。
    取不到（无令牌、端点错、网络失败）直接抛，不用空列表冒充「没有历史」。
    """
    result = subprocess.run(["gh", "api", "--paginate", endpoint], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh api {endpoint} 退出码 {result.returncode}：{result.stderr.strip()}")
    rows, seen, index, raw = [], set(), 0, result.stdout
    decoder = json.JSONDecoder()
    while True:
        while index < len(raw) and raw[index] in " \r\n\t":
            index += 1
        if index >= len(raw):
            return rows
        page, index = decoder.raw_decode(raw, index)
        for row in page.get(key, []):
            if row.get("id") not in seen:
                seen.add(row.get("id"))
                rows.append(row)


def run_day(row: dict) -> date:
    """运行开始时刻转 UTC+8 的日期；`run_started_at` 缺失（一直排队没真正开始）退回 `created_at`。"""
    stamp = row.get("run_started_at") or row.get("created_at") or ""
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(CLOCK).date()


def artifact_anchor(name: str, date: str) -> int | None:
    """产物名 `Selffont-yy.m.d.d0.r0` 反推当日首条运行号 `r0 - d0 + 1`；口径不合返回 None。"""
    version = name.split("-", 1)[1] if "-" in name else ""
    parts = version.split(".")
    if len(parts) != 5 or ".".join(parts[:3]) != date:
        return None
    try:
        day, total = int(parts[3]), int(parts[4])
    except ValueError:
        return None
    return total - day + 1 if day >= 1 and total >= day else None


def ci_version_numbers(runs: list[dict], artifacts: list[dict], run_number: int,
                       now: datetime) -> tuple[str, int, int, int]:
    """差值锚定法取号：返回 (日期, 当日序号, 总序号, 当日首条运行号 R_first)。

    总序号取 `run_number` 原值（同一 run 重试时 GitHub 不换 run_number，版本号自然不变）。
    当日序号按差值锚定：当日现存 `build.yml` 运行的最小 `run_number`，与当日现存产物
    `Selffont-yy.m.d.d0.r0` 反推的 `r0 - d0 + 1`，两者取小作 `R_first`（都没有就取当前
    `run_number`），当日序号 = 当前 `run_number - R_first + 1`。失败运行同样占号，
    `pull_request` 运行永不计入。锚点比当前号还大（旧运行已删）时钳到当前号，序号不小于 1。

    纯函数：只吃 API 读到的数据，不碰网络也不碰 git，自检用合成数据覆盖各分支。
    """
    total = int(check_number(str(run_number), "总序号", 1))
    moment = now.astimezone(CLOCK)
    date = f"{moment.year % 100}.{moment.month}.{moment.day}"
    today = moment.date()
    anchors = []
    for row in runs:
        if row.get("event") == "pull_request" or not row.get("run_number"):
            continue
        try:
            started = run_day(row)
        except (TypeError, ValueError):
            continue
        if started == today:
            anchors.append(int(row["run_number"]))
    for row in artifacts:
        anchor = artifact_anchor(row.get("name", ""), date)
        if anchor is not None:
            anchors.append(anchor)
    first = min(min(anchors), total) if anchors else total
    day = total - first + 1
    check_number(str(day), "当日序号", 1)
    return date, day, total, first


def query_ci_version() -> tuple[str, str, str]:
    """CI 现场取号：读 `build.yml` 运行列表与全仓产物列表，按差值锚定法算出三段版本。

    取不到即抛：不降级、不编数。启动行打印 head SHA、run_id、run_number、R_first、当日序号
    与最终版本，和产物名逐字可对。
    """
    repo = (os.environ.get("REPO") or os.environ.get("GITHUB_REPOSITORY") or "").strip()
    run_number = (os.environ.get("RUN_NUMBER") or os.environ.get("GITHUB_RUN_NUMBER") or "").strip()
    if not repo or not run_number.isdigit() or int(run_number) < 1:
        sys.exit("--query-ci 只在 CI 里成立：REPO/GITHUB_REPOSITORY 与 "
                           f"RUN_NUMBER/GITHUB_RUN_NUMBER 都要取到，实际 REPO={repo!r} "
                           f"RUN_NUMBER={run_number!r}")
    now = datetime.now(timezone.utc).astimezone(CLOCK)
    runs = gh_json(f"repos/{repo}/actions/workflows/build.yml/runs?per_page=100", "workflow_runs")
    artifacts = gh_json(f"repos/{repo}/actions/artifacts?per_page=100", "artifacts")
    date, day, total, first = ci_version_numbers(runs, artifacts, int(run_number), now)
    print(f"[取号] head={os.environ.get('GITHUB_SHA', '未提供')} "
          f"run_id={os.environ.get('GITHUB_RUN_ID', '未提供')} run_number={total} R_first={first} "
          f"当日序号={day} 版本={date}.{day}.{total}（UTC+8 {now:%Y-%m-%d %H:%M:%S}）", file=sys.stderr)
    return date, str(day), str(total)


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
          query: bool = False, keep_web_fonts: bool = False,
          supplemental_font_sources: tuple[dict, ...] | None = None,
          cjk: bool = True) -> list[str]:
    """base/font 是本地路径或 URL（None 用默认源）；返回警告列表。

    supplementals=None 使用仓库固定的 OFL 来源；显式空 tuple 仅供离线自检夹具使用。
    """
    cache = ROOT / "build/cache"
    build_num = build_num or os.environ.get("SELFFONT_BUILD") or None
    day = day or os.environ.get("SELFFONT_DAY") or None
    date = date or os.environ.get("SELFFONT_DATE") or None
    warnings: list[str] = []
    if query:
        if build_num or day or date:
            raise ValueError("版本号只认一个来源：--query-ci 与 --build/--day/--date 不能混用")
        date, day, build_num = query_ci_version()  # 取数失败直接抛：不编数、不出非发行包；day 恒为数字串
    prop = stamp_version((ROOT / "module/module.prop").read_text(encoding="utf-8"),
                         build_num, day=day, date=date)
    # 命名跟版本号同一套：正式发布带 yy.m.d.当日序号.总序号，迭代版只留稳定名字。
    global CJK_RELEASE_VERSION
    CJK_RELEASE_VERSION = re.search(r"^version=(.*)$", prop, flags=re.M).group(1).strip()
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
    supplemental_sources = (SUPPLEMENTAL_FONT_SOURCES if supplemental_font_sources is None
                            else supplemental_font_sources)
    supplementals = load_supplemental_fonts(supplemental_sources, cache)

    with zipfile.ZipFile(base_path) as archive:
        members = font_members(archive)
        names = {member.filename for member in members}
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

        # 二创汉字字库：数据 → 轮廓 → 一份独立 OTF，作为单独 family 排在主字体之前。
        # build_vf 会逐字 pop 掉传进来的字典（三万字全按 Python 对象摊开要 500 MB 以上），
        # 所以字数要先记下来。
        glyphs = cjk_glyphs() if cjk else {}
        glyph_count = len(glyphs)
        cjk_font = build_cjk_font(glyphs, carrier) if glyphs else b""
        # 框架读 font_fallback.xml（新语法）；Skia 读库存 fonts.xml（另一份，本模块也换）。
        template = (ROOT / "fonts.xml").read_bytes()
        xml = configure_fonts(template, name, ladder, cjk=bool(glyph_count))
        # Skia 只认 /system/etc/fonts.xml：Flutter / WebView / 厂商小组件走这条路。
        # 只出插入行，由安装脚本插进设备自己那份（整份替换会丢掉 OPPO Sans 等 OEM 字件）。
        faces = ([(cjk_naming(CJK_RELEASE_VERSION)[1], 400)] if glyphs else []) + [(name, 400)]
        legacy = legacy_rows(faces)
        xml_root = ET.fromstring(xml)
        references = [(node.text or "").strip() for node in xml_root.iter("font")]
        referenced = set(references)
        member_by_file = {PurePosixPath(member.filename).name: member for member in members}
        extra_by_file = {extra["filename"]: extra for extra in supplementals}
        extra_names = {extra["filename"] for extra in supplementals}
        for extra in supplementals:
            filename = extra["filename"]
            if references.count(filename) != 1:
                raise ValueError(f"补充字体必须在 fonts.xml 中恰好引用一次：{filename}")
            member = member_by_file.get(filename)
            if member and hashlib.sha256(archive.read(member)).hexdigest() != extra["sha256"]:
                # 基础包自带同名文件但版本不同（实测 MFGA 基础包里的 NotoSansPro.otf 与本仓固定的
                # 那份不是同一版）。以本仓固定、带许可与覆盖区间声明的那份为准：同名字件一律只用
                # 补充字体这一份，基础包里的旧副本不打包——记警告，不静默二选一。
                warnings.append(f"基础包自带同名但内容不同的 {filename}，改打包本仓固定的那份。")
        bundled = [member for member in members if PurePosixPath(member.filename).name in referenced
                   and PurePosixPath(member.filename).name not in extra_names]

        # 火狐 pref 尾链：火狐的逐字回退不读 fonts.xml，逐字兜底时全清单乱序扫描，选中的字体和系统
        # 不同（花体/生僻字符两副面孔）。把补充字库的内部家族名按 fonts.xml 顺序追加到每条名单末尾，
        # 让它和系统走同一条链。火狐只认字件内部名（优先 typographic），现场从基础包读取。
        families, done = [], set()
        for node in xml_root.iter("font"):
            fname = (node.text or "").strip()
            if fname in done or fname in (name, CARRIER) or fname in OLD_PRIMARY:
                continue
            done.add(fname)
            member = member_by_file.get(fname)
            if fname in extra_by_file:
                # 同名字件以补充字体为准（上面已把基础包里的旧副本排除在打包之外），家族名也取它的。
                family = extra_by_file[fname]["family"]
            elif member:
                try:
                    with TTFont(io.BytesIO(archive.read(member)), lazy=True) as font:
                        family = font["name"].getDebugName(16) or font["name"].getDebugName(1)
                except Exception:  # 坏字件跳过，不影响构建
                    continue
            else:
                continue  # 设备自带（读不到内部名），交给系统
            if family and family not in families:
                families.append(family)
        config = (ROOT / "module/geckoview-config.yaml").read_text(encoding="utf-8")
        if families:
            tail = ", ".join(families)
            config = re.sub(r'^(  font\.name-list\.[^:]+: ")([^"]*)(")$',
                            lambda match: f"{match.group(1)}{match.group(2)}, {tail}{match.group(3)}",
                            config, flags=re.M)

        config = apply_web_font_switch(config, keep_web_fonts)
        output.parent.mkdir(parents=True, exist_ok=True)
        write_module(output, archive, bundled, name, packaged, xml, prop, config, supplementals,
                     cjk_font, legacy)

    version = next(line.split("=", 1)[1] for line in prop.splitlines() if line.startswith("version="))
    print(f"构建完成：{output}  版本 {version}")
    print(f"  主字体 {face['family']!r} → {RENAME}（{name},{len(ladder)} 档）")
    print(f"  补充字库 {len(bundled)} 个基础字体 + {len(supplementals)} 个固定许可外部字体；"
          "fonts.xml 其余引用由设备自带（Noto/OEM，不打包）")
    print(f"  二创汉字 {glyph_count} 字 / {len(cjk_font) / 1e6:.1f} MB"
          f"（{cjk_naming(CJK_RELEASE_VERSION)[0]}，排在主字体之前）"
          if glyph_count else "  二创汉字：无数据，跳过")
    print("  网页自带字体：放行（--keep-web-fonts）" if keep_web_fonts else "  网页自带字体：压成文渊")
    for message in warnings:
        warn(message)
    return warnings


def write_module(output: Path, archive: zipfile.ZipFile, bundled: list[zipfile.ZipInfo],
                 name: str, packaged: bytes, xml: bytes, prop: str, config: str,
                 supplementals: list[dict], cjk_font: bytes = b"", legacy: bytes = b"") -> None:
    """写模块 zip：被配置引用的基础包字体 + 固定许可外部字体 + 主字体 + 原生 KSU 模块布局。

    两份配置走两条路：`font_fallback.xml` 是新语法，安装脚本投放到所有
    `font_fallback*.xml` / `fonts_base.xml` / `fonts_ule.xml`（Android 框架读）；
    `fonts-insert.xml` 只是几条 `<font>` 行，安装脚本把它们插进设备**自己那份**
    `/system/etc/fonts.xml`（Skia 读：Flutter / WebView / 厂商小组件）。插而不换，
    是因为设备那份里有 OPPO Sans 等 OEM 字件，整份替换会把它们删掉。
    """
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as destination:
        for member in bundled:
            destination.writestr(member.filename, archive.read(member))
        # 同名字件只有一份，且固定用补充字体这一份（bundled 已在调用侧排掉同名的基础包副本）。
        # 许可文本同样只写一次：多个补充字体共用同一份 OFL（实测三个来源都叫 NewUnicode-OFL.txt），
        # 重复写会让 zip 里出现同名条目，解包时要人确认覆盖，CI 直接卡死。同名但内容不同就报错。
        written_licenses: dict[str, bytes] = {}
        for supplemental in supplementals:
            destination.writestr(f"system/fonts/{supplemental['filename']}", supplemental["data"])
            license_name = supplemental["license_filename"]
            if license_name in written_licenses:
                if written_licenses[license_name] != supplemental["license_data"]:
                    raise ValueError(f"同名许可文本内容不同：{license_name}")
                continue
            written_licenses[license_name] = supplemental["license_data"]
            destination.writestr(f"licenses/{license_name}", supplemental["license_data"])
        destination.writestr(f"system/fonts/{name}", packaged)
        if cjk_font:
            destination.writestr(f"system/fonts/{cjk_naming(CJK_RELEASE_VERSION)[1]}", cjk_font)
            destination.writestr(f"licenses/{CJK_LICENSE_NAME}", CJK_LICENSE.read_bytes())
        destination.writestr("font_fallback.xml", xml)
        destination.writestr("fonts-insert.xml", legacy)
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


def make_music_font(glyph_count=200):
    """离线构建测试用字体：足够覆盖 Noto Music 的固定音符区段门槛。"""
    codepoints = range(0x1D100, 0x1D100 + glyph_count)
    order = [".notdef", *(f"u{codepoint:04X}" for codepoint in codepoints)]
    b = FontBuilder(1000, isTTF=True)
    b.setupGlyphOrder(order)
    b.setupCharacterMap({codepoint: f"u{codepoint:04X}" for codepoint in codepoints})
    b.setupGlyf({name: box(40, 0, 460, 700) for name in order})
    b.setupHorizontalMetrics(dict.fromkeys(order, (500, 0)))
    b.setupHorizontalHeader(ascent=800, descent=-200)
    b.setupNameTable({"familyName": "Noto Music", "styleName": "Regular",
                      "uniqueFontIdentifier": "Noto Music Test", "fullName": "Noto Music Regular",
                      "psName": "NotoMusic-Regular"})
    b.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200, usWeightClass=400)
    b.setupPost()
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

def legacy_rows(faces: list[tuple[str, int]]) -> bytes:
    """Skia 那份配置要插入的字件行（`<font ...>`，缩进四格，一行一条）。

    Android 框架读 `font_fallback.xml`，Flutter / WebView / 部分厂商小组件走 Skia，
    而 Skia 把配置路径写死成 `/system/etc/fonts.xml`（`google/skia`
    `src/ports/SkFontMgr_android_parser.cpp`：`LMP_SYSTEM_FONTS_FILE` 在第 31 行，
    `parse_config_file(...)` 在第 777 行）。只换 framework 那几份时，这些程序照旧读 OEM
    配置——2026-10-28 真机：`/system/etc/fonts.xml` 里 Selffont **0** 次，另三份各 16 次。

    **不能整份替换**：仓库里的 `fonts.xml` 是 AOSP+MIUI 混编模板，设备那份里有 OPPO Sans
    等 OEM 字件（真机反馈：天气小组件落到 OPPO Sans）。整份盖掉等于把这些字件一起删掉。
    所以这里只出「要插的行」，由安装脚本把它插进**设备自己那份**文件里，其余行原样保留。
    """
    return "".join(f'    <font weight="{weight}" style="normal">{name}</font>\n'
                   for name, weight in faces).encode("utf-8")


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

    # 语言区（locale fallback family）：缺字时按「完整 BCP-47 标签 → 仅语言 → 顺序」匹配，
    # 语言区优先于默认区顺序（AOSP font_fallback.xml 头注）。整族删掉会让中文场景的缺字
    # 落到语言区里的厂商字体（Noto CJK 等），所以原来只放旧主字体的 CJK 语言区换成主字体单字件。
    def locales(document):
        return {tuple(sorted(family.attrib.items())): [(n.text or "").strip() for n in family.findall("font")]
                for family in document.findall("family") if family.get("lang") or family.get("variant")}

    template_root = ET.fromstring(template)
    assert len(locales(root)) == len(locales(template_root)), "语言区家族数变了：不许整族删语言区"
    # 主人不要的厂商字体（MiSans）：配置里一条引用都不许留，也不许留下空家族节点。
    assert not [(node.text or "").strip() for node in root.iter("font")
                if UNWANTED_FONTS.search((node.text or "").strip())], "配置里还留着不要的厂商字体"
    assert all(family.findall("font") for family in root.findall("family")), "有空家族节点"
    assert [f.get("lang") for f in root.findall("family") if f.get("lang") == "zh"] == ["zh"], "zh 语言区应保留"
    # 真机只实测了语言区混族卡开机；这里对全部族一视同仁，是保守护栏（命名族 / 默认族 / 匿名族 /
    # 语言区）。哪天确需混写，先拿证据改这条，不要绕过它。
    for family in root.findall("family"):
        kinds = {node.get("supportedAxes") is not None for node in family.findall("font")}
        assert len(kinds) == 1, f"族 {family.attrib} 混了 supportedAxes 字件与普通字件（真机实测语言区会卡开机）"
    def locales(document):
        return [(family.get("lang"), family.get("variant"),
                 [(n.text or "").strip() for n in family.findall("font")])
                for family in document.findall("family") if family.get("lang") or family.get("variant")]
    before, after = locales(template_root), locales(root)
    assert [(lang, variant) for lang, variant, _ in before] == \
        [(lang, variant) for lang, variant, _ in after], "语言区家族被删、被加或被重排"
    for (lang, variant, files), (_, _, got) in zip(before, after):
        kept = [name for name in files
                if name not in OLD_PRIMARY | {CARRIER} and not UNWANTED_FONTS.search(name)]
        if is_cjk_locale(lang) and not variant:
            # 清空的族换成主字体单字件；还有其他字件的族逐字不动（不混主字体）。
            assert got == (kept or ["V.ttf"]), f"CJK 语言区 {lang} 应是 {kept or ['V.ttf']}，实际 {got}"
        elif set(files) & OLD_PRIMARY:
            assert got == ["V.ttf"], f"语言区 {lang} 的旧主字体应被主字体整体顶掉，实际 {got}"
        else:
            # 非 CJK 语言区（含 emoji 的 und-Zsye）逐字未改：主字体不进去，顺序也不动。
            assert got == files, f"非 CJK 语言区 {lang} 被改动：{got} != {files}"
    # 命名族：该被接管的只有 PRIMARY_FAMILIES 减去度量家族（即 serif——它本来放旧数字主字件）；
    # 其余命名族本来各有自己的字体（monospace=DroidSansMono、casual=ComingSoon…），逐字不动。
    def named(document):
        return {family.get("name"): [(n.text or "").strip() for n in family.findall("font")]
                for family in document.findall("family") if family.get("name")}
    template_named, ours_named = named(template_root), named(root)
    assert {name for name, nodes in ours_named.items()
            if any(text == "V.ttf" for text in nodes)} == {"serif"}, \
        "被主字体接管的命名族应只有 serif（它本来放旧数字主字件，不换就是一族空引用）"
    # 这五族本来各有自己的字体（2026-10-07 真机确认五个字件都在 /system/fonts）：
    # 本来是什么字体就保持什么字体。期望值独立写死，不从 PRIMARY_FAMILIES 推——否则改常量
    # 就自动改期望，断言成了同义反复（变异测试实测过：那样写抓不到回归）。
    for name, native in (("monospace", "DroidSansMono.ttf"), ("serif-monospace", "CutiveMono.ttf"),
                         ("casual", "ComingSoon.ttf"), ("cursive", "DancingScript-Regular.ttf"),
                         ("sans-serif-smallcaps", "CarroisGothicSC-Regular.ttf")):
        got = ours_named.get(name)
        assert got == template_named[name] and native in got, \
            f"{name} 应保持本来字体 {native}，实际 {got}"
    for name, files in template_named.items():
        if name in PRIMARY_FAMILIES or set(files) & OLD_PRIMARY:
            continue
        assert ours_named.get(name) == files, \
            f"命名族 {name} 被改动：{ours_named.get(name)} != {files}"
    for family in root.findall("family"):
        for node in family.findall("font"):
            assert (node.text or "").strip() not in OLD_PRIMARY, "残留旧数字主字体"
            if (node.text or "").strip() == "V.ttf":
                assert node.get("supportedAxes") == "wght,ital" and not node.findall("axis"), \
                    "主字体一律新语法：带 supportedAxes、无 axis 子节点"
                assert node.get("weight") is None and node.get("style") is None, \
                    "带 supportedAxes 的字件不该再写 weight/style"
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

        def test_build(**kwargs):
            kwargs.setdefault("supplemental_font_sources", ())
            kwargs.setdefault("cjk", False)   # 自检夹具不跑两万字描边
            return build(**kwargs)
        fonts_dir = tmp / "fonts"
        fonts_dir.mkdir()
        regular = fonts_dir / "P-Regular.ttf"
        regular.write_bytes(make_font())
        base, output = tmp / "base.zip", tmp / "out" / "Selffont.zip"
        base_zip(base, {"Roboto-Regular.ttf": make_carrier(),
                        "NotoSansPro.otf": make_font(family="Noto Sans Pro"),  # 真字体：验尾链要读内部家族名
                        "DeadWeight.ttf": b"dead"})
        music_font_path = tmp / "NotoMusic-Regular.ttf"
        music_font_path.write_bytes(make_music_font())
        music_license_path = tmp / "NotoMusic-OFL.txt"
        music_license_path.write_text("SIL OPEN FONT LICENSE Version 1.1\nTest license fixture\n", encoding="utf-8")
        music_source = {
            "filename": "NotoMusic-Regular.ttf", "url": str(music_font_path),
            "sha256": digest(music_font_path), "family": "Noto Music",
            "license_filename": "NotoMusic-OFL.txt", "license_url": str(music_license_path),
            "license_sha256": digest(music_license_path),
            "license_marker": "SIL OPEN FONT LICENSE Version 1.1",
            "coverage_range": (0x1D100, 0x1D1FF), "minimum_outline_mappings": 200,
        }
        test_build(base=str(base), font=str(regular), output=output, build_num="9", day="2", date="26.9.30",
                   supplemental_font_sources=(music_source,))

        with zipfile.ZipFile(output) as archive:
            members = set(archive.namelist())
            for expected in ("module.prop", "LICENSES.md", "customize.sh",
                             "firefox.sh", "web-fonts.sh", "action.sh", "hotswap.sh", "geckoview-config.yaml",
                             "font_fallback.xml", "fonts-insert.xml", "licenses/WenYuan-OFL.txt",
                             "system/fonts/NotoMusic-Regular.ttf", "licenses/NotoMusic-OFL.txt",
                             "system/fonts/P-Regular.ttf", "system/fonts/Roboto-Regular.ttf",
                             "system/fonts/NotoSansPro.otf", "licenses/MFGA-base-LICENSES.md"):
                assert expected in members, f"缺成员 {expected}"
            for absent in ("report.json", "system/fonts/DeadWeight.ttf",
                           "fonts.xml", "font_fallback_cjkvf.xml"):
                assert absent not in members, f"不该有的成员 {absent}"
            installed_prop = archive.read("module.prop").decode()
            assert "version=26.9.30.2.9" in installed_prop and "\nversionCode=9\n" in installed_prop, installed_prop
            assert (archive.getinfo("customize.sh").external_attr >> 16) == stat.S_IFREG | 0o755
            assert (archive.getinfo("hotswap.sh").external_attr >> 16) == stat.S_IFREG | 0o755, \
                "热切换脚本没进包或没有可执行位"
            assert (archive.getinfo("system/fonts/P-Regular.ttf").external_attr >> 16) == stat.S_IFREG | 0o644
            packaged = archive.read("system/fonts/P-Regular.ttf")
            xml = archive.read("font_fallback.xml").decode()
            legacy = archive.read("fonts-insert.xml").decode()
            config = archive.read("geckoview-config.yaml").decode()
            assert "  layout.css.font-variations.enabled: true" in config.splitlines(), \
                "ZIP 内 Gecko 配置未开启 CSS 可变字体支持"
            music_packaged = archive.read("system/fonts/NotoMusic-Regular.ttf")
            music_license_packaged = archive.read("licenses/NotoMusic-OFL.txt")

        # 归一 + 改名之后：轮廓/cmap/轴不动，家族名换成 RENAME,hhea 对齐空壳。
        before, after = glyph_signature(make_font()), glyph_signature(packaged)
        assert before["outlines"] == after["outlines"] and before["cmap"] == after["cmap"], "轮廓或 cmap 被改了"
        assert before["axes"] == after["axes"] and after["family"] == RENAME
        assert TTFont(io.BytesIO(packaged))["hhea"].ascent == 930, "包内字体未归一"
        # Skia 那份只出「插入行」：每条都是带字重与样式的静态字件行，且只列真正打进包里的文件。
        rows = [line.strip() for line in legacy.splitlines() if line.strip()]
        assert rows == ['<font weight="400" style="normal">P-Regular.ttf</font>'], legacy
        assert "P-Regular.ttf" in xml
        assert "NotoMusic-Regular.ttf" in xml
        assert music_packaged == music_font_path.read_bytes()
        assert b"SIL OPEN FONT LICENSE Version 1.1" in music_license_packaged
        assert ", Noto Music\"" in config, "补充 OFL 字体家族未追加到 Gecko 尾链"
        music_cmap = TTFont(io.BytesIO(music_packaged)).getBestCmap() or {}
        assert sum(0x1D100 <= codepoint <= 0x1D1FF for codepoint in music_cmap) >= 200
        # 单一配置、单一写法：主字体一律「一条 supportedAxes 字件」，接管家族与旧版一致。
        def ours_by_family(document):
            root = ET.fromstring(document)
            return {family.get("name"): [n for n in family.findall("font")
                                         if (n.text or "").strip() == "P-Regular.ttf"]
                    for family in root.findall("family")}

        families = {name: nodes for name, nodes in ours_by_family(xml).items() if nodes}
        assert {"serif"} <= set(families), "接管家族少了"
        assert not {"monospace", "serif-monospace", "casual", "cursive",
                    "sans-serif-smallcaps"} & set(families), "本来有自己字体的命名族不该被接管"
        assert all(len(nodes) == 1 and nodes[0].get("supportedAxes") == "wght,ital"
                   and not nodes[0].findall("axis") and nodes[0].get("weight") is None
                   for nodes in families.values()), "应是一条 supportedAxes 字件"
        root = ET.fromstring(xml)
        assert {node.text.strip() for node in root.find("family[@name='sans-serif']").findall("font")} == {CARRIER}
        assert "P-Regular.ttf" in {node.text.strip() for node in root.iter("font")}
        # 包内配置的语言区：CJK 语言区有主字体单字件（语言区优先于默认区顺序），Noto 族原样留着、不混主字体。
        locale = [family for family in root.findall("family") if is_cjk_locale(family.get("lang"))]
        assert locale, "包内配置没有 CJK 语言区"
        assert any([(n.text or "").strip() for n in f.findall("font")] == ["P-Regular.ttf"] for f in locale), \
            "CJK 语言区应有主字体单字件"
        assert any("NotoSansCJK-Regular.ttc" in [(node.text or "").strip() for node in family.findall("font")]
                   for family in locale), "语言区原有字件应保留（覆盖只加不减）"
        assert not any("P-Regular.ttf" in [(n.text or "").strip() for n in f.findall("font")]
                       and len(f.findall("font")) > 1 for f in locale), "语言区不许混主字体与其他字件（真机卡开机）"
        assert "MiSans" not in xml, "包内配置不该引用 MiSans"
        # 尾链：补充字库内部家族名按 fonts.xml 顺序拼进每条名单，开头（本来字体或文渊）不动。
        assert ", Noto Sans Pro, Noto Music\"" in config, "补充字体尾链顺序未拼进火狐配置"
        for line in config.splitlines():
            if line.strip().startswith("font.name-list."):
                name_list_ok(line)

        # --keep-web-fonts 时那一行应带 Selffont:keep 标记。
        test_build(base=str(base), font=str(regular), output=output, build_num="9", day="2", date="26.9.30",
              keep_web_fonts=True)
        with zipfile.ZipFile(output) as archive:
            kept = archive.read("geckoview-config.yaml").decode()
            assert re.search(rf"^{re.escape(WEB_FONT_KEPT)}$", kept, re.M), "网页字体未放行"
            assert not re.search(rf"^{re.escape(WEB_FONT_ACTIVE)}$", kept, re.M), "放行后 pref 仍生效"
            for line in kept.splitlines():  # 放行后名单本身仍完整、开头仍是本来字体或文渊
                if line.strip().startswith("font.name-list."):
                    name_list_ok(line)
        # 没有五段版本数据就不出包（规范：取数失败停止出包和上传）。
        try:
            test_build(base=str(base), font=str(regular), output=tmp / "out" / "nostamp.zip")
            raise AssertionError("没有版本数据的构建未被拒绝")
        except ValueError as error:
            assert "版本号缺少" in str(error), error
        assert default_output(stamp_version((ROOT / "module/module.prop").read_text(),
                                           "9", day="2", date="26.9.30")).name == "Selffont-26.9.30.2.9.zip"

        # 自由化：主字体按自己的文件名安装，不要求固定命名；非字体后缀明确报错。
        custom = fonts_dir / "Weird-Name.ttf"
        custom.write_bytes(make_font(family="Custom Face"))
        test_build(base=str(base), font=str(custom), output=output, build_num="9", day="2", date="26.9.30")
        with zipfile.ZipFile(output) as archive:
            assert "system/fonts/Weird-Name.ttf" in archive.namelist()
            assert "Weird-Name.ttf" in archive.read("font_fallback.xml").decode()
        try:
            test_build(base=str(base), font=str(fonts_dir / "x.woff2"), output=output,
                  build_num="9", day="2", date="26.9.30")
            raise AssertionError("非字体后缀未被拒绝")
        except ValueError:
            pass

        # 没有空壳 / 空壳不可用 → 直接拒绝打包，不静默降级（不做冗余降级）。
        base_zip(base, {"SomeFont.ttf": b"supplemental"})
        for message in ("没有它就不做归一",):
            try:
                test_build(base=str(base), font=str(regular), output=output, build_num="9", day="2", date="26.9.30")
                raise AssertionError("缺空壳未被拒绝")
            except ValueError as error:
                assert message in str(error), error
        base_zip(base, {"Roboto-Regular.ttf": make_carrier(visible=True)})  # 可见字形的 Roboto 不是空壳
        try:
            test_build(base=str(base), font=str(regular), output=output, build_num="9", day="2", date="26.9.30")
            raise AssertionError("可见字形的空壳未被拒绝")
        except ValueError as error:
            assert "度量空壳" in str(error), error
        # 静态主字体（没有 wght 轴）同样直接拒绝：配置只出 supportedAxes。
        static_font = fonts_dir / "Static.ttf"
        static_font.write_bytes(make_font(axes=False))
        base_zip(base, {"Roboto-Regular.ttf": make_carrier()})
        try:
            test_build(base=str(base), font=str(static_font), output=output, build_num="9", day="2", date="26.9.30")
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
                test_build(base=str(bad_zip), font=str(regular), output=output, build_num="9", day="2", date="26.9.30")
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
            test_build(base=str(link_zip), font=str(regular), output=output, build_num="9", day="2", date="26.9.30")
            raise AssertionError("符号链接字体未被拒绝")
        except ValueError:
            pass
        try:
            test_build(base=str(base), font=str(regular), output=base, build_num="9", day="2", date="26.9.30")
            raise AssertionError("输出覆盖了输入")
        except ValueError:
            pass


# ---------------------------------------------------------------- 版本盖戳

@check
def version_stamp():
    """盖戳：yy.m.d.[当日序号.]总序号，versionCode = 总序号；总序号/日期缺一就拒绝出包。"""
    prop = (ROOT / "module/module.prop").read_text()
    stamped = stamp_version(prop, "42", day="3", date="26.9.30")
    assert "version=26.9.30.3.42" in stamped and "versionCode=42" in stamped, stamped
    assert "v26" not in stamped, "展示版本不该带 v"
    assert VERSION_RE.fullmatch("26.9.30.3.42")
    for bad in ("26.9.30", "26.9.30.3.42.7", "dev"):
        assert not VERSION_RE.fullmatch(bad), bad
    # 当日序号从 1 起（规范 2026-10-31：版本串里 `0` 不是合法段），0 必须被拒。
    for zero in ("0", "00"):
        try:
            stamp_version(prop, "42", day=zero, date="26.9.30")
            raise AssertionError(f"当日序号 {zero!r} 未被拒绝")
        except ValueError:
            pass
    # 补零的日期同样是非法产物：26.11.01 不是 26.11.1。
    for padded in ("26.11.01", "26.09.30", "26.9.30.0.42"):
        assert not VERSION_RE.fullmatch(padded), padded
    # 四段只在本地手工省略 --day 时退化；CI 的 --query-ci 自动取数恒有当日序号，不走这条路径。
    # 命名跟版本号同一套：迭代版不带日期，正式发布带 yy.m.d.当日序号.总序号。
    global CJK_RELEASE_VERSION
    old = CJK_RELEASE_VERSION
    try:
        CJK_RELEASE_VERSION = None
        assert cjk_naming(None) == (CJK_FAMILY, CJK_FONT_NAME), cjk_naming(None)
        CJK_RELEASE_VERSION = "26.10.30.1.42"
        assert cjk_naming(CJK_RELEASE_VERSION) == ("Selfrounds CJK 26.10.30.1.42",
                                                   "SelfroundsCJK-VF-26.10.30.1.42.ttf"), cjk_naming(CJK_RELEASE_VERSION)
        CJK_RELEASE_VERSION = "dev"
        assert cjk_naming(CJK_RELEASE_VERSION) == (CJK_FAMILY, CJK_FONT_NAME), "dev 不该带日期"
    finally:
        CJK_RELEASE_VERSION = old
    degraded = stamp_version(prop, "42", day=None, date="26.9.30")
    assert "version=26.9.30.42" in degraded and "versionCode=42" in degraded, degraded
    assert VERSION_RE4.fullmatch("26.9.30.42")
    assert not VERSION_RE4.fullmatch("26.9.30.3.42"), "四段正则不该收五段"
    # 总序号、日期缺一就停：不出非发行包，也不静默编数。
    for kwargs in ({}, {"date": "26.9.30"}, {"build": "42"}):
        try:
            stamp_version(prop, kwargs.get("build"), day=kwargs.get("day"), date=kwargs.get("date"))
            raise AssertionError(f"缺段未被拒绝：{kwargs}")
        except ValueError as error:
            assert "不可豁免" in str(error), error
    try:
        default_output(prop)  # 仓库里的 module.prop 是非发行默认，没有规范版本就不给产物名
        raise AssertionError("非发行版本不该有产物名")
    except ValueError as error:
        assert "版本号" in str(error), error
    assert default_output(stamped).name == "Selffont-26.9.30.3.42.zip"
    assert default_output(degraded).name == "Selffont-26.9.30.42.zip"
    for bad in ("abc", "4 2", "9.", "0"):
        try:
            stamp_version(prop, bad, day="3", date="26.9.30")
            raise AssertionError(f"非法总序号未被拒绝：{bad!r}")
        except ValueError:
            pass
    for bad in ("-1", "x"):
        try:
            stamp_version(prop, "42", day=bad, date="26.9.30")
            raise AssertionError(f"非法当日序号未被拒绝：{bad!r}")
        except ValueError:
            pass
    try:
        stamp_version(prop, "42", day="3", date="26.9")
        raise AssertionError("非法日期未被拒绝")
    except ValueError:
        pass


@check
def ci_version_numbering():
    """取号口径：总序号取 `run_number` 原值，当日序号按差值锚定法算；PR 运行永不计入。"""
    def run(number, started, event="push"):
        return {"id": number, "run_number": number, "event": event, "run_started_at": started}

    def art(name, ident):
        return {"id": ident, "name": name}

    now = datetime(2026, 10, 27, 9, 30, tzinfo=CLOCK)   # UTC+8 当天上午
    today, yesterday = "26.10.27", "26.10.26"
    # 1) 今天第一次运行：无历史运行、无产物，R_first 就是当前号，当日序号 1。
    assert ci_version_numbers([], [], 210, now) == (today, 1, 210, 210)
    # 2) 今天已有两条运行（含一次失败）：按最小 run_number 锚定，失败运行同样占号。
    runs = [run(207, "2026-10-27T00:10:00+00:00"), run(209, "2026-10-27T00:30:00+00:00")]
    assert ci_version_numbers(runs, [], 210, now) == (today, 4, 210, 207)
    # 3) 昨天的运行不算今天：仍按今天首条起算。
    assert ci_version_numbers([run(200, "2026-10-26T12:00:00+00:00")], [], 210, now) == (today, 1, 210, 210)
    # 4) pull_request 运行永不计入。
    assert ci_version_numbers([run(205, "2026-10-27T00:05:00+00:00", "pull_request")], [], 210, now) \
        == (today, 1, 210, 210)
    # 5) 产物反推锚点：26.10.27.3.500 → R_first=498，当前 503 就是当日第 6 条。
    assert ci_version_numbers([], [art(f"Selffont-{today}.3.500", 1)], 503, now) \
        == (today, 6, 503, 498)
    # 6) 两个锚点取小：运行最小号 496 比产物反推的 498 更早。
    assert ci_version_numbers([run(496, "2026-10-27T00:01:00+00:00")],
                              [art(f"Selffont-{today}.3.500", 1)], 503, now) == (today, 8, 503, 496)
    # 7) 段数不是五段、或日期不是今天的产物不参与锚定。
    assert ci_version_numbers([], [art(f"Selffont-{today}.3", 1),
                                   art(f"Selffont-{yesterday}.3.500", 2)], 210, now) \
        == (today, 1, 210, 210)
    # 8) 当日序号 0、总序号小于当日序号的畸形名忽略，不当锚点。
    assert ci_version_numbers([], [art(f"Selffont-{today}.0.500", 1),
                                   art(f"Selffont-{today}.5.3", 2)], 210, now) == (today, 1, 210, 210)
    # 9) 锚点比当前号还大（旧运行已删）时钳到当前号，当日序号不小于 1。
    assert ci_version_numbers([], [art(f"Selffont-{today}.3.600", 1)], 210, now) == (today, 1, 210, 210)
    # 10) 日界按 UTC+8：UTC 10-27 16:30 = UTC+8 10-28 00:30，日期跨到 28 号，前一条 23:00 的运行不算。
    late = datetime(2026, 10, 27, 16, 30, tzinfo=timezone.utc)
    assert ci_version_numbers([run(300, "2026-10-27T15:00:00+00:00")], [], 301, late) \
        == ("26.10.28", 1, 301, 301)
    # 日期段格式：yy.m.d，月日不补零。
    assert re.fullmatch(r"\d{2}\.(1[0-2]|[1-9])\.(3[01]|[12][0-9]|[1-9])", ci_version_numbers([], [], 1, now)[0])
    # 产物名反推的边界：day=1 时 R_first 就是总序号本身。
    assert artifact_anchor(f"Selffont-{today}.1.700", today) == 700
    assert artifact_anchor(f"Selffont-{today}.2.700", today) == 699
    assert artifact_anchor("Selffont-26.10.27", today) is None


# ---------------------------------------------------------------- 火狐（Gecko）接入

@check
def firefox_bridge():
    """火狐接入：首选项只前置不清空 + install/remove 行为（PATH 上的 am 用替身）。"""
    config = (ROOT / "module/geckoview-config.yaml").read_text(encoding="utf-8")
    assert config.startswith("prefs:\n") or "\nprefs:\n" in config, "Gecko 配置必须只有 prefs 段"
    assert "  layout.css.font-variations.enabled: true" in config.splitlines(), \
        "Gecko 必须启用 CSS 可变字体支持，才能按 ital 轴绘制真斜体"
    lines = [line.strip() for line in config.splitlines() if line.strip().startswith("font.name-list.")]
    assert len(lines) >= 20, f"首选项太少：{len(lines)}"
    for line in lines:  # 只插入不清空：开头是谁由 NATIVE_FIRST 定，后面原样保留 Gecko 默认回退链
        name_list_ok(line)

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
        (modpath / "fonts-insert.xml").write_text(
            '    <font weight="400" style="normal">Any-Name.ttf</font>\n', encoding="utf-8")
        (modpath / "system/fonts/Any-Name.ttf").write_bytes(b"font")
        system = tmp / "sysroot"
        # AOSP 读 /system/etc/font_fallback.xml；ColorOS 读 /system_ext/etc/fonts_base.xml 与
        # fonts_ule.xml（设备日志实证）。库存 fonts.xml 一律不碰。
        # 设备自己那份：ColorOS 味——OPPO Sans 打头、中日韩语言族、非中日韩语言族、emoji 族、
        # 注释、以及一条自闭合族。整份替换会把这些 OEM 字件全删掉，所以只许插不许换。
        stock_legacy = """<?xml version="1.0" encoding="utf-8"?>
<familyset version="23">
    <!-- first font is default -->
    <family>
        <font weight="400" style="normal">OPPOSans-Regular.ttf</font>
        <font weight="700" style="normal">OPPOSans-Bold.ttf</font>
    </family>
    <family name="sans-serif">
        <font weight="400" style="normal">OPPOSans-Regular.ttf</font>
    </family>
    <family name="serif">
        <font weight="400" style="normal">NotoSerif-Regular.ttf</font>
    </family>
    <family lang="zh,zh-Hans,zh-Hant">
        <font weight="400" style="normal">NotoSansCJKsc-Regular.otf</font>
    </family>
    <family lang="ja">
        <font weight="400" style="normal">NotoSansCJKjp-Regular.otf</font>
    </family>
    <family lang="und-Arab">
        <font weight="400" style="normal">NotoNaskhArabic.ttf</font>
    </family>
    <family lang="und-Zsye">
        <font weight="400" style="normal">NotoColorEmoji.ttf</font>
    </family>
    <family name="empty-self-close" />
</familyset>
"""
        for directory in ("system/etc", "system_ext/etc", "product/etc"):
            (system / directory).mkdir(parents=True)
            (system / directory / "fonts.xml").write_text(stock_legacy, encoding="utf-8")
        (system / "system/etc/font_fallback.xml").write_text("<familyset>old-modern</familyset>")
        (system / "system/etc/font_fallback_cjkvf.xml").write_text("<familyset>old-cjkvf</familyset>")
        (system / "system/etc/fonts_customization.xml").write_text("<other-schema/>")
        (system / "system_ext/etc/fonts_base.xml").write_text("<familyset>old-coloros-base</familyset>")
        (system / "system_ext/etc/fonts_ule.xml").write_text("<familyset>old-coloros-ule</familyset>")
        env = {**os.environ, "MODPATH": str(modpath), "SELFFONT_SYSTEM_ROOT": str(system)}
        harness = modpath / "harness.sh"
        harness.write_text('ui_print() { echo "$@"; }\n'
                           'abort() { echo "ABORT: $*" >&2; exit 1; }\n'
                           f'. "{modpath / "customize.sh"}"\n')

        result = sh([str(harness)], env)
        assert result.returncode == 0, result.stderr
        # 投放设备实际会读的每一份配置（AOSP 的 font_fallback* 与 ColorOS 的 fonts_base / fonts_ule），
        # 内容都是同一份新语法；库存 fonts.xml 与 fonts_customization.xml 都不碰。
        for relative in ("system/etc/font_fallback.xml", "system/etc/font_fallback_cjkvf.xml",
                         "system/system_ext/etc/fonts_base.xml", "system/system_ext/etc/fonts_ule.xml"):
            target = modpath / relative
            assert target.read_text() == "<familyset modern/>", f"{relative} 应放新语法"
        # Skia 只读 /system/etc/fonts.xml（SkFontMgr_android_parser.cpp 写死）；插入而不替换：
        # 原有每一行（含 OEM 字件、注释、自闭合族）逐字保留，只在我们该管的三类族里加行。
        skia = (modpath / "system/etc/fonts.xml").read_text(encoding="utf-8")
        assert skia.splitlines()[:0] == []
        # 去掉我们加的字件行之后，设备原文件的每一行都必须**按原顺序**保留
        # （新增的是「默认链那一族」的外壳两行，所以不是逐行相等，而是原文件是子序列）。
        kept = [line for line in skia.splitlines() if "Any-Name.ttf" not in line]
        original = stock_legacy.splitlines()
        index = 0
        for line in kept:
            if index < len(original) and line == original[index]:
                index += 1
        assert index == len(original), f"设备原文件被改动：只剩 {index}/{len(original)} 行按序保留"
        blocks = re.split(r"(?=<family[ >])", skia)
        ours = [b for b in blocks if "Any-Name.ttf" in b]
        # 4 处：新建的默认链 1 处 + sans-serif + zh + ja（其余语言族一概不插）。
        assert len(ours) == 4, f"应插 4 处（新建默认族 + sans-serif + zh + ja），实际 {len(ours)}"
        assert any("OPPOSans-Regular.ttf" in b and "Any-Name.ttf" in b for b in ours), "默认链没插到 OPPO Sans 前面"
        assert not any("NotoNaskhArabic" in b or "NotoColorEmoji" in b or "NotoSerif" in b
                       for b in ours), "非中日韩语言族 / serif / emoji 不该插"
        for directory in ("system_ext/etc", "product/etc"):
            assert not (modpath / directory / "fonts.xml").exists(), \
                f"{directory} 的 fonts.xml 不该被替换"
        assert not (modpath / "system/etc/fonts_customization.xml").exists(), "自选配置不该被碰"
        assert "已替换 4 份字体配置" in result.stdout, "应报告替换数量：" + result.stdout
        assert "Skia 配置 /system/etc/fonts.xml：已插 4 处" in result.stdout, \
            "应报告 Skia 插入位置数：" + result.stdout

        # 设备一份可替换配置都没有（Android 15 以下）→ 中止安装，不假装成功。
        for relative in ("system/etc/font_fallback.xml", "system/etc/font_fallback_cjkvf.xml",
                         "system_ext/etc/fonts_base.xml", "system_ext/etc/fonts_ule.xml"):
            (system / relative).unlink()
        result = sh([str(harness)], env)
        assert result.returncode != 0 and "没有可替换的字体配置" in result.stderr, result
        (system / "system/etc/font_fallback.xml").write_text("<familyset>old-modern</familyset>")
        (system / "system/etc/font_fallback_cjkvf.xml").write_text("<familyset>old-cjkvf</familyset>")
        (system / "system_ext/etc/fonts_base.xml").write_text("<familyset>old-coloros-base</familyset>")
        (system / "system_ext/etc/fonts_ule.xml").write_text("<familyset>old-coloros-ule</familyset>")

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
        result = sh([str(action), "web"], env)  # 网页字体那条：keep → block
        assert result.returncode == 0 and state.read_text().strip() == "block", result
        assert re.search(rf"^{re.escape(WEB_FONT_ACTIVE)}$", bridge.read_text(encoding="utf-8"), re.M), \
            "toggle 没变回压"
        # 模块更新（customize.sh）刷新副本时按状态走：先在管理器里选 keep，再跑一次安装脚本。
        assert sh([str(action), "web"], env).returncode == 0 and state.read_text().strip() == "keep"
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
        # 管理器按钮的默认动作 = 字体热切换（不是网页字体）：干跑一遍，只验接线与输出。
        dry = {**env, "SELFFONT_DRY_RUN": "1", "SELFFONT_STATE": str(tmp / "hot.state"),
               "SELFFONT_SYSTEM_ROOT": str(tmp), "SELFFONT_RELOAD": "none"}
        result = sh([str(action)], dry)
        assert result.returncode == 0 and "dry-run" in result.stdout and "现在状态" in result.stdout, result
        status_out = sh([str(action), "status"], dry).stdout
        assert "状态 off" in status_out, status_out
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


@check
def supplemental_font_reference():
    """OFL 替代字体必须处在通用回退链，紧随 NotoUnicode，且来源固定。"""
    root = ET.fromstring((ROOT / "fonts.xml").read_bytes())
    references = [(node.text or "").strip() for node in root.iter("font")]
    filename = NOTO_MUSIC_SOURCE["filename"]
    assert references.count(filename) == 1, f"{filename} 必须恰好引用一次"
    assert "Symbola-13.otf" not in references, "不可再分发的 Symbola 不得重新打包"
    assert references.index(filename) == references.index("NotoUnicode.otf") + 1, \
        "Noto Music 应在 NotoUnicode 之后补缺，避免覆盖它的控制字符字形"
    families = [family for family in root.findall("family")
                if any((node.text or "").strip() == filename for node in family.findall("font"))]
    assert len(families) == 1 and families[0].get("lang") is None, \
        "通用音乐符号回退不应误标为单一 Unicode Script"
    assert len(NOTO_MUSIC_SOURCE["sha256"]) == len(NOTO_MUSIC_SOURCE["license_sha256"]) == 64
    assert NOTO_MUSIC_SOURCE["coverage_range"] == (0x1D100, 0x1D1FF)
    assert NOTO_MUSIC_SOURCE["minimum_outline_mappings"] >= 200


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


@check
def module_hotswap():
    """热切换：真机两次事故后的五条规矩，逐条可判。

    ① 不许任何形式的整目录 bind 到 /system 路径（目录只走 overlay，bind 只收常规文件）；
    ② 空文件占位只在 `SELFFONT_SYSTEM_ROOT` 假根下建；
    ③ 挂之前记录目标顶层 mnt_id，`off`/`panic` 只摘「顶层 mnt_id 等于我们记的那个」的层，
       被别的东西盖住就报出来、不猜、不摘别人的；
    ④ 失败一定回滚到挂之前的状态（按 done 反序摘）；
    ⑤ `panic` 摘掉本脚本挂过的一切、删 merged/upper/work，打印 /proc/mounts 里 fonts 剩余行。

    下面用假根 + 只改挂载表的 `mount`/`umount` 桩跑**真脚本**：验的是我的计划、守卫、
    mnt_id 记账与回滚分支，**不是**真机能不能挂上——overlay 能不能在这台 ROM 的 init
    命名空间挂成功、SELinux 放不放行，只有真机能回答，一条都不假装。
    """
    module = ROOT / "module"
    scripts = sorted(module.glob("*.sh"))
    assert scripts, "module/ 里没有脚本"
    for script in scripts:
        result = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"{script.name} 语法错误：{result.stderr.strip()}"
    hotswap = module / "hotswap.sh"
    text = hotswap.read_text(encoding="utf-8")
    for needed in ("mount -t overlay", "upperdir=", "mount --bind", "umount", "sha256sum",
                   "cmd font", "guard_mount", "top_mnt_id", "mnt_id_exists", "cmd_panic"):
        assert needed in text, f"hotswap.sh 少了关键一步：{needed}"
    assert 'ns_run sh "$SELF" __ns' in text, "命名空间里的第二趟没有走 `sh 本脚本`"
    # ② 全文件只许一处建占位文件，而且必须在假根守卫之后。
    assert text.count(': > "$abs"') == 1, "建占位文件的写法变了，检查要跟着改"
    guard = 'if [ -n "$ROOT" ] && [ ! -e "$abs" ]; then'
    assert guard in text and text.index(guard) < text.index(': > "$abs"'), \
        "空文件占位没有假根守卫：真机 /system 只读，会在 /data 里留下成排 0 字节文件"
    action = (module / "action.sh").read_text(encoding="utf-8")
    assert "hotswap.sh" in action, "action.sh 的默认动作没有接到热切换"

    def run(script: Path, *args: str, extra_env=None):
        env = {**os.environ, "PATH": os.environ["PATH"], **(extra_env or {})}
        return subprocess.run(["sh", str(script), *args], env=env, capture_output=True, text=True)

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        mod = tmp / "mod"
        (mod / "system/fonts").mkdir(parents=True)
        (mod / "system/etc").mkdir(parents=True)
        shutil.copy2(hotswap, mod / "hotswap.sh")
        for name in ("Noto.ttf", "Roboto-Regular.ttf"):
            (mod / "system/fonts" / name).write_bytes(b"sys-font")
        (mod / "system/fonts/Selffont-WenYuanRoundedSCVF.ttf").write_bytes(b"new-primary")
        (mod / "system/fonts/SelfroundsCJK-VF-26.10.31.5.249.ttf").write_bytes(b"new-cjk")
        (mod / "system/etc/fonts_base.xml").write_bytes(b"xml")
        (mod / "system/etc/fonts_extra.xml").write_bytes(b"xml-extra")   # 假系统里没有
        sysroot = tmp / "sys"
        (sysroot / "system/fonts").mkdir(parents=True)
        (sysroot / "system/etc").mkdir(parents=True)
        for name in ("Noto.ttf", "Roboto-Regular.ttf"):
            (sysroot / "system/fonts" / name).write_bytes(b"sys-font")
        (sysroot / "system/etc/fonts_base.xml").write_bytes(b"xml")
        state = tmp / "st"
        fake_mountinfo = tmp / "mountinfo"
        fake_mountinfo.write_text(
            f"100 30 0:50 / {sysroot}/system/fonts rw - overlay overlay "
            f"lowerdir=/data/adb/modules/MFGA/system/fonts:/system/fonts\n", encoding="utf-8")
        (tmp / "idseq").write_text("100", encoding="utf-8")

        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "mount").write_text(
            '#!/bin/sh\nprintf "mount %s\\n" "$*" >> "$LOG"\n'
            'case "$1" in\n'
            '  --bind) src=$2; dst=$3; type=none; opts="rw - none bind" ;;\n'
            '  -t) type=$2; src=$3; opts=$5; dst=$6\n'
            '      [ -f "$FAIL_OVERLAY" ] && { echo "mount: invalid argument" >&2; exit 32; } ;;\n'
            '  *) exit 1 ;;\n'
            'esac\n'
            'id=$(( $(cat "$IDSEQ") + 1 )); echo "$id" > "$IDSEQ"\n'
            'printf "%s 30 0:50 / %s rw - %s %s %s\\n" "$id" "$dst" "$type" "$src" "$opts" >> "$MI"\n'
            'if [ "$type" = none ]; then cp -f "$src" "$dst"; '
            'else for f in "$UP"/*; do [ -f "$f" ] && cp -f "$f" "$dst/${f##*/}"; done; fi\n'
            'exit 0\n', encoding="utf-8")
        (bin_dir / "umount").write_text(
            '#!/bin/sh\nprintf "umount %s\\n" "$*" >> "$LOG"\nmp=$1\n'
            '[ -f "$FAIL_UMOUNT" ] && { echo "umount: $mp: Device or resource busy" >&2; exit 32; }\n'
            'top=$(awk -v mp="$mp" \'$5==mp && $1+0>m {m=$1+0} END {print m+0}\' "$MI")\n'
            '[ "$top" -eq 0 ] && exit 32\n'
            'awk -v id="$top" \'$1 != id\' "$MI" > "$MI.new" && mv "$MI.new" "$MI"\n'
            'exit 0\n', encoding="utf-8")
        (bin_dir / "nsenter").write_text('#!/bin/sh\nshift 3\nexec "$@"\n', encoding="utf-8")
        (bin_dir / "cmd").write_text('#!/bin/sh\nexit 1\n', encoding="utf-8")
        for path in bin_dir.iterdir():
            path.chmod(0o755)

        log = tmp / "log"
        env = {"SELFFONT_SYSTEM_ROOT": str(sysroot), "SELFFONT_STATE": str(state),
               "SELFFONT_UPPER": str(tmp / "upper"), "SELFFONT_WORK": str(tmp / "work"),
               "SELFFONT_MERGED": str(tmp / "merged"), "SELFFONT_MOUNTINFO": str(fake_mountinfo),
               "SELFFONT_NSENTER": "nsenter -t 1 -m",
               "PATH": f"{bin_dir}:{os.environ['PATH']}", "LOG": str(log),
               "IDSEQ": str(tmp / "idseq"), "MI": str(fake_mountinfo), "UP": str(tmp / "upper")}

        def unit_lines():
            path = Path(str(state) + ".units")
            return path.read_text().splitlines() if path.exists() else []

        def fake_mounts():
            return fake_mountinfo.read_text().splitlines()

        # ②(计划) + ��：dry-run 只打印，一条 overlay、不逐字体 bind、不动系统。
        result = run(mod / "hotswap.sh", "on", "--dry-run", extra_env=env)
        assert result.returncode == 0, result.stderr
        assert len([ln for ln in result.stdout.splitlines() if "mount -t overlay" in ln]) == 1, result.stdout
        assert not [ln for ln in result.stdout.splitlines()
                    if "mount --bind" in ln and "/system/fonts/" in ln], "出现了逐字体 bind（②）"
        assert not (sysroot / "system/etc/fonts_extra.xml").exists(), "dry-run 动了系统"

        # 正常 on：③ 记 mnt_id（pre 里应看到挂之前那层的 100），② 只有一条 overlay。
        log.write_text("", encoding="utf-8")
        result = run(mod / "hotswap.sh", "on", "--reload=none", extra_env=env)
        assert result.returncode == 0, (result.stdout, result.stderr)
        units = unit_lines()
        assert units[0].startswith("#boot "), units
        ids = {}
        for line in units[1:]:
            kind, rel, mid = line.split("|")
            ids[rel] = mid
            assert mid.isdigit(), f"账里没记 mnt_id：{line}"
        assert "overlay|system/fonts" in [ln.rsplit("|", 1)[0] for ln in units[1:]], units
        pre = Path(str(state) + ".pre").read_text()
        assert "pre|overlay|system/fonts|100" in pre, f"挂之前没记下目标那层的 mnt_id：{pre}"
        assert len([ln for ln in fake_mounts() if "upperdir=" in ln]) == 1, "挂出来的 overlay 不是一条"
        # ② 假根里的占位文件：只在这个假系统里出现，真机路径上没有这段代码
        assert (sysroot / "system/etc/fonts_extra.xml").exists(), "假根里没建占位文件"
        assert result.returncode == 0

        # ③ 有人在我们上面盖了一层：status 变 partial，off 不许摘别人的层。
        foreign = (f"900 30 0:60 / {sysroot}/system/fonts rw - f2fs /dev/block/dm-76 rw\n")
        fake_mountinfo.write_text(fake_mountinfo.read_text() + foreign, encoding="utf-8")
        assert run(mod / "hotswap.sh", "status", extra_env=env).stdout.strip() == "partial"
        log.write_text("", encoding="utf-8")
        result = run(mod / "hotswap.sh", "off", "--reload=none", extra_env=env)
        assert result.returncode == 1, (result.stdout, result.stderr)
        assert "上面还压着 mnt_id 900" in result.stdout, result.stdout
        assert not [c for c in log.read_text().splitlines() if c.endswith("/system/fonts")], \
            "被盖住时仍然按路径去摘了别人的层"
        assert any(line.startswith("900 ") for line in fake_mounts()), "把别人的挂载摘掉了"
        # ③ 第二道：就算计划里混进了被盖住的那一层，__ns undo 也不许按路径去摘
        crafted = tmp / "undo.plan"
        crafted.write_text(f"overlay|system/fonts|{ids['system/fonts']}\n", encoding="utf-8")
        log.write_text("", encoding="utf-8")
        result = run(mod / "hotswap.sh", "__ns", "undo", str(crafted), extra_env=env)
        assert result.returncode != 0 and "被别的挂载盖住" in result.stdout, result.stdout
        assert not [c for c in log.read_text().splitlines() if c.startswith("umount ")], \
            "ns_undo 按路径摘了被盖住的层（③）"
        assert any(line.startswith("900 ") for line in fake_mounts()), "ns_undo 摘了别人的挂载"
        # 撤掉那层，off 才能按 mnt_id 精确摘掉我们的
        fake_mountinfo.write_text("\n".join(ln for ln in fake_mounts() if not ln.startswith("900 ")) + "\n",
                                  encoding="utf-8")
        log.write_text("", encoding="utf-8")
        result = run(mod / "hotswap.sh", "off", "--reload=none", extra_env=env)
        assert result.returncode == 0, (result.stdout, result.stderr)
        umounts = [c for c in log.read_text().splitlines() if c.startswith("umount ")]
        assert umounts, "off 一个都没摘"
        assert all(c.endswith(str(sysroot) + "/system/fonts") or "/system/etc/" in c for c in umounts), umounts
        assert [line for line in fake_mounts() if line.startswith("100 ")], "把开机那层也摘了（③）"

        # ④ 失败回滚：overlay 挂不上时，已经挂上的配置要摘回去、账清空。
        fail_marker = tmp / "fail"
        fail_marker.write_bytes(b"")
        log.write_text("", encoding="utf-8")
        result = run(mod / "hotswap.sh", "on", "--reload=none", extra_env={**env, "FAIL_OVERLAY": str(fail_marker)})
        assert result.returncode == 1, (result.returncode, result.stdout)
        assert "已回滚到挂之前" in result.stdout, result.stdout
        assert any(c.startswith("umount ") for c in log.read_text().splitlines()), "失败后没有回滚（④）"
        assert not unit_lines() and not Path(str(state) + ".journal").exists(), "回滚后账没清"
        assert not Path(str(state) + ".pre").exists(), "回滚后 pre 没清"

        # ① 守卫：拿目录当 bind 源（= 把 merged 绑到 /system/fonts 那种写法）直接拒，连 mount 都不调。
        bad = tmp / "bad.plan"
        bad.write_text("overlay|system/fonts\nfile|system/fonts\n", encoding="utf-8")
        log.write_text("", encoding="utf-8")
        result = run(mod / "hotswap.sh", "__ns", "apply", str(bad), extra_env=env)
        assert result.returncode != 0 and "不是常规文件" in result.stdout, result.stdout
        assert not [c for c in log.read_text().splitlines() if "--bind" in c], "目录 bind 被放行（①）"
        bad.write_text("overlay|system/fonts\noverlay|system/fonts\n", encoding="utf-8")
        result = run(mod / "hotswap.sh", "__ns", "apply", str(bad), extra_env=env)
        assert result.returncode != 0 and "只允许 1 条" in result.stdout, result.stdout

        # ⑤ panic：被盖住时不动别人的层、也不删正被挂着的 upper；清干净后删目录并报告。
        run(mod / "hotswap.sh", "on", "--reload=none", extra_env=env)
        (tmp / "merged").mkdir()
        (tmp / "merged" / "x.ttf").write_bytes(b"junk")
        fake_mountinfo.write_text(fake_mountinfo.read_text() + foreign, encoding="utf-8")
        result = run(mod / "hotswap.sh", "panic", extra_env=env)
        assert result.returncode == 1, (result.stdout, result.stderr)
        assert (tmp / "upper").exists(), "还没摘干净就删了正被 overlay 用的 upper"
        assert not (tmp / "merged").exists(), "panic 没删 merged（旧版垃圾）"
        assert "与 fonts 相关的剩余行" in result.stdout, result.stdout
        fake_mountinfo.write_text("\n".join(ln for ln in fake_mounts() if not ln.startswith("900 ")) + "\n",
                                  encoding="utf-8")
        result = run(mod / "hotswap.sh", "panic", extra_env=env)
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert not (tmp / "upper").exists() and not (tmp / "work").exists(), "panic 没删 upper/work"
        assert not Path(str(state) + ".units").exists(), "panic 没清账"
        assert all(not ln.startswith("100 ") or "/system/fonts" in ln for ln in fake_mounts())
        assert len([ln for ln in fake_mounts() if "upperdir=" in ln]) == 0, "panic 之后还有我们的 overlay"


@check
def cjk_font():
    """二创汉字字库：数据能读、能编成 OTF、在配置里单独成族且排在主字体之前。

    只用 3 个字验管线，不在这里跑两万字（--check 要能几秒跑完）。
    """
    import io as _io
    assert CJK_DATA.exists(), f"缺少二创汉字数据：{CJK_DATA}"
    assert CJK_LICENSE.exists() and b"SIL OPEN FONT LICENSE" in CJK_LICENSE.read_bytes(), \
        "二创字体必须随包带 OFL 文本（母版 Maruko 是 SIL OFL 1.1）"
    global CJK_RELEASE_VERSION
    saved, CJK_RELEASE_VERSION = CJK_RELEASE_VERSION, None   # 检查固定用迭代版的命名
    try:
        return _cjk_font_check()
    finally:
        CJK_RELEASE_VERSION = saved


def _cjk_font_check():
    import io as _io
    import sys as _sys

    _sys.path.insert(0, str(ROOT / "tools"))
    import cjk_vf                                   # 读 GPOS 里的字偶距给自己验
    glyphs = cjk_glyphs()
    assert len(glyphs) >= 19000, f"二创汉字只读到 {len(glyphs)} 字"
    # `A` `H` `o` `y` 是给字偶距自检用的：母版真排的 `Ay` 是咬进去的（最小白 44），
    # `HH`/`oo` 没压过（168/96）。四个字两组对照，正好能判「有没有压错对象」。
    sample = {cp: glyphs[cp] for cp in
              (0x4E00, 0x53E3, 0x9F98, 0x31, 0x20, 0x41, 0x48, 0x6F, 0x79,
               0x6A, 0x5B, 0x7B, 0x2B) if cp in glyphs}
    data = build_cjk_font(dict(sample))          # build_vf 会消费传入的字典，这里给副本
    carrier = layout_metrics(TTFont(_io.BytesIO(make_carrier())))
    calibrated = build_cjk_font(dict(sample), carrier)
    # 高度重校准：和主字体（文渊）同一函数、同一空壳，行框必须是同一套数字。
    with TTFont(_io.BytesIO(calibrated)) as font:
        hhea, os2 = font["hhea"], font["OS/2"]
        assert (hhea.ascent, hhea.descent, hhea.lineGap) == (930, -250, 0), \
            f"汉字字件行高未对齐空壳：{hhea.ascent}/{hhea.descent}/{hhea.lineGap}"
        assert (os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap) == (930, -250, 0), \
            f"汉字字件 typo 未对齐空壳：{os2.sTypoAscender}/{os2.sTypoDescender}"
        low, high = ink_envelope(font)
        assert os2.usWinAscent >= high and os2.usWinDescent >= -low, \
            f"汉字字件裁剪包络切墨：ink={low}..{high} win={os2.usWinDescent}/{os2.usWinAscent}"
    with TTFont(_io.BytesIO(data)) as font:
        assert font["head"].unitsPerEm == 1000
        assert font["name"].getDebugName(1) == cjk_naming(None)[0]
        assert set(font.getBestCmap()) == set(sample), "码位没有一对一落进 cmap"
        # 字宽是构建期自算的：全角占一个 em，半角按本字墨宽加侧距。
        # 全写成 1000 的话，这个字件（排在主字体之前）会把拉丁和数字摊成方块。
        hmtx, cmap_here = font["hmtx"], font.getBestCmap()
        assert hmtx[cmap_here[0x4E00]][0] == 1000, "全角字宽必须是 1000"
        assert hmtx[cmap_here[0x31]][0] < 600, f"数字字宽没自算：{hmtx[cmap_here[0x31]][0]}"
        assert 0x20 in cmap_here, "空格没有补进 cmap：它在母版里没有轮廓，必须补空字形"
        assert hmtx[cmap_here[0x20]][0] == 250, f"空格字宽 {hmtx[cmap_here[0x20]][0]} 不等于四分之一 em"
        # 非字母的前进量取自母版逐字量出来的表（`tools/side_targets.bin`）：三档模型对它们
        # 量不准，`+` 曾差 194 单位、`[` `{` 被 200 的下限夹住。这里挡住「表丢了/没接上」。
        assert cjk_vf.side_target(0x2B)[0] > 850, "side_targets.bin 没接上：`+` 的前进量又被压扁了"
        assert hmtx[cmap_here[0x2B]][0] > 850, f"`+` 前进量 {hmtx[cmap_here[0x2B]][0]}，母版是 922"
        assert hmtx[cmap_here[0x5B]][0] > 280, f"`[` 前进量 {hmtx[cmap_here[0x5B]][0]}，母版是 317"
        assert hmtx[cmap_here[0x7B]][0] > 350, f"`{{` 前进量 {hmtx[cmap_here[0x7B]][0]}，母版是 389"
        # 负 LSB 的字必须留着负左边距：母版 `j` 的 lsb 是 −63，钩本来就伸到前一个字下面。
        # 这一条挡的是「按整字墨迹反推侧距」那个 bug——`j` 曾被整体右移 92 单位。
        assert hmtx[cmap_here[0x6A]][1] < 0, f"`j` 的左边距变成了 {hmtx[cmap_here[0x6A]][1]}，负 LSB 丢了"
        assert hmtx[cmap_here[0x6A]][0] < 260, f"`j` 的字宽 {hmtx[cmap_here[0x6A]][0]}，母版是 235"
        # 字偶距：目标是母版**真排**出来的白（tools/kern_targets.bin），不是一把固定尺。
        # 母版压过的 `Ay` 必须咬进去；母版没压过的 `HH`、只压 2 个单位的 `oo` 不许跟着压。
        assert "GPOS" in font, "字偶距没有写进 GPOS：母版里 Ay 靠字对咬合，缺了就散架"
        ay = cjk_vf.kern_value(font, 0x41, 0x79)
        hh = cjk_vf.kern_value(font, 0x48, 0x48)
        oo = cjk_vf.kern_value(font, 0x6F, 0x6F)
        assert ay <= -150, f"Ay 没有咬进去：{ay}（母版真排的笔距是 473，最小白 44）"
        assert abs(hh) < 12, f"HH 被压了：{hh}（母版 HH 的最小白 168，不该动）"
        assert -40 <= oo <= 0, f"oo 的字偶距越界：{oo}（母版 oo 最小白 96，本字件自然白是 111）"
        glyph_set = font.getGlyphSet()
        blanks = {f"uni{cp:04X}" for cp in (0x20,) if cp in sample}
        for name in font.getGlyphOrder()[1:]:
            pen = BoundsPen(glyph_set)
            glyph_set[name].draw(pen)
            if name in blanks:
                assert pen.bounds is None, f"{name} 是空白字符，不该有轮廓"
            else:
                assert pen.bounds is not None, f"{name} 没有轮廓"
    xml = configure_fonts((ROOT / "fonts.xml").read_bytes(), PRIMARY_NAME,
                          [{"axes": [("wght", 400)]}], cjk=True)
    root = ET.fromstring(xml)
    holders = [family for family in root.findall("family")
               if any((node.text or "").strip() == cjk_naming(None)[1] for node in family.findall("font"))]
    assert len(holders) == 1, "二创字件必须恰好出现在一个 family 里"
    alone = holders[0]
    assert len(alone.findall("font")) == 1, "二创字件不能与别的字件同族（真机会卡开机）"
    assert alone.get("lang") is None and alone.get("name") is None, "二创族放在默认区，不带语言/名字"
    order = list(root)
    primary_family = next(child for child in order
                          if child.tag == "family"
                          and any((node.text or "").strip() == PRIMARY_NAME
                                  for node in child.findall("font")))
    assert order.index(alone) < order.index(primary_family), \
        "二创族必须排在主字体之前，否则永远轮不到它"


def emit_cjk_font(out_dir: Path) -> None:
    """出二创汉字字件：数据 → 可变字体 → 行框锚定设备空壳 → 三个静态实例。

    这一段原来是 `tools/build_cjk.py`。规范禁止把一次性辅助脚本堆在仓库里（同一个
    `build.py` 能跑完的事，不该多一个入口），所以并回来当一个参数。
    """
    import io
    import time
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    out_dir.mkdir(parents=True, exist_ok=True)
    start = time.time()
    glyphs = cjk_glyphs()
    print(f"读数据 {len(glyphs)} 字 {time.time() - start:.1f}s", flush=True)

    # 度量空壳：设备上就是基础包里的 Roboto；本机用自检里的同一份夹具，行框同一套数字。
    carrier = layout_metrics(TTFont(io.BytesIO(make_carrier()), recalcBBoxes=False))
    print("空壳度量", carrier, flush=True)

    start = time.time()
    data = build_cjk_font(glyphs, carrier)
    print(f"编字体并校准 {len(data) / 1e6:.1f} MB {time.time() - start:.1f}s", flush=True)
    (out_dir / cjk_naming(CJK_RELEASE_VERSION)[1]).write_bytes(data)

    font = TTFont(io.BytesIO(data), recalcBBoxes=False)
    hhea, os2 = font["hhea"], font["OS/2"]
    print(f"  hhea {hhea.ascent}/{hhea.descent}/{hhea.lineGap}"
          f"  typo {os2.sTypoAscender}/{os2.sTypoDescender}/{os2.sTypoLineGap}"
          f"  win {os2.usWinAscent}/{os2.usWinDescent}")
    low, high = ink_envelope(font)
    print(f"  墨迹包络 {low}..{high}  字形数 {len(font.getGlyphOrder())}", flush=True)
    del font

    for weight in (300, 400, 500):
        inst = instantiateVariableFont(TTFont(io.BytesIO(data)), {"wght": weight})
        buf = io.BytesIO()
        inst.save(buf)
        (out_dir / f"static-{weight}.ttf").write_bytes(buf.getvalue())
        print(f"  静态 {weight} {len(buf.getvalue()) / 1e6:.1f} MB", flush=True)
    print("完成", flush=True)


def preview_chars(chars: str, glyphs: dict[int, dict]) -> dict[int, dict]:
    """预览选字：按输入顺序去重、跳过数据里没有的码位，返回按码位排序的子集。

    不做全量构建，是为了「改一笔、几秒钟看见」：数据改完直接跑
    `.venv/bin/python build.py --preview 鬱響鬢`，不必等 50 分钟的全量出件。
    """
    order = list(dict.fromkeys(cp for cp in map(ord, chars) if cp in glyphs))
    if not order:
        raise ValueError(f"这些字都不在 {CJK_DATA.name} 里：{chars!r}")
    return {cp: glyphs[cp] for cp in sorted(order)}


def emit_preview(chars: str, out_dir: Path, compare: Path | None = None, size: int = 200) -> None:
    """预览路径（规范「设计取向记录」要求的热重载）：只编选中的字，出小字体 + 母版对照图。

    `--compare` 给母版 TTF 时，用同一套 FreeType 渲染（`tools/freetype_iou.py`）出上下两排
    对照图，并打印每字 IoU；不给就只出 `preview.ttf`。产物写在 out_dir（默认 `work/preview/`），
    不入库。
    """
    import time

    start = time.time()
    glyphs = cjk_glyphs()
    print(f"读数据 {len(glyphs)} 字 {time.time() - start:.1f}s", flush=True)
    subset = preview_chars(chars, glyphs)
    start = time.time()
    data = build_cjk_font(dict(subset))
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "preview.ttf"
    target.write_bytes(data)
    print(f"编 {len(subset)} 字 → {target} {len(data) / 1024:.0f} KB {time.time() - start:.1f}s",
          flush=True)
    if compare is None:
        return

    import sys as _sys

    _sys.path.insert(0, str(ROOT / "tools"))
    from PIL import Image, ImageDraw, ImageFont
    import freetype_iou

    chars_sorted = [chr(cp) for cp in subset]
    cell_w = size + 60
    cell_h = size + 50
    gutter = 56
    width = gutter + cell_w * len(chars_sorted) + 20
    height = cell_h * 2 + 60
    canvas = Image.new("L", (width, height), 255)
    pen = ImageDraw.Draw(canvas)
    label_font = ImageFont.truetype(str(compare), 34)
    pen.text((8, 30), "母", font=label_font, fill=0)
    pen.text((8, cell_h + 30), "本", font=label_font, fill=0)
    values = []
    for index, char in enumerate(chars_sorted):
        x = gutter + index * cell_w
        pair = None
        for row, path in enumerate((compare, target)):
            ink, (dx, dy) = freetype_iou.bitmap(path, char, size)
            top = 30 + row * cell_h
            if ink.size:
                glyph = Image.new("L", (ink.shape[1], ink.shape[0]), 255)
                glyph.paste(0, mask=Image.fromarray((ink * 255).astype("uint8")))
                left = x + max((cell_w - ink.shape[1]) // 2 + dx, 0)
                canvas.paste(glyph, (left, top + size + dy))
        values.append(freetype_iou.compare(compare, target, char, size))
        pen.text((x + 4, 30 + 2 * cell_h - 40), f"{values[-1]:.3f}", font=label_font, fill=0)
    png = out_dir / "preview.png"
    canvas.save(png)
    print(f"对照图 {png}（上排母版、下排本版；每格下方是该字 IoU）", flush=True)
    ordered = sorted(values)
    print(f"IoU 中位 {ordered[len(ordered) // 2]:.3f}  最低 {ordered[0]:.3f}  "
          f"（{len(values)} 字，{size} px 同基线）", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="跑内建自检：不下载、不打包")
    parser.add_argument("--cjk-font", type=Path, metavar="DIR",
                        help="只出二创汉字字件（可变 + 三个静态实例）到 DIR，不下载、不打包")
    parser.add_argument("--preview", metavar="字…",
                        help="只编这几个字出预览小字体（几秒），配合 --compare 出母版对照图")
    parser.add_argument("--preview-out", type=Path, metavar="DIR", default=ROOT / "work" / "preview",
                        help="预览产物目录（默认 work/preview/，不入库）")
    parser.add_argument("--compare", type=Path, metavar="TTF",
                        help="预览对照用的母版字体（不给就只出 preview.ttf）")
    parser.add_argument("--base", help="基础包 ZIP：本地路径或 URL（默认下载并缓存）")
    parser.add_argument("--font", metavar="PATH|URL", help="主字体：本地文件或 URL（默认用内置来源）")
    parser.add_argument("--output", type=Path,
                        help="产物路径（默认跟版本走：build/Selffont-<五段版本>.zip）")
    parser.add_argument("--build", help="总序号：版本号倒数第一段，同时写进 versionCode（默认读 $SELFFONT_BUILD）")
    parser.add_argument("--day", help="当日序号：不传就是四段版本 yy.m.d.总序号（默认读 $SELFFONT_DAY）")
    parser.add_argument("--date", help="版本日期 YY.M.D（默认读 $SELFFONT_DATE）")
    parser.add_argument("--query-ci", action="store_true",
                        help="用 gh api 现场取号：总序号=本次 run_number，当日序号按差值锚定法算；"
                             "不查 git 提交数；取不到就报错停止（不出包、不上传），"
                             "不与 --build/--day/--date 混用")
    parser.add_argument("--keep-web-fonts", action="store_true",
                        help="放行网页自带字体（图标字体等）；默认压成文渊")
    args = parser.parse_args()
    if args.preview:
        emit_preview(args.preview, args.preview_out, args.compare)
    elif args.cjk_font:
        emit_cjk_font(args.cjk_font)
    elif args.check:
        run_checks()
    else:
        build(base=args.base, font=args.font, output=args.output, build_num=args.build,
              day=args.day, date=args.date, query=args.query_ci,
              keep_web_fonts=args.keep_web_fonts)


if __name__ == "__main__":
    main()
