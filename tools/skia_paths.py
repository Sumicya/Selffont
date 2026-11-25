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

    ★★ 2026-11-26 第二次修正。上一版（11-25）把「命名族」整层删掉了，理由是从
    parser.cpp:311 的 `fIsFallbackFont = false` 推出「带名字的族进不了回退表，所以
    族名 sans-serif 不可能被匹配到」。这个推理漏了一步：`onMatchFamilyStyleCharacter`
    的五层顺序里，**第一层不是回退表，是命名族表 `fNameToFamilyMap`**。
    SkFontMgr_android.cpp 现行源码（逐行抄，见下面注释的行号）：

      onMatchFamilyStyleCharacter(familyName, style, bcp47, n, character)   :346
        // 5 层顺序，注释原文就写在函数里
        find(familyName, lang, elegant):
          1) if (!familyName.isEmpty())
               find_family_style_character(familyName, fNameToFamilyMap, ...,
                   [](name, ntf){ return name == ntf.name; })              :371  ← 命名族！
          2) if (!familyName.isEmpty())
               find_family_style_character(familyName, fFallbackNameToFamilyMap,
                   [](name, ntf){ return name == ntf.styleSet->fFallbackFor; })
          3) find_family_style_character(SkString(), fFallbackNameToFamilyMap,
                   [](_, ntf){ return ntf.styleSet->fFallbackFor.isEmpty(); })  ← 无名族
          4) find_family_style_character(familyName, fNameToFamilyMap,
                   [](name, ntf){ return name != ntf.name; })
          5) find_family_style_character(familyName, fFallbackNameToFamilyMap, ...)

    所以：**名字精确相等的命名族在第一层就被问**，命中即返回，根本走不到第 3 层的无名族。
    上一版据此把「插命名族」判成无效，是本项目连续多轮「复算 100%、真机不变」的直接原因。
    这里把第一层补回来，并把命名族的匹配写成 ASCII 小写化的精确相等（onMatchFamily 的实现）。

    另外两条不变的事实仍然有效：
      · find_family_style_character 每族**只取一个面**（matchAStyle → matchStyleCSS3），
        并列时先出现的赢（SkFontMgr.cpp:242 的 `maxScore < currentScore` 严格小于）。
      · 拿到面之后还要问 unicharToGlyph：没有就继续下一个名字（下一条命中的族）。
        这一条才是「我方不覆盖的字符自动由设备接住」的机制来源。
    """
    def hit(haystack: list[dict]) -> str | None:
        for family in haystack:
            if not family["faces"]:
                continue
            face = family["faces"][match_style_css3(family["faces"], weight)]
            if character in cmaps.get(face["file"], set()):
                return face["file"]
        return None

    named = [f for f in families if not f["fallback"] and f.get("name")]
    fallback = [f for f in families if f["fallback"]]
    for current in ((family_name,) if family_name else ()) + (None,):
        if current:
            # 1) 名字精确相等的命名族（onMatchFamily 用 SkAutoAsciiToLC 小写化后精确比较）
            got = hit([f for f in named if (f.get("name") or "").lower() == current.lower()])
            if got:
                return got
            # 2) fallbackFor 等于请求名的回退族
            got = hit([f for f in fallback if f["fallback_for"] == current])
            if got:
                return got
        # 3) fallbackFor 为空的匿名回退族，按文件顺序
        got = hit([f for f in fallback if not f["fallback_for"]])
        if got:
            return got
        if current:
            # 4) 名字不等于请求名的命名族
            got = hit([f for f in named if (f.get("name") or "").lower() != current.lower()])
            if got:
                return got
            # 5) fallbackFor 既不为空也不等于请求名的回退族
            got = hit([f for f in fallback if f["fallback_for"] not in (None, "", current)])
            if got:
                return got
    return None


def _selftest() -> None:
    # matchStyleCSS3：同权重取先出现的（Skia 严格小于，不更新）——这是「族首还是族尾」的全部差别。
    assert match_style_css3([{"weight": 400}, {"weight": 400}]) == 0
    assert match_style_css3([{"weight": 400}, {"weight": 700}], weight=400) == 0
    assert match_style_css3([{"weight": 400}, {"weight": 700}], weight=700) == 1
    # 400 请求下 500 比 300 更近（Skia 在 400..500 之间偏好更重）
    assert match_style_css3([{"weight": 300}, {"weight": 500}], weight=400) == 1

    # ① 命名族**有效**（2026-11-26 修正）：onMatchFamilyStyleCharacter 的第一层
    #    就是按名字精确匹配 fNameToFamilyMap，命中即返回，走不到第 3 层无名族。
    #    上一版这里断言「插命名族不该生效」，正是连续多轮「复算通过、真机不变」的根因。
    named_head = [
        {"name": "sans-serif", "lang": "", "fallback": False, "fallback_for": None,
         "faces": [{"file": "ours.ttf", "weight": 400, "slant": 0},
                   {"file": "dev.ttf", "weight": 400, "slant": 0}]},
        {"name": None, "lang": "zh", "fallback": True, "fallback_for": None,
         "faces": [{"file": "dev_zh.ttf", "weight": 400, "slant": 0}]},
    ]
    cmaps = {"ours.ttf": {0x4E2D}, "dev.ttf": {0x4E2D}, "dev_zh.ttf": {0x4E2D}}
    assert choose(named_head, cmaps, 0x4E2D) == "ours.ttf", \
        "插命名族族首必须生效（第一层按名字匹配）"

    # ①b 我方没有的字形走哪条路，必须说准（这一条我上一版又说错了）。
    #     find_family_style_character **每族只取一个面**：sans-serif 族里 matchAStyle 选中的
    #     就是我方那条，我方没有该字形 ⇒ 这个族交不出面 ⇒ 跳到**下一个族**，
    #     不是「同族的下一条」。所以我方字件在同族里对全部字符是「取代」，不是「分工」。
    #     分工发生在族之间：第 3 层（fallbackFor 为空的匿名回退族，按文件顺序）接住剩下的字符。
    cmaps2 = dict(cmaps, **{"dev.ttf": {0x4E2D, 0x1F600}})   # 同族设备那条有 emoji，也用不上
    assert choose(named_head, cmaps2, 0x1F600) is None, \
        "同族的下一条不会被问到（每族只取一个面）：我方没有的字符跳到下一个族"
    assert choose(named_head, cmaps, 0x1F600) is None, "谁都画不出时返回 None，不伪造"
    # ①b 的反向：第 3 层匿名回退族有我方没有的字形 ⇒ 由它接住（这才是真机上的兜底路径）。
    cmaps3 = dict(cmaps, **{"dev_zh.ttf": {0x4E2D, 0x1F600}})
    assert choose(named_head, cmaps3, 0x1F600) == "dev_zh.ttf", \
        "我方不覆盖的字符由匿名回退族接住（第 3 层）——这条才是不出豆腐块的机制"

    # ①c 族尾等于没插：并列同权重时 matchStyleCSS3 取先出现的。
    named_tail = [
        {"name": "sans-serif", "lang": "", "fallback": False, "fallback_for": None,
         "faces": [{"file": "dev.ttf", "weight": 400, "slant": 0},
                   {"file": "ours.ttf", "weight": 400, "slant": 0}]},
    ]
    assert choose(named_tail, cmaps, 0x4E2D) == "dev.ttf", "族尾等于没插"

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
