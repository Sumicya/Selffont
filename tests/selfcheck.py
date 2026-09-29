#!/usr/bin/env python3
"""Selffont 自检:打包器、度量归一、配置生成与模块脚本的最小行为检查。

无测试框架、无夹具模块。`python3 tests/selfcheck.py` 一把跑完,
全部通过打印 PASS,任何失败非零退出。
"""
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build as builder  # noqa: E402
from fontTools.fontBuilder import FontBuilder  # noqa: E402
from fontTools.pens.ttGlyphPen import TTGlyphPen  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def box(x0, y0, x1, y1):
    pen = TTGlyphPen(None)
    pen.moveTo((x0, y0)), pen.lineTo((x0, y1)), pen.lineTo((x1, y1)), pen.lineTo((x1, y0))
    pen.closePath()
    return pen.glyph()


def make_font(family="Test Primary", weight=400, upm=1000, axes=True):
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
    b.setupOS2(sTypoAscender=880, sTypoDescender=-120, usWinAscent=1160, usWinDescent=288, usWeightClass=weight)
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
    b.setupOS2(sTypoAscender=930, sTypoDescender=-250, usWinAscent=930, usWinDescent=250)
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


def faces(name, **face):
    return {name: {"family": face.get("family", name), "weight": face.get("weight", 400),
                   "axes": face.get("axes", {})}}


# ---------------------------------------------------------------- 度量归一(真机验证的角标修复)

@check
def metric_normalization():
    carrier = builder.layout_metrics(TTFont(io.BytesIO(make_carrier())))
    data = make_font()
    normalized, report = builder.normalize_metrics(data, carrier)
    result = TTFont(io.BytesIO(normalized))
    assert (result["hhea"].ascent, result["hhea"].descent) == (930, -250), "hhea 未对齐空壳"
    assert (result["OS/2"].sTypoAscender, result["OS/2"].sTypoDescender) == (930, -250), "typo 未对齐"
    assert report["original"]["hhea"] == [1160, -288, 0], "原度量未记录"
    assert report["digitInkY"] == [-10, 744], "数字墨迹未记录"
    builder.assert_glyphs_preserved(data, normalized)  # 轮廓/cmap/家族/轴必须逐字节不变
    scaled = TTFont(io.BytesIO(builder.normalize_metrics(make_font(upm=2048), carrier)[0]))
    assert scaled["hhea"].ascent == round(930 * 2048 / 1000), "upm 缩放错误"
    # 会切数字墨迹的归一必须被拒:空壳 ascent 700 盖不住数字墨迹 744。
    try:
        builder.normalize_metrics(make_font(), dict(carrier, hhea=[700, -100, 0]))
        raise AssertionError("切墨迹的归一未被拒绝")
    except ValueError:
        pass
    # 空壳判定:可见字形的 Roboto 不能当空壳。
    assert builder.carrier_metrics(make_carrier(visible=True)) is None
    assert builder.carrier_metrics(make_carrier())["hhea"] == [930, -250, 0]
    assert builder.carrier_metrics(b"not a font") is None


# ---------------------------------------------------------------- 字重阶梯与 fonts.xml 生成

@check
def fonts_xml():
    vf = faces("V.ttf", axes={"wght": (100, 400, 900), "ital": (0, 0, 1)})
    ladder = builder.weight_ladder(vf)
    assert len(ladder) == 18 and all(entry["axes"] for entry in ladder), "可变字体应出 9 档 × 2 风格带轴"
    assert [entry["weight"] for entry in ladder if not entry["italic"]] == list(builder.WEIGHTS)
    # 轴范围窄:只出范围内的档,不拒绝。
    assert [entry["weight"] for entry in builder.weight_ladder(faces("V.ttf", axes={"wght": (200, 400, 700)}))]
    assert [entry["weight"] for entry in builder.weight_ladder(faces("V.ttf", axes={"wght": (200, 400, 700)}))
            if not entry["italic"]] == [200, 300, 400, 500, 600, 700]
    # 静态:声明字重就近映射(并列取较重),单文件也能打包。
    static = builder.weight_ladder(faces("S.ttf", weight=500))
    assert len(static) == 18 and {entry["file"] for entry in static} == {"S.ttf"} and not static[0].get("axes")

    template = (ROOT / "fonts.xml").read_bytes()
    root = builder.ET.fromstring(builder.configure_fonts(template, ladder, True))
    default = root.find("family[@name='sans-serif']")
    assert {node.text.strip() for node in default.findall("font")} == {builder.CARRIER}, "默认家族应保留度量空壳"
    fallback = list(root)[list(root).index(default) + 1]
    assert fallback.get("name") is None and len(fallback.findall("font")) == 18, "匿名字形回退应紧随默认家族"
    assert {node.text.strip() for node in fallback.findall("font")} == {"V.ttf"}
    for family in root.findall("family"):
        for node in family.findall("font"):
            assert (node.text or "").strip() not in builder.OLD_PRIMARY, "残留旧数字主字体"
    # 静态主字体不生成 axis;可变主字体生成 axis。
    static_root = builder.ET.fromstring(builder.configure_fonts(template, static, True))
    ours = [node for family in static_root.findall("family") for node in family.findall("font")
            if (node.text or "").strip().startswith("S.")]
    assert ours and not any(node.findall("axis") for node in ours), "静态主字体不该生成 axis"
    assert b"<axis" in builder.ET.tostring(
        builder.ET.fromstring(builder.configure_fonts(template, ladder, True)), encoding="utf-8")

    # 自由化:没有空壳时,度量家族也指向主字体(放弃度量隔离,不拒绝构建)。
    no_carrier = builder.ET.fromstring(builder.configure_fonts(template, ladder, False))
    for name in ("sans-serif", "sans-serif-condensed"):
        got = no_carrier.findall(f"family[@name='{name}']")[0].findall("font")
        assert {node.text.strip() for node in got} == {"V.ttf"}, name
    assert not [node for family in no_carrier.findall("family") for node in family.findall("font")
                if (node.text or "").strip() == builder.CARRIER], "无空壳时仍引用 Roboto"

    # 输入防线:默认家族不是 Roboto 空壳的 fonts.xml 拒绝替换。
    foreign = template.replace(b'<family name="sans-serif">', b'<family name="elsewhere">', 1)
    try:
        builder.configure_fonts(foreign, ladder, True)
        raise AssertionError("非 Roboto 默认家族未被拒绝")
    except ValueError:
        pass
    try:
        builder.configure_fonts(b"<not-familyset/>", ladder, True)
        raise AssertionError("非 familyset 未被拒绝")
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
    b.setupOS2()
    b.setupPost()
    out = io.BytesIO()
    b.save(out)
    pruned, count = builder.prune_blank_mappings(out.getvalue())
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
        light, regular = fonts_dir / "P-Light.ttf", fonts_dir / "P-Regular.ttf"
        light.write_bytes(make_font(weight=300))
        regular.write_bytes(make_font(weight=400))
        base, output = tmp / "base.zip", tmp / "out" / "Selffont.zip"
        base_zip(base, {"Roboto-Regular.ttf": make_carrier(), "NotoSansPro.otf": b"supplemental",
                        "DeadWeight.ttf": b"dead"})
        report = builder.build(base=str(base), font=[str(light), str(regular)], output=output, revision="selfcheck")

        with zipfile.ZipFile(output) as archive:
            members = set(archive.namelist())
            for expected in ("module.prop", "fonts.xml", "report.json", "LICENSES.md", "customize.sh", "action.sh",
                             "firefox.sh", "geckoview-config.yaml",
                             "system/fonts/P-Light.ttf", "system/fonts/P-Regular.ttf",
                             "system/fonts/Roboto-Regular.ttf", "system/fonts/NotoSansPro.otf",
                             "licenses/MFGA-base-LICENSES.md"):
                assert expected in members, f"缺成员 {expected}"
            assert "system/fonts/DeadWeight.ttf" not in members, "死重未丢弃"
            assert archive.read("module.prop") == (ROOT / "module/module.prop").read_bytes()
            assert (archive.getinfo("customize.sh").external_attr >> 16) == stat.S_IFREG | 0o755
            assert (archive.getinfo("system/fonts/P-Regular.ttf").external_attr >> 16) == stat.S_IFREG | 0o644
            packaged = archive.read("system/fonts/P-Regular.ttf")
            xml = archive.read("fonts.xml").decode()

        assert report["revision"] == "selfcheck"
        assert report["primary"]["family"] == "Test Primary" and report["primary"]["installedFamily"] == builder.RENAME
        assert sorted(map(int, report["primary"]["weightMap"])) == list(builder.WEIGHTS)
        assert report["metricCarrier"]["file"] == builder.CARRIER
        assert report["unreferencedFontsDropped"] == ["DeadWeight.ttf"]
        assert report["emojiCoverage"] == [], "测试字体没有 emoji 段覆盖"
        assert len(report["metricNormalization"]) == 2 and "P-Regular.ttf" in xml

        # 归一 + 改名之后:轮廓/cmap/轴不动,家族名换成 RENAME。
        before, after = builder.glyph_signature(make_font(weight=400)), builder.glyph_signature(packaged)
        assert before["outlines"] == after["outlines"] and before["cmap"] == after["cmap"], "轮廓或 cmap 被改了"
        assert before["axes"] == after["axes"] and after["family"] == builder.RENAME
        assert TTFont(io.BytesIO(packaged))["hhea"].ascent == 930, "包内字体未归一"

        # 自由化:主字体按自己的文件名安装,不要求固定命名;非字体后缀明确报错。
        custom = fonts_dir / "Weird-Name.ttf"
        custom.write_bytes(make_font(family="Custom Face"))
        builder.build(base=str(base), font=[str(custom)], output=output)
        with zipfile.ZipFile(output) as archive:
            assert "system/fonts/Weird-Name.ttf" in archive.namelist()
            assert "Weird-Name.ttf" in archive.read("fonts.xml").decode()
        try:
            builder.build(base=str(base), font=[str(fonts_dir / "x.woff2")], output=output)
            raise AssertionError("非字体后缀未被拒绝")
        except ValueError:
            pass

        # 没有空壳 → 跳过归一并警告,构建继续(自由化)。
        base_zip(base, {"SomeFont.ttf": b"supplemental"})
        report = builder.build(base=str(base), font=[str(regular)], output=output)
        assert not report["metricNormalization"] and report["metricCarrier"] is None
        assert any("Roboto" in warning for warning in report["warnings"])
        with zipfile.ZipFile(output) as archive:
            root = builder.ET.fromstring(archive.read("fonts.xml"))
        assert {node.text.strip() for node in root.find("family[@name='sans-serif']").findall("font")} == {"P-Regular.ttf"}

        # 信任边界:路径穿越 / 绝对路径 / 符号链接成员拒绝,输出不许覆盖输入。
        for bad in ("system/fonts/../../evil.ttf", "/abs.ttf"):
            bad_zip = tmp / "bad.zip"
            base_zip(bad_zip, {}, licenses=False)
            with zipfile.ZipFile(bad_zip, "a") as archive:
                archive.writestr(bad, b"x")
            try:
                builder.build(base=str(bad_zip), font=[str(regular)], output=output)
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
            builder.build(base=str(link_zip), font=[str(regular)], output=output)
            raise AssertionError("符号链接字体未被拒绝")
        except ValueError:
            pass
        try:
            builder.build(base=str(base), font=[str(regular)], output=base)
            raise AssertionError("输出覆盖了输入")
        except ValueError:
            pass


# ---------------------------------------------------------------- 火狐(Gecko)接入

@check
def firefox_bridge():
    """火狐接入:首选项只前置不清空 + install/remove 行为(PATH 上的 am/settings 用替身)。"""
    config = (ROOT / "module/geckoview-config.yaml").read_text(encoding="utf-8")
    assert config.startswith("prefs:\n") or "\nprefs:\n" in config, "Gecko 配置必须只有 prefs 段"
    lines = [line.strip() for line in config.splitlines() if line.strip().startswith("font.name-list.")]
    assert len(lines) >= 20, f"首选项太少:{len(lines)}"
    for line in lines:  # 只前置:每条都必须以本模块家族名开头,后面原样保留 Gecko 默认回退链
        value = line.split(":", 1)[1].strip().strip('"')
        assert value.startswith(builder.RENAME + ","), f"未前置或家族名不符:{line}"
    assert config.count('"') % 2 == 0, "引号不配对"
    assert builder.emoji_ceiling({0x41: "A", 0x1F600: "grin"}) == 0x1F600
    assert builder.emoji_ceiling({0x41: "A"}) is None

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shim, calls = tmp / "bin", tmp / "calls"
        shim.mkdir()
        (shim / "am").write_text(f'#!/bin/sh\necho "am $*" >> {calls}\n')
        (shim / "settings").write_text('#!/bin/sh\necho "$SELFFONT_TEST_DEBUG_APP"\n')
        for name in ("am", "settings"):
            (shim / name).chmod(0o755)
        data = tmp / "local/tmp"
        env = {**os.environ, "PATH": f"{shim}:{os.environ['PATH']}", "FIREFOX_DATA_DIR": str(data),
               "FIREFOX_PACKAGE": "org.mozilla.firefox", "SELFFONT_TEST_DEBUG_APP": "org.mozilla.firefox"}

        result = sh([str(ROOT / "module/firefox.sh")], env)
        assert result.returncode == 0, result.stderr
        target = data / "org.mozilla.firefox-geckoview-config.yaml"
        assert target.read_bytes() == (ROOT / "module/geckoview-config.yaml").read_bytes(), "配置没原样落地"
        assert "am set-debug-app --persistent org.mozilla.firefox" in calls.read_text()
        assert "debug_app = org.mozilla.firefox" in result.stdout, result.stdout

        result = sh([str(ROOT / "module/firefox.sh"), "remove"], env)
        assert result.returncode == 0 and not target.exists(), result
        assert "am clear-debug-app" in calls.read_text()

        assert sh([str(ROOT / "module/firefox.sh"), "wat"], env).returncode == 2, "未知参数应报用法错"


# ---------------------------------------------------------------- 模块运行时脚本

def sh(args, env):
    return subprocess.run(["sh", *args], env=env, capture_output=True, text=True)


@check
def runtime_scripts():
    for script in ("customize.sh", "action.sh"):
        assert sh(["-n", str(ROOT / "module" / script)], os.environ).returncode == 0, f"{script} 语法错误"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        modpath = tmp / "module"
        (modpath / "system/fonts").mkdir(parents=True)
        (modpath / "module.prop").write_text((ROOT / "module/module.prop").read_text())
        (modpath / "fonts.xml").write_bytes(b"<familyset/>")
        (modpath / "system/fonts/Any-Name.ttf").write_bytes(b"font")
        for path in sorted((ROOT / "module").iterdir()):  # 模块目录照打包后的样子铺开
            if path.is_file():
                shutil.copy(path, modpath / path.name)
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
        (modpath / "system/fonts/Any-Name.ttf").write_bytes(b"font")

        result = sh([str(modpath / "action.sh")], env)
        assert result.returncode == 0 and "[Selffont]" in result.stdout, result
        assert "unknown" in result.stdout and "Bundled fonts: 1" in result.stdout
        assert "Firefox: firefox.sh 可接入" in result.stdout


# ---------------------------------------------------------------- 仓库自身的数据与常量

@check
def repo_constants():
    """不下载任何东西:默认来源、模块字段、真实 fonts.xml 的前置条件都在位。"""
    assert builder.PRIMARY_URL.endswith("WenYuanRoundedSCVF.ttf") and builder.BASE_URL.endswith(".zip")
    assert len(builder.PRIMARY_SHA256) == len(builder.BASE_SHA256) == 64
    assert builder.PRIMARY_NAME.endswith(".ttf") and builder.RENAME == "Selffont Rounded SC VF"
    prop = (ROOT / "module/module.prop").read_text()
    assert all(f"{key}=" in prop for key in builder.MODULE_KEYS), prop
    # 版本号带日期,versionCode = YYYYMMDD + 当日两位构建序号;两者日期必须一致(发布前抓错)。
    version, code = (re.search(rf"^{key}=(.+)$", prop, re.M) for key in ("version", "versionCode"))
    assert version and code and version.group(1).startswith("v"), prop
    date = re.search(r"\((\d{4})-(\d{2})-(\d{2})\)", version.group(1))
    assert date, f"版本号应带日期:v4.2.0 (YYYY-MM-DD)"
    assert len(code.group(1)) == 10 and code.group(1)[:8] == "".join(date.groups()), \
        f"versionCode 的日期部分应与版本日期一致:{version.group(1)} / {code.group(1)}"
    # configure_fonts 的前置条件:真实 fonts.xml 的默认家族必须正好是度量空壳。
    root = builder.ET.fromstring((ROOT / "fonts.xml").read_bytes())
    assert {node.text.strip() for node in root.find("family[@name='sans-serif']").findall("font")} == {builder.CARRIER}
    # 真实模板引用的字体名与基础包目录约定一致。
    assert all(not name.startswith("/") and ".." not in name
               for name in {node.text.strip() for node in root.iter("font")})


def main():
    failed = 0
    for fn in CHECKS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as error:  # noqa: BLE001
            failed += 1
            import traceback
            print(f"FAIL {fn.__name__}: {error}")
            traceback.print_exc()
    if failed:
        print(f"{failed} 个检查失败")
        sys.exit(1)
    print(f"{len(CHECKS)} 项全部通过")


if __name__ == "__main__":
    main()
