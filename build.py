#!/usr/bin/env python3
"""Selffont 打包器：一个主字体 + 基础包 + 固定许可补充字体 → KernelSU 模块 zip;--check 跑内建自检。

  pip install -r requirements.txt
  python3 build.py --check                       # 自检：无框架，assert 直跑，不下载不打包
  python3 build.py [--font X.ttf] [--base Y.zip] [--output O.zip]
                   [--build 总序号] [--day 当日序号] [--date YY.M.D] [--query-ci]

版本号按全局规范：yy.m.d.当日序号.总序号（五段，展示不含 v），versionCode = 总序号。号源只有
一处：CI 运行数。总序号 = `build.yml` 本次运行的 `run_number` 原值，不做基线相减；当日序号
（当日 = `run_started_at` 转 UTC+8）用差值锚定法算：取当日现存 `build.yml` 运行的最小
`run_number`，与当日现存产物 `selffont-yy.m.d.d0.r0` 反推出的 `r0 - d0 + 1`，两者取小作当日
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
# 二创汉字的语言标签：只认汉字场景（简/繁），不认 ja / ko —— 假名、谚文不归它，
# 日文里的汉字也该跟系统走文渊的字形。见 configure_fonts 里 Minikin 打分的注释。
CJK_LANG = "zh-Hans,zh-Hant"
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
PROJECT = "selffont"  # 产物名与 artifact 名的项目段：<项目名>-<版本>；自版模块就叫这个前缀
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
                    cjk: bool = False, cjk_name: str | None = None,
                    cjk_family: str | None = None) -> bytes:
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
    # 二创汉字族：单独一个 family，**带 zh 语言标签**，排在所有 CJK 语言区族之前。
    # 它是可变字体，字件节点必须带 supportedAxes；混写静态字件会让 ColorOS 卡第一屏，
    # 所以它只放自己一个字件（纯族，形状与 swap_fonts 产出的主字体族一致）。
    #
    # 为什么非带 lang 不可：Minikin 的 getFamilyForChar 逐族打分，不是「语言区整段优先」，
    # 也不是「默认区按文件顺序取第一个有码位的」——
    #   score = 覆盖分 << 29 | 语言分 << 1 | 变体分          （calcFamilyScore）
    # 覆盖分只有「第 0 族且命中」拿满分，其余有码位的一律 1 分，所以**多个族都覆盖同一码位时，
    # 由语言分决定胜负，分数相同才按文件顺序取靠前的**。不带 lang 的匿名族语言分恒为 0，
    # 会被任何 lang 匹配上的 zh 族（语言分 ≥1，语言+文字双匹配拿 4）压掉。
    # 自 dafc875 起的配置正是这样：第 1 族（匿名，我们）对 法 覆盖=1、语言=0，
    # 第 10/11/121/122 族（lang=zh…，现已换成主字体=文渊）覆盖=1、语言=4 → 中文全落文渊。
    # 补上 lang 并抢在它们前面之后，两族同分，按顺序取靠前的那个 —— 我们。
    # 缺字（全角标点、假名、扩展区…）语言分再高也拿不到覆盖分，照旧落语言区里的主字体。
    index = list(root).index(default) + 1
    if cjk:
        cjk_locale_at = [i for i, family in enumerate(root)
                         if is_cjk_locale(family.get("lang")) and not family.get("variant")]
        if cjk_locale_at:
            index = min([index, *cjk_locale_at])  # 抢在第一个 CJK 语言区族之前：同分时顺序取胜
        own = ET.Element("family")
        own.set("lang", CJK_LANG)
        if cjk_family:
            own.set("name", cjk_family)      # 母版直通：字节没改，族名也得是它自己的
        if cjk_family:
            # 静态母版：写 weight，不能写 supportedAxes（那是可变字体才有的）
            node = ET.SubElement(own, "font", style="normal", weight="400")
        else:
            # 可变字件：写 supportedAxes，不写 weight（运行时按 wght 实例化）。
            node = ET.SubElement(own, "font", style="normal", supportedAxes=CJK_AXES)
        node.text = cjk_name or cjk_naming(CJK_RELEASE_VERSION)[1]
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
    """产物名跟版本走：selffont-<版本>.zip（规范 <项目名>-<版本>）；五段或退化四段都认，别的不出包。"""
    stamped = re.search(r"^version=(.+)$", prop, flags=re.M)
    core = stamped.group(1) if stamped else ""
    if not (VERSION_RE.fullmatch(core) or VERSION_RE4.fullmatch(core)):
        raise ValueError(f"产物名需要规范版本号（五段，本地手工省略 --day 时退化四段），实际 version={core!r}："
                         "先 --query-ci 取数，或显式传 --date/--day/--build")
    return ROOT / "build" / f"{PROJECT}-{core}.zip"


def version_core(date: str, build: str, day: str | None = None) -> str:
    """版本号核心：五段 yy.m.d.当日序号.总序号；day 为 None（本地手工省略 --day）时退化四段 yy.m.d.总序号。"""
    return f"{date}.{day}.{build}" if day else f"{date}.{build}"


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


# 取号只有一份实现：`tools/ci_version.py`（纯标准库，selfrounds／hotswap 两条工作流没有
# fontTools 也能直接跑）。这里只导入，不复制——两处各写一遍，迟早会算出差一个数。
def _load_version_module():
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "tools"))
    import ci_version
    return ci_version


_ci_version = _load_version_module()
KEEP_RUNS = _ci_version.KEEP_RUNS
artifact_anchor = _ci_version.artifact_anchor
check_number = _ci_version.check_number
ci_version_numbers = _ci_version.ci_version_numbers
gh_json = _ci_version.gh_json
query_ci_version = _ci_version.query_ci_version
run_day = _ci_version.run_day


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
          cjk: bool = True, passthrough_mother: str | None = None,
          module_id: str | None = None, fixture: bool = False) -> list[str]:
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
        # 母版直通：不改任何轮廓，把母版字节原样放进包里，只做挂载与配置。
        # 用途是量基准——五条判据对着它比，任何改动都跟它差多少一目了然。
        passthrough_name = None
        if passthrough_mother:
            mother_path = Path(passthrough_mother)
            if not mother_path.is_file():
                raise ValueError(f"母版直通要给一个本地文件：{passthrough_mother}")
            cjk_font = mother_path.read_bytes()
            passthrough_name = mother_path.name
            glyphs = {}
            glyph_count = 0
            # 刷进手机后管理器里只有 module.prop 这几行能认人：直通包的 name/description
            # 必须自己说明白，否则会跟文渊圆体的发行件长得一模一样（版本号还更高）。
            digest = hashlib.sha256(cjk_font).hexdigest()[:7]
            # 基准件必须与发行件**不同 id**：同一个 id 就只能靠抬 versionCode 去压发行件，
            # 抬上去之后发行件的总序号（现在是三位数）在管理器眼里永远是「降级」，
            # 刷过基准件的机器再也装不回正规包，除非卸载。2026-11-01 那次 90 万序号就是这么来的。
            if module_id:
                prop = re.sub(r"^id=.*$", lambda _m: f"id={module_id}", prop, flags=re.M)
            prop = re.sub(r"^name=.*$", lambda _m: "name=Selffont 母版直通（水平/竖向定位修正）", prop, flags=re.M)
            prop = re.sub(
                r"^description=.*$",
                lambda _m: ("description=母版直通包：汉字取自 %s（源 sha256 %s…），"
                            "轮廓一个点没改，只把偏出字格中线（横向）与设计中线（竖向）的字整体平移归位；"
                            "拉丁与符号仍走文渊圆体；只做基准对照，不是发行件；"
                            f"模块 id 为 {module_id or '（同发行件）'}，与发行件分开，刷它不挡正规包更新。"
                            % (passthrough_name, digest)),
                prop, flags=re.M)
            warnings.append(f"母版直通：{passthrough_name} 进包（轮廓不改、只整体平移归位），"
                            "只用于基准测量，不是发行件。")
        else:
            glyphs = cjk_glyphs() if cjk else {}
            glyph_count = len(glyphs)
            cjk_font = build_cjk_font(glyphs, carrier) if glyphs else b""
        # 框架读 font_fallback.xml（新语法）；Skia 读库存 fonts.xml（另一份，本模块也换）。
        template = (ROOT / "fonts.xml").read_bytes()
        cjk_file = passthrough_name or (cjk_naming(CJK_RELEASE_VERSION)[1] if glyph_count else None)
        if cjk_file:
            # 直通时按母版自己的内部族名写配置：字节没改，名字也得是它自己的。
            with TTFont(io.BytesIO(cjk_font), lazy=True) as _mother:
                cjk_family = (_mother["name"].getDebugName(16) or _mother["name"].getDebugName(1)
                              or "Maruko Gothic")
        else:
            cjk_family = None
        xml = configure_fonts(template, name, ladder, cjk=bool(cjk_file),
                              cjk_name=cjk_file, cjk_family=cjk_family)
        # Skia 只认 /system/etc/fonts.xml：Flutter / WebView / 厂商小组件走这条路。
        # 只出插入行，由安装脚本插进设备自己那份（整份替换会丢掉 OPPO Sans 等 OEM 字件）。
        # 二创汉字只开放 wght 300–500（tools/cjk_vf.py），超出这条阶梯的请求本来就落到主字体。
        cjk_ladder = weight_ladder({"wght": (300, 400, 500)})
        faces = ([(cjk_file, cjk_ladder)] if cjk_file else []) + [(name, ladder)]
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

        # 默认族 sans-serif 的每一个字件必须真打进包。这一族是 system_server 开机就要用的，
        # 「引用得到、字件不在包里、靠设备自带」在缺件的机型上会让字体配置解析失败（2026-11-01
        # 进安全模式）。宁可打包失败，也不要出一个引用了空名字的配置。
        default_family = xml_root.find("family[@name='sans-serif']")
        packaged_names = ({PurePosixPath(m.filename).name for m in bundled} | extra_names
                          | {name, cjk_file} - {None})
        # 覆盖清单：配置引用了 139 个名字，包里只带得走设备也认得的那些。清单落进模块，
        # 是为了让「覆盖不全」变成一份可读的名单——缺的是哪个名字、由谁提供，一目了然，
        # 而不是等真机上看到某个字没换再回头猜。Android 解析器找不到字件时跳过该条，
        # 字符继续走回退链：所以这些名字如果设备上也没有，那些字符就不会是本包的字形。
        device_supplied = sorted(name_ for name_ in referenced - packaged_names if name_)
        coverage = (
            "Selffont 覆盖清单（构建期生成）\n\n"
            f"打包的字件 {len(packaged_names)} 个：\n"
            + "".join(f"  {item}\n" for item in sorted(packaged_names))
            + f"\n配置引用、但本包不带、由设备 /system/fonts 提供的名字 {len(device_supplied)} 个：\n"
            + "".join(f"  {item}\n" for item in device_supplied)
            + "\n说明：Android 的字体解析器遇到找不到的字件会跳过那一条，字符继续走回退链。\n"
              "第二组名字如果设备上也没有，那些字符就不是本包的字形——这是覆盖缺口唯一的来源，\n"
              "不是漏打包。要补齐，把对应字件放进基础包或增列补充字库。\n"
        )

        if default_family is not None:
            missing_carrier = sorted({(node.text or "").strip()
                                      for node in default_family.findall("font")} - packaged_names)
            if missing_carrier:
                raise ValueError(f"默认族 sans-serif 引用了不打包的字件 {missing_carrier}："
                                 "这一族开机就要用，不能靠设备自带")

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
                     cjk_font, legacy, cjk_file=cjk_file, coverage=coverage)

    version = next(line.split("=", 1)[1] for line in prop.splitlines() if line.startswith("version="))
    print(f"构建完成：{output}  版本 {version}"
          + ("（自检夹具，非发行版：日期/序号由测试固定传参）" if fixture else ""))
    print(f"  主字体 {face['family']!r} → {RENAME}（{name},{len(ladder)} 档）")
    print(f"  补充字库 {len(bundled)} 个基础字体 + {len(supplementals)} 个固定许可外部字体；"
          f"配置共引用 {len(device_supplied) + len(packaged_names)} 个名字，"
          f"其中 {len(device_supplied)} 个由设备自带（明细见包内 coverage.txt）")
    print(f"  二创汉字 {glyph_count} 字 / {len(cjk_font) / 1e6:.1f} MB"
          f"（{cjk_naming(CJK_RELEASE_VERSION)[0]}，排在主字体之前）"
          if glyph_count else "  二创汉字：无数据，跳过")
    print("  网页自带字体：放行（--keep-web-fonts）" if keep_web_fonts else "  网页自带字体：压成文渊")
    for message in warnings:
        warn(message)
    return warnings


def write_module(output: Path, archive: zipfile.ZipFile, bundled: list[zipfile.ZipInfo],
                 name: str, packaged: bytes, xml: bytes, prop: str, config: str,
                 supplementals: list[dict], cjk_font: bytes = b"", legacy: bytes = b"",
                 cjk_file: str | None = None, coverage: str = "") -> None:
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
            destination.writestr(f"system/fonts/{cjk_file or cjk_naming(CJK_RELEASE_VERSION)[1]}",
                                 cjk_font)
            destination.writestr(f"licenses/{CJK_LICENSE_NAME}", CJK_LICENSE.read_bytes())
        destination.writestr("font_fallback.xml", xml)
        destination.writestr("fonts-insert.xml", legacy)
        if coverage:
            destination.writestr("coverage.txt", coverage.encode("utf-8"))
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
    """跑一段 shell。

    ★ 必须限时（§18：超时按未完成）。注入型 bug —— 比如在抓日志的子 shell 里起一个
    `while :; do ...; done &` —— 会把管道写端一直开着，`subprocess.run` 永远等不到 EOF，
    整个 --check 挂死。挂死和「红」是两回事：挂死没人看得见，红才是判据。
    """
    return subprocess.run(["sh", *args], env=env, capture_output=True, text=True, timeout=120)


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

def legacy_rows(faces: list[tuple[str, list[dict]]]) -> bytes:
    """Skia 那份配置要插入的字件行（`<font ...>`，缩进四格，一行一条）。

    Android 框架读 `font_fallback.xml`，Flutter / WebView / 部分厂商小组件走 Skia，
    而 Skia 把配置路径写死成 `/system/etc/fonts.xml`（`google/skia`
    `src/ports/SkFontMgr_android_parser.cpp`：`LMP_SYSTEM_FONTS_FILE` 在第 31 行，
    `parse_config_file(...)` 在第 777 行）。只换 framework 那几份时，这些程序照旧读 OEM
    配置——2026-10-28 真机：`/system/etc/fonts.xml` 里 Selffont **0** 次，另三份各 16 次。

    **不能整份替换**：仓库里的 `fonts.xml` 是 AOSP+MIUI 混编模板，设备那份里有 OPPO Sans
    等 OEM 字件（真机反馈：天气小组件落到 OPPO Sans）。整份盖掉等于把这些字件一起删掉。
    所以这里只出「要插的行」，由安装脚本把它插进**设备自己那份**文件里，其余行原样保留。

    一条字重一行，是因为 Skia 按 `weight`/`style` 逐条匹配：只写 400 一条时，App 里
    500/700 的粗体全部落回设备的 Roboto，看起来就是「只有正文是我们、标题不是」。
    主字体带 ital 轴，斜体单独成条；二创汉字只有 wght 轴，调用方传入的阶梯里不含斜体。
    """
    rows = []
    for name, ladder in faces:
        for entry in ladder:
            style = "italic" if entry["italic"] else "normal"
            rows.append(f'    <font weight="{entry["weight"]}" style="{style}">{name}</font>\n')
    return "".join(rows).encode("utf-8")


@check
def skia_insert_rows():
    """Skia 那份插入行必须覆盖整条阶梯：只写 400 一条时，App 里标题/粗体全落回设备字体。"""
    ladder = weight_ladder({"wght": (100, 400, 900), "ital": (0, 0, 1)})
    rows = legacy_rows([("F.ttf", ladder)]).decode("utf-8").splitlines()
    assert len(rows) == len(ladder) == 18, f"阶梯 {len(ladder)} 档，只出了 {len(rows)} 行"
    assert sum('style="italic"' in row for row in rows) == 9, "斜体档位没出全"
    weights = {row.split('weight="', 1)[1].split('"', 1)[0] for row in rows}
    assert weights == {str(weight) for weight in WEIGHTS}, f"字重不全：{sorted(weights)}"
    assert all(row.startswith('    <font ') for row in rows), "缩进/行首不对，插进设备配置会破坏语法"


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

    # 二创汉字族：必须带 zh 语言标签，且排在所有 CJK 语言区族之前。Minikin 给每个族打分
    # （覆盖分 << 29 | 语言分 << 1 | 变体分，见 configure_fonts 的注释），同一码位多个族都有时
    # 覆盖分打平，胜负全看语言分；语言分也打平才按文件顺序取靠前的。不带 lang 的匿名族
    # 语言分恒为 0 —— 这就是「包回退到文渊」的成因，改回匿名族会让这条断言先炸。
    cjk_root = ET.fromstring(configure_fonts(template, "V.ttf", ladder, cjk=True, cjk_name="C.ttf"))
    cjk_families = list(cjk_root)
    cjk_own = [family for family in cjk_families
               if [(node.text or "").strip() for node in family.findall("font")] == ["C.ttf"]]
    assert len(cjk_own) == 1, "二创汉字族应恰好一个"
    cjk_own = cjk_own[0]
    assert {tag.strip() for tag in (cjk_own.get("lang") or "").split(",")} >= {"zh-Hans", "zh-Hant"}, \
        "二创汉字族必须带 zh 语言标签：匿名族语言分为 0，中文永远落语言区里的主字体"
    assert {node.get("supportedAxes") for node in cjk_own.findall("font")} == {CJK_AXES}, \
        "二创汉字族只能是纯可变字件（混写静态字件真机卡第一屏）"
    zh_at = [index for index, family in enumerate(cjk_families)
             if family is not cjk_own and is_cjk_locale(family.get("lang"))]
    assert cjk_families.index(cjk_own) < min(zh_at), \
        "二创汉字族必须排在所有 CJK 语言区族之前：语言分打平时按文件顺序取靠前的"

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
            kwargs.setdefault("fixture", True)  # 打印时标明这是夹具版本，不是发行版
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
                             "firefox.sh", "web-fonts.sh", "action.sh", "hotswap.sh", "skia.sh",
                             "geckoview-config.yaml",
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
        assert rows, "fonts-insert.xml 为空：Skia（Flutter / WebView）那条路上没有字件可读"
        assert all(row.endswith(">P-Regular.ttf</font>") for row in rows), legacy
        assert all(row.startswith("<font weight=") and ('style="normal"' in row or 'style="italic"' in row)
                   for row in rows), legacy
        assert len(rows) == len(set(rows)), f"插入行有重复：{rows}"
        assert any('weight="400"' in row for row in rows), "缺 400：正文会落回设备字体"
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
                                           "9", day="2", date="26.9.30")).name == "selffont-26.9.30.2.9.zip"

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
    assert default_output(stamped).name == "selffont-26.9.30.3.42.zip"
    assert default_output(degraded).name == "selffont-26.9.30.42.zip"
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
    assert ci_version_numbers([], [art(f"{PROJECT}-{today}.3.500", 1)], 503, now) \
        == (today, 6, 503, 498)
    # 6) 两个锚点取小：运行最小号 496 比产物反推的 498 更早。
    assert ci_version_numbers([run(496, "2026-10-27T00:01:00+00:00")],
                              [art(f"{PROJECT}-{today}.3.500", 1)], 503, now) == (today, 8, 503, 496)
    # 7) 段数不是五段、或日期不是今天的产物不参与锚定。
    assert ci_version_numbers([], [art(f"{PROJECT}-{today}.3", 1),
                                   art(f"{PROJECT}-{yesterday}.3.500", 2)], 210, now) \
        == (today, 1, 210, 210)
    # 8) 顶到保留上限 + 全今天的 + 零产物，过去必须拒绝出包；那判据在从未成功出包的
    #    工作流上是死循环（selfrounds #44/#45）。现在清理侧钉住首条，照常算。
    capped = [run(number, f"2026-10-27T0{number % 10}:10:00+00:00") for number in (206, 207, 208, 209, 210)]
    assert ci_version_numbers(capped[:5], [], 210, now) == (today, 5, 210, 206), \
        "连挂 5 次后第 6 次必须能出包（当日序号 5），不许再抛异常拒绝"
    # 8b) 同一场景换成 zero-gap 的连续号：40..44 五条，第 45 次运行 → 当日序号 6。
    dead = [run(number, "2026-10-27T01:00:00+00:00") for number in (40, 41, 42, 43, 44)]
    assert ci_version_numbers(dead, [], 45, now)[1] == 6, "死锁反例：第 6 次必须能算出当日序号 6"
    # 8c) 清理侧必须真的钉住当日首条，否则上面的推断没有依据 —— 直接调它的纯函数验。
    import importlib.util as _ilu2
    import os as _os
    # cleanup.py 在模块顶层就读这几个环境变量并校验，导入前得先备好（用最小可信值）。
    _env_backup = {k: _os.environ.get(k) for k in ("GH_TOKEN", "REPO", "RUN_ID", "CLEANUP_APPLY")}
    _os.environ.update({"GH_TOKEN": "probe", "REPO": "probe/probe",
                        "RUN_ID": "1", "CLEANUP_APPLY": "false"})
    _spec2 = _ilu2.spec_from_file_location("clean_probe", ROOT / ".github" / "scripts" / "cleanup.py")
    _cl = _ilu2.module_from_spec(_spec2)
    _spec2.loader.exec_module(_cl)
    _rows = [{"id": n, "run_number": n, "event": "push",
              "run_started_at": f"2026-10-27T0{n % 10}:10:00+00:00"} for n in (206, 207, 208, 209)]
    assert _cl.pinned_anchor(_rows, now) == 206, \
        f"清理侧没钉住当日首条：{_cl.pinned_anchor(_rows, now)}（应 206），取号器就没有依据"
    # ★ 只验证 pinned_anchor() 的返回值是不够的：删运行那段的 `if row["id"] == anchor_id`
    #   被删掉时，pinned_anchor() 照样返回正确值，自检照样绿 —— 变异测试抓不到就是假测试。
    #   所以直接检查「删除决策」这一层：钉住的那条必须不出现在待删清单里。
    assert 'if row["id"] == anchor_id:' in (ROOT / ".github" / "scripts" / "cleanup.py").read_text(
        encoding="utf-8"), "清理脚本删运行那段跳过了当日首条判据：钉住等于没钉"
    # 往日运行不参与钉住（钉的是「今天」的首条）。
    assert _cl.pinned_anchor([{"id": 1, "run_number": 1, "event": "push",
                              "run_started_at": "2026-10-26T12:00:00+00:00"}], now) is None
    for _k, _v in _env_backup.items():          # 探针不许污染后面的检查项
        if _v is None:
            _os.environ.pop(_k, None)
        else:
            _os.environ[_k] = _v
    # 9) 同上但有产物锚点：产物名绝对值可证，照常算（496..500 与 503 同一条序列）。
    late = [run(number, f"2026-10-27T0{number % 10}:10:00+00:00") for number in (496, 497, 498, 499, 500)]
    assert ci_version_numbers(late, [art(f"{PROJECT}-{today}.3.500", 1)], 503, now)[1] == 8
    # 10) 今日只四条、总数没到上限：没有被删过，照常算。
    assert ci_version_numbers(capped[:4], [], 210, now)[1] == 5
    # 11) 顶到上限但还留着往日运行：往日那条被删光了才会删到今天的，所以今天的首条可证。
    mixed = [run(206, "2026-10-26T12:00:00+00:00")] + capped[1:]
    assert ci_version_numbers(mixed, [], 210, now)[1] == 4

    # 11) 当日序号 0、总序号小于当日序号的畸形名忽略，不当锚点。
    assert ci_version_numbers([], [art(f"{PROJECT}-{today}.0.500", 1),
                                   art(f"{PROJECT}-{today}.5.3", 2)], 210, now) == (today, 1, 210, 210)
    # 9) 锚点比当前号还大（旧运行已删）时钳到当前号，当日序号不小于 1。
    assert ci_version_numbers([], [art(f"{PROJECT}-{today}.3.600", 1)], 210, now) == (today, 1, 210, 210)
    # 10) 日界按 UTC+8：UTC 10-27 16:30 = UTC+8 10-28 00:30，日期跨到 28 号，前一条 23:00 的运行不算。
    late = datetime(2026, 10, 27, 16, 30, tzinfo=timezone.utc)
    assert ci_version_numbers([run(300, "2026-10-27T15:00:00+00:00")], [], 301, late) \
        == ("26.10.28", 1, 301, 301)
    # 日期段格式：yy.m.d，月日不补零。
    assert re.fullmatch(r"\d{2}\.(1[0-2]|[1-9])\.(3[01]|[12][0-9]|[1-9])", ci_version_numbers([], [], 1, now)[0])
    # 产物名反推的边界：day=1 时 R_first 就是总序号本身。
    assert artifact_anchor(f"{PROJECT}-{today}.1.700", today) == 700
    assert artifact_anchor(f"{PROJECT}-{today}.2.700", today) == 699
    assert artifact_anchor(f"{PROJECT}-26.10.27", today) is None
    assert artifact_anchor(f"build-{today}.1.320", today) is None, "母版序列不许进自版号源"
    # 每条工作流只认自己那一类产物：母版读 `build-`，自版读 `selffont-`，两边互不串号。
    assert artifact_anchor(f"build-{today}.1.320", today, "build-") == 320
    assert artifact_anchor(f"{PROJECT}-{today}.1.320", today, "build-") is None
    assert ci_version_numbers([], [art(f"build-{today}.1.320", 1)], 324, now, "build-") \
        == (today, 5, 324, 320)
    # 母版那条：5 条当日运行顶到保留上限、但有 `build-` 产物锚点，照常算。
    capped_build = [run(number, f"2026-10-27T0{number % 10}:10:00+00:00") for number in (320, 321, 322, 323, 324)]
    assert ci_version_numbers(capped_build, [art(f"build-{today}.1.320", 2)], 324, now, "build-")[1] == 5


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
        # 默认 off：模块里不许有 system/etc/fonts.xml——插进去会让 Flutter（Skia）界面大片没字，
        # 详见 module/skia.sh 头注。开关 on/off 走 skia.sh，这里两条都验。
        assert not (modpath / "system/etc/fonts.xml").exists(), \
            "默认不许产出 Skia 配置：它会让 Flutter 界面没字（Selffont:skia=off）"
        assert "Selffont:skia=off" in result.stdout, "安装时应报告 Skia 那条路是关的：" + result.stdout
        env_on = dict(env, SELFFONT_SKIA_STATE=str(tmp / "skia.state"))
        on = sh([str(modpath / "skia.sh"), "on"], env_on)
        assert on.returncode == 0, on.stderr
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
        assert "Skia /system/etc/fonts.xml：已插 4 处" in on.stdout, "应报告 Skia 插入位置数：" + on.stdout
        off = sh([str(modpath / "skia.sh"), "off"], env_on)
        assert off.returncode == 0 and not (modpath / "system/etc/fonts.xml").exists(), \
            "skia.sh off 必须删掉模块里那份文件（重启后回设备原文件）"

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
        # 网页字体开关已从管理器按钮里移出（按钮只做清场与状态），直接走 web-fonts.sh。
        assert sh([str(action), "web"], env).returncode == 2, "action.sh 不该再有 web 动作"
        result = sh([str(web), "toggle"], env)  # 网页字体那条：keep → block
        assert result.returncode == 0 and state.read_text().strip() == "block", result
        assert re.search(rf"^{re.escape(WEB_FONT_ACTIVE)}$", bridge.read_text(encoding="utf-8"), re.M), \
            "toggle 没变回压"
        # 模块更新（customize.sh）刷新副本时按状态走：先在管理器里选 keep，再跑一次安装脚本。
        assert sh([str(web), "keep"], env).returncode == 0 and state.read_text().strip() == "keep"
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
        # 管理器按钮 = 清场 + 打印状态（本机不支持运行期换字体），不再有切换动作。
        dry = {**env, "SELFFONT_DATA": str(tmp / "data"), "SELFFONT_BASE": str(tmp / "hot"),
               "SELFFONT_SYSTEM_FONTS": str(tmp / "fonts"),
               "SELFFONT_MOUNTINFO": str(tmp / "mountinfo"), "SELFFONT_MOUNTS": str(tmp / "mounts")}
        (tmp / "fonts").mkdir(exist_ok=True)
        (tmp / "mountinfo").write_text(f"100 30 0:50 / {tmp}/fonts rw - overlay overlay lowerdir=/system/fonts\n",
                                       encoding="utf-8")
        (tmp / "mounts").write_text(f"rootfs / rootfs rw 0 0\noverlay {tmp}/fonts overlay rw 0 0\n",
                                    encoding="utf-8")
        result = sh([str(action), "status"], dry)
        assert result.returncode == 0 and "本机不支持" in result.stdout, result
        result = sh([str(action)], dry)
        assert result.returncode == 0 and "panic" in result.stdout and "删掉了" in result.stdout, result
        (modpath / "harness.sh").unlink()

    # 开机守卫（2026-11-08 事故）：卡在**第一屏不动**、主人长按电源键强制重启
    # （ro.boot.bootreason=2sec_reboot → AOSP bootstat.cpp 映射 cold,rtc,2sec）。
    # 进程是阻塞不是崩溃，所以 pstore / dropbox / tombstone 全空，证据只剩 logcat。
    # 这里验死三件真会致命的事：连续失败会自动停用、走到底会清零、日志有体积上界。
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        data = tmp / "data"
        guard = ROOT / "module/post-fs-data.sh"
        night = ROOT / "module/service.sh"
        assert sh(["-n", str(guard)], os.environ).returncode == 0, "post-fs-data.sh 语法错误"
        assert sh(["-n", str(night)], os.environ).returncode == 0, "service.sh 语法错误"
        moddir = tmp / "module"
        moddir.mkdir()
        # 窗口给极大值：这个夹具测的是「第 1/2/3 次开机」的计数与停用，
        # 不是快速重启保护。默认 300 在沙箱里（uptime 百来秒）会被判成「活过了」
        # 而反复清零，夹具就测歪了。
        env = {**os.environ, "MODDIR": str(moddir), "SELFFONT_DATA": str(data),
               "SELFFONT_NO_LOGCAT": "1", "SELFFONT_MAX_BOOT_FAIL": "2",
               "SELFFONT_FAST_REBOOT_WINDOW": "999999999"}

        # 每一「次开机」给一个不同的 btime，模拟真的重启。不给的话会全部被去重判成
        # 同一次开机——这正是第一版拿 uptime 当判据时的错法。
        boot_seq = {"n": 0}

        def boot():
            boot_seq["n"] += 1
            return sh([str(guard)], dict(env, SELFFONT_BOOT_ID=str(300000 + boot_seq["n"])))

        # ★ 2026-11-08 真机第五次输出：post-fs-data.d/sf-guard.sh 与 /data/adb/selffont
        #   目录时间戳都是 17:12，目录里却**一个账都没有**——脚本被 init source 进去之后
        #   在写第一行之前就走了（根因：`${0%/*}` 在 source 时拿到的是父进程路径）。
        #   两件必须锁死：
        #   ① 一进来就写一行「守卫进来了」：没这行就分不清「没跑」和「跑了但写不进去」；
        #   ② MODDIR 不许从 $0 猜；夹具故意不给它，必须能从模块目录自己认出来。
        gsrc = guard.read_text(encoding="utf-8")
        assert "守卫进来了" in gsrc, "守卫没有第一行硬证据：又分不清「没跑」和「跑了没写进去」"
        gcode = [ln for ln in gsrc.splitlines() if not ln.lstrip().startswith("#")]
        assert not any("${0%/*}" in ln for ln in gcode), \
            "MODDIR 又从 $0 猜了：被 init source 时那是父进程路径（只看代码行）"
        mods = tmp / "mods"
        (mods / "selffont-bench").mkdir(parents=True)
        nodir = tmp / "nodir"
        (nodir / "m").mkdir(parents=True)
        # 有意不给 MODDIR：真机上被 init source 时它要么为空、要么是错的。
        e0 = {**os.environ, "SELFFONT_DATA": str(nodir / "d"),
              "SELFFONT_MODULES": str(mods), "SELFFONT_NO_LOGCAT": "1",
              "SELFFONT_MAX_BOOT_FAIL": "0"}
        e0.pop("MODDIR", None)
        assert sh([str(guard)], e0).returncode == 0
        log0 = (nodir / "d" / "guard.log").read_text(encoding="utf-8")
        assert "守卫进来了" in log0, "不给 MODDIR 时连第一行都没写：路径又猜错了"
        assert "selffont-bench" in log0, "没从模块目录自己认出 MODDIR"
        assert (mods / "selffont-bench/disable").exists(), \
            "认出了 MODDIR 却没停用：自动跳过失效，主人还是要手动进安全模式"

        # ★ 守卫有两条触发路径：打包进模块（KernelSU 自己 source）+ 手工放进
        #   /data/adb/post-fs-data.d/（init 直接执行）。两条同时在，一次开机计数涨 2，
        #   阈值 2 就会让**每次正常开机**都在第 2 次自己打 disable。
        #   这里在同一秒内跑两次，计数必须只涨 1；日志里要写明「本次不重复计数」。
        dup = tmp / "dup"
        (dup / "d").mkdir(parents=True)
        (dup / "m").mkdir(parents=True)
        ed = {k: v for k, v in os.environ.items() if k != "MODDIR"}
        # 这个夹具测的是「同一次开机去重」，不是快速重启保护。
        # 窗口必须给一个**极大值**让「快速重启」恒成立、不触发清零；
        # 给 0 会反过来每次都清零（uptime 恒大于 0），给默认 300 又会被沙箱的
        # 百来秒 uptime 判成「活过了」——三种都不对，只有极大值才是中性。
        ed.update({"SELFFONT_DATA": str(dup / "d"), "SELFFONT_MODULES": str(dup / "m"),
                   "SELFFONT_NO_LOGCAT": "1", "SELFFONT_MAX_BOOT_FAIL": "99",
                   "SELFFONT_BOOT_ID": "100000", "SELFFONT_FAST_REBOOT_WINDOW": "999999999"})
        sh([str(guard)], ed)
        sh([str(guard)], ed)
        cnt = (dup / "d" / "boot-count").read_text().strip()
        assert cnt == "1", f"同一次开机被算了 {cnt} 次：两份脚本同时在时每开机计数涨 2，好机器也会被停用"
        assert "本次开机已计过数" in (dup / "d" / "guard.log").read_text(encoding="utf-8"), \
            "去重生效了却没在日志里写明：下次又一个看不懂的空账"
        # ★ 反过来的一半更要命：**下一次开机必须照常计数**。
        #   第一版拿 /proc/uptime 的秒数当判据，两次开机都可能在第 3 秒跑到这里，
        #   uptime 一样 → 第二次被当成「同一次开机」跳过计数，
        #   恰恰在「反复卡机」那个场景下把守卫废掉。改用每次开机唯一的 btime。
        ed2 = dict(ed, SELFFONT_BOOT_ID="200000")
        sh([str(guard)], ed2)
        assert (dup / "d" / "boot-count").read_text().strip() == "2", \
            "下一次开机没计数：去重把两次不同的开机当成一次了（uptime 判据就犯这个错）"

        # 第 1、2 次：计数涨到阈值以内，不许停用。
        for want in ("1", "2"):
            assert boot().returncode == 0
            assert (data / "boot-count").read_text().strip() == want
            assert not (moddir / "disable").exists(), f"第 {want} 次就停用了（阈值是 2，太早）"
        # 第 3 次：越过阈值，必须自己打 disable。这是「主人不必再进安全模式」的那一步。
        assert boot().returncode == 0
        assert (moddir / "disable").exists(), "连续第 3 次开机没走到底却不停用：守卫是空的"
        # 计数不是从零硬编码：写一个脏值（非数字）不许把守卫带崩，也不许当成 0 之后立刻停用。
        (data / "boot-count").write_text("坏值\n")
        (moddir / "disable").unlink()
        assert boot().returncode == 0 and (data / "boot-count").read_text().strip() == "1", \
            "脏计数没有被当成 0 重来"

        # 走到底 = service.sh 等到 sys.boot_completed=1 之后清零。
        # getprop 用夹具顶替：真机上那是系统属性，沙箱里没有。
        (data / "boot-count").write_text("2\n")
        fake_bin = tmp / "bin"
        fake_bin.mkdir()
        (fake_bin / "getprop").write_text("#!/bin/sh\necho 1\n", encoding="utf-8")
        (fake_bin / "getprop").chmod(0o755)
        done = sh([str(night)], {**env, "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                                 "SELFFONT_BOOT_WAIT": "3"})
        assert done.returncode == 0, done
        assert not (data / "boot-count").exists(), "开机走到底了却没清零：下次会把好机器停用"
        # 没等到 boot_completed（模拟卡住）：计数必须保留，那是「上次没走到底」的唯一记录。
        (data / "boot-count").write_text("1\n")
        (fake_bin / "getprop").write_text("#!/bin/sh\necho 0\n", encoding="utf-8")
        stuck = sh([str(night)], {**env, "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                                  "SELFFONT_BOOT_WAIT": "1"})
        assert stuck.returncode == 0, stuck
        assert (data / "boot-count").read_text().strip() == "1", "卡住时计数被清掉了"

        # ★ 2026-11-08 真机：boot.log 有 1707 行，看着挺充实，但卡住那几分钟
        #   一行都没有。原因两处：① `-s 白名单` 只抓 8 个 tag，桌面每 5 秒重载字体
        #   把 180 秒窗口填满，ActivityManager/Watchdog 的报错挤不进来；
        #   ② 抓不到时静默退出，事后说不清是「没跑」还是「没 logd」。
        gc = [ln for ln in gsrc.splitlines() if not ln.lstrip().startswith("#")]
        logcat_lines = [ln for ln in gc if "logcat" in ln]
        assert logcat_lines, "找不到 logcat 抓取"
        assert not any("-s " in ln for ln in logcat_lines), \
            "logcat 又用 -s 白名单了：刷屏标签会把主干挤掉（真机 1707 行全是 Typeface）"
        assert any("grep -v" in ln and "Typeface: Preloading" in ln for ln in gc), \
            "没有用黑名单排除刷屏标签"
        # 只查字面句会被自己改文案坑（这次就是：句子改成 $_sock 就误红）。
        # 结构断言：**没 logd 时的那行日志**必须在，且真机默认路径必须是 /dev/socket/logdw。
        # 文案改过两次（「等了 15 秒没有…」→「$_sock 不存在…」），所以断言结构而不是整句：
        # 只要「logd 没起来」这件事被写进 guard.log 就行。
        assert "logd 没起来" in gsrc and "本次没抓到" in gsrc, \
            "抓不到日志时静默退出：说不清是没跑还是 logd 没起来"
        assert "_sock=${SELFFONT_LOGD_SOCKET:-/dev/socket/logdw}" in gsrc, \
            "logd 探针的默认路径被改了：真机上就是 /dev/socket/logdw"
        assert "实际跑了" in gsrc, "抓完不记真实时长：真机上写死「180 秒到」，实际跑了 31 分钟"
        # ★ 真机实测：写死「180 秒到」时，22:33:15 → 23:04:44 跑了 31 分 29 秒。
        #   时长必须现算。锁死：不许再出现写死的「180 秒到」这种句子。
        gcode2 = [ln for ln in gsrc.splitlines() if not ln.lstrip().startswith("#")]
        assert not any("180 秒到" in ln for ln in gcode2), \
            "时长又写死了：报的秒数和真实秒数是两回事（只看代码行）"
        assert "SELFFONT_BOOT_LOG_SECONDS" in gsrc, "抓取上限不可调，只能靠改脚本"
        # 边抓边封顶：原来只在下次开机检查体积，一次就写了 100,453 行 / 22 MB。
        assert "NR > cap" in gsrc or "awk -v cap" in gsrc, \
            "没有边抓边封顶：真机一次写了 100,453 行（22 MB）"
        # 守夜超时那行必须真写出来（真机 22:06 那次就是一句话都没有，分不清
        # 「守夜被 init 清掉」和「守夜跑了没等不到」）。用 0 秒超时造超时。
        nd = tmp / "night"
        (nd / "d").mkdir(parents=True)
        (nd / "d" / "boot-count").write_text("1\n")
        fake = nd / "bin"
        fake.mkdir()
        (fake / "getprop").write_text("#!/bin/sh\necho 0\n")
        (fake / "getprop").chmod(0o755)
        en = {**os.environ, "SELFFONT_DATA": str(nd / "d"), "SELFFONT_BOOT_WAIT": "1",
              "PATH": f"{fake}:{os.environ.get('PATH','')}"}
        sh([str(night)], en)
        nlog = (nd / "d" / "guard.log").read_text(encoding="utf-8")
        assert "守夜进来了" in nlog, "守夜没有第一行硬证据"
        assert "计数保留" in nlog, "守夜超时那行没写：真机上就是靠它分「被清掉」和「等不到」"
        assert (nd / "d" / "boot-count").read_text().strip() == "1", \
            "没等到 sys.boot_completed 却把计数清了：下次开机就分不清上次卡没卡"

        # ★ 2026-11-09 自查（不看真机，自己找出来的）三处：
        #   ① ⑫ 的去重用 `for seen in $SHOWN`，路径带空格会被拆词，去重整个失效。
        #      真机 Download 里就有 `Nagram/Saved Attachments` 这种名字。
        #   ② MAX / MAX_BYTES / WAIT / SECONDS 四个环境变量裸取，给非数字时
        #      `[ -gt ]` 报 Illegal number 返回 2，if 判假 —— 守卫**永远不停用**，
        #      而且日志里一个字都不提。
        #   ③ sf-why.sh 只要 boot.log 存在就算「读到证据」，哪怕七个关键词全是 0。
        cleanup_src = (ROOT / "tools/sf-clean.sh").read_text(encoding="utf-8")
        # 只看代码行：注释里那句复盘会被字符串匹配误判成功。
        cleanup_code = [ln for ln in cleanup_src.splitlines() if not ln.lstrip().startswith("#")]
        assert not any("for seen in $SHOWN" in ln for ln in cleanup_code), \
            "⑫ 的去重又在按空格拆词：路径带空格时整个失效（真机有 Saved Attachments）"
        assert any("while IFS= read -r seen" in ln for ln in cleanup_code), "⑫ 去重没有按行读"
        for f, name in ((guard, "post-fs-data.sh"), (night, "service.sh")):
            txt = f.read_text(encoding="utf-8")
            # _cap 也必须有非数字兜底：它是真正限制抓取量的那个变量。
            for var in ("MAX", "MAX_BYTES", "_cap", "_limit_s", "WAIT"):
                # 判据不能用「出现过 ${VAR}」——把兜底那行删掉后 ${VAR} 也就不在了，
                # 检查会被**整个跳过**（我自己撞过一次：删掉兜底，检查仍然绿）。
                # 改成看赋值本身：只要这个变量被赋过默认值，就必须有 case 兜底。
                if f"{var}=${{" in txt or f"{var}=$" in txt:
                    assert f'case "${var}" in' in txt, \
                        f"{name} 的 {var} 裸取：非数字时 [ -gt ] 报错并判假，守卫静默失效"
        why_src = (ROOT / "tools/sf-why.sh").read_text(encoding="utf-8")
        why_code = [ln for ln in why_src.splitlines() if not ln.lstrip().startswith("#")]
        # 结构断言：必须有「按命中总数决定算不算证据」这段，而不是只查字面词。
        assert any('if [ "$total" -gt 0 ]' in ln for ln in why_code), \
            "sf-why 又把空 boot.log 当成证据：文件在、七个关键词全是 0，也算「读到了」"

        # ★ 2026-11-09 真机实测后的两条硬要求：
        #   ① 阈值默认必须是 1。真机卡住是「开机 81 秒自己重启」的自循环，
        #      阈值 2 要白挨约 4 分钟；主人要求「检测 1 次就 ban」。
        #   ② 判据必须是 -gt。-ge 会让**第 1 次开机**就停用，好机器也被关
        #      —— 我自己改错过一次，夹具当场打回。
        assert "MAX=${SELFFONT_MAX_BOOT_FAIL:-1}" in gsrc, \
            "阈值默认不是 1：主人要的是一次就停，卡住时每轮约 81 秒"
        assert 'if [ "$n" -gt "$MAX" ]' in gsrc, \
            "判据不是 -gt：改成 -ge 会让第一次开机就自己停用（好机器也被关）"
        assert "SELFFONT_FAST_REBOOT_WINDOW" in gsrc, "没有快速重启窗口：意外断电会误杀模块"
        # ★ 2026-11-09 真机第二轮（17:30:35）打回来的：守卫自己报「上限 2097152 字节」，
        #   只跑 2.8 秒 / 10485 行就断，七个关键词里 ActivityManager/Watchdog/minikin/
        #   FontManager 全是 0。根因是**两处默认值分叉**：MAX_BYTES 我改成了 8 MiB，
        #   但真正限制「本次抓多少」的 _cap 还写着 2097152；2097152/200 = 10485，
        #   和真机行数一模一样。上次的断言只查字符串「SELFFONT_BOOT_LOG_BYTES 存在」，
        #   所以这种分叉照样通过——现在必须逐个默认值相等。
        import re as _re
        cap_defaults = _re.findall(r"_cap=\$\{SELFFONT_BOOT_LOG_BYTES:-([0-9]+)\}", gsrc)
        max_defaults = _re.findall(r"MAX_BYTES=\$\{SELFFONT_BOOT_LOG_BYTES:-([0-9]+)\}", gsrc)
        assert cap_defaults, "找不到实际控制抓取上限的 _cap（抓多少由它决定，不是 MAX_BYTES）"
        assert max_defaults, "找不到 MAX_BYTES 默认值"
        assert cap_defaults[0] == max_defaults[0], (
            f"抓取上限两处默认值分叉：_cap={cap_defaults[0]} / MAX_BYTES={max_defaults[0]}"
            "——真机就是这么只抓到 2.8 秒 / 10485 行（2097152/200）的")
        # 2026-11-09 真机第三轮：8 MiB 预算只写出 4.79 MiB 就断，因为断的是**行数**
        # （41943 = 8388608 ÷ 200），而实测每行只有 119.6 字节。行数必须由字节预算推出来，
        # 且不许再加「最小行数」下限，否则两层封顶再次脱钩。
        assert "_lines=$(( _cap / 50 ))" in gsrc, \
            "行数封顶没从字节预算推出来：真机上就出现 8 MiB 只写 4.79 MiB（41943 = 8388608÷200）"
        _glines = [ln for ln in gsrc.splitlines()
                   if not ln.lstrip().startswith("#") and "_lines" in ln and "-lt" in ln]
        assert not _glines, \
            f"行数又加了最小下限（{_glines}）：两层封顶会脱钩，真机上 8 MiB 只写出 4.79 MiB"
        # 覆盖能力必须够到真机 81 秒自重启：实测写入速率 219 KB/s（5,017,814 字节 / 22.4 秒）。
        _capn = int(cap_defaults[0])
        cover = _capn / (5017814 / 22.4)
        assert cover >= 81, f"上限 {_capn} 字节只够覆盖 {cover:.0f} 秒，真机 81 秒就重启，抓不到卡死那一步"
        assert cap_defaults[0] == "25165824", \
            f"抓取上限不是 24 MiB（现在 {cap_defaults[0]}）：2 MiB 只够 2.8 秒，8 MiB 只够 37 秒"
        # 夹具：假 logcat 无限吐行，跑一次必须**真的停在上限附近**，
        # 而不是「报了个上限然后自己就断了」。没有这个夹具，上一轮的分叉就是这么漏过去的。
        capd = tmp / "captest"
        (capd / "d").mkdir(parents=True)
        (capd / "m/selffont-bench").mkdir(parents=True)
        (capd / "sock").mkdir()
        (capd / "sock/logdw").touch()
        fake_lc = capd / "fakelogcat"
        fake_lc.write_text(
            "#!/bin/sh\ni=0\nwhile [ $i -lt 200000 ]; do i=$((i+1)); \n"
            "printf '11-09 17:30:35.123  1074  1099 I ActivityManager: 第 %06d 行，这是一条长度接近真机平均的测试日志内容用于占位填充字符\\n' $i\n"
            "done\n", encoding="utf-8")
        fake_lc.chmod(0o755)
        ec = {h: v for h, v in os.environ.items() if h != "MODDIR"}
        ec.update({"SELFFONT_DATA": str(capd / "d"), "SELFFONT_MODULES": str(capd / "m"),
                   "SELFFONT_BOOT_ID": "31", "SELFFONT_BOOT_LOG_SECONDS": "1",
                   "SELFFONT_BOOT_LOG_BYTES": "2097152",
                   "SELFFONT_FAST_REBOOT_WINDOW": "999999999",
                   "SELFFONT_LOGD_SOCKET": str(capd / "sock/logdw"),
                   "SELFFONT_LOGCTL": str(fake_lc),
                   "PATH": f"{capd}:{os.environ.get('PATH','')}"})
        rcap = sh([str(guard)], ec)
        assert rcap.returncode == 0, rcap
        glog = capd / "d/guard.log"
        for _ in range(60):
            if "抓日志：停止" in glog.read_text(encoding="utf-8"):
                break
            time.sleep(0.2)
        gt = glog.read_text(encoding="utf-8")
        assert "抓日志：开始" in gt, "夹具里的抓日志根本没启动：这段现在验不到，别当它过了"
        assert "抓日志：停止" in gt, "抓日志没有真正停下：边抓边封顶失效了"
        b_cap = (capd / "d/boot.log").stat().st_size
        # 关键：断的是**字节**，不是行数。真机 8 MiB 那轮只写出 4.79 MiB
        # （41943 = 8388608÷200）就是按行数断的。这里要求顶到 2 MiB 的 95% 以上。
        # 上下都要卡：只卡下限抓不到「按行数断」的反向错误——按行数算会**超出**字节预算
        # （半行都不许超，awk 超了就 exit，最多多出一行的余量）。
        assert 2097152 * 0.95 <= b_cap <= 2097152 + 200, \
            (f"给了 2 MiB 却写出 {b_cap} 字节（{b_cap/2097152*100:.0f}%）："
             "封顶不是按实际字节算的（按行数算会写到 5 MB 外）")

        # ★ 2026-11-09 真机第四轮（18:01:59）：24 MiB 只用了 8.07 MiB、180 秒只跑了 56.8 秒。
        #   守卫只写「实际跑了 56.8 秒」，**说不清为什么停**——和写死「180 秒到」同一类错。
        #   停止原因必须由 logcat 自己的退出码说出来：
        #     0 = logcat 自己结束（logd 断开/系统开始关机）  124 = 到时间上限
        #     141 = 撞体积上限（awk 先退出）                143 = 被 SIGTERM
        assert "logcat.err" in gsrc, "logcat 的 stderr 没落盘：停了以后查不出为什么停"
        assert ".lc-rc" in gsrc, "没有记录 logcat 退出码：分不清「到时限」和「logd 断开」"
        for code, meaning in (("0", "logd 断开"), ("124", "到时间上限"), ("141", "撞体积上限")):
            assert f"{code})" in gsrc and meaning in gsrc, f"退出码 {code} 没被解释（{meaning}）"
        assert "最后一条日志时间" in gsrc, \
            "没报日志最后一条的时间戳：卡住的时刻就在这附近，比「跑了 N 秒」有用"
        # 夹具：假 logcat 自己 exit 0 / 撞体积上限，两种停止原因必须分辨得出来。
        for tag, body, want, nbytes, bid in (
            ("rc0", 'i=0\nwhile [ $i -lt 400 ]; do i=$((i+1)); '
                    'printf \'11-09 18:01:30.123  1074  1099 I ActivityManager: 第 %04d 行\\n\' $i; done\n'
                    'echo "logcat: failed to connect to logd" >&2\nexit 0\n',
             "logcat 自己结束", "25165824", "491"),
            ("rc141", 'i=0\nwhile [ $i -lt 300000 ]; do i=$((i+1)); '
                      'printf \'11-09 18:01:30.123  1074  1099 I ActivityManager: 第 %06d 行，长度接近真机平均值的填充内容\\n\' $i; done\n',
             # 文案已从「撞体积上限（awk 先退出）」改成「撞体积/行数上限（awk exit 3）」——
             # 因为现在优先用 awk 自己的退出码，不再赌管道左端异步写的 .lc-rc。
             "撞体积/行数上限", "2097152", "492"),
        ):
            rd = tmp / f"rc-{tag}"
            (rd / "d").mkdir(parents=True)
            (rd / "m/selffont-bench").mkdir(parents=True)
            (rd / "sock").mkdir()
            (rd / "sock/logdw").touch()
            fl = rd / "fakelogcat"
            fl.write_text("#!/bin/sh\n" + body, encoding="utf-8")
            fl.chmod(0o755)
            er = {h: v for h, v in os.environ.items() if h != "MODDIR"}
            er.update({"SELFFONT_DATA": str(rd / "d"), "SELFFONT_MODULES": str(rd / "m"),
                       "SELFFONT_BOOT_ID": bid, "SELFFONT_BOOT_LOG_SECONDS": "30",
                       "SELFFONT_BOOT_LOG_BYTES": nbytes,
                       "SELFFONT_FAST_REBOOT_WINDOW": "999999999",
                       "SELFFONT_LOGD_SOCKET": str(rd / "sock/logdw"),
                       "SELFFONT_LOGCTL": str(fl),
                       "PATH": f"{rd}:{os.environ.get('PATH','')}"})
            sh([str(guard)], er)
            rl = rd / "d/guard.log"
            for _ in range(100):
                if "抓日志：停止" in rl.read_text(encoding="utf-8"):
                    break
                time.sleep(0.2)
            rtxt = rl.read_text(encoding="utf-8")
            assert "抓日志：停止" in rtxt, f"{tag}: 抓日志没停下，这组夹具没验到东西"
            assert want in rtxt, \
                f"{tag}: 停止原因没写出来（应含「{want}」），实际：{rtxt.strip().splitlines()[-1]}"
            if tag == "rc0":
                assert (rd / "d/logcat.err").exists(), "logcat 的 stderr 没落盘（rc0 夹具）"
                assert "failed to connect" in (rd / "d/logcat.err").read_text(encoding="utf-8")
        # ★ 2026-11-09：logcat.err 必须**每次开机重写**。跨开机追加会越滚越大，
        #   而每次开机只关心这一轮为什么停。
        assert ': > "$DATA/logcat.err"' in gsrc, "logcat.err 没有每次开机重写：会跨开机无限累积"
        # ★ 心跳（2026-11-09 改按字节，§8 禁 sleep）：真机 logcat 在第 54 秒自己断
        #   （那是系统开始关机），只靠「实际跑了 N 秒」看不出断的那一刻写到哪儿了。
        #   现在每满 1 MiB 由**同一个 awk** 写一行「N 字节 / N 行 / 最后一条时间戳」，
        #   不另起子进程、不 sleep；撞上限时显式写 TRUNCATED（Balanov/uncut 判据）。
        assert "抓日志心跳" in gsrc, "没有抓取心跳：分不清「一直在抓」和「早就断了、只是没退出」"
        assert "SELFFONT_HEARTBEAT_BYTES" in gsrc, "心跳粒度不可调"
        assert "TRUNCATED" in gsrc, "撞上限不显式报：截断被静默吞掉（违 uncut 判据）"
        assert "reason=%s" in gsrc, "TRUNCATED 没报是撞字节还是撞行数"
        # 心跳与截断都必须在**过滤 logcat 的同一个 awk** 里，不许再起 sleep 子进程。
        gcode_no_comment = [ln for ln in gsrc.splitlines() if not ln.lstrip().startswith("#")]
        # §8「禁 sleep 与手写循环」：交付脚本里一处都不许有，注释里提到不算。
        # 原来只查「sleep 10」这个字面量，变异体写成 `sleep 10` 才红、写别的就漏（自己撞过）。
        _sleeps = [ln.strip() for ln in gcode_no_comment if "sleep" in ln]
        assert not _sleeps, f"post-fs-data.sh 里有 sleep（§8 禁）：{_sleeps}"
        # ★ 2026-11-09 CI 连续 10 条红的根因（build #362–#366 / selfrounds #39–#43）：
        #   POSIX 说 `length($0)` 数**字符**，只有 C locale 下才数字节。
        #   沙箱是 mawk（单字节实现）碰巧按字节算，本地假绿；GitHub Actions 的 gawk 在
        #   LANG=C.UTF-8 下数字符（同一行 148 字节 / 88 字符 = 1.68 倍），
        #   「上限 2 MiB」写成 168% 的字节，字节断言当场炸。
        #   真机同样是 UTF-8 环境：不修就是封顶失效、/data 被写满。
        # awk 调用跨好几行（管道 + -v 参数 + 程序体），按**整段**判：
        # 从出现 `awk` 的那行到程序体里 `length($0)`，中间必须有 LC_ALL=C。
        _gcode_text = "\n".join(gcode_no_comment)
        _m = re.search(r"^.*awk.*?length\(\$0\)", _gcode_text, re.S | re.M)
        assert _m, "找不到按字节计的 awk（`n += length($0) + 1`）"
        assert "LC_ALL=C" in _m.group(0), \
            "按字节计的 awk 没加 LC_ALL=C：UTF-8 下 length() 数字符，封顶失效（CI 连续 10 条红就是这个）"
        # 兜底：断言锁不住真机 awk 的实际语义，抓完必须用 wc -c 复核真实字节并硬截断。
        assert "封顶失效" in gsrc and "hardcut" in gsrc, \
            "没有 wc -c 事后复核：真机 awk 若按字符算，封顶会静默失效"
        # awk 自己的退出码要优先于管道左端异步写的 .lc-rc。
        assert 'if [ "$_awk_rc" = "3" ]' in gsrc, \
            "丢掉了 awk 的 exit 3：管道竞态下 .lc-rc 可能是空的，会误报「读不到」"
        hbd = tmp / "hbtest"
        (hbd / "d").mkdir(parents=True)
        (hbd / "m/selffont-bench").mkdir(parents=True)
        (hbd / "sock").mkdir()
        (hbd / "sock/logdw").touch()
        hbl = hbd / "fakelogcat"
        hbl.write_text(
            "#!/bin/sh\ni=0\nwhile [ $i -lt 200000 ]; do i=$((i+1)); "
            "printf '11-09 18:01:30.123  1074  1099 I Typeface: 第 %06d 行，长度接近真机平均值的填充内容用于占位\\n' $i; done\n",
            encoding="utf-8")
        hbl.chmod(0o755)
        (hbd / "d/logcat.err").write_text("上一轮的旧错误\n", encoding="utf-8")
        ehb = {h: v for h, v in os.environ.items() if h != "MODDIR"}
        ehb.update({"SELFFONT_DATA": str(hbd / "d"), "SELFFONT_MODULES": str(hbd / "m"),
                    "SELFFONT_BOOT_ID": "493", "SELFFONT_BOOT_LOG_SECONDS": "60",
                    "SELFFONT_BOOT_LOG_BYTES": "2097152",
                    "SELFFONT_FAST_REBOOT_WINDOW": "999999999",
                    "SELFFONT_LOGD_SOCKET": str(hbd / "sock/logdw"),
                    "SELFFONT_LOGCTL": str(hbl),
                    "PATH": f"{hbd}:{os.environ.get('PATH','')}"})
        sh([str(guard)], ehb)
        hl = hbd / "d/guard.log"
        for _ in range(200):
            if "抓日志：停止" in hl.read_text(encoding="utf-8"):
                break
            time.sleep(0.2)
        htt = hl.read_text(encoding="utf-8")
        assert "抓日志：停止" in htt, "心跳夹具：抓日志没停下"
        assert "抓日志心跳" in htt, \
            "心跳没写出来：真机上就分不清「一直在抓」和「第 54 秒就断了」"
        # 截断必须显式写在 boot.log 的**最后一行**，且不能被缓冲打乱顺序。
        tail = (hbd / "d/boot.log").read_text(encoding="utf-8").rstrip("\n").splitlines()[-1]
        assert tail.startswith("TRUNCATED:"), f"截断标记不是末行（{tail[:60]}）：缓冲顺序被打乱"
        assert "reason=" in tail, f"TRUNCATED 没写原因：{tail}"
        assert "TRUNCATED" in htt, "guard.log 里没有截断记录"
        assert "上一轮的旧错误" not in (hbd / "d/logcat.err").read_text(encoding="utf-8"), \
            "logcat.err 跨开机累积：上一轮的错误还在，这一轮的查不出来"
        # ★ service.sh：等待必须放进后台子进程。init 收尾时会回收 service.d 的前台进程，
        #   前台等待循环被杀了就永远清不掉 boot-count —— 与 post-fs-data 的死分支叠加，
        #   正常用一天重启一次模块就自杀（2026-11-09 主人打回）。
        nsrc = night.read_text(encoding="utf-8")
        ncode = [ln for ln in nsrc.splitlines() if not ln.lstrip().startswith("#")]
        assert any(ln.strip() == ") &" for ln in ncode), \
            "守夜没把等待放进后台子进程：被 init 回收后 boot-count 永远清不掉"
        # 实际调用行是 `timeout "$WAIT" "$RESETPROP" -w sys.boot_completed 1`：
        # 变量名里没有 resetprop 字样，判据要看 `-w sys.boot_completed`。
        assert any("-w sys.boot_completed" in ln for ln in ncode), \
            "守夜没有事件等待（resetprop -w sys.boot_completed）：退回轮询就必然要 sleep"
        assert not any("sleep" in ln for ln in ncode), \
            f"守夜里还有 sleep：{[ln.strip() for ln in ncode if 'sleep' in ln]}"
        assert "WAIT" in nsrc and "timeout" in nsrc, "resetprop -w 没有超时封顶：等不到会永久挂一个子进程"
        # ★ 2026-11-09 教训：上一轮的现场不是「分析完」才没的，是被清账命令 rm 掉的。
        #   那次 guard.log 停在「logcat 自己结束」，而「谁发起重启」的证据就在 boot.log 里。
        #   所以开机必须**自动扫上一轮日志**：结论进 guard.log，原文留成 boot.log.prev，
        #   新一轮从空文件开始（混在一份里就说不清哪行属于哪次开机）。
        assert "scan_boot_log" in gsrc, "没有把扫描逻辑函数化：自动扫和手动扫会分成两套判据"
        assert "boot.log.prev" in gsrc, "上一轮原文没留档：清账一删就再没有现场"
        scd = tmp / "scantest"
        (scd / "d").mkdir(parents=True)
        (scd / "m/selffont-bench").mkdir(parents=True)
        (scd / "d/boot.log").write_text(
            "11-09 18:01:56.312  1209  1209 W statsd  : statsd terminated on receiving signal 15.\n"
            "11-09 18:01:56.336  1646  1662 D EMDLOGGER1: sys.shutdown.requested =\n"
            "11-09 18:01:50.000  1000  1000 E Watchdog: WATCHDOG KILLING SYSTEM PROCESS\n",
            encoding="utf-8")
        esc = {h: v for h, v in os.environ.items() if h != "MODDIR"}
        esc.update({"SELFFONT_DATA": str(scd / "d"), "SELFFONT_MODULES": str(scd / "m"),
                    "SELFFONT_BOOT_ID": "494", "SELFFONT_NO_LOGCAT": "1",
                    "SELFFONT_FAST_REBOOT_WINDOW": "999999999"})
        sh([str(guard)], esc)
        st = (scd / "d/guard.log").read_text(encoding="utf-8")
        assert "上一轮日志扫描" in st, "开机没有自动扫上一轮日志：又得靠人记得跑命令"
        assert "sys.shutdown.requested" in st and "命中 1" in st, "扫描没认出 sys.shutdown.requested"
        # 真机原句是「receiving signal 15」和「signal number=15」，模式写 received 会漏。
        # 单独验 signal 那条：只放真机原句「receiving signal 15」，
        # 别的模式一条都不该命中，所以「命中 1」必须出现在 signal 那一行。
        sd2 = tmp / "sig15"
        (sd2 / "d").mkdir(parents=True)
        (sd2 / "m/selffont-bench").mkdir(parents=True)
        (sd2 / "d/boot.log").write_text(
            "11-09 18:01:56.312  1209  1209 W statsd  : statsd terminated on receiving signal 15.\n",
            encoding="utf-8")
        sh([str(guard)], {**os.environ, "SELFFONT_DATA": str(sd2 / "d"),
                          "SELFFONT_MODULES": str(sd2 / "m"), "SELFFONT_BOOT_ID": "495",
                          "SELFFONT_NO_LOGCAT": "1",
                          "SELFFONT_FAST_REBOOT_WINDOW": "999999999"})
        s15 = [ln for ln in (sd2 / "d/guard.log").read_text(encoding="utf-8").splitlines()
               if "signal 15|" in ln]
        assert s15 and s15[0].endswith("命中 1"), \
            f"signal 15 那条模式没命中真机原句「receiving signal 15」：{s15}"
        assert "扫描原文" in st and "WATCHDOG KILLING" in st, "没有摘出原文：还得再去 grep"
        assert (scd / "d/boot.log.prev").exists(), "上一轮原文没留成 boot.log.prev"
        assert (scd / "d/boot.log").read_text(encoding="utf-8") == "", \
            "新一轮 boot.log 不是空的：新旧两轮混在一份里，说不清哪行属于哪次开机"
        # 手动扫描脚本必须与守卫共用**同一份**判据（scan_boot_log），不许另写一套；
        # 并且输出不许走 /dev/stdout、/dev/tty、/proc/self/fd/1 —— 这三样在 Android 的
        # root shell 下会「探测能写、实际写不进去」，整段扫描一行都出不来（撞过三次）。
        scan = ROOT / "tools/sf-scan.sh"
        ssrc = scan.read_text(encoding="utf-8")
        scode = [ln for ln in ssrc.splitlines() if not ln.lstrip().startswith("#")]
        assert any("scan_boot_log" in ln for ln in scode), "手动扫描没有复用守卫的 scan_boot_log"
        assert 'awk \'/^scan_boot_log' in ssrc or "scan_boot_log\\(\\)" in ssrc, \
            "没有从守卫里抽 scan_boot_log 函数体"
        for bad in ("/dev/stdout", "/dev/tty", "/proc/self/fd/1"):
            hits = [ln for ln in scode if bad in ln]
            assert not hits, \
                f"手动扫描把输出直连到 {bad}（{hits}）：真机上打不开，整段结果一行都出不来"
        assert "cat \"$OUT\"" in ssrc, "扫描结果没有打回终端"
        # 夹具：跑一遍手动扫描，必须真的把命中数打出来
        st2 = tmp / "scantool"
        (st2 / "data").mkdir(parents=True)
        (st2 / "data/boot.log.prev").write_text(
            "11-09 18:01:56.312 W statsd  : statsd terminated on receiving signal 15.\n"
            "11-09 18:01:50.000 E Watchdog: WATCHDOG KILLING SYSTEM PROCESS\n", encoding="utf-8")
        (st2 / "data/boot.log").write_text("11-09 18:10:00.000 I ActivityManager: 新一轮\n",
                                           encoding="utf-8")
        rout = sh([str(scan)], {**os.environ, "SELFFONT_DATA": str(st2 / "data"),
                               "SELFFONT_GUARD": str(guard),
                               "SELFFONT_SCAN_OUT": str(st2 / "out.txt")})
        assert rout.returncode == 0, rout
        assert "boot.log.prev" in rout.stdout, "手动扫描没扫上一轮日志"
        assert "命中 1" in rout.stdout, f"手动扫描没打出命中数：{rout.stdout[:400]}"
        assert "WATCHDOG KILLING" in rout.stdout, "手动扫描没摘原文"
        # 不设 SELFFONT_BOOT_LOG_BYTES 时必须用 8 MiB（41943 行），这是主人这一轮要的。
        ec2 = {k: v for k, v in ec.items() if k != "SELFFONT_BOOT_LOG_BYTES"}
        ec2["SELFFONT_BOOT_ID"] = "32"
        ec2["SELFFONT_DATA"] = str(capd / "d2")
        ec2["SELFFONT_MODULES"] = str(capd / "m2")
        (capd / "d2").mkdir()
        (capd / "m2/selffont-bench").mkdir(parents=True)
        sh([str(guard)], ec2)
        glog2 = capd / "d2/guard.log"
        for _ in range(60):
            if "抓日志：停止" in glog2.read_text(encoding="utf-8"):
                break
            time.sleep(0.2)
        assert "上限 1 秒 / 25165824 字节" in glog2.read_text(encoding="utf-8"), \
            "默认上限不是 24 MiB：2 MiB 只够 2.8 秒、8 MiB 只够 37 秒，真机 81 秒才重启"
        # ★ 2026-11-09 主人打回的致命 bug：窗口判据原来读 /proc/uptime，
        #   而 post-fs-data 在开机第 2~5 秒跑，uptime 永远 ~3 秒 < 300 ——
        #   「活过窗口期就清零」是**死分支**，正常重启一次就把模块关掉。
        #   现在判据是 `boot_id - 上次的 boot_id`（两个 btime 相减），夹具必须用它。
        # 只看**窗口判据那一段**（从「开机计数」到「先写计数再干别的」之间）。
        # 抓取时长那边用 /proc/uptime 量「跑了多少秒」是正当的，不许一刀切。
        _win_start = gsrc.index("# ---- ① 开机计数 ----")
        _win_end = gsrc.index("# 先写计数再干别的")
        _win_block = [ln for ln in gsrc[_win_start:_win_end].splitlines()
                      if not ln.lstrip().startswith("#")]
        assert not any("/proc/uptime" in ln for ln in _win_block), \
            ("窗口判据又回去读 /proc/uptime 了：开机第 3 秒时它永远小于窗口，分支永远走不到。"
             f"违规行：{[ln.strip() for ln in _win_block if '/proc/uptime' in ln]}")
        assert "boot_id - _last" in gsrc or "_lived=$(( boot_id - _last ))" in gsrc, \
            "窗口判据不是两个 btime 相减：那就算不出「上次开机活了多久」"
        # 场景 A：上次开机活了 4 小时（btime 差 14400 ≥ 300）→ 必须清零、不停用
        win = tmp / "wintest"
        (win / "d").mkdir(parents=True)
        (win / "m/selffont-bench").mkdir(parents=True)
        (win / "d" / "boot-count").write_text("3\n")
        (win / "d" / "pfd-seen").write_text("1000000\n")
        ew = {h: v for h, v in os.environ.items() if h != "MODDIR"}
        ew.update({"SELFFONT_DATA": str(win / "d"), "SELFFONT_MODULES": str(win / "m"),
                   "SELFFONT_BOOT_ID": "1014400", "SELFFONT_NO_LOGCAT": "1",
                   "SELFFONT_FAST_REBOOT_WINDOW": "300"})
        sh([str(guard)], ew)
        assert not (win / "m/selffont-bench/disable").exists(), \
            "上次开机活了 4 小时（≥ 窗口 300 秒），这次却把它停用了：一次正常重启就误杀模块"
        assert (win / "d" / "boot-count").read_text().strip() == "1", \
            "活过窗口期却没清零：计数会一直累积，迟早误停用"
        wlog = (win / "d" / "guard.log").read_text(encoding="utf-8")
        assert "上次开机存活 14400 秒" in wlog, f"没报上次开机活了多久：{wlog[-400:]}"
        # 场景 B：上次开机只活了 81 秒（< 300）→ 必须累加，超过阈值就停用
        win2 = tmp / "wintest2"
        (win2 / "d").mkdir(parents=True)
        (win2 / "m/selffont-bench").mkdir(parents=True)
        (win2 / "d" / "boot-count").write_text("1\n")
        (win2 / "d" / "pfd-seen").write_text("2000000\n")
        ew2 = {h: v for h, v in os.environ.items() if h != "MODDIR"}
        ew2.update({"SELFFONT_DATA": str(win2 / "d"), "SELFFONT_MODULES": str(win2 / "m"),
                    "SELFFONT_BOOT_ID": "2000081", "SELFFONT_NO_LOGCAT": "1",
                    "SELFFONT_FAST_REBOOT_WINDOW": "300", "SELFFONT_MAX_BOOT_FAIL": "1"})
        sh([str(guard)], ew2)
        assert (win2 / "m/selffont-bench/disable").exists(), \
            "上次只活了 81 秒（卡住特征）却没停用：守卫失效"

        # ★ 2026-11-09 真机：清完账 ls 一看还躺着 boot.log.1 = 13,219,112 字节（12.6 MB）。
        #   旧版只在**本次开机开始时**给 boot.log 封顶，写坏的 boot.log 被 mv 成 .1 之后
        #   再没人管它；清理命令只删 boot.log，宿主机上就永远留一份 13 MB。
        #   夹具：给一个超上限的 .1，跑一次开机，.1 必须整份消失。
        big = tmp / "big1"
        (big / "d").mkdir(parents=True)
        (big / "m").mkdir(parents=True)
        (big / "d" / "boot.log.1").write_bytes(b"x" * 50000)
        (big / "d" / "boot.log").write_bytes(b"y" * 100)
        eb = {h: v for h, v in os.environ.items() if h != "MODDIR"}
        eb.update({"SELFFONT_DATA": str(big / "d"), "SELFFONT_MODULES": str(big / "m"),
                   "SELFFONT_BOOT_ID": "1", "SELFFONT_BOOT_LOG_BYTES": "2048",
                   "SELFFONT_NO_LOGCAT": "1"})
        sh([str(guard)], eb)
        assert not (big / "d" / "boot.log.1").exists(), \
            "超过上限的 boot.log.1 没人管：真机上就留了一份 12.6 MB（清理命令只删 boot.log）"

        # 日志上界：不封顶的话卡死循环里每次开机都写，能把 /data 写满。
        assert "SELFFONT_BOOT_LOG_BYTES" in guard.read_text(encoding="utf-8"), \
            "开机日志没有体积上界"
        # 停用之后不许再抓日志（模块已不生效，抓了也没人看，只会继续占空间）。
        # 全机清理工具（tools/sf-clean.sh）：主人 2026-11-08 原话「你们 ai 做的事总要别人
        # 擦屁股，所以我向你要全机清理命令」。这里锁死三件真会出事的行为——
        # ①默认只读；②`--delete` 也必须留住真标记 disable；③别人的开机脚本一个字节不动。
        clean = ROOT / "tools/sf-clean.sh"
        assert sh(["-n", str(clean)], os.environ).returncode == 0, "sf-clean.sh 语法错误"
        root = tmp / "clean"
        for sub in ("adb/modules/selffont-bench", "adb/modules/other", "adb/sf-crash/20260101-000000",
                    "adb/ksu/log", "adb/post-fs-data.d", "adb/boot-completed.d",
                    "tmp", "dl"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        (root / "adb/modules/selffont-bench/module.prop").write_text("id=selffont-bench\n")
        (root / "adb/modules/selffont-bench/disable").write_text("")     # 真标记：必须留
        (root / "adb/modules/selffont-bench/disablebak").write_text("")  # 假标记：可删
        (root / "adb/modules/other/module.prop").write_text("id=other\n")
        (root / "adb/sf-crash/20260101-000000/dmesg.old.log").write_text("x")
        (root / "adb/ksu/log/x.log").write_text("x")
        (root / "adb/post-fs-data.d/sf-guard.sh").write_text("x")        # 我们的：可删
        (root / "adb/post-fs-data.d/someone.sh").write_text("x")         # 别人的：必须留
        (root / "adb/boot-completed.d/hmaoss.sh").write_text("x")        # 别人的：必须留
        (root / "tmp/MFGA-base.zip").write_text("x")
        (root / "dl/selffont.zip").write_text("x")                       # 要刷的包：不自动删
        rewritten = tmp / "clean.sh"
        text = clean.read_text(encoding="utf-8")
        for old, new in (("/data/adb", str(root / "adb")),
                         ("/data/local/tmp", str(root / "tmp")),
                         ("/storage/emulated/0/Download", str(root / "dl")),
                         ('[ "$(id -u)" = "0" ] ||', "true ||")):
            text = text.replace(old, new)
        rewritten.write_text(text, encoding="utf-8")

        # ① 默认只读：什么都不许没。
        assert sh([str(rewritten)], os.environ).returncode == 0
        assert (root / "adb/sf-crash").exists() and (root / "adb/ksu/log").exists(), \
            "默认模式下就删了东西"
        assert (root / "tmp/MFGA-base.zip").exists(), "默认模式下就删了东西"
        # ② --delete：可删的清掉，真标记与别人的脚本必须还在。
        assert sh([str(rewritten), "--delete"], os.environ).returncode == 0
        assert not (root / "adb/sf-crash").exists(), "sf-crash 没删掉"
        assert not (root / "tmp/MFGA-base.zip").exists(), "临时副本没删掉"
        assert not (root / "adb/modules/selffont-bench/disablebak").exists(), "假标记没删掉"
        # 真标记必须还在 —— 而且必须在第 ⑧ 段**真的走到过**之后还在。
        # 这一段单跑一次：夹具里只放真标记／不放 `disablebak`，否则第 ⑥ 段的
        # `*bak*` 扫描会先把假标记删掉，第 ⑧ 段就没进分支，断言等于没测。
        solo = root / "solo"
        (solo / "modules/selffont-bench").mkdir(parents=True)
        (solo / "modules/selffont-bench/module.prop").write_text("id=selffont-bench\n")
        (solo / "modules/selffont-bench/disable").write_text("")
        solo_sh = tmp / "clean-solo.sh"
        solo_text = clean.read_text(encoding="utf-8")
        for a, b in (("/data/adb", str(solo)), ("/data/local/tmp", str(solo / "tmp")),
                     ("/storage/emulated/0/Download", str(solo / "dl")),
                     ('[ "$(id -u)" = "0" ] ||', "true ||")):
            solo_text = solo_text.replace(a, b)
        solo_sh.write_text(solo_text, encoding="utf-8")
        assert sh([str(solo_sh), "--delete"], os.environ).returncode == 0
        assert (solo / "modules/selffont-bench/disable").exists(), \
            "删了真标记 disable：模块会复活，下次开机还可能卡在第一屏"
        assert (root / "adb/post-fs-data.d/someone.sh").exists(), "删了别人的开机脚本"
        assert (root / "adb/boot-completed.d/hmaoss.sh").exists(), "删了别人的开机脚本"
        assert (root / "dl/selffont.zip").exists(), "把可能要刷的包删了"
        assert (root / "adb/modules/selffont-bench/module.prop").exists(), "没加 --keep-module 就删了模块"
        # ④ 别人的模块里的同名但不同用途的文件：真机 2026-11-08 输出把
        #    GGAT_10007/update.json（KernelSU 模块更新信息）与 hma_oss_zygisk/update_desc.sh
        #    （那个模块自己的脚本）列成了「假标记可删」——glob `update*` 范围太大。
        #    这里锁死：它们既不许被列为可删，也不许在 --delete 之后消失。
        alien = root / "alien"
        (alien / "modules/hma_oss_zygisk").mkdir(parents=True)
        (alien / "modules/GGAT_10007").mkdir(parents=True)
        (alien / "modules/tricky_store").mkdir(parents=True)
        (alien / "modules/hma_oss_zygisk/module.prop").write_text("id=hma_oss_zygisk\n")
        (alien / "modules/hma_oss_zygisk/update_desc.sh").write_text("#!/bin/sh\necho hi\n")
        (alien / "modules/hma_oss_zygisk/module.prop.bak").write_text("old prop\n")
        (alien / "modules/GGAT_10007/module.prop").write_text("id=GGAT_10007\n")
        (alien / "modules/GGAT_10007/update.json").write_text('{"versionCode":1}\n')
        (alien / "modules/tricky_store/module.prop").write_text("id=tricky_store\n")
        (alien / "modules/tricky_store/keybox.xml.bak").write_text("x" * 2000)
        alien_sh = tmp / "clean-alien.sh"
        alien_text = clean.read_text(encoding="utf-8")
        for a, b in (("/data/adb", str(alien)), ("/data/local/tmp", str(alien / "tmp")),
                     ("/storage/emulated/0/Download", str(alien / "dl")),
                     ('[ "$(id -u)" = "0" ] ||', "true ||")):
            alien_text = alien_text.replace(a, b)
        alien_sh.write_text(alien_text, encoding="utf-8")
        listing = sh([str(alien_sh)], os.environ).stdout
        for must_not_list in ("update.json", "update_desc.sh", "keybox.xml.bak", "module.prop.bak"):
            hits = [ln for ln in listing.splitlines() if must_not_list in ln and "[删]" in ln]
            assert not hits, f"别人的 {must_not_list} 被列成可删：{hits}"
        assert sh([str(alien_sh), "--delete"], os.environ).returncode == 0
        for must_survive in ("modules/hma_oss_zygisk/update_desc.sh",
                             "modules/hma_oss_zygisk/module.prop.bak",
                             "modules/GGAT_10007/update.json",
                             "modules/tricky_store/keybox.xml.bak",
                             "modules/hma_oss_zygisk/module.prop"):
            assert (alien / must_survive).exists(), f"--delete 删了别人的 {must_survive}"

        # ★ 开机守卫 sf-guard.sh / sf-night.sh 必须**永不删**：它们是「卡在第一屏」
        #   定因的唯一工具（连续 3 次没走到底自动停用 + logcat 落盘）。
        #   第一版把它们列成可删，一跑 --delete 就把定因能力删了。
        keepboot = root / "keepboot"
        (keepboot / "adb/post-fs-data.d").mkdir(parents=True)
        (keepboot / "adb/service.d").mkdir(parents=True)
        (keepboot / "adb/post-fs-data.d/sf-guard.sh").write_text("x")
        (keepboot / "adb/service.d/sf-night.sh").write_text("x")
        (keepboot / "adb/post-fs-data.d/sf-pstore.sh").write_text("x")
        kb_sh = tmp / "clean-keepboot.sh"
        kb_text = clean.read_text(encoding="utf-8")
        kb_text = kb_text.replace("/data/local/tmp", str(keepboot / "tmp"))
        kb_text = kb_text.replace("/storage/emulated/0", str(keepboot / "sd"))
        kb_text = kb_text.replace("/data/adb", str(keepboot / "adb"))
        kb_text = kb_text.replace('[ "$(id -u)" = "0" ] ||', "true ||")
        kb_sh.write_text(kb_text, encoding="utf-8")
        assert sh([str(kb_sh), "--delete"], os.environ).returncode == 0
        assert (keepboot / "adb/post-fs-data.d/sf-guard.sh").exists(), \
            "--delete 删了开机守卫 sf-guard.sh：崩溃定因能力没了"
        assert (keepboot / "adb/service.d/sf-night.sh").exists(), \
            "--delete 删了守夜 sf-night.sh：计数永远不清零，好机器也会被停用"
        assert not (keepboot / "adb/post-fs-data.d/sf-pstore.sh").exists(), \
            "旧收集脚本 sf-pstore.sh 该删没删"

        # ⑤ 覆盖面：主人 2026-11-08 当场问「其他文件夹怎么不查」——第一版只扫
        #    /data/adb 一个目录，`/data/adb/sf-crash`（22 MB）还被 stat 报成 4 KB。
        #    这里锁两件：目录大小必须用 du 算；三个根（/data、/storage、/cache）都得进扫描范围。
        clean_text = clean.read_text(encoding="utf-8")
        assert "du -sk" in clean_text and "if [ -d \"$1\" ]" in clean_text, \
            "kb() 对目录没用 du：22 MB 的目录会被报成 4 KB（真机实测）"
        assert "for root in /data /storage/emulated/0 /cache" in clean_text, \
            "全盘扫描的根少了：不能只查 /data/adb"
        # 真机第二版在「── /data」卡死：这根底下就是 /data/data（几十万文件），
        # 而 ⑭ 里写着「不查 /data/data」。必须有 prune，且剪枝清单是按 $root 现算的
        # （写死绝对路径的话沙箱夹具测不到，改结构就悄悄失效）。
        assert "-prune" in clean_text, "全盘扫描没有剪枝：会在 /data/data 上卡死（真机实测）"
        assert 'prune="$prune -path $p -o"' in clean_text, \
            "剪枝写死了绝对路径：沙箱夹具测不到，改目录结构就悄悄失效"
        assert "124" in clean_text, "超时必须按退出码 124 判，否则空目录会被误报成超时（真机实测）"
        # 夹具实测：/data/data 与 /data/misc 里的 *selffont* 不许被列出来。
        scope = tmp / "scope"
        (scope / "data/data/com.someapp").mkdir(parents=True)
        (scope / "data/misc").mkdir(parents=True)
        (scope / "data/keepme").mkdir(parents=True)
        (scope / "data/data/com.someapp/selffont-should-not-appear").write_text("x")
        (scope / "data/misc/selffont-alsono").write_text("x")
        (scope / "data/keepme/selffont-should-appear").write_text("x")
        scope_sh = tmp / "clean-scope.sh"
        scope_text = clean.read_text(encoding="utf-8")
        for a, b in ((str(scope / "data"), str(scope / "data")),):
            pass
        # 顺序要紧：**先**换整行扫描根，**再**换各段路径。
        # 反过来做过一次，前面把 /storage/emulated/0 与 /cache 替换掉之后，
        # 整行 `for root in /data /storage/emulated/0 /cache` 就再也匹配不到，
        # 三个根全变成空，夹具成了「什么都没扫」的假通过。
        scope_text = scope_text.replace("for root in /data /storage/emulated/0 /cache",
                                        f"for root in {scope}/data {scope}/sd {scope}/cache")
        scope_text = scope_text.replace("/data/local/tmp", str(scope / "data/local/tmp"))
        scope_text = scope_text.replace("/storage/emulated/0", str(scope / "sd"))
        scope_text = scope_text.replace("/cache", str(scope / "cache"))
        scope_text = scope_text.replace("/data/adb", str(scope / "data/adb"))
        scope_text = scope_text.replace('[ "$(id -u)" = "0" ] ||', "true ||")
        scope_sh.write_text(scope_text, encoding="utf-8")
        out = sh([str(scope_sh)], os.environ).stdout
        assert "selffont-should-appear" in out, f"该列的没列：{out[-500:]}"
        assert "selffont-should-not-appear" not in out, "进了 /data/data：真机就是在这卡死的"
        assert "selffont-alsono" not in out, "进了 /data/misc"

        # ★ 真机第三版：/storage/emulated/0 与 /cache 底下没有 data/misc/system 这些子目录，
        #   prune 变空串，拼出 `\( \(  \) -prune \)`，find 报
        #   `invalid expression; empty parentheses are not allowed`，被 2>/dev/null 吞掉，
        #   这两根**永远输出空**，看着像「没有垃圾」。
        #   真机证据：⑫ 在 /storage/emulated/0 下是空的，⑬ 却列出同一位置 23 MB 的 selffont 目录。
        #   夹具：造一个**没有**那些子目录的根，里面的 selffont 必须在 ⑫ 段被列出来。
        flat = tmp / "flat"
        (flat / "sd/Download/selffont").mkdir(parents=True)
        (flat / "sd/Download/selffont/pkg.zip").write_text("x")
        flat_sh = tmp / "clean-flat.sh"
        flat_text = clean.read_text(encoding="utf-8")
        flat_text = flat_text.replace("for root in /data /storage/emulated/0 /cache",
                                      f"for root in {flat}/sd")
        flat_text = flat_text.replace("/data/local/tmp", str(flat / "tmp"))
        flat_text = flat_text.replace("/storage/emulated/0", str(flat / "sd"))
        flat_text = flat_text.replace("/cache", str(flat / "nocache"))
        flat_text = flat_text.replace("/data/adb", str(flat / "data/adb"))
        flat_text = flat_text.replace('[ "$(id -u)" = "0" ] ||', "true ||")
        flat_sh.write_text(flat_text, encoding="utf-8")
        flat_run = sh([str(flat_sh)], os.environ)
        # ★ 断言只切 ⑫ 那一段。第一版断言整份输出里有没有 "Download/selffont"，
        #   结果被 ⑬「占地排行」满足（⑬ 同样列出那个目录），变异版照样全绿。
        #   「断言被别处的输出满足」是最常见的假通过写法，先把范围切出来再断言。
        flat_out = flat_run.stdout
        flat_12 = flat_out.split("⑫ 全盘按名字找")[-1].split("⑬ 占地最多")[0] \
            if "⑫ 全盘按名字找" in flat_out else ""
        assert "Download/selffont" in flat_12, \
            f"空剪枝让这一根彻底失效（真机就是这样漏掉 /storage/emulated/0）：{flat_12[-400:]}"
        assert "invalid expression" not in flat_out + flat_run.stderr
        assert "没有**查的地方" in clean_text or "没有" in clean_text, "没交代哪些地方没查"

        # ★ 真机第三版（2026-11-08 18:43 输出）打回三个噪音，全在 ⑫：
        #   ① /data/media/0 与 /storage/emulated/0 是同一卷，23524 KB 被列了两遍；
        #   ② 备份目录已整条列出，里面 5 个 xml 又各列一遍；
        #   ③ 本模块目录自己的 licenses/MFGA-base-LICENSES.md、MarukoGothic-OFL.txt
        #      名字里带 MFGA/Maruko，中了「按名字找」的圈，被当垃圾列出来。
        noise = tmp / "noise"
        (noise / "data/media/0/Download/selffont/backup-x").mkdir(parents=True)
        for i in (1, 2, 3):
            (noise / f"data/media/0/Download/selffont/backup-x/{i}-fonts.xml").write_text("<x/>")
        (noise / "data/adb/modules/selffont-bench/licenses").mkdir(parents=True)
        (noise / "data/adb/modules/selffont-bench/licenses/MFGA-base-LICENSES.md").write_text("x")
        (noise / "data/adb/modules/selffont-bench/licenses/MarukoGothic-OFL.txt").write_text("x")
        (noise / "sd/Download/selffont").mkdir(parents=True)
        (noise / "sd/Download/selffont/pkg.zip").write_text("x")
        noise_sh = tmp / "clean-noise.sh"
        nt = clean.read_text(encoding="utf-8")
        nt = nt.replace("for root in /data /storage/emulated/0 /cache",
                        f"for root in {noise}/data {noise}/sd {noise}/nocache")
        nt = nt.replace("/data/local/tmp", str(noise / "tmp"))
        nt = nt.replace("/storage/emulated/0", str(noise / "sd"))
        nt = nt.replace("/cache", str(noise / "nocache"))
        nt = nt.replace("/data/adb", str(noise / "data/adb"))
        nt = nt.replace('[ "$(id -u)" = "0" ] ||', "true ||")
        noise_sh.write_text(nt, encoding="utf-8")
        no = sh([str(noise_sh)], os.environ).stdout
        n12 = no.split("⑫ 全盘按名字找")[-1].split("⑬ 占地最多")[0]
        assert n12.count("Download/selffont") == 1, \
            f"同一卷列了两遍（/data/media/0 与 /storage 是一个地方）：{n12}"
        assert "MFGA-base-LICENSES.md" not in n12 and "MarukoGothic-OFL.txt" not in n12, \
            f"本模块自己目录里的文件被当成垃圾列出来了：{n12}"
        assert "1-fonts.xml" not in n12, f"目录已整条列出，里面的文件又各列一遍：{n12}"
        assert "/media/" not in n12.split("/sd")[0], "⑫ 的 /data 那一根没剪掉 media"

        # ★ 2026-11-08 真机两次连跑（相隔一分钟）打回来的：⑬ 里 Nagram 一次整个消失、
        #   一次显示 0.0 MB（先前那次是 237.9 MB）。根因是 `2>/dev/null` 把 du 的报错吞了，
        #   读不到就静默给 0 或干脆不给行——又一个「看着查了其实没查」。
        #   锁死：du 报 0 但目录非空时，必须印「读不准」而不是 0.0 MB；报错必须原样列出。
        tail12 = clean.read_text(encoding="utf-8")
        assert "没读到" in tail12, "⑬ 对「du 报 0 但目录非空」没有明说，会印一个假 0.0 MB"
        assert "FUSE" not in tail12, "⑬ 又把「du 没读到」猜成了 FUSE 读不全：猜错原因比不说更糟"
        assert "du 报错被跳过" in tail12, "⑬ 吞掉了 du 的报错，读不到也不会有人知道"
        # 结构断言：这两条才是原 bug 的形态。只查字面词的话，把判据改成 if false 也照样绿。
        du_lines = [ln for ln in tail12.splitlines() if "du -sk" in ln]
        assert du_lines and all('2>"$ERRS"' in ln for ln in du_lines if "sort -rn" in ln), \
            "⑬ 的 du 又把报错丢给 /dev/null 了：读不到会静默变成 0 或直接不给行"
        assert any("ls -A" in ln for ln in tail12.splitlines()), \
            "⑬ 没有用 ls -A 判断目录非空：du 报 0 的目录会被当成真的空"

        # ★ 崩溃定因工具（tools/sf-why.sh）：主人 2026-11-08「还有崩溃定因」。
        #   它自己的失效方式很阴：读不到的目录被 2>/dev/null 闷掉，整份报告一片空白，
        #   看着像「查了，没发现问题」——这正是本轮全机清理做废过的那个坑。
        #   这里锁三件：①非 root 必须拒绝下结论；②一块证据都没有时必须判「判不出来」
        #   并逐条列出缺哪块；③造真证据时必须判出具体那一块。
        why = ROOT / "tools/sf-why.sh"
        assert sh(["-n", str(why)], os.environ).returncode == 0, "sf-why.sh 语法错误"
        # 只看代码行：文件头那句「刻意不用 2>/dev/null」是解释，拿它比会误判。
        why_code = [ln for ln in why.read_text(encoding="utf-8").splitlines()
                    if not ln.lstrip().startswith("#")]
        assert not any("2>/dev/null" in ln for ln in why_code), \
            "sf-why.sh 里出现 2>/dev/null：读不到会被闷成空白，等于假装查过"

        empty = tmp / "why-empty"
        (empty / "sys/fs/pstore").mkdir(parents=True)

        def run_why(rootdir, *args):
            env = dict(os.environ, SELFFONT_ROOT=str(rootdir), SELFFONT_FAKE_ROOT="1")
            return sh([str(why), *args], env)

        # ① 非 root：不许给结论（真机上 pstore/dropbox/tombstone 都读不到）。
        env_nr = dict(os.environ, SELFFONT_ROOT=str(empty))
        nr = sh([str(why)], env_nr)
        assert nr.returncode == 2, "非 root 也照常下结论：非 root 的「没证据」不算数"
        assert "不是 root" in nr.stdout

        # ② 全空：必须说「判不出来」，且把读不到的块一条条列出来。
        e = run_why(empty)
        assert e.stdout.count("判不出来") >= 1, f"全空却没有判「判不出来」：{e.stdout[-400:]}"
        for must_report in ("/data/system/dropbox", "/data/tombstones", "boot.log"):
            assert must_report in e.stdout.split("没查成")[-1], \
                f"没查成的地方漏报 {must_report}：{e.stdout.split('没查成')[-1][:300]}"

        # ③ 造真证据：dropbox 的 `_crash@时间戳`、tombstone 的 keyProcess、
        #    守卫计数、disable 标记——四样都要认出来。
        full = tmp / "why-full"
        for sub in ("sys/fs/pstore", "data/system/dropbox", "data/tombstones",
                    "data/adb/selffont", "data/adb/modules/selffont-bench"):
            (full / sub).mkdir(parents=True)
        (full / "sys/fs/pstore/console-ramoops-0").write_text("panic\n")
        # 真机的名字就是 `_crash@<毫秒>`，第一版只认 `_crash_` 会全漏。
        (full / "data/system/dropbox/system_server_crash@1789000000000.txt").write_text(
            "Process: com.android.systemui\n")
        (full / "data/tombstones/tombstone_01").write_text(
            "pid: 99, tid: 99, name: system_server  >>> system_server <<<\nkeyProcess: 1\n")
        (full / "data/adb/selffont/boot-count").write_text("3\n")
        (full / "data/adb/selffont/guard.log").write_text("第 3 次开机开始（阈值 2）\n")
        (full / "data/adb/modules/selffont-bench/disable").write_text("")
        f = run_why(full)
        assert "system_server_crash@1789000000000.txt" in f.stdout, \
            "dropbox 的 `_crash@<时间戳>` 没认出来（只认 `_crash_` 会全漏）"
        assert "keyProcess=1" in f.stdout, "tombstone 的 keyProcess 没列"
        assert "带 disable 标记" in f.stdout, "模块被停用这件事没报出来"
        assert "判不出来" not in f.stdout, f"明明有证据还判不出来：{f.stdout[-400:]}"

        # ③ 未知参数不许当成默认跑。
        assert sh([str(rewritten), "--yes-delete-everything"], os.environ).returncode == 2, \
            "未知参数没有拒绝"

        # 用**代码行**的锚点，不用注释里的字样：文件头那条 `SELFFONT_NO_LOGCAT=1`
        # 是给主人看的说明，拿它比顺序会拿注释和代码比，比出来的结论没有意义。
        guard_src = guard.read_text(encoding="utf-8")
        disable_at = guard_src.index(': > "$MODDIR/disable"')
        logcat_at = guard_src.index('${SELFFONT_NO_LOGCAT:-0}')
        assert disable_at < logcat_at, "停用判断必须排在抓日志之前"


# ---------------------------------------------------------------- 仓库自身的数据与常量

@check
def center_x():
    """横向归中：默认关；打开后只平移、不缩放、不动字宽，且只碰满格字。

    母版 10% 的满格字墨心偏中线 20~54 单位（`羽` −31、`扁` −54.5），按母版框对齐会把
    偏差原样抄过来。`SELFFONT_CENTER=1` 时把它平移回 500。这里用三个字验死两件事：
    默认态一个点都不许动；打开后所有点的 x 位移必须完全相等（「只平移」的证明）。
    """
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "tools"))
    import box_align
    import cjk_vf
    import design_cjk

    glyphs = cjk_glyphs()
    sample = [ord(ch) for ch in "羽扁日" if ord(ch) in glyphs]
    assert len(sample) == 3, "抽样字不在字库里"
    saved = box_align.CENTER_X
    try:
        rings = {}
        for cp in sample:
            data = glyphs[cp]
            cjk_vf.settle_junction_widths(data)
            rs, _flags = cjk_vf._glyph_rings_all(data, cp)
            rings[cp] = cjk_vf.align_face_height(rs)

        box_align.CENTER_X = False
        off = {cp: box_align.apply_all(rings[cp], cp) for cp in sample}
        for cp in sample:
            assert off[cp] == box_align.apply(rings[cp], cp), "关闭时必须与旧行为逐点相同"

        box_align.CENTER_X = True
        on = {cp: box_align.apply_all(rings[cp], cp) for cp in sample}
        moved = 0
        for cp in sample:
            before = [p for ring in off[cp][400] for p in ring]
            after = [p for ring in on[cp][400] for p in ring]
            shifts = {round(b[0] - a[0], 3) for a, b in zip(before, after)}
            assert len(shifts) == 1, f"{chr(cp)} 各点 x 位移不一致（不是纯平移）：{len(shifts)} 种"
            dx = shifts.pop()
            assert all(b[1] == a[1] for a, b in zip(before, after)), f"{chr(cp)} y 被改动了"
            width = max(p[0] for p in before) - min(p[0] for p in before)
            if width >= box_align.CENTER_WIDE:
                centre = (min(p[0] for p in after) + max(p[0] for p in after)) / 2
                assert abs(centre - 500) <= 0.01, f"{chr(cp)} 归中后墨心 {centre} 不在 500"
                assert abs(dx) > 0.4, f"{chr(cp)} 满格字却没被归中（dx={dx}）"
                moved += 1
        assert moved >= 2, "满格字样本没有被归中，判据等于没测"
        # 字宽不受影响：汉字前进量恒为 1000（归中只动轮廓，不动 advance）。
        assert cjk_vf.advance_of(sample[0], on[sample[0]]) == 1000, "归中改动了字宽"
        # 两条边界：非满格字（窄部件）与「母版偏差超兜底线」都不许动。
        box_align.CENTER_X = True
        narrow = {400: [[(0.0, 0.0), (100.0, 10.0), (100.0, 0.0), (0.0, 0.0)]]}
        assert box_align.center_x(narrow, -1, target=(0, 0, 100, 10)) == narrow, \
            "窄字（非满格）被归中了"
        wide_ring = {400: [[(0.0, 0.0), (1000.0, 0.0), (1000.0, 900.0), (0.0, 900.0)]]}
        crazy = (0, 0, 1700, 900)        # 墨心 850，偏 350 > CENTER_MAX
        assert box_align.center_x(wide_ring, -1, target=crazy) == wide_ring, \
            "母版偏差超兜底线的字被归中了（表坏时会把字挪飞）"
    finally:
        box_align.CENTER_X = saved


@check
def garbage_scanner():
    """全机垃圾排查脚本：语法过、非 root 拒绝下结论、只读不删、--delete 只删该删的。

    上一版手工脚本栽在 `su -c ... || sh ...` 上：兜底那一半以普通用户跑，
    `/data/adb` 读不到，五段全打印「（无）」——**假结论比没查更坏**。
    所以这里的断言按「会不会骗人」排序，第一条就是非 root 必须退出码 3。
    """
    script = ROOT / "tools/check_garbage.sh"
    assert script.is_file(), "缺 tools/check_garbage.sh"
    assert sh(["-n", str(script)], os.environ).returncode == 0, "check_garbage.sh 语法错误"
    body = script.read_text()
    assert "id -u" in body and "exit 3" in body, "非 root 必须直接退出，不许继续打印（无）"
    device = ROOT / "tools/probe_device.sh"
    assert device.is_file(), "缺 tools/probe_device.sh（真机探针）"
    assert sh(["-n", str(device)], os.environ).returncode == 0, "probe_device.sh 语法错误"
    dbody = device.read_text()
    assert "id -u" in dbody and "不算数" in dbody, "真机探针必须自己标注非 root 的结论不可信"
    assert '--delete' in body, "必须保留 --delete 开关"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        download = tmp / "storage/emulated/0/Download"
        module = tmp / "data/adb/modules/MFGA"
        service = tmp / "data/adb/service.d"
        for path in (download / "Nagram", module, service, tmp / "data/local/tmp"):
            path.mkdir(parents=True)
        # 三类样本：真垃圾（*.bak、ksubak、误写标记）、假垃圾（BakaSU 应用）、
        # 绝不能删的（真 disable 标记、开机脚本）。
        junk = [download / "MFGA.bak", download / "ksubak.zip",
                module / "disablebak", module / "old.orig",
                tmp / "data/local/tmp/selffont.zip",
                tmp / "data/adb/selffont-skia.state"]
        keep = [download / "Nagram/BakaSU_v4.2.0-rc3.apk", module / "disable",
                module / "module.prop", service / "01-font.sh"]
        for path in junk + keep:
            path.write_bytes(b"x")
        env = dict(os.environ, SELFFONT_SCAN_BASE=str(tmp))

        dry = subprocess.run(["sh", str(script)], env=env, capture_output=True, text=True)
        assert dry.returncode == 0, f"夹具跑不通：{dry.stderr[-400:]}"
        assert all(path.exists() for path in junk), f"只读模式删了东西：{[p for p in junk if not p.exists()]}"
        for path in junk:
            assert str(path) in dry.stdout, f"只读模式漏报 {path.name}"
        assert "BakaSU_v4.2.0-rc3.apk" in dry.stdout, "名字带 bak 的正常应用必须被列进「仅供辨认」"
        assert "01-font.sh" in dry.stdout, "开机脚本没有被列出来"
        assert "汇总" in dry.stdout and "KB" in dry.stdout, "缺汇总行（条目数与字节数）"

        wiped = subprocess.run(["sh", str(script), "--delete"], env=env,
                               capture_output=True, text=True)
        assert wiped.returncode == 0, f"--delete 跑不通：{wiped.stderr[-400:]}"
        assert all(not path.exists() for path in junk), f"该删的没删：{[p for p in junk if p.exists()]}"
        assert all(path.exists() for path in keep), f"删了不该删的：{[p for p in keep if not p.exists()]}"
        assert "↳ 已删" in wiped.stdout, "--delete 没打印删了什么"


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
def dead_code():
    """§9 旧代码清零：标识符只出现一次、import 零用、只写不读的变量。

    判据不在本文件里另写一套——扫描器是 tools/deadcode.py，它自己列盲区。
    这里只负责「非 0 就挂」，这样本地 --check 与 CI 走同一条判据。
    """
    result = subprocess.run([sys.executable, str(ROOT / "tools/deadcode.py")],
                            capture_output=True, text=True)
    assert result.returncode == 0, "死码未清零：\n" + result.stdout[-3000:]
    assert "合计 0 处死码" in result.stdout, result.stdout[-2000:]
    # ★ 2026-11-09 主人打回四条，逐条钉死，防止扫描器再悄悄瞎掉：
    #   ① ast 计数把赋值目标数了两遍（`FOO = 1` 的目标本来就是 ast.Name(Store)），
    #      于是「零引用常量」检测率恒为 0%。夹具：临时文件里造一个零引用常量必须被抓出。
    #   ② `.sh` 只写不读的变量原来根本不扫（文件头注释却吹了牛）。
    #   ③ 被 eval 进来的函数会读的变量不能算死（否则删了就是真 bug，我踩过）。
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("dc_probe", ROOT / "tools/deadcode.py")
    _dc = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_dc)

    import tempfile as _tf
    _probe_root = Path(_tf.mkdtemp(prefix="sf-dcprobe-"))
    probe = _probe_root
    probe.mkdir(exist_ok=True)
    (probe / "const_probe.py").write_text(
        "UNUSED_CONST = 1\nUSED_CONST = 2\nprint(USED_CONST)\n", encoding="utf-8")
    ast_counts = _dc.ast_name_counts(probe)
    assert ast_counts.get("UNUSED_CONST") == 1, \
        f"ast 计数把赋值数了两遍：UNUSED_CONST={ast_counts.get('UNUSED_CONST')}（应为 1），零引用常量永远抓不到"
    assert ast_counts.get("USED_CONST") == 2, \
        f"定义+一次引用应为 2：{ast_counts.get('USED_CONST')}"

    (probe / "w.sh").write_text("#!/bin/sh\nDEAD_VAR=1\nLIVE_VAR=2\necho \"$LIVE_VAR\"\n",
                                encoding="utf-8")
    assert [n for _, n in _dc.shell_write_only(probe / "w.sh")] == ["DEAD_VAR"], \
        f".sh 只写不读没扫对：{_dc.shell_write_only(probe / 'w.sh')}"
    (probe / "e.sh").write_text(
        "#!/bin/sh\nEVAL_VAR=1\neval \"$(sed -n '1p' x)\"\n", encoding="utf-8")
    assert _dc.shell_write_only(probe / "e.sh") == [], \
        "有 eval 的文件仍被判定只写不读：那变量可能被 eval 进来的函数读，删了就是真 bug"



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


# 四类产物各归一条工作流（主人第六、七次强调）：build 出母版、selffont 出自版（冻着）、
# selfrounds 出字体本身、hotswap 出热切换——**四条工作流，四条名字，四类前缀，不许混在一条里**。
# `log-` 是失败时的诊断件，不是交付物，四条都可能出。
#
# 母版产物名按主人口径走 `build-<版本>`（2026-11-06 曾改成 `Selffont-母版-<版本>`，已按主人要求改回）。
ARTIFACT_OWNER = {
    "build-": {"build.yml"},
    "selffont-": {"selffont.yml"},
    "selfrounds-": {"selfrounds.yml"},
    "log-": {"build.yml", "selffont.yml", "selfrounds.yml", "hotswap.yml"},
    "hotswap-": {"hotswap.yml"},
}


@check
def workflow_format():
    """§12 工作流格式：每个 workflow 同一套，几个、几种由仓里定。

    这条检查故意不看文件内容做了什么，只看七样格式——name、注释行数、顶层 env、
    并发组、清理 job、步骤名、artifact 三样。任何一样不齐就红，红了不许推送。
    """
    import re
    import yaml

    class _Strict(yaml.SafeLoader):
        """重复键直接报错。

        `yaml.safe_load` 遇到重复键只保留最后一个——同一次改动里我写出两段 `env:`、
        两个 `overwrite:`，它一声不响地通过，GitHub 那边却整份判「invalid workflow」，
        运行起来 0 个 job。宽松解析器给出的绿是假的。
        """

    def _no_dup(loader, node, deep=False):
        seen = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            assert key not in seen, f"重复键 {key!r} 第 {key_node.start_mark.line + 1} 行"
            seen[key] = loader.construct_object(value_node, deep=deep)
        return seen

    _Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dup)

    folder = ROOT / ".github" / "workflows"
    names = {}
    for path in sorted(folder.glob("*.yml")):
        stem = path.stem
        text = path.read_text(encoding="utf-8")
        data = yaml.load(text, Loader=_Strict)

        # 1. name 与文件名一致、不重复
        assert data.get("name") == stem, f"{path.name}: name={data.get('name')!r} 应等于文件名 {stem!r}"
        assert stem not in names, f"工作流名重复：{stem}"
        names[stem] = path

        # 2. 顶部注释 1–5 行
        head = []
        for line in text.splitlines():
            if line.startswith("#"):
                head.append(line)
            else:
                break
        assert 1 <= len(head) <= 5, f"{path.name}: 顶部注释 {len(head)} 行，要求 1–5 行"

        # 3. 顶层 env 两键
        env = data.get("env") or {}
        assert env.get("SEGMENTS") == "5" or env.get("SEGMENTS") == 5, f"{path.name}: 顶层 env 缺 SEGMENTS"
        assert str(env.get("CLEANUP_APPLY")).lower() == "true", f"{path.name}: 顶层 env 缺 CLEANUP_APPLY"

        # 4. 并发组 <仓>-<用途>、cancel-in-progress 为 false
        conc = data.get("concurrency") or {}
        assert conc.get("group") == f"selffont-{stem}", \
            f"{path.name}: 并发组 {conc.get('group')!r}，要求 selffont-{stem}"
        assert str(conc.get("cancel-in-progress")).lower() == "false", f"{path.name}: cancel-in-progress 必须为 false"

        # 5. 自带清理 job：if: always()、调 cleanup.py（同组由第 4 条的顶层并发组保证）
        cleanup = [job for job in (data.get("jobs") or {}).values()
                   if ".github/scripts/cleanup.py" in str(job)]
        assert cleanup, f"{path.name}: 没有调 .github/scripts/cleanup.py 的清理 job"
        for job in cleanup:
            assert "always()" in str(job.get("if", "")), f"{path.name}: 清理 job 必须挂 if: always()"

        # 6. 步骤名中文
        for job_name, job in (data.get("jobs") or {}).items():
            for step in job.get("steps", []):
                label = step.get("name")
                assert label, f"{path.name}/{job_name}: 有步骤没有 name"
                assert re.search(r"[\u4e00-\u9fff]", label), f"{path.name}/{job_name}: 步骤名不是中文：{label!r}"

        # 7. artifact 三样
        for job_name, job in (data.get("jobs") or {}).items():
            for step in job.get("steps", []):
                if "upload-artifact" not in str(step.get("uses", "")):
                    continue
                with_ = step.get("with") or {}
                for key in ("retention-days", "if-no-files-found", "overwrite"):
                    assert key in with_, f"{path.name}/{job_name}: artifact 缺 {key}"
                assert with_["if-no-files-found"] == "error", \
                    f"{path.name}/{job_name}: if-no-files-found 必须是 error"

        # 8a. 冻结要能被检查：尚未合格的自研字体两条工作流都不许挂 push。
        # 上一版只查 selffont，selfrounds 出的就是同一个还没合格的字体，却一直挂着 push，
        # 每次推送都拿四个字的预览图冠上正式产物名上传（主人 2026-11-09 指出）。冻结必须两条一起冻。
        if stem in ("selffont", "selfrounds"):
            triggers = data.get("on") or data.get(True) or {}
            if isinstance(triggers, str):
                triggers = {triggers: None}
            assert "push" not in triggers, \
                (f"{path.name} 冻结中，不许挂 push（字体不合格，出包要有合格命令）。"
                 "job 级 if 挡不住，实测 2026-11-06 白跑一次 53 分钟）")

        # 8. 名字与产物一对一：四类前缀各归各的工作流，工作流名与 job 名必须是自己的产物
        for job_name, job in (data.get("jobs") or {}).items():
            prefixes = set()
            for step in job.get("steps", []):
                if "upload-artifact" not in str(step.get("uses", "")):
                    continue
                label = str((step.get("with") or {}).get("name", ""))
                prefix = label.split("${{")[0]
                owner = ARTIFACT_OWNER.get(prefix)
                assert owner, f"{path.name}/{job_name}: 产物前缀 {prefix!r} 不在四类里（{sorted(ARTIFACT_OWNER)}）"
                assert path.name in owner, \
                    f"{path.name}/{job_name}: 产物 {label!r} 只属于 {sorted(owner)}，不该在这里出"
                prefixes.add(prefix)
            if prefixes:
                # 一个 job 只许出一类产物：非诊断产物前缀只许一个（`log-` 是诊断件，不计）。
                products = prefixes - {"log-"}
                assert len(products) <= 1, \
                    f"{path.name}/{job_name}: 一个 job 出了 {sorted(products)} 多类产物，一类都不许多"
        # 工作流名必须等于自己的产物名（`build`↔`build-` 正是这一条）。
        if stem in {p.rstrip("-") for p in ARTIFACT_OWNER}:
            assert path.name in ARTIFACT_OWNER[f"{stem}-"], \
                f"{path.name}: 前缀 {stem}- 归 {sorted(ARTIFACT_OWNER[f'{stem}-'])}，不含本文件"
        else:
            owned = [p for p, ws in ARTIFACT_OWNER.items() if path.name in ws and p != "log-"]
            assert owned, f"{path.name}: 这件工作流一件属于自己的产物都没有（{sorted(ARTIFACT_OWNER)}）"
            assert len(owned) == 1, f"{path.name}: 它名下有 {owned} 多个前缀，一条工作流只许一类产物"

        # 8b. 母版产物的名字与保留期（按主人口径）：名字是 `build-<版本>`，保留期 5 天。
        if stem == "build":
            for step in (data.get("jobs") or {}).get("build", {}).get("steps", []):
                if "upload-artifact" not in str(step.get("uses", "")):
                    continue
                with_ = step.get("with") or {}
                label = str(with_.get("name", ""))
                assert label == f"build-${{{{ env.VERSION }}}}", \
                    f"{path.name}: 母版产物名必须是 build-<版本>，收到 {label!r}"
                assert str(with_.get("retention-days")) == "5", \
                    f"{path.name}: 母版产物 retention-days 必须是 5（30 天太占，Actions 产物总量上限 5 个）"


@check
def no_auto_publish():
    """流水线里不许有发版能力，产物名里不许带 SHA。

    2026-11-06 的现场：为了「325 没有链接」加了 `gh release create`，出了 326；随后整段撤回、
    连 Release 一起删；再之后又加回来，还补了 `--target`。三轮反复都因为一件事没有定论——
    **发版是手工动作**（规范 §11／§13：Release 手工）。所以这条检查只钉死两件：
    一，`.github` 里不出现任何发版调用（`gh release` / `action-gh-release` / `push --tags`）；
    二，README 不承诺 Release 下载地址。要让直链出现，必须先改这条检查——那一步必然是一次显式的对话。

    顺带钉 §13 的命名：artifact 名只许 `<项目名>-<版本>`，后缀里不带 SHA。所以四条工作流里
    任何 `upload-artifact` 的 name 都不许出现 `SHA8` / `GITHUB_SHA`。
    """
    folder = ROOT / ".github"
    tokens = ("gh release", "action-gh-release", "push --tags")
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix not in {".yml", ".yaml", ".py"}:
            continue
        text = path.read_text(encoding="utf-8")
        for token in tokens:
            assert token not in text, \
                f"{path.relative_to(ROOT)}: 出现发版调用 {token!r}——发版是手工动作，流水线里不许有"

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "releases/latest" not in readme and "releases/download" not in readme, \
        "README 不许承诺 Release 下载地址：发版是手工动作，流水线不再产出它"

    import yaml
    for path in sorted((folder / "workflows").glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (data.get("jobs") or {}).items():
            for step in job.get("steps", []):
                if "upload-artifact" not in str(step.get("uses", "")):
                    continue
                label = str((step.get("with") or {}).get("name", ""))
                assert "SHA8" not in label and "GITHUB_SHA" not in label, \
                    f"{path.name}/{job_name}: 产物名 {label!r} 带 SHA——§13 后缀只许 <版本>"
                if label.startswith("log-"):
                    continue          # 诊断件（失败日志），名字走 run_id，不是交付物
                assert label.endswith("${{ env.VERSION }}"), \
                    f"{path.name}/{job_name}: 产物名 {label!r} 的后缀必须是 ${{{{ env.VERSION }}}}（五段版本）"


def run_checks(only: str | None = None) -> None:
    failed = 0
    selected = [fn for fn in CHECKS if only is None or fn.__name__ == only]
    if only is not None and not selected:
        print(f"没有叫 {only} 的检查项；现有：{', '.join(fn.__name__ for fn in CHECKS)}")
        sys.exit(2)
    for fn in selected:
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
    print(f"{len(selected)} 项全部通过")


@check
def passthrough_font():
    """母版直通：CJK 字件必须是母版的**同一串字节**，一个轮廓点都不许动。

    直通包是用来量基准的：五条判据对着它比，任何改动都跟它差多少一目了然。所以这里
    断言三件事——包里的字件 sha256 等于源文件、配置引用的文件名是它自己的名字、
    配置里的族名是母版内部族名（静态字体写 weight，不写 supportedAxes）。
    """
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        base = tmp / "base.zip"
        base_zip(base, {"Roboto-Regular.ttf": make_carrier()})
        regular = tmp / "P-Regular.ttf"
        regular.write_bytes(make_font())
        mother = tmp / "MarukoGothicCJKsc-Regular.ttf"
        mother.write_bytes(make_font(family="Maruko Gothic", axes=False))
        output = tmp / "out" / "Selffont.zip"
        build(base=str(base), font=str(regular), output=output, build_num="9", day="2",
              date="26.9.30", cjk=False, supplemental_font_sources=(),
              passthrough_mother=str(mother), fixture=True)
        with zipfile.ZipFile(output) as archive:
            member = f"system/fonts/{mother.name}"
            assert member in archive.namelist(), sorted(archive.namelist())
            assert hashlib.sha256(archive.read(member)).hexdigest() == digest(mother), \
                "直通包里的母版被改了字节（只许原样挂载）"
            xml = archive.read("font_fallback.xml").decode()
            root = ET.fromstring(xml)
            own = [f for f in root.iter("family")
                   if any((n.text or "").strip() == mother.name for n in f.findall("font"))]
            assert own, "配置里没有引用直通字件"
            node = own[0].find("font")
            assert node.get("weight") == "400" and node.get("supportedAxes") is None, \
                "静态母版不许写成 supportedAxes（那是可变字件的写法）"
            assert own[0].get("name") and "Maruko" in own[0].get("name"), own[0].get("name")
            assert archive.read("fonts-insert.xml").decode().count(mother.name) >= 1, \
                "Skia 那份插入行里也得有直通字件"

        # 基准件必须与发行件**不同 id**。同一个 id 只有一条路能让基准件盖住发行件：把
        # versionCode 抬到发行件之上（2026-11-01 那次抬到 90 万）——抬完发行件的三位数总序号
        # 在管理器眼里永远是降级，刷过基准件的机器再也换不回正规包。id 分开就没有这个问题。
        bench = tmp / "out" / "bench.zip"
        build(base=str(base), font=str(regular), output=bench, build_num="7", day="1", fixture=True,
              date="26.11.1", cjk=False, supplemental_font_sources=(),
              passthrough_mother=str(mother), module_id="selffont-bench")
        with zipfile.ZipFile(bench) as archive:
            bench_prop = archive.read("module.prop").decode()
        fields = dict(line.split("=", 1) for line in bench_prop.splitlines() if "=" in line)
        assert fields["id"] == "selffont-bench", f"基准件没换独立 id：{fields['id']}"
        assert fields["versionCode"] == "7", f"基准件不该抬 versionCode：{fields['versionCode']}"
        assert "selffont-bench" in fields["description"], "包说明没写清它的 id 与发行件不同"


@check
def module_hotswap():
    """运行期换字体：本机四条路全部判死（真机证据），脚本只许剩下「报告」与「清场」。

    判据（都能在这台没装 Android 的机器上判）：
      1. `module/hotswap.sh` 里**不许出现任何发起挂载的语句**（要的是 `mount -t overlay`
         与 `mount --bind` 这两个字符串一个都不出现），只许用 `umount` 去摘残留；
      2. 四个子命令只剩 `status` 与 `panic`；`on`/`off`/`toggle`/`verify` 存在即判失败；
      3. `action.sh` 的按钮只接 `status` / `skia` 开关与 `panic`，没有运行期挂载切换与 `web` 动作；
      4. 四条判死证据的原文都在脚本注释与 README 里（`Invalid argument`、
         `Read-only file system`、探针不出现、`install-debug-cert`）。
    """
    module = ROOT / "module"
    for script in sorted(module.glob("*.sh")):
        result = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"{script.name} 语法错误：{result.stderr.strip()}"
    hotswap = (module / "hotswap.sh").read_text(encoding="utf-8")
    for banned in ("mount -t overlay", "mount --bind", "nsenter", "upperdir=$UPPER,workdir"):
        assert banned not in hotswap, f"hotswap.sh 里还有发起挂载的语句：{banned}"
    assert "umount" in hotswap, "panic 需要 umount 才能摘残留"
    for gone in ("cmd_on", "cmd_off", "cmd_verify", "cmd_toggle"):
        assert gone not in hotswap, f"hotswap.sh 还留着运行期切换的实现：{gone}"
    assert "cmd_status" in hotswap and "cmd_panic" in hotswap, "status/panic 必须保留"
    for evidence in ("Invalid argument", "Read-only file system", "install-debug-cert",
                     "开机快照"):
        assert evidence in hotswap, f"hotswap.sh 少了判死证据：{evidence}"

    action = (module / "action.sh").read_text(encoding="utf-8")
    for gone in ('"$MODDIR/hotswap.sh" toggle', "web)", "hotswap.sh\" on", "hotswap.sh\" off"):
        assert gone not in action, f"action.sh 还留着切换动作：{gone}"
    assert "hotswap.sh\" status" in action
    assert "panic" in action and "本机不支持运行期换字体" in action
    # Skia 开关是标记文件 + 重启落地，不是运行期挂载：它必须走 skia.sh，不许自己写挂载。
    assert "skia.sh" in action and "mount" not in action, "action.sh 的 Skia 开关必须交给 skia.sh"

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for evidence in ("Invalid argument", "Read-only file system", "install-debug-cert"):
        assert evidence in readme, f"README 少了判死证据：{evidence}"
    assert "本机不支持运行期换字体" in readme or "不支持运行期换字体" in readme, \
        "README 没写清「不支持运行期换字体」"
    # 用假挂载表跑 status/panic：认得出的才摘，开机那层 overlay 不许当残留。
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        data = tmp / "data"
        (data / "upper").mkdir(parents=True)
        (data / "merged").mkdir(parents=True)
        (data / "merged" / "x.ttf").write_bytes(b"0")
        (data / "upper" / "y.ttf").write_bytes(b"0")
        state = tmp / "st"
        Path(str(state) + ".state").write_text("a\n", encoding="utf-8")
        fonts = tmp / "fonts"
        fonts.mkdir()
        mounts = tmp / "mounts"
        mounts.write_text(
            "rootfs / rootfs rw 0 0\n"
            f"/dev/block/dm-76 {fonts} f2fs rw 0 0\n"
            "/dev/block/sda1 /data f2fs rw 0 0\n", encoding="utf-8")
        mountinfo = tmp / "mountinfo"
        mountinfo.write_text(
            f"100 30 0:50 / {fonts} rw - overlay overlay lowerdir=/system/fonts\n"
            f"900 30 0:60 / {fonts} rw - f2fs /dev/block/dm-76 rw\n", encoding="utf-8")
        script = tmp / "hotswap.sh"
        shutil.copy2(module / "hotswap.sh", script)
        # 沙箱里没有 CAP_SYS_ADMIN，umount 会失败；用一个只改挂载表、记录调用的壳替身。
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        umount_log = tmp / "umount.log"
        (bin_dir / "umount").write_text(
            '#!/bin/sh\nprintf "%s\\n" "$1" >> "$UMOUNT_LOG"\n'
            # 真 umount 只摘顶层：同一路径上 mnt_id 最大的那一层
            'top=$(awk -v mp="$1" \'$5 == mp { if ($1 + 0 > m) m = $1 + 0 } END { print m + 0 }\' "$MI")\n'
            '[ "$top" -eq 0 ] && exit 32\n'
            'awk -v id="$top" \'$1 != id\' "$MI" > "$MI.new" && mv "$MI.new" "$MI"\n',
            encoding="utf-8")
        (bin_dir / "umount").chmod(0o755)
        env = {**os.environ, "SELFFONT_DATA": str(data), "SELFFONT_BASE": str(state),
               "SELFFONT_SYSTEM_FONTS": str(fonts), "SELFFONT_MOUNTINFO": str(mountinfo),
               "SELFFONT_MOUNTS": str(mounts), "PATH": f"{bin_dir}:{os.environ['PATH']}",
               "UMOUNT_LOG": str(umount_log), "MI": str(mountinfo)}

        def run_hs(*args):
            return subprocess.run(["sh", str(script), *args], env=env, capture_output=True, text=True)

        result = run_hs("status")
        assert result.returncode == 0 and "本机不支持" in result.stdout, result.stdout
        assert "900" in result.stdout and "整目录 bind 残留" in result.stdout, result.stdout
        assert "100" not in result.stdout, "把开机那层 overlay 也算成我们的残留了"

        result = run_hs("panic")
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert "摘下" in result.stdout and "900" in result.stdout, result.stdout
        assert "与 fonts 相关的剩余行" in result.stdout, result.stdout
        assert umount_log.read_text().strip() == str(fonts),             f"panic 摘错了东西：{umount_log.read_text()!r}"
        assert not data.exists(), "panic 没删工作目录"
        assert not Path(str(state) + ".state").exists(), "panic 没清状态文件"
        assert "100 30 0:50" in mountinfo.read_text(), "panic 把开机那层也摘了"

        result = run_hs("on")
        assert result.returncode == 2, "on 这个子命令必须已经不存在（不许有第四版挂载实现）"


@check
def probe_position():
    """定位探针能跑、量具自己没写错：`tools/probe_position.py` 的常量必须与构建期一致。

    探针不读字体文件（本机没有成品），它把「摆位」那一段复算一遍：settle_junction_widths
    → align_face_height → box_align.apply。这里只验它**量的东西没走样**——
    win 必须盖住字身框（否则「行框不裁字」那一条白测），判据线必须比 2% em 宽一点点，
    抽样必须真的抽到汉字。真正跑全库用 `python tools/probe_position.py --sample 300`。
    """
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "tools"))
    import probe_position as probe
    assert probe.EM == 1000 and probe.WIDE < probe.EM, "满格判据的宽度阈值不合理"
    assert probe.TOL_HARD > probe.TOL >= 20, "判据线必须严于 3% em，且提示线要宽于判据线"
    assert probe.cjk_vf.HHEA_ASCENT > 900 and probe.cjk_vf.HHEA_DESCENT < -160, \
        f"win 装不下字身框 {probe.cjk_vf.FRAME}：行框那一条等于没测"
    assert probe.cjk_vf.FRAME[3] <= probe.cjk_vf.HHEA_ASCENT, "字身框上沿高过 win 上沿"
    sample = probe.sample_codepoints(None, 8)
    assert len(sample) == 8 and all(probe.cjk_vf.is_han(cp) for cp in sample), \
        f"抽样没抽到汉字：{[hex(cp) for cp in sample[:4]]}"
    rows = probe.measure(sample)["rows"]
    assert len(rows) == 8, f"复算的字数不对：{len(rows)}"
    r = probe.report(probe.measure(sample))
    assert r["advance"]["not_1000"] == [], f"汉字 advance 不是 1000：{r['advance']['not_1000']}"
    assert not r["outside"], f"复算出来的字出字身框：{r['outside'][:3]}"
    assert probe.verdict(r)[-1].startswith("判定: "), "没有判定行"


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
    # `法`（0x6CD5）是端头多边形的锚字：它的收笔端在母版里是正圆，
    # LINE_TOL/ARC_STEPS 一改回去就会变成一圈直线，下面的断言就在这个字上判。
    sample = {cp: glyphs[cp] for cp in
              (0x4E00, 0x53E3, 0x9F98, 0x6CD5, 0x31, 0x20, 0x41, 0x48, 0x6F, 0x79,
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
        # 端头不许是折线（2026-11-01 主人指出的「多边形」）：`法` 的 `去` 字收笔端，
        # 改前 LINE_TOL=0.80 + ARC_STEPS=9 让整圈半圆被判成 12 段直线，6× 下就是多边形。
        # 判据：收笔端点 45 单位内的轮廓段里，直线段占比 ≤ 50%；且端头不能整圈都是直线。
        from fontTools.pens.recordingPen import RecordingPen as _Rec
        pen = _Rec()
        font.getGlyphSet()[font.getBestCmap()[0x6CD5]].draw(pen)
        point, segments, previous = (893.0, -18.0), [], None
        for op, args in pen.value:
            if op == "moveTo":
                previous = args[0]
            elif op in ("lineTo", "qCurveTo", "curveTo"):
                end = args[-1]
                if previous is not None:
                    near = min(((previous[0] - point[0]) ** 2 + (previous[1] - point[1]) ** 2,
                                (end[0] - point[0]) ** 2 + (end[1] - point[1]) ** 2)) < 45 ** 2
                    if near:
                        segments.append(op)
                previous = end
        straight = segments.count("lineTo")
        assert segments, "`法` 的收笔端点附近没量到轮廓段：坐标锚点漂了？"
        assert straight < len(segments), f"`法` 收笔端整圈都是直线（{len(segments)} 段）：端头成了多边形"
        assert straight / len(segments) <= 0.5, \
            f"`法` 收笔端直线段 {straight}/{len(segments)}，超过一半：端头是多边形（LINE_TOL/ARC_STEPS 被改回？）"
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
    assert alone.get("name") is None, "二创族不带名字：它按语言区参与回退，不是可选家族"
    # 曾经这里断言「不带语言、只要排在主字体之前就行」——那是错的：Minikin 逐族打分
    # （覆盖分<<29 | 语言分<<1 | 变体分），匿名族语言分恒 0，中文全被语言区里的主字体抢走。
    # 现在要求带 zh 标签，且排在所有 CJK 语言区族之前，语言分打平时才按顺序取胜。
    assert {tag.strip() for tag in (alone.get("lang") or "").split(",")} >= {"zh-Hans", "zh-Hant"}, \
        "二创族必须带 zh 语言标签，否则语言分为 0，中文永远落语言区里的主字体"
    order = list(root)
    zh_families = [family for family in order
                   if family is not alone and is_cjk_locale(family.get("lang"))]
    assert zh_families, "模板里应有 CJK 语言区族（本断言同时防止测试夹具漂移成空集）"
    assert order.index(alone) < min(order.index(family) for family in zh_families), \
        "二创族必须排在所有 CJK 语言区族之前：语言分打平时按文件顺序取靠前的"


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
    # 只跑指定的检查项。变异测试要一条一条验，全量一次 25 秒，五次就两分钟起步。
    parser.add_argument("--only", metavar="名字", help="只跑这一项检查（配合 --check）")
    parser.add_argument("--cjk-font", type=Path, metavar="DIR",
                        help="只出二创汉字字件（可变 + 三个静态实例）到 DIR，不下载、不打包")
    parser.add_argument("--passthrough-mother", metavar="TTF",
                        help="母版直通：把这份 TTF 原样放进包（不改任何轮廓），只用于量基准")
    parser.add_argument("--module-id", metavar="ID",
                        help="改写模块 id（基准件用独立的 id，避免与发行件同一 id 互相压制 versionCode）")
    parser.add_argument("--preview", metavar="字…",
                        help="只编这几个字出预览小字体（几秒），配合 --compare 出母版对照图")
    parser.add_argument("--preview-out", type=Path, metavar="DIR", default=ROOT / "work" / "preview",
                        help="预览产物目录（默认 work/preview/，不入库）")
    parser.add_argument("--compare", type=Path, metavar="TTF",
                        help="预览对照用的母版字体（不给就只出 preview.ttf）")
    parser.add_argument("--base", help="基础包 ZIP：本地路径或 URL（默认下载并缓存）")
    parser.add_argument("--font", metavar="PATH|URL", help="主字体：本地文件或 URL（默认用内置来源）")
    parser.add_argument("--output", type=Path,
                        help="产物路径（默认跟版本走：build/selffont-<五段版本>.zip）")
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
        run_checks(args.only)
    else:
        build(base=args.base, font=args.font, output=args.output, build_num=args.build,
              day=args.day, date=args.date, query=args.query_ci,
              keep_web_fonts=args.keep_web_fonts,
              passthrough_mother=args.passthrough_mother, module_id=args.module_id)


@check
def review_marks():
    """§19 检讨标记机自检：`tools/mark.py` 的插与验必须同源、且真能抓假。

    这批自检是必要的，因为上一轮「先用 tools/mark.py 实测通过」这句话说了三遍，
    而那个文件**从来没存在过** —— 工具不接进 --check，就会烂成一句空话。
    """
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("mark_probe", ROOT / "tools/mark.py")
    mk = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mk)

    body = "汉字" * 5100                      # 10200 汉字
    marked = mk.insert(body)
    assert mk.strip_marks(marked) == body, "插标记吃掉了正文"
    assert [int(x) for x in mk.MARK.findall(marked)] == list(range(100, 10201, 100)), \
        "标记位置不是每满 100 汉字一枚"
    ok, problems, line = mk.check(marked)
    assert ok, f"合规稿被判不合格：{problems}"

    # 六种造假各造一次，必须全部变红（宁可这个自检自己挂，也不许造假蒙过去）
    cases = {
        "手改标记": marked.replace("〔200〕", "〔150〕", 1),
        "删一个汉字（间隔变 99）": marked[:marked.index("汉", 10)] + marked[marked.index("汉", 10) + 1:],
        "末尾漏标 240 字": marked + "汉字" * 120,
        "极短稿只有 1 枚标记（不足一万）": mk.insert("汉字" * 150),
        "无标记裸稿": "汉字" * 90,
        "删掉首枚标记": marked.replace("〔100〕", "", 1),
        "标记数虚报（去掉一半）": mk.MARK.sub("", marked[: len(marked) // 2]) + marked[len(marked) // 2:],
    }
    for label, text in cases.items():
        bad_ok, bad_problems, _ = mk.check(text)
        assert not bad_ok, f"造假没被抓：{label}"
    assert "本篇汉字 10200" in line and "末枚〔10200〕" in line, line


if __name__ == "__main__":
    main()
