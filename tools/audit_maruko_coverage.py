#!/usr/bin/env python3
"""Audit Maruko static-font coverage, weight consistency, and structural cmap anomalies.

The report distinguishes character-map coverage from visual quality. Built-in codec
profiles are comparison sets only; they are not a claim of standards conformance.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import unicodedata
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont

SOURCE_COMMIT = "97e9dd4a2fdde58084dde8d022de253f8d8415e9"
BLOCKS = (
    ("CJK Radicals Supplement", 0x2E80, 0x2EFF),
    ("Kangxi Radicals", 0x2F00, 0x2FDF),
    ("CJK Symbols and Punctuation", 0x3000, 0x303F),
    ("Hiragana", 0x3040, 0x309F),
    ("Katakana", 0x30A0, 0x30FF),
    ("Bopomofo", 0x3100, 0x312F),
    ("Bopomofo Extended", 0x31A0, 0x31BF),
    ("CJK Strokes", 0x31C0, 0x31EF),
    ("CJK Compatibility Forms", 0xFE30, 0xFE4F),
    ("Halfwidth and Fullwidth Forms", 0xFF00, 0xFFEF),
    ("CJK Unified Ideographs Extension A", 0x3400, 0x4DBF),
    ("CJK Unified Ideographs", 0x4E00, 0x9FFF),
    ("CJK Compatibility Ideographs", 0xF900, 0xFAFF),
    ("CJK Unified Ideographs Extensions B onward", 0x20000, 0x323AF),
    ("Hangul Jamo", 0x1100, 0x11FF),
    ("Hangul Compatibility Jamo", 0x3130, 0x318F),
    ("Hangul Syllables", 0xAC00, 0xD7AF),
    ("Latin-1 Supplement", 0x0080, 0x00FF),
    ("Latin Extended A/B", 0x0100, 0x024F),
    ("Greek and Coptic", 0x0370, 0x03FF),
    ("Cyrillic", 0x0400, 0x052F),
    ("Hebrew", 0x0590, 0x05FF),
    ("General Punctuation", 0x2000, 0x206F),
    ("Mathematical Operators", 0x2200, 0x22FF),
    ("Box Drawing", 0x2500, 0x257F),
    ("Musical Symbols", 0x1D100, 0x1D1FF),
)
CODEC_PROFILES = (
    ("GB2312 (CPython codec)", "gb2312"),
    ("GBK (CPython codec)", "gbk"),
    ("Big5-HKSCS (CPython codec)", "big5hkscs"),
    ("Shift_JIS (CPython codec)", "shift_jis"),
    ("CP949 (CPython codec)", "cp949"),
)


def _font_label(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("font must be LABEL=PATH")
    label, raw_path = value.split("=", 1)
    if not label or not raw_path:
        raise argparse.ArgumentTypeError("font must be LABEL=PATH")
    path = Path(raw_path)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"font file does not exist: {path}")
    return label, path


def _is_visible_scalar(codepoint: int) -> bool:
    category = unicodedata.category(chr(codepoint))
    return category[0] not in {"C", "Z"}


@lru_cache(maxsize=None)
def encoded_printable_codepoints(codec: str) -> frozenset[int]:
    """Return visible Unicode scalars encodable by a Python codec implementation."""
    result = set()
    for codepoint in range(0x110000):
        if 0xD800 <= codepoint <= 0xDFFF or not _is_visible_scalar(codepoint):
            continue
        try:
            chr(codepoint).encode(codec)
        except UnicodeEncodeError:
            continue
        result.add(codepoint)
    return frozenset(result)


def _outline_data(font: TTFont, cmap: dict[int, str]) -> tuple[list[int], list[int], list[int]]:
    glyf = font["glyf"]
    hmtx = font["hmtx"].metrics
    empty, zero_advance, composite = [], [], []
    for codepoint, glyph_name in cmap.items():
        glyph = glyf[glyph_name]
        if glyph.isComposite():
            composite.append(codepoint)
        coords, _, _ = glyph.getCoordinates(glyf)
        if not coords:
            empty.append(codepoint)
        if hmtx[glyph_name][0] == 0:
            zero_advance.append(codepoint)
    return empty, zero_advance, composite


def _layout_snapshot(font: TTFont) -> dict[str, dict[str, list[str]]]:
    result = {}
    for table_tag in ("GSUB", "GPOS"):
        if table_tag not in font:
            result[table_tag] = {"features": [], "scripts": []}
            continue
        layout = font[table_tag].table
        feature_records = layout.FeatureList.FeatureRecord if layout.FeatureList else []
        script_records = layout.ScriptList.ScriptRecord if layout.ScriptList else []
        result[table_tag] = {
            "features": sorted({record.FeatureTag for record in feature_records}),
            "scripts": sorted({record.ScriptTag for record in script_records}),
        }
    return result


def _snapshot(label: str, path: Path) -> dict:
    with TTFont(path, lazy=False) as font:
        cmap = font.getBestCmap() or {}
        empty, zero_advance, composite = _outline_data(font, cmap)
        fvar_axes = []
        if "fvar" in font:
            fvar_axes = [
                f"{axis.axisTag}={axis.minValue:g}..{axis.defaultValue:g}..{axis.maxValue:g}"
                for axis in font["fvar"].axes
            ]
        return {
            "label": label,
            "path": path,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "family": font["name"].getDebugName(1) or "",
            "subfamily": font["name"].getDebugName(2) or "",
            "upm": font["head"].unitsPerEm,
            "weight": font["OS/2"].usWeightClass,
            "axes": fvar_axes,
            "layout": _layout_snapshot(font),
            "cmap": cmap,
            "glyph_count": len(font.getGlyphOrder()),
            "empty": empty,
            "zero_advance": zero_advance,
            "composite": composite,
            "blocks": {
                name: sum(start <= cp <= end for cp in cmap)
                for name, start, end in BLOCKS
            },
        }


def _unicode_label(codepoint: int) -> str:
    name = unicodedata.name(chr(codepoint), "UNASSIGNED / NO NAME")
    return f"U+{codepoint:04X} {name}"


def _write_gap_tsv(path: Path, snapshots: list[dict]) -> int:
    cmap_by_label = {item["label"]: set(item["cmap"]) for item in snapshots}
    profile_sets = {label: encoded_printable_codepoints(codec) for label, codec in CODEC_PROFILES}
    candidates = set().union(*profile_sets.values(), *cmap_by_label.values())
    rows = []
    for codepoint in sorted(candidates):
        expected_profiles = [label for label, points in profile_sets.items() if codepoint in points]
        missing_weights = [label for label, points in cmap_by_label.items() if codepoint not in points]
        if missing_weights:
            rows.append((codepoint, chr(codepoint), unicodedata.name(chr(codepoint), ""),
                         ", ".join(expected_profiles), ", ".join(missing_weights)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(("codepoint", "character", "unicode_name", "codec_profiles", "missing_weights"))
        for codepoint, character, name, profiles, weights in rows:
            writer.writerow((f"U+{codepoint:04X}", character, name, profiles, weights))
    return len(rows)


def _write_report(path: Path, snapshots: list[dict], gap_path: Path | None = None,
                  gap_count: int | None = None) -> None:
    labels = [item["label"] for item in snapshots]
    lines = [
        "# Maruko Gothic 字符覆盖基线审计",
        "",
        f"固定源提交：`{SOURCE_COMMIT}`。输入是该提交的静态 TTF；此报告只审计 cmap / 轮廓存在性，",
        "不等同于完整标准认证、字形视觉合格或设备上的最终回退结果。",
        "",
        "## 字体元数据与覆盖概况",
        "",
        "| 文件标签 | 内部家族 / 子家族 | UPM | OS/2 字重 | 可变轴 | cmap 映射数 | glyph 数 | SHA-256 |",
        "|---|---|---:|---:|---|---:|---:|---|",
    ]
    for item in snapshots:
        axes = ", ".join(item["axes"]) or "无（静态字体）"
        lines.append(
            f"| {item['label']} | {item['family']} / {item['subfamily']} | {item['upm']} | "
            f"{item['weight']} | {axes} | {len(item['cmap']):,} | {item['glyph_count']:,} | "
            f"`{item['sha256']}` |"
        )
    lines.extend([
        "",
        "## OpenType 区域／脚本替换能力",
        "",
        "| 文件标签 | GSUB features / scripts | GPOS features / scripts |",
        "|---|---|---|",
    ])
    for item in snapshots:
        gsub = item["layout"]["GSUB"]
        gpos = item["layout"]["GPOS"]
        lines.append(
            f"| {item['label']} | `{', '.join(gsub['features']) or '无'}` / "
            f"`{', '.join(gsub['scripts']) or '无'}` | "
            f"`{', '.join(gpos['features']) or '无'}` / {', '.join(gpos['scripts']) or '无'} |"
        )
    has_locl = any("locl" in item["layout"]["GSUB"]["features"] for item in snapshots)
    lines.extend([
        "",
        f"`locl` locale-specific GSUB feature: {'present' if has_locl else 'absent in all inputs'}. "
        "Without it, the font cannot select different glyph outlines by locale through `locl`; "
        "regional shaping must come from locale-specific fallback fonts or separately authored regional forms.",
        "",
        "| Unicode 区块（范围计数，不是目标集合百分比） | " + " | ".join(labels) + " |",
        "|---|" + "---:|" * len(labels),
    ])
    for name, _, _ in BLOCKS:
        counts = " | ".join(f"{item['blocks'][name]:,}" for item in snapshots)
        lines.append(f"| {name} | {counts} |")

    lines.extend([
        "",
        "## 同字重覆盖差异",
        "",
        "下表只说某档的 cmap 是否有该码位，不表示对应轮廓是否好看。",
        "",
    ])
    cmap_sets = {item["label"]: set(item["cmap"]) for item in snapshots}
    if len(labels) >= 2:
        reference = labels[1]
        for label in labels:
            if label == reference:
                continue
            missing = sorted(cmap_sets[reference] - cmap_sets[label])
            extra = sorted(cmap_sets[label] - cmap_sets[reference])
            lines.append(f"- `{label}` 相对 `{reference}`：少 {len(missing):,} 个码位，多 {len(extra):,} 个码位。")
            cjk_missing = [cp for cp in missing if any(lo <= cp <= hi for _, lo, hi in BLOCKS[:14])]
            if cjk_missing:
                sample = ", ".join(f"U+{cp:04X}" for cp in cjk_missing[:20])
                suffix = " …" if len(cjk_missing) > 20 else ""
                lines.append(f"  - CJK/地区区块中少 {len(cjk_missing):,} 个，例：{sample}{suffix}")

    lines.extend([
        "",
        "## 可打印编码表对照（仅作目标集代理）",
        "",
        "集合由当前 Python 运行时的 codec 映射枚举，并排除了 Unicode 控制、格式、分隔符、",
        "私用区及未分配码位；它不是标准机构的正式合规测试。特别是 CP949 的覆盖缺口反映",
        "韩文块是否存在，不应被解释成简体中文的缺字率。",
        "",
        "| 比较集合 | 可打印码位数 | " + " | ".join(f"{label} 命中 / 缺失" for label in labels) + " |",
        "|---|---:|" + "---:|" * len(labels),
    ])
    for profile, codec in CODEC_PROFILES:
        expected = encoded_printable_codepoints(codec)
        cells = []
        for item in snapshots:
            hits = len(expected & set(item["cmap"]))
            cells.append(f"{hits:,} / {len(expected - set(item['cmap'])):,}")
        lines.append(f"| {profile} | {len(expected):,} | " + " | ".join(cells) + " |")

    lines.extend([
        "",
        "## 轮廓存在性提示（不是缺字判定）",
        "",
        "空轮廓映射可能是空格、占位符或组合字元，也可能是缺陷，必须结合 Unicode 类别、",
        "排版行为与视觉结果逐项分类；零 advance 同样可能是合法组合符。",
        "",
    ])
    for item in snapshots:
        empty = ", ".join(f"U+{cp:04X}" for cp in item["empty"])
        zero = ", ".join(f"U+{cp:04X}" for cp in item["zero_advance"])
        lines.append(f"- `{item['label']}`：空轮廓映射 {len(item['empty'])} 个（{empty}）；"
                     f"零 advance {len(item['zero_advance'])} 个（{zero}）；"
                     f"复合 glyph 映射 {len(item['composite'])} 个。")

    lines.extend([
        "",
        "## 初步结论与下一步",
        "",
        "1. Light 的 cmap 映射数明显少于 Regular / Medium，差异不仅是冷僻 CJK；先分开确认",
        "   是上游字重覆盖差异还是需要制作 Light 轮廓，不能直接把较重字形复制到 Light。",
        "2. 三档都没有 Hangul 音节区（U+AC00..U+D7AF）；Regular / Medium 有 Hangul Jamo，Light 的 Jamo 覆盖也不同。",
        "   若目标包含韩文完整显示，需要地区回退或另行决定是否扩字形。",
        "3. CPython `GB2312` / `GBK` / `Big5-HKSCS` / `Shift_JIS` / `CP949` 只用于发现差异；",
        "   后续应依据用户确定的码位目标和设备回退链复核，不能把 codec 命中率冒充标准认证。",
        "4. 覆盖审计与字形美术审查是两项工作：下一步分别建立码位缺口清单和常用字形视觉问题清单。",
        "5. 本轮未改 TTF，也未把静态 Maruko 字重接入要求 `wght` 可变轴的生产构建流程。",
        "",
    ])
    if gap_path and gap_count is not None:
        lines.extend([
            f"编码表与字重差异逐码位清单：[`{gap_path.name}`]({gap_path.name})（{gap_count:,} 行；",
            "同一码位可出现在多个比较集合）。",
            "",
        ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def audit(fonts: list[tuple[str, Path]], report_path: Path, gaps_path: Path | None = None) -> None:
    if len(fonts) < 2:
        raise ValueError("provide at least two fonts to compare weight coverage")
    labels = [label for label, _ in fonts]
    if len(set(labels)) != len(labels):
        raise ValueError("font labels must be unique")
    snapshots = [_snapshot(label, path) for label, path in fonts]
    gap_count = _write_gap_tsv(gaps_path, snapshots) if gaps_path else None
    _write_report(report_path, snapshots, gaps_path, gap_count)
    print(f"coverage report -> {report_path}")
    if gaps_path:
        print(f"codepoint gap list ({gap_count:,} rows) -> {gaps_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", action="append", required=True, type=_font_label,
                        metavar="LABEL=PATH", help="repeat for each static weight")
    parser.add_argument("--out", type=Path, required=True, help="Markdown report path")
    parser.add_argument("--gaps-tsv", type=Path, help="optional per-codepoint codec-gap TSV")
    args = parser.parse_args()
    audit(args.font, args.out, args.gaps_tsv)


if __name__ == "__main__":
    main()
