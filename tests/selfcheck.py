#!/usr/bin/env python3
"""Selffont 自检:打包器、度量归一、配置生成与模块脚本的最小行为检查。

无测试框架、无夹具模块。`python3 tests/selfcheck.py` 一把跑完,
全部通过打印 PASS,任何失败非零退出。
"""
import io
import json
import os
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


def make_font(family="WenYuan Rounded SC VF", upm=1000, axes=True):
    order = [".notdef", "space", *"0123456789", "A"]
    b = FontBuilder(upm, isTTF=True)
    b.setupGlyphOrder(order)
    cmap = {32: "space", 65: "A", **{ord(d): d for d in "0123456789"}}
    b.setupCharacterMap(cmap)
    glyphs = {".notdef": box(0, 0, 500, 700), "space": TTGlyphPen(None).glyph()}
    for d in "0123456789":
        glyphs[d] = box(40, -10, 460, 744)
    glyphs["A"] = box(20, 0, 480, 700)
    b.setupGlyf(glyphs)
    b.setupHorizontalMetrics(dict.fromkeys(order, (500, 0)))
    b.setupHorizontalHeader(ascent=1160, descent=-288)
    b.setupNameTable({"familyName": family, "styleName": "Regular",
                      "uniqueFontIdentifier": family, "fullName": family, "psName": family})
    b.setupOS2(sTypoAscender=880, sTypoDescender=-120, usWinAscent=1160, usWinDescent=288)
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


# ---------------------------------------------------------------- 度量归一(真机验证的角标修复)

@check
def metric_normalization():
    carrier = builder.layout_metrics(TTFont(io.BytesIO(make_carrier())))
    font = make_font()
    normalized, report = builder.normalize_metrics(font, carrier)
    result = TTFont(io.BytesIO(normalized))
    assert (result["hhea"].ascent, result["hhea"].descent) == (930, -250), "hhea 未对齐载体"
    assert (result["OS/2"].sTypoAscender, result["OS/2"].sTypoDescender) == (930, -250), "typo 未对齐"
    assert report["original"]["hhea"] == [1160, -288, 0], "原度量未记录"
    builder.assert_glyphs_preserved(font, normalized)  # 轮廓/cmap/家族/轴必须逐字节不变
    scaled = TTFont(io.BytesIO(builder.normalize_metrics(
        make_font(upm=2048), carrier)[0]))
    assert scaled["hhea"].ascent == round(930 * 2048 / 1000), "upm 缩放错误"
    # 会切数字墨迹的归一必须被拒:载体 ascent 700 盖不住数字墨迹 744。
    try:
        builder.normalize_metrics(make_font(), dict(carrier, hhea=[700, -100, 0]))
        raise AssertionError("切墨迹的归一未被拒绝")
    except ValueError:
        pass
    # 可见字形的 Roboto 不能当载体。
    assert builder.carrier_info(make_carrier(visible=True)) is None
    assert builder.carrier_info(make_carrier()) is not None


# ---------------------------------------------------------------- fonts.xml 配置生成

@check
def configure_fonts():
    xml_bytes = builder.configure_fonts(
        (ROOT / "fonts.xml").read_bytes(), "Selffont-primary.ttf",
        builder.weight_ladder({"wght": (100, 400, 900), "ital": (0, 0, 1)}), "Roboto-Regular.ttf")
    root = builder.ET.fromstring(xml_bytes)
    def fonts(name):
        return root.findall(f"family[@name='{name}']")[0].findall("font")

    assert len(fonts("serif")) == 18, "serif 应为 9 字重 × 2 风格"
    assert all(f.text.strip() == "Selffont-primary.ttf" for f in fonts("serif"))
    assert {(a.get("tag")) for f in fonts("serif") for a in f.findall("axis")} == {"wght", "ital"}
    # 度量家族保留 Roboto 空壳原样(防角标回退)。
    assert all(f.text.strip() == "Roboto-Regular.ttf" for f in fonts("sans-serif"))
    assert all(f.text.strip() == "Roboto-Regular.ttf" for f in fonts("sans-serif-condensed"))
    # 默认家族之后紧跟匿名字形回退家族。
    default = root.find("family[@name='sans-serif']")
    fallback = list(root)[list(root).index(default) + 1]
    assert fallback.get("name") is None and len(fallback.findall("font")) == 18
    # 旧数字主字体家族(100.ttf~900.ttf)整体消失。
    for family in root.findall("family"):
        for node in family.findall("font"):
            assert (node.text or "").strip() not in builder.OLD_PRIMARY, "残留旧数字主字体"

    # 自由化:没有载体时,度量家族也指向主字体(放弃度量隔离,不拒绝构建)。
    no_carrier = builder.ET.fromstring(builder.configure_fonts(
        (ROOT / "fonts.xml").read_bytes(), "Selffont-primary.ttf",
        builder.weight_ladder({"wght": (100, 400, 900), "ital": (0, 0, 1)}), None))
    for name in ("sans-serif", "sans-serif-condensed"):
        got = no_carrier.findall(f"family[@name='{name}']")[0].findall("font")
        assert all(f.text.strip() == "Selffont-primary.ttf" for f in got), name
    no_roboto = builder.ET.fromstring(builder.configure_fonts(
        (ROOT / "fonts.xml").read_bytes(), "S.ttf",
        builder.weight_ladder({}), None))
    assert not [node for family in no_roboto.findall("family") for node in family.findall("font")
                if (node.text or "").strip() == "Roboto-Regular.ttf"], "无载体时仍引用 Roboto"

    # 静态字体:全字重同一文件,零 axis 元素。
    static_ladder = builder.weight_ladder({})
    assert [e["weight"] for e in static_ladder] == list(range(100, 1000, 100))
    static_root = builder.ET.fromstring(builder.configure_fonts(
        (ROOT / "fonts.xml").read_bytes(), "S.ttf", static_ladder, "Roboto-Regular.ttf"))
    for family in static_root.findall("family"):
        for node in family.findall("font"):
            if (node.text or "").strip() == "S.ttf":
                assert not node.findall("axis"), "静态字体不应生成 axis"

    # 轴越界夹取,不拒绝。
    clamped = builder.weight_ladder({"wght": (200, 400, 700), "ital": (0, 0, 1)})
    assert [e["weight"] for e in clamped if not e["italic"]] == [200, 300, 400, 500, 600, 700]

    # 输入防线:默认家族不是 Roboto 空壳的 fonts.xml 拒绝替换。
    foreign = (ROOT / "fonts.xml").read_bytes().replace(b'<family name="sans-serif">',
                                                       b'<family name="elsewhere">', 1)
    try:
        builder.configure_fonts(foreign, "S.ttf", static_ladder, "Roboto-Regular.ttf")
        raise AssertionError("非 Roboto 默认家族未被拒绝")
    except ValueError:
        pass


# ---------------------------------------------------------------- 端到端构建 + 自由化路径

@check
def build_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        font, base, output = tmp / "font.ttf", tmp / "base.zip", tmp / "out" / "Selffont.zip"
        font.write_bytes(make_font())
        base_zip(base, {"Roboto-Regular.ttf": make_carrier(),
                        "NotoSansPro.otf": b"supplemental",
                        "DeadWeight.ttf": b"dead"})
        report = builder.build(font, base, output, revision="selfcheck")
        with zipfile.ZipFile(output) as archive:
            members = set(archive.namelist())
            for expected in ("module.prop", "fonts.xml", "report.json", "LICENSES.md",
                             "customize.sh", "action.sh", "webroot/index.html",
                             "system/fonts/Selffont-primary.ttf", "system/fonts/Roboto-Regular.ttf",
                             "system/fonts/NotoSansPro.otf", "licenses/WenYuan-OFL.txt",
                             "licenses/MFGA-base-LICENSES.md"):
                assert expected in members, f"缺成员 {expected}"
            assert "system/fonts/DeadWeight.ttf" not in members, "死重未丢弃"
            prop = dict(line.split("=", 1) for line in archive.read("module.prop").decode().splitlines())
            assert prop["id"] == "MFGA" and prop["versionCode"] == "2026092600"
            assert (archive.getinfo("customize.sh").external_attr >> 16) == stat.S_IFREG | 0o755
            packaged = archive.read("system/fonts/Selffont-primary.ttf")
            assert json.loads(archive.read("report.json"))["revision"] == "selfcheck"
        builder.assert_glyphs_preserved(font.read_bytes(), packaged)
        assert TTFont(io.BytesIO(packaged))["hhea"].ascent == 930, "包内字体未归一"
        assert "DeadWeight.ttf" in report["unreferencedFontsDropped"]
        assert report["metricNormalization"] is not None

        # 自由化:外来家族名照样打包,只警告 Gecko 名要同步。
        font.write_bytes(make_font(family="My Own Font"))
        report = builder.build(font, base, output)
        assert any("My Own Font" in w for w in report["warnings"]), "家族名漂移未警告"

        # 自由化:静态字体照样打包。
        font.write_bytes(make_font(axes=False))
        report = builder.build(font, base, output)
        assert report["weightLadder"] == list(range(100, 1000, 100))

        # 自由化:没有载体照样打包,归一跳过 + 警告。
        base_zip(base, {"SomeFont.ttf": b"supplemental"})
        report = builder.build(font, base, output)
        assert report["metricNormalization"] is None
        assert any("Roboto" in w for w in report["warnings"])

        # 信任边界:路径穿越 / 绝对路径 / 符号链接成员拒绝。
        for bad in ("system/fonts/../../evil.ttf", "/abs.ttf"):
            bad_zip = tmp / "bad.zip"
            base_zip(bad_zip, {}, licenses=False)
            with zipfile.ZipFile(bad_zip, "a") as archive:
                archive.writestr(bad, b"x")
            try:
                builder.build(font, bad_zip, tmp / "no.zip")
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
            builder.build(font, link_zip, tmp / "no.zip")
            raise AssertionError("符号链接字体未拒绝")
        except ValueError:
            pass
        # 输出不能覆盖输入。
        try:
            builder.build(font, base, base)
            raise AssertionError("输出覆盖了输入")
        except ValueError:
            pass


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
        (modpath / "system/fonts/Selffont-primary.ttf").write_bytes(b"font")
        (modpath / "fonts.xml").write_bytes(b"<familyset/>")
        (modpath / "module.prop").write_text("version=v2.0.0\n")
        # 与部署一致:脚本随模块放进 MODPATH。
        for script in ("customize.sh", "action.sh"):
            shutil.copy(ROOT / "module" / script, modpath / script)
        system = tmp / "sysroot"
        for directory in ("etc", "system_ext/etc", "product/etc"):
            (system / directory).mkdir(parents=True)
            (system / directory / "font.xml").write_text("<familyset>old</familyset>")
        (system / "etc/fonts_customization.xml").write_text("<other-schema/>")
        env = {**os.environ, "MODPATH": str(modpath), "SELFFONT_SYSTEM_ROOT": str(system)}

        # KSU 安装环境的最小模拟:先 source 桩,再 source 被测脚本。
        harness = modpath / "harness.sh"
        harness.write_text(
            'ui_print() { echo "$@"; }\n'
            'abort() { echo "ABORT: $*" >&2; exit 1; }\n'
            '. "%s"\n' % (modpath / "customize.sh"))
        result = sh([str(harness)], env)
        assert result.returncode == 0, result.stderr
        for directory in ("etc", "system_ext/etc", "product/etc"):
            copied = modpath / system.relative_to("/") / directory / "font.xml"
            assert copied.read_text() == "<familyset/>", directory
        assert not (modpath / "system/etc/fonts_customization.xml").exists(), "自选配置不该被碰"
        assert "已替换 3 份" in result.stdout, "应报告替换数量:" + result.stdout

        # 缺主字体必须中止。
        (modpath / "system/fonts/Selffont-primary.ttf").unlink()
        result = sh([str(harness)], env)
        assert result.returncode != 0 and "ABORT" in result.stderr

        # action.sh:诊断在无 getprop 环境降级而非崩溃;logs 只留自己的行。
        (modpath / "system/fonts/Selffont-primary.ttf").write_bytes(b"font")
        result = sh([str(modpath / "action.sh")], env)
        assert result.returncode == 0 and "[Selffont]" in result.stdout and "unknown" in result.stdout
        assert sh([str(modpath / "action.sh"), "gms", "--confirm"], env).returncode == 2, "已删动作应报用法错"

        logdir = tmp / "log"
        logdir.mkdir()
        (logdir / "modules.log").write_text(
            "07-26 00:00:00.000 LSPosed/Bridge(1)[Other: X]: noise\n"
            "07-26 00:00:01.000 LSPosed/Bridge(1)[Selffont: Entry]: [attach] api=36\n")
        result = sh([str(modpath / "action.sh"), "logs"],
                    {**env, "SELFFONT_LOG_DIR": str(logdir)})
        assert result.returncode == 0 and "[attach]" in result.stdout and "noise" not in result.stdout
        result = sh([str(modpath / "action.sh"), "logs"],
                    {**env, "SELFFONT_LOG_DIR": str(tmp / "absent")})
        assert result.returncode == 0 and "[logs-missing]" in result.stdout


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
