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


def make_font(family="Test Primary", weight=400, upm=1000, axes=True):
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
    b.setupOS2(sTypoAscender=880, sTypoDescender=-120, usWinAscent=1160, usWinDescent=288,
               usWeightClass=weight)
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


TEST_SOURCES = {
    "module": builder.SOURCES["module"],
    "primary": {"family": "Test Primary", "vf": False, "files": [
        {"installed": "P-Light.ttf", "weight": 300},
        {"installed": "P-Regular.ttf", "weight": 400},
    ]},
    "extras": [],
    "base": builder.SOURCES["base"],
}


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
        (ROOT / "fonts.xml").read_bytes(),
        builder.map_weights([{"installed": "P-L.ttf", "weight": 300},
                             {"installed": "P-R.ttf", "weight": 400},
                             {"installed": "P-M.ttf", "weight": 500},
                             {"installed": "P-B.ttf", "weight": 700},
                             {"installed": "P-K.ttf", "weight": 900}]),
        builder.map_weights([{"installed": "X-R.ttf", "weight": 400}]), "Roboto-Regular.ttf")
    root = builder.ET.fromstring(xml_bytes)

    def fonts(name):
        return root.findall(f"family[@name='{name}']")[0].findall("font")

    assert len(fonts("serif")) == 18, "serif 应为 9 字重 × 2 风格"
    files = {f.text.strip() for f in fonts("serif")}
    assert files <= {"P-L.ttf", "P-R.ttf", "P-M.ttf", "P-B.ttf", "P-K.ttf"}, files
    order5 = [f.text.strip() for f in fonts("serif")][:9]
    assert order5 == [f"P-{s}.ttf" for s in ("L", "L", "L", "R", "M", "B", "B", "K", "K")], order5
    # 度量家族保留 Roboto 空壳原样(防角标回退)。
    assert all(f.text.strip() == "Roboto-Regular.ttf" for f in fonts("sans-serif"))
    assert all(f.text.strip() == "Roboto-Regular.ttf" for f in fonts("sans-serif-condensed"))
    # 默认家族之后紧跟匿名字形回退家族,且主字体在前、扩展字库随后。
    default = root.find("family[@name='sans-serif']")
    fallback = list(root)[list(root).index(default) + 1]
    order = [f.text.strip() for f in fallback.findall("font")]
    assert len(order) == 36, f"回退家族应为主18+扩展18:{len(order)}"
    assert order[18:27] == ["X-R.ttf"] * 9, "扩展字库应在主字体斜体之后"
    # 旧数字主字体家族整体消失。
    for family in root.findall("family"):
        for node in family.findall("font"):
            assert (node.text or "").strip() not in builder.OLD_PRIMARY, "残留旧数字主字体"

    # 自由化:没有载体时,度量家族也指向主字体(放弃度量隔离,不拒绝构建)。
    no_carrier = builder.ET.fromstring(builder.configure_fonts(
        (ROOT / "fonts.xml").read_bytes(),
        builder.map_weights([{"installed": "P-R.ttf", "weight": 400}]), [], None))
    for name in ("sans-serif", "sans-serif-condensed"):
        got = no_carrier.findall(f"family[@name='{name}']")[0].findall("font")
        assert all(f.text.strip() == "P-R.ttf" for f in got), name
    no_roboto = [node for family in no_carrier.findall("family") for node in family.findall("font")
                 if (node.text or "").strip() == "Roboto-Regular.ttf"]
    assert not no_roboto, "无载体时仍引用 Roboto"

    # 静态零轴;可变轴单文件。
    our_axis = [a for family in root.findall("family") for f in family.findall("font")
                if (f.text or "").strip().startswith("P-") for a in f.findall("axis")]
    assert not our_axis, "静态主字体不应生成 axis"
    vf_ladder = builder.ladder_for({"vf": True, "files": [{"installed": "V.ttf", "weight": 400}]},
                                   {"wght": (100, 400, 900), "ital": (0, 0, 1)})
    assert len(vf_ladder) == 18 and all(e["axes"] for e in vf_ladder), "vf 阶梯应有轴"
    vf_root = builder.ET.fromstring(builder.configure_fonts(
        (ROOT / "fonts.xml").read_bytes(), vf_ladder, [], "Roboto-Regular.ttf"))
    assert "<axis" in builder.ET.tostring(vf_root, encoding="unicode")

    # 轴越界夹取,不拒绝(vf 主字体)。
    vf_primary = {"vf": True, "files": [{"installed": "V.ttf", "weight": 400}]}
    clamped = builder.ladder_for(vf_primary, {"wght": (200, 400, 700), "ital": (0, 0, 1)})
    assert [e["weight"] for e in clamped if not e["italic"]] == [200, 300, 400, 500, 600, 700]
    full = builder.ladder_for(vf_primary, {"wght": (100, 400, 900), "ital": (0, 0, 1)})
    assert len(full) == 18, "全轴程应 9 字重 × 2 风格"

    # 输入防线:默认家族不是 Roboto 空壳的 fonts.xml 拒绝替换。
    foreign = (ROOT / "fonts.xml").read_bytes().replace(b'<family name="sans-serif">',
                                                       b'<family name="elsewhere">', 1)
    try:
        builder.configure_fonts(foreign, builder.map_weights(
            [{"installed": "P-R.ttf", "weight": 400}]), [], "Roboto-Regular.ttf")
        raise AssertionError("非 Roboto 默认家族未被拒绝")
    except ValueError:
        pass


# ---------------------------------------------------------------- 端到端构建 + 自由化路径

@check
def build_end_to_end():
    real_sources = builder.SOURCES
    builder.SOURCES = TEST_SOURCES
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fonts_dir = tmp / "fonts"
            fonts_dir.mkdir()
            (fonts_dir / "P-Light.ttf").write_bytes(make_font(weight=300))
            (fonts_dir / "P-Regular.ttf").write_bytes(make_font(weight=400))
            (fonts_dir / "X-Regular.ttf").write_bytes(make_font(family="Test Extra"))
            builder.SOURCES = {**TEST_SOURCES, "extras": [
                {"installed": "X-Regular.ttf", "weight": 400, "url": str(fonts_dir / "X-Regular.ttf")}]}
            base, output = tmp / "base.zip", tmp / "out" / "Selffont.zip"
            base_zip(base, {"Roboto-Regular.ttf": make_carrier(),
                            "NotoSansPro.otf": b"supplemental",
                            "DeadWeight.ttf": b"dead"})
            report = builder.build(base, output, revision="selfcheck", font_override=fonts_dir)
            with zipfile.ZipFile(output) as archive:
                members = set(archive.namelist())
                for expected in ("module.prop", "fonts.xml", "report.json", "LICENSES.md",
                                 "customize.sh", "action.sh",
                                 "system/fonts/P-Light.ttf", "system/fonts/P-Regular.ttf",
                                 "system/fonts/X-Regular.ttf", "system/fonts/Roboto-Regular.ttf",
                                 "system/fonts/NotoSansPro.otf"):
                    assert expected in members, f"缺成员 {expected}"
                assert "system/fonts/DeadWeight.ttf" not in members, "死重未丢弃"
                prop = dict(line.split("=", 1) for line in archive.read("module.prop").decode().splitlines())
                assert prop["id"] == TEST_SOURCES["module"]["id"]
                assert prop["versionCode"] == str(TEST_SOURCES["module"]["versionCode"])
                assert (archive.getinfo("customize.sh").external_attr >> 16) == stat.S_IFREG | 0o755
                packaged = archive.read("system/fonts/P-Regular.ttf")
                assert json.loads(archive.read("report.json"))["revision"] == "selfcheck"
            builder.assert_glyphs_preserved(make_font(weight=400), packaged)
            assert TTFont(io.BytesIO(packaged))["hhea"].ascent == 930, "包内字体未归一"
            assert "DeadWeight.ttf" in report["unreferencedFontsDropped"]
            assert report["metricNormalization"] and len(report["metricNormalization"]) == 2

            # 主字体名漂移 → 警告不拦截(自由化)。
            (fonts_dir / "P-Regular.ttf").write_bytes(make_font(family="Drifted"))
            report = builder.build(base, output, font_override=fonts_dir)
            assert any("Drifted" in w for w in report["warnings"])

            # 无载体基础包 → 归一跳过 + 警告(自由化)。
            base_zip(base, {"SomeFont.ttf": b"supplemental"})
            report = builder.build(base, output, font_override=fonts_dir)
            assert all(v is None for v in report["metricNormalization"].values()) or \
                not report["metricNormalization"]
            assert any("Roboto" in w for w in report["warnings"])

            # 主字体缺文件 → 明确报错(需要 --font)。
            try:
                builder.build(base, output)
                raise AssertionError("缺少主字体时未报错")
            except ValueError:
                pass

            # 信任边界:路径穿越 / 绝对路径 / 符号链接成员拒绝。
            for bad in ("system/fonts/../../evil.ttf", "/abs.ttf"):
                bad_zip = tmp / "bad.zip"
                base_zip(bad_zip, {}, licenses=False)
                with zipfile.ZipFile(bad_zip, "a") as archive:
                    archive.writestr(bad, b"x")
                try:
                    builder.build(bad_zip, tmp / "no.zip", font_override=fonts_dir)
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
                builder.build(link_zip, tmp / "no.zip", font_override=fonts_dir)
                raise AssertionError("符号链接字体未拒绝")
            except ValueError:
                pass
            try:
                builder.build(base, base, font_override=fonts_dir)
                raise AssertionError("输出覆盖了输入")
            except ValueError:
                pass
    finally:
        builder.SOURCES = real_sources


@check
def real_sources_config():
    """仓库真实 sources.json 的结构自检(不下载)。"""
    primary = builder.SOURCES["primary"]
    assert primary["family"] == "Selffont Rounded SC VF", "主字体应为文渊 VF(内部名,规避保留名 WenYuan/文渊)"
    assert primary["rename"] == "Selffont Rounded SC VF", "归一属 OFL 修改,必须整体改名"
    assert primary["vf"] is True and len(primary["files"]) == 1
    f = primary["files"][0]
    assert f["installed"] == "Selffont-WenYuanRoundedSCVF.ttf" and f["weight"] == 400
    assert f["sha256"] == "e9ebde68d6d45ad5998765505677d1fb95821318fc693982f873e73fc27a2122"
    ladder = builder.ladder_for(primary, {"wght": (100, 400, 900)})
    weights = sorted({e["weight"] for e in ladder if not e["italic"]})
    assert weights == [100, 200, 300, 400, 500, 600, 700, 800, 900], weights
    assert all(e["file"] == "Selffont-WenYuanRoundedSCVF.ttf" for e in ladder)
    assert builder.SOURCES["extras"] == []
    module = builder.SOURCES["module"]
    assert module["id"] == "MFGA" and module["version"].startswith("v3.")


# ---------------------------------------------------------------- 空壳映射剪除

@check
def blank_prune():
    """空壳映射剪除:映射到空白字形的非空白码位被剪,字形集合不动。"""
    import io
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont as TF
    fb = FontBuilder(1000, isTTF=True)
    order = [".notdef", "A", "B"]
    fb.setupGlyphOrder(order)
    pen_a = TTGlyphPen(None)
    pen_a.moveTo((0, 0)); pen_a.lineTo((100, 0)); pen_a.lineTo((100, 100)); pen_a.closePath()
    fb.setupCharacterMap({0x41: "A", 0x42: "B"})
    fb.setupGlyf({"A": pen_a.glyph(), "B": TTGlyphPen(None).glyph(),
                  ".notdef": TTGlyphPen(None).glyph()})
    fb.setupHorizontalMetrics({g: (500, 0) for g in order})
    fb.setupHorizontalHeader(ascent=930, descent=-250)
    fb.setupNameTable({"familyName": "T", "styleName": "Regular"})
    fb.setupOS2(); fb.setupPost()
    buf = io.BytesIO(); fb.save(buf)
    pruned, count = builder.prune_blank_mappings(buf.getvalue())
    assert count == 1, count  # 唯一码位计数(format4/12 同码位只算一个)
    cmap = TF(io.BytesIO(pruned)).getBestCmap()
    assert 0x41 in cmap and 0x42 not in cmap
    assert set(TF(io.BytesIO(pruned)).getGlyphOrder()) == set(order), "只剪映射,不删字形"


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
        (modpath / "system/fonts/Selffont-WenYuanRoundedSCVF.ttf").write_bytes(b"font")
        (modpath / "fonts.xml").write_bytes(b"<familyset/>")
        (modpath / "module.prop").write_text("version=v2.2.0\n")
        for script in ("customize.sh", "action.sh"):
            shutil.copy(ROOT / "module" / script, modpath / script)
        system = tmp / "sysroot"
        for directory in ("etc", "system_ext/etc", "product/etc"):
            (system / directory).mkdir(parents=True)
            (system / directory / "font.xml").write_text("<familyset>old</familyset>")
        (system / "etc/fonts_customization.xml").write_text("<other-schema/>")
        env = {**os.environ, "MODPATH": str(modpath), "SELFFONT_SYSTEM_ROOT": str(system)}

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

        (modpath / "system/fonts/Selffont-WenYuanRoundedSCVF.ttf").unlink()
        result = sh([str(harness)], env)
        assert result.returncode != 0 and "ABORT" in result.stderr

        (modpath / "system/fonts/Selffont-WenYuanRoundedSCVF.ttf").write_bytes(b"font")
        result = sh([str(modpath / "action.sh")], env)
        assert result.returncode == 0 and "[Selffont]" in result.stdout and "unknown" in result.stdout
        assert sh([str(modpath / "action.sh"), "gms", "--confirm"], env).returncode == 2, "已删动作应报用法错"


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
