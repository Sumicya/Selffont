#!/usr/bin/env python3
"""复刻 Skia 的逐字回退，回答「这个码位在 Skia 里由哪个字件画」。

为什么要有这个文件：Flutter 的字体全走 Skia（`flutter/engine`
`txt/src/txt/platform_android.cc`：`GetDefaultFontFamilies()` 返回 `{"sans-serif"}`、
`SkFontMgr_New_Android(nullptr, …)`），而 minikin 走 `SystemFonts.java` 的
`FONTS_XML = "/system/etc/font_fallback.xml"`。两条路读**不同的文件**，所以
「装完 minikin 换字了」不能推出「Flutter 也换了」。本工具按 Skia 源码的判定顺序
逐字复算，改配置之前先看每个码位落到谁身上。

判据出处（google/skia main，逐条对应）：
  src/ports/SkFontMgr_android_parser.cpp  familyHandler：无 name 的族是 fallback 族
      （`fIsFallbackFont`），有 lang 只影响 fLanguages，不影响族的匹配优先级。
  src/ports/SkFontMgr_android.cpp  onMatchFamilyStyleCharacter 的五层顺序；
      find_family_style_character 里每个族**只取一个** face（`matchAStyle`），
      只查那一个 `unicharToGlyph(character) != 0`。
  src/core/SkFontMgr.cpp  matchStyleCSS3：width → slant → weight 打分，
      并列时 `if (maxScore < currentScore)` 是严格小于，**先出现的赢**。
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from fontTools.ttLib import TTFont

# SkFontStyle 的权重档；<font weight> 缺省 0 时取字件自身 style（parser: fontFile.fWeight != 0）
NORMAL_WIDTH = 5


def _width_score(current: int, pattern: int = NORMAL_WIDTH) -> int:
    if pattern <= NORMAL_WIDTH:
        return 10 - pattern + current if current <= pattern else 10 - current
    return 10 + pattern - current if current > pattern else current


def _slant_score(current: int, pattern: int = 0) -> int:
    # score[pattern][current]，取 Upright 那一行
    return [3, 1, 2][current]


def _weight_score(current: int, pattern: int) -> int:
    if pattern == current:
        return 1000
    if pattern < 400:
        return 1000 - pattern + current if current <= pattern else 1000 - current
    if pattern <= 500:
        if pattern <= current <= 500:
            return 1000 + pattern - current
        if current <= pattern:
            return 500 + current
        return 1000 - current
    return 1000 + pattern - current if current > pattern else current


def match_style_css3(faces: list[dict], weight: int = 400, slant: int = 0) -> int:
    """返回 faces 里被 matchStyleCSS3 选中的下标（并列取先出现的）。"""
    best, best_at = -1, 0
    for i, face in enumerate(faces):
        score = _width_score(face.get("width", NORMAL_WIDTH))
        score = (score << 8) + _slant_score(face.get("slant", 0))
        score = (score << 8) + _weight_score(face.get("weight", 400), weight)
        if best < score:
            best, best_at = score, i
    return best_at


def parse_families(path: Path) -> list[dict]:
    """解析 LMP 语法的 fonts.xml（version>=21），只取本工具要用的字段。"""
    families = []
    for node in ET.fromstring(path.read_bytes()).iter("family"):
        name = node.get("name")
        lang = node.get("lang") or ""
        faces = []
        for font in node.findall("font"):
            faces.append({
                "file": (font.text or "").strip(),
                "weight": int(font.get("weight") or 0),
                "slant": 1 if font.get("style") == "italic" else 0,
                "fallback_for": font.get("fallbackFor"),
            })
        # fFallbackFor 只由 <font fallbackFor="…"> 设置（parser.cpp fontHandler），
        # 族上的 lang 不影响它；无 name 的族一律进 fFallbackNameToFamilyMap
        # （addFamily 里补一个 "NN##fallback" 名字），与有没有 lang 无关。
        families.append({"name": name, "lang": lang, "faces": faces,
                         "fallback": name is None,
                         "fallback_for": next((f.get("fallback_for") for f in node.findall("font")
                                               if f.get("fallbackFor")), None)})
    return families


def choose(families: list[dict], cmaps: dict[str, set[int]],
           character: int, weight: int = 400,
           family_name: str | None = "sans-serif") -> str | None:
    """按 Skia 的五层顺序，返回画这个码位的字件名（None = 谁都画不出）。"""
    def hit(haystack: list[dict]) -> str | None:
        for family in haystack:
            if not family["faces"]:
                continue
            face = family["faces"][match_style_css3(family["faces"], weight)]
            if character in cmaps.get(face["file"], set()):
                return face["file"]
        return None

    named = [f for f in families if not f["fallback"]]
    fallback = [f for f in families if f["fallback"]]
    # 五层顺序照抄 onMatchFamilyStyleCharacter，逐条对应源码注释里的 1..5。
    if family_name:
        got = hit([f for f in named if f["name"] == family_name])          # 1 命名族精确匹配
        if got:
            return got
        got = hit([f for f in fallback if f["fallback_for"] == family_name])  # 2 fallbackFor 匹配
        if got:
            return got
    got = hit([f for f in fallback if not f["fallback_for"]])              # 3 fallbackFor 为空的匿名族
    if got:
        return got
    got = hit([f for f in named if f["name"] != family_name])              # 4 其余命名族
    if got:
        return got
    return hit([f for f in fallback if f["fallback_for"]])                 # 5 其余 fallbackFor


def _selftest() -> None:
    # matchStyleCSS3：同权重取先出现的（Skia 严格小于，不更新）——这是「插族首还是族尾」的全部差别。
    assert match_style_css3([{"weight": 400}, {"weight": 400}]) == 0
    assert match_style_css3([{"weight": 400}, {"weight": 700}], weight=400) == 0
    assert match_style_css3([{"weight": 400}, {"weight": 700}], weight=700) == 1
    # 400 请求下 500 比 300 更近（Skia 在 400..500 之间偏好更重）
    assert match_style_css3([{"weight": 300}, {"weight": 500}], weight=400) == 1
    # 族名不匹配时，第四层才会被走到——Flutter 请求 sans-serif，中日韩 lang 族只在第四层
    families = [
        {"name": "sans-serif", "lang": "", "fallback": False, "fallback_for": None,
         "faces": [{"file": "dev.ttf", "weight": 400, "slant": 0}]},
        {"name": None, "lang": "zh", "fallback": True, "fallback_for": None,
         "faces": [{"file": "ours.ttf", "weight": 400, "slant": 0}]},
    ]
    cmaps = {"dev.ttf": {0x4E2D}, "ours.ttf": {0x4E2D, 0x9FFF}}
    assert choose(families, cmaps, 0x4E2D) == "dev.ttf", "同码位时设备族该赢"
    assert choose(families, cmaps, 0x9FFF) == "ours.ttf", "设备没有的码位才轮到我们"
    # 第 3 层：无 name、无 fallbackFor 的匿名族（带 lang 也算）按文件顺序扫。
    families.append({"name": None, "lang": "und-Zsye", "fallback": True, "fallback_for": None,
                     "faces": [{"file": "emoji.ttf", "weight": 400, "slant": 0}]})
    cmaps["emoji.ttf"] = {0x1F600}
    assert choose(families, cmaps, 0x1F600) == "emoji.ttf", "emoji 必须落到匿名 emoji 族"
    # 第 2 层：fallbackFor 命中的匿名族排在「其余匿名族」之前。
    families.insert(1, {"name": None, "lang": "", "fallback": True, "fallback_for": "sans-serif",
                        "faces": [{"file": "ff.ttf", "weight": 400, "slant": 0}]})
    cmaps["ff.ttf"] = {0x263A}
    assert choose(families, cmaps, 0x263A) == "ff.ttf", "fallbackFor 匹配的族该在第 3 层之前"
    print("selftest ok")


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] == "--selftest":
        _selftest()
        return 0
    config = Path(argv[1])
    fonts = [Path(item) for item in argv[2:]]
    cmaps = {}
    for path in fonts:
        with TTFont(path, lazy=True) as font:
            cmaps[path.name] = set(font.getBestCmap())
    families = parse_families(config)
    ours = [name for name in cmaps if "Selffont" in name]
    probe = sorted({cp for name in ours for cp in cmaps[name]})
    hit = sum(1 for cp in probe if choose(families, cmaps, cp) in ours)
    print(f"配置 {config}：{len(families)} 个族"
          f"（fallback 族 {sum(1 for f in families if f['fallback'])}）")
    print(f"本包字件 {len(ours)} 个、{len(probe):,} 个码位；"
          f"Skia 请求 sans-serif 时由本包画的 {hit:,} 个（{100 * hit / max(len(probe), 1):.2f}%）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
