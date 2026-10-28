#!/usr/bin/env python3
"""Compare same-commit Maruko SC/TC/JP static-font coverage and Han outlines.

Cmap and outline-signature differences are diagnostics, not standards compliance
or a judgment that a regional form is visually correct.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import unicodedata
from pathlib import Path

from fontTools.ttLib import TTFont

SOURCE_COMMIT = "97e9dd4a2fdde58084dde8d022de253f8d8415e9"
REGIONS = ("SC", "TC", "JP")
WEIGHTS = ("Light", "Regular", "Medium")
HAN_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x323AF))
CJK_BLOCKS = (
    ("Han BMP", 0x4E00, 0x9FFF),
    ("Han Extension A", 0x3400, 0x4DBF),
    ("Han Compatibility", 0xF900, 0xFAFF),
    ("Han Supplementary B onward", 0x20000, 0x323AF),
    ("CJK Punctuation", 0x3000, 0x303F),
    ("CJK Radicals and Kangxi", 0x2E80, 0x2FDF),
    ("Bopomofo", 0x3100, 0x312F),
    ("Kana", 0x3040, 0x30FF),
    ("Hangul Jamo", 0x1100, 0x11FF),
    ("Hangul Compatibility Jamo", 0x3130, 0x318F),
    ("Hangul Syllables", 0xAC00, 0xD7AF),
)


def parse_font(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("font must be REGION-WEIGHT=PATH")
    label, raw_path = value.split("=", 1)
    if not label or not raw_path:
        raise argparse.ArgumentTypeError("font must be REGION-WEIGHT=PATH")
    path = Path(raw_path)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"font file does not exist: {path}")
    return label, path


def _layout_features(font: TTFont) -> dict[str, list[str]]:
    result = {}
    for tag in ("GSUB", "GPOS"):
        if tag not in font:
            result[tag] = []
            continue
        feature_list = font[tag].table.FeatureList
        result[tag] = sorted({record.FeatureTag for record in feature_list.FeatureRecord}) if feature_list else []
    return result


def _snapshot(label: str, path: Path) -> dict:
    with TTFont(path, lazy=False) as font:
        cmap = font.getBestCmap() or {}
        axes = []
        if "fvar" in font:
            axes = [f"{axis.axisTag}={axis.minValue:g}..{axis.defaultValue:g}..{axis.maxValue:g}"
                    for axis in font["fvar"].axes]
        return {
            "label": label,
            "path": path,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "family": font["name"].getDebugName(1) or "",
            "subfamily": font["name"].getDebugName(2) or "",
            "weight": font["OS/2"].usWeightClass,
            "upm": font["head"].unitsPerEm,
            "axes": axes,
            "layout": _layout_features(font),
            "cmap": cmap,
            "glyph_count": font["maxp"].numGlyphs,
            "blocks": {name: sum(start <= cp <= end for cp in cmap)
                       for name, start, end in CJK_BLOCKS},
        }


def _outline_signature(font: TTFont, codepoint: int) -> tuple[tuple, tuple[int, ...], tuple[int, ...]]:
    glyph_name = font.getBestCmap()[codepoint]
    coords, end_points, flags = font["glyf"][glyph_name].getCoordinates(font["glyf"])
    return tuple(coords), tuple(end_points), tuple(flags)


def compare_region_pair(a: dict, b: dict, han_only: bool = True) -> dict:
    a_cmap, b_cmap = a["cmap"], b["cmap"]
    shared = set(a_cmap) & set(b_cmap)
    if han_only:
        shared = {cp for cp in shared if any(lo <= cp <= hi for lo, hi in HAN_RANGES)}
    a_font, b_font = TTFont(a["path"], lazy=False), TTFont(b["path"], lazy=False)
    coordinate_differences = structure_differences = 0
    try:
        for cp in shared:
            sig_a = _outline_signature(a_font, cp)
            sig_b = _outline_signature(b_font, cp)
            if sig_a[1:] != sig_b[1:]:
                structure_differences += 1
            elif sig_a[0] != sig_b[0]:
                coordinate_differences += 1
    finally:
        a_font.close()
        b_font.close()
    only_a = set(a_cmap) - set(b_cmap)
    only_b = set(b_cmap) - set(a_cmap)
    if han_only:
        only_a = {cp for cp in only_a if any(lo <= cp <= hi for lo, hi in HAN_RANGES)}
        only_b = {cp for cp in only_b if any(lo <= cp <= hi for lo, hi in HAN_RANGES)}
    return {
        "shared": len(shared),
        "only_a": len(only_a),
        "only_b": len(only_b),
        "outline_coordinate_diff": coordinate_differences,
        "outline_structure_diff": structure_differences,
    }


def _validate_fonts(fonts: list[tuple[str, Path]]) -> None:
    labels = {label for label, _ in fonts}
    expected = {f"{region}-{weight}" for region in REGIONS for weight in WEIGHTS}
    if labels != expected:
        missing, extra = sorted(expected - labels), sorted(labels - expected)
        raise ValueError(f"need exactly SC/TC/JP × Light/Regular/Medium; missing={missing}, extra={extra}")
    if len(fonts) != len(labels):
        raise ValueError("font labels must be unique")


def _write_gaps(path: Path, snapshots: dict[str, dict]) -> int:
    labels = [f"{region}-{weight}" for region in REGIONS for weight in WEIGHTS]
    candidates = set().union(*(set(snapshots[label]["cmap"]) for label in labels))
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(("codepoint", "character", "unicode_name", *labels))
        for cp in sorted(candidates):
            present = [cp in snapshots[label]["cmap"] for label in labels]
            if all(present):
                continue
            writer.writerow((f"U+{cp:04X}", chr(cp), unicodedata.name(chr(cp), ""),
                             *["yes" if value else "no" for value in present]))
            count += 1
    return count


def _write_report(path: Path, snapshots: dict[str, dict], pairs: dict[tuple[str, str, str], dict], gap_path: Path | None,
                  gap_count: int | None) -> None:
    lines = [
        "# Maruko Gothic 多地区静态字重覆盖审计",
        "",
        f"固定来源为同一上游提交 [`{SOURCE_COMMIT}`](https://github.com/max32002/maruko-gothic/tree/{SOURCE_COMMIT})。",
        "三套地区字形均来自 Maruko Gothic 本身；本报告的 cmap/轮廓签名差异是技术审计，不等同于字形美术验收或国家标准认证。",
        "",
        "## 来源与元数据",
        "",
        "| 地区 | 字重 | 内部家族 / 子家族 | OS/2 weight | UPM | cmap | glyph 数 | 轴 | SHA-256 |",
        "|---|---|---|---:|---:|---:|---:|---|---|",
    ]
    for region in REGIONS:
        for weight in WEIGHTS:
            item = snapshots[f"{region}-{weight}"]
            axes = ", ".join(item["axes"]) or "静态"
            lines.append(
                f"| {region} | {weight} | {item['family']} / {item['subfamily']} | {item['weight']} | "
                f"{item['upm']} | {len(item['cmap']):,} | {item['glyph_count']:,} | {axes} | `{item['sha256']}` |"
            )

    lines.extend([
        "",
        "本矩阵仅比较三地区共有的 Light / Regular / Medium；固定提交还提供 JP Bold / Black，但 SC / TC 没有对应静态文件，故未纳入横向比较。",
        "",
        "## CJK 区块映射数",
        "",
    ])
    for region in REGIONS:
        lines.extend([
            f"### {region}",
            "",
            "| 区块 | Light | Regular | Medium |",
            "|---|---:|---:|---:|",
        ])
        for block, _, _ in CJK_BLOCKS:
            counts = [snapshots[f"{region}-{weight}"]["blocks"][block] for weight in WEIGHTS]
            lines.append(f"| {block} | " + " | ".join(f"{count:,}" for count in counts) + " |")
        lines.append("")

    lines.extend([
        "## 地区 cmap 差异与同码位轮廓差异",
        "",
        "`轮廓签名差异`按 expanded TrueType coordinates、contour endpoints 与 on-curve flags 的精确值比较。",
        "这不是曲线几何等价测试：点序/组件展开方式不同会被记为差异；报告也不判断地区字形是否正确，需独立人工校稿。",
        "",
        "| 字重 | 比较 | 共同 Han 码位 | 仅左侧 Han 码位 | 仅右侧 Han 码位 | 仅坐标不同 | 点数/端点/on-curve flags 不同 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ])
    for weight in WEIGHTS:
        for region_a, region_b in (("SC", "TC"), ("SC", "JP"), ("TC", "JP")):
            result = pairs[(weight, region_a, region_b)]
            lines.append(
                f"| {weight} | {region_a} ↔ {region_b} | {result['shared']:,} | {result['only_a']:,} | "
                f"{result['only_b']:,} | {result['outline_coordinate_diff']:,} | "
                f"{result['outline_structure_diff']:,} |"
            )

    all_locl = any("locl" in snapshots[f"{region}-{weight}"]["layout"]["GSUB"]
                   for region in REGIONS for weight in WEIGHTS)
    lines.extend([
        "",
        f"All nine inputs are static; locale-specific GSUB `locl` is "
        f"{'present in at least one input' if all_locl else 'absent in every input'}. "
        "For regional forms, select the matching SC/TC/JP font family by locale instead of expecting one file to switch itself.",
        "",
        "## Korean coverage and other script limits",
        "",
        "The pinned repository tree has SC, TC, and JP families, but no KR family. All three regions have zero mapped Hangul syllables `U+AC00..U+D7AF`; Korean must remain on a Korean-capable fallback unless a separate Maruko KR design source is found or approved.",
        "No Music Symbols are mapped. Arabic and Devanagari are also outside these CJK files' current cmap coverage. Keep script-specific fonts in the fallback chain rather than silently borrowing their outlines.",
        "",
        "## Implications for expansion",
        "",
        "1. This same Maruko commit already provides separate SC / TC / JP static families. Use them as the first-party source for those three locales; do not synthesize regional Han forms from SC alone.",
        "2. Coverage differs by region and weight. Audit the exact target codepoint sets before editing; the `Light` family is substantially smaller than Regular/Medium in all three locales.",
        "3. Cmap presence is not proof of a usable outline or correct region glyph. The next visual pass must review common/standard test strings per locale, then classify missing-codepoint, topology, local-stroke, and style issues separately.",
        "4. The current production builder expects a variable `wght` font. All nine source files are static. Integrating them requires a deliberate static-family build path or validated variable-font construction; none has been done here.",
        "",
    ])
    if gap_path and gap_count is not None:
        lines.extend([
            f"Regional/weight cmap differences: [`{gap_path.name}`]({gap_path.name}) ({gap_count:,} rows; codepoints not present in all nine files).",
            "",
        ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def audit(fonts: list[tuple[str, Path]], report_path: Path, gaps_path: Path | None = None) -> None:
    _validate_fonts(fonts)
    snapshots = {label: _snapshot(label, path) for label, path in fonts}
    pairs = {}
    for weight in WEIGHTS:
        for region_a, region_b in (("SC", "TC"), ("SC", "JP"), ("TC", "JP")):
            a, b = snapshots[f"{region_a}-{weight}"], snapshots[f"{region_b}-{weight}"]
            pairs[(weight, region_a, region_b)] = compare_region_pair(a, b)
    gap_count = _write_gaps(gaps_path, snapshots) if gaps_path else None
    _write_report(report_path, snapshots, pairs, gaps_path, gap_count)
    print(f"regional coverage report -> {report_path}")
    if gaps_path:
        print(f"regional/weight cmap differences ({gap_count:,} rows) -> {gaps_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", action="append", required=True, type=parse_font,
                        metavar="REGION-WEIGHT=PATH", help="repeat for SC/TC/JP × three weights")
    parser.add_argument("--out", type=Path, required=True, help="Markdown report path")
    parser.add_argument("--gaps-tsv", type=Path, help="optional codepoint-level regional/weight cmap gaps")
    args = parser.parse_args()
    audit(args.font, args.out, args.gaps_tsv)


if __name__ == "__main__":
    main()
