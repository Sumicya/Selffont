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
    """按 Skia 的真实代码路径，返回画这个码位的字件名（None = 谁都画不出）。

    ★ 2026-11-25 修正。旧版这里凭空写了一层「命名族精确匹配」，据此三次得出
    「族首插法 100%」的结论，三次真机都没变。真实代码（SkFontMgr_android.cpp）：

      onMatchFamilyStyleCharacter(familyName, …)             :374
          for currentFamilyName in { familyName, SkString() }  :385
              for elegant in {1, 0}
                  ... find_family_style_character(currentFamilyName, …)
      find_family_style_character()                           :342
          for i in fallbackNameToFamilyMap:                   :348
              if familyName != family->fFallbackFor: continue :350   ← 只比 fFallbackFor
              if langTag 不匹配 face->fLang: continue         :355
              if variant 不匹配: continue                     :363
              if face->unicharToGlyph(character) != 0: return face

    两条硬事实：
      1) 它遍历的是 **fFallbackNameToFamilyMap**，而 parser.cpp:311 在族带 name= 时
         把 fIsFallbackFont 置 false —— 带名字的族根本不进这张表。所以族名
         `sans-serif` 在这条路上**不可能**被匹配到（AOSP 真实配置里
         fallbackFor="sans-serif" 出现 0 次）。旧版那一层是假的。
      2) 请求族名取 `families[0]`（FontCollection.cpp:340），Flutter 默认是
         sans-serif；所以第一轮必然空过，**真正生效的只有第二轮的空族名**：
         只找 fFallbackFor == "" 的无名族，**按文件顺序**。
    """
    def hit(haystack: list[dict]) -> str | None:
        for family in haystack:
            if not family["faces"]:
                continue
            face = family["faces"][match_style_css3(family["faces"], weight)]
            if character in cmaps.get(face["file"], set()):
                return face["file"]
        return None

    # 逐字回退只在无名族组成的那张表里找；命中的条件是 fFallbackFor 相等。
    fallback = [f for f in families if f["fallback"]]
    for current in ((family_name,) if family_name else ()) + (None,):
        got = hit([f for f in fallback if f["fallback_for"] == current])
        if got:
            return got
    # 命名族只经 matchFamily/matchStyle 参与（Flutter 的默认字面走这条），
    # 那是另一条路径，不属于逐字回退；这里返回 None 表示「逐字回退画不出」。
    return None


def _selftest() -> None:
    # matchStyleCSS3：同权重取先出现的（Skia 严格小于，不更新）——这是「族首还是族尾」的全部差别。
    assert match_style_css3([{"weight": 400}, {"weight": 400}]) == 0
    assert match_style_css3([{"weight": 400}, {"weight": 700}], weight=400) == 0
    assert match_style_css3([{"weight": 400}, {"weight": 700}], weight=700) == 1
    # 400 请求下 500 比 300 更近（Skia 在 400..500 之间偏好更重）
    assert match_style_css3([{"weight": 300}, {"weight": 500}], weight=400) == 1

    # ① 命名族对逐字回退**无效**：find_family_style_character 只遍历无名族
    #    （parser.cpp:311 在族带 name= 时置 fIsFallbackFont=false）。插 sans-serif 族首
    #    一个字都不换 —— 2026-11-25 前三次真机「没变」就是这个。
    named_only = [
        {"name": "sans-serif", "lang": "", "fallback": False, "fallback_for": None,
         "faces": [{"file": "ours.ttf", "weight": 400, "slant": 0},
                   {"file": "dev.ttf", "weight": 400, "slant": 0}]},
        {"name": None, "lang": "zh", "fallback": True, "fallback_for": None,
         "faces": [{"file": "dev_zh.ttf", "weight": 400, "slant": 0}]},
    ]
    cmaps = {"ours.ttf": {0x4E2D}, "dev.ttf": {0x4E2D}, "dev_zh.ttf": {0x4E2D}}
    assert choose(named_only, cmaps, 0x4E2D) == "dev_zh.ttf", \
        "插命名族不该生效：逐字回退看不到命名族"

    # ② 插无名族族首才生效。
    anon_head = [
        {"name": None, "lang": "zh", "fallback": True, "fallback_for": None,
         "faces": [{"file": "ours.ttf", "weight": 400, "slant": 0},
                   {"file": "dev_zh.ttf", "weight": 400, "slant": 0}]},
    ]
    assert choose(anon_head, cmaps, 0x4E2D) == "ours.ttf", "无名族族首该生效"

    # ③ 族尾等于没插（matchStyleCSS3 并列取先出现的）。
    anon_tail = [
        {"name": None, "lang": "zh", "fallback": True, "fallback_for": None,
         "faces": [{"file": "dev_zh.ttf", "weight": 400, "slant": 0},
                   {"file": "ours.ttf", "weight": 400, "slant": 0}]},
    ]
    assert choose(anon_tail, cmaps, 0x4E2D) == "dev_zh.ttf", "族尾不该生效"

    # ④ 排在 zh 之前的无 lang 匿名族会先赢（真机第三次的形状）：
    #    MFGA 那份配置 [2] 是 100.ttf..900.ttf 同一套中文全字重，排在 zh[10] 之前。
    blocker_ahead = [
        {"name": None, "lang": "", "fallback": True, "fallback_for": None,
         "faces": [{"file": "dev.ttf", "weight": 400, "slant": 0}]},
        {"name": None, "lang": "zh", "fallback": True, "fallback_for": None,
         "faces": [{"file": "ours.ttf", "weight": 400, "slant": 0},
                   {"file": "dev_zh.ttf", "weight": 400, "slant": 0}]},
    ]
    assert choose(blocker_ahead, cmaps, 0x4E2D) == "dev.ttf", \
        "前面的无 lang 匿名族必须先赢：所以它也得插"
    blocker_fixed = [
        {"name": None, "lang": "", "fallback": True, "fallback_for": None,
         "faces": [{"file": "ours.ttf", "weight": 400, "slant": 0},
                   {"file": "dev.ttf", "weight": 400, "slant": 0}]},
        {"name": None, "lang": "zh", "fallback": True, "fallback_for": None,
         "faces": [{"file": "ours.ttf", "weight": 400, "slant": 0},
                   {"file": "dev_zh.ttf", "weight": 400, "slant": 0}]},
    ]
    assert choose(blocker_fixed, cmaps, 0x4E2D) == "ours.ttf", "挡路族插上以后才轮到我们"

    # ⑤ 生僻符号：我们不认识的码位仍落后面那些 Unicode 族（不能整片豆腐）。
    cmaps["u18.ttf"] = {0x1D300}
    with_unicode = blocker_fixed + [
        {"name": None, "lang": "", "fallback": True, "fallback_for": None,
         "faces": [{"file": "u18.ttf", "weight": 400, "slant": 0}]},
    ]
    assert choose(with_unicode, cmaps, 0x1D300) == "u18.ttf", "我们不认识的符号必须仍落设备字件"

    # ⑥ fallbackFor 相等才算命中（它只由 <font fallbackFor> 设置）。
    with_ff = anon_head + [
        {"name": None, "lang": "", "fallback": True, "fallback_for": "sans-serif",
         "faces": [{"file": "ff.ttf", "weight": 400, "slant": 0}]},
    ]
    cmaps["ff.ttf"] = {0x263A}
    assert choose(with_ff, cmaps, 0x263A) == "ff.ttf", "fallbackFor 匹配的族该先被问到"
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
          f"Skia 逐字回退由本包画的 {hit:,} 个（{100 * hit / max(len(probe), 1):.2f}%）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
