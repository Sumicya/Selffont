#!/usr/bin/env python3
"""Research audit of glyph-outline centerline segment lengths.

This is a measurement tool, not a stroke reconstruction or font converter. It
skeletonizes a rasterized glyph and measures graph paths between skeleton
endpoints/junctions. Those paths are geometric centerline segments, NOT
semantic Chinese strokes. Coarse orientation buckets (horizontal, vertical,
diagonal) are only proxies for cross-glyph comparison.

The tool reports within-glyph segment-length dispersion and, per orientation,
the cross-glyph dispersion of each glyph's median segment length. It writes
CSV rows for every sample occurrence (so repeated characters retain their
weight) and a Markdown summary. It never changes font outlines.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
from fontTools.ttLib import TTFont
from skimage.morphology import skeletonize

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.stroke_width_audit import rasterize_glyph  # noqa: E402

DEFAULT_CHARS = (
    "一二三十口日回国了乙人入八木林森永心必水走建进这远道你好中国"
    "语言文字书写规范长美丽颜色锦绣风雨雪龙马鸟虫鱼电子已己巳也包囚暖田"
)
ORIENTATIONS = ("H", "V", "D")
OFFSETS = tuple(
    (dr, dc)
    for dr in (-1, 0, 1)
    for dc in (-1, 0, 1)
    if (dr, dc) != (0, 0)
)
CSV_FIELDS = (
    "weight", "sample_index", "char", "codepoint", "glyph_name",
    "branch_count", "total_centerline_fu", "branch_min_fu",
    "branch_median_fu", "branch_max_fu", "branch_cv",
    "H_count", "H_median_fu", "H_cv",
    "V_count", "V_median_fu", "V_cv",
    "D_count", "D_median_fu", "D_cv",
    "short_branches_lt10_fu",
)


def _edge_key(a: tuple[int, int], b: tuple[int, int]):
    return (a, b) if a < b else (b, a)


def skeleton_graph(skeleton: np.ndarray) -> dict[tuple[int, int], tuple[tuple[int, int], ...]]:
    """Build an 8-neighbor graph while suppressing diagonal corner shortcuts."""
    pixels = set(zip(*np.nonzero(skeleton)))
    graph: dict[tuple[int, int], tuple[tuple[int, int], ...]] = {}
    for row, col in pixels:
        adjacent = []
        for dr, dc in OFFSETS:
            other = (row + dr, col + dc)
            if other not in pixels:
                continue
            if dr and dc:
                # When an orthogonal pixel already connects this pair's corner,
                # omit the diagonal shortcut to avoid counting a 2x2 stair-step
                # as a triangle or making junction degree depend on pixelization.
                if (row + dr, col) in pixels or (row, col + dc) in pixels:
                    continue
            adjacent.append(other)
        graph[(row, col)] = tuple(sorted(adjacent))
    return graph


def trace_centerline_paths(skeleton: np.ndarray) -> list[list[tuple[int, int]]]:
    """Trace skeleton paths between endpoints/junctions, including pure cycles."""
    graph = skeleton_graph(skeleton)
    nodes = {point for point, neighbors in graph.items() if len(neighbors) != 2}
    visited: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    paths: list[list[tuple[int, int]]] = []

    # Start at every endpoint or junction and trace each incident edge once.
    for start in sorted(nodes):
        for first in graph[start]:
            key = _edge_key(start, first)
            if key in visited:
                continue
            visited.add(key)
            path = [start, first]
            previous, current = start, first
            while current not in nodes:
                candidates = [point for point in graph[current] if point != previous]
                if not candidates:
                    break
                following = candidates[0]
                key = _edge_key(current, following)
                if key in visited:
                    break
                visited.add(key)
                path.append(following)
                previous, current = current, following
            if len(path) >= 2:
                paths.append(path)

    # Components with every pixel degree 2 are cycles and have no natural node.
    for start in sorted(graph):
        for first in graph[start]:
            if _edge_key(start, first) in visited:
                continue
            visited.add(_edge_key(start, first))
            path = [start, first]
            previous, current = start, first
            while current != start:
                candidates = [point for point in graph[current] if point != previous]
                following = next(
                    (point for point in candidates if _edge_key(current, point) not in visited),
                    None,
                )
                if following is None:
                    break
                visited.add(_edge_key(current, following))
                path.append(following)
                previous, current = current, following
            if len(path) >= 2:
                paths.append(path)
    return paths


def path_length_fu(path: Iterable[tuple[int, int]], units_per_pixel: float) -> float:
    points = list(path)
    pixels = sum(
        math.hypot(b[0] - a[0], b[1] - a[1])
        for a, b in zip(points, points[1:])
    )
    return pixels * units_per_pixel


def orientation_bucket(path: Iterable[tuple[int, int]]) -> str:
    """Classify a path by its PCA axis; this is a coarse geometric proxy."""
    points = np.asarray([(col, -row) for row, col in path], dtype=float)
    if len(points) < 2:
        return "D"
    centered = points - points.mean(axis=0)
    cov = centered.T @ centered
    values, vectors = np.linalg.eigh(cov)
    axis = vectors[:, int(np.argmax(values))]
    angle = math.degrees(math.atan2(axis[1], axis[0])) % 180.0
    if angle < 22.5 or angle >= 157.5:
        return "H"
    if 67.5 <= angle < 112.5:
        return "V"
    return "D"


def _cv(values: Iterable[float]) -> float | None:
    array = np.asarray(list(values), dtype=float)
    if array.size < 2 or float(array.mean()) <= 0:
        return None
    return float(array.std() / array.mean())


def analyze_mask(mask: np.ndarray, units_per_pixel: float) -> dict:
    skeleton = skeletonize(mask)
    paths = trace_centerline_paths(skeleton)
    measurements = []
    for path in paths:
        length = path_length_fu(path, units_per_pixel)
        if length <= 0:
            continue
        measurements.append({
            "length_fu": length,
            "orientation": orientation_bucket(path),
            "path": path,
        })
    lengths = [entry["length_fu"] for entry in measurements]
    by_orientation = {
        category: [entry["length_fu"] for entry in measurements if entry["orientation"] == category]
        for category in ORIENTATIONS
    }
    return {
        "skeleton_pixels": int(np.count_nonzero(skeleton)),
        "paths": measurements,
        "branch_count": len(lengths),
        "total_centerline_fu": float(sum(lengths)),
        "branch_min_fu": float(min(lengths)) if lengths else None,
        "branch_median_fu": float(np.median(lengths)) if lengths else None,
        "branch_max_fu": float(max(lengths)) if lengths else None,
        "branch_cv": _cv(lengths),
        "by_orientation": {
            category: {
                "count": len(values),
                "median_fu": float(np.median(values)) if values else None,
                "cv": _cv(values),
            }
            for category, values in by_orientation.items()
        },
        "short_branches_lt10_fu": sum(length < 10.0 for length in lengths),
    }


def _parse_font_arg(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("字体参数格式应为 WEIGHT=PATH")
    weight, path = value.split("=", 1)
    if not weight or not path:
        raise argparse.ArgumentTypeError("字体参数格式应为 WEIGHT=PATH")
    return weight, Path(path)


def _summarize(weight: str, rows: list[dict], chars: str) -> dict:
    branch_cvs = [row["branch_cv"] for row in rows if row["branch_cv"] is not None]
    total_lengths = [row["total_centerline_fu"] for row in rows]
    cross_orientation = {}
    for category in ORIENTATIONS:
        values = [
            row[f"{category}_median_fu"]
            for row in rows
            if row[f"{category}_median_fu"] is not None
        ]
        cross_orientation[category] = {
            "glyph_occurrences": len(values),
            "mean_median_fu": float(np.mean(values)) if values else None,
            "cv_across_glyphs": _cv(values),
        }
    return {
        "weight": weight,
        "sample_occurrences": len(chars),
        "unique_characters": len(set(chars)),
        "mean_intraglyph_branch_cv": float(np.mean(branch_cvs)) if branch_cvs else None,
        "glyphs_with_intraglyph_cv": len(branch_cvs),
        "median_total_centerline_fu": float(np.median(total_lengths)) if total_lengths else None,
        "cross_glyph_orientation_medians": cross_orientation,
        "interpretation": (
            "Raster medial-axis paths between endpoints/junctions, not semantic Hanzi strokes. "
            "H/V/D are coarse PCA orientation groups. Exploratory baseline only."
        ),
    }


def _write_markdown(path: Path, summaries: list[dict], px: int, chars: str) -> None:
    lines = [
        "# Maruko Gothic 中心线长度基线（研究审计）",
        "",
        f"样本项：{len(chars)}；不同字符：{len(set(chars))}；栅格：{px}px。",
        "",
        "**指标解释**：从填充字形的中轴骨架提取端点/分叉点之间的几何路径，统计单字内路径长度离散度；按 PCA 方向粗分 H/V/D，再比较各字同方向路径长度中位数的跨字 CV。H/V/D 不是汉字笔画语义分类，骨架分支也不等于完整汉字笔画。此报告是原字形的探索性基线，不是设计质量结论、筑紫相似度分数或生产验收。",
        "",
        "## 汇总",
        "",
        "| 字重 | 样本项 | 有效字内 CV 字数 | 平均字内分支 CV | 中位总中心线长度 (FU) | H 跨字 CV | V 跨字 CV | D 跨字 CV |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        cross = summary["cross_glyph_orientation_medians"]
        fmt = lambda value: "—" if value is None else f"{value:.4f}"
        lines.append(
            f"| {summary['weight']} | {summary['sample_occurrences']} | "
            f"{summary['glyphs_with_intraglyph_cv']} | "
            f"{fmt(summary['mean_intraglyph_branch_cv'])} | "
            f"{fmt(summary['median_total_centerline_fu'])} | "
            f"{fmt(cross['H']['cv_across_glyphs'])} | "
            f"{fmt(cross['V']['cv_across_glyphs'])} | "
            f"{fmt(cross['D']['cv_across_glyphs'])} |"
        )
    lines.extend([
        "",
        "## 局限与使用边界",
        "",
        "- 栅格化与骨架化对分辨率、字重、交叉点拓扑敏感；细小分支可能是拓扑结果，不一定对应设计笔画。",
        "- H/V/D 只按骨架路径主轴方向分组，不能把 H 组误读成所有字中的同一类横画。跨字 CV 只能用于筛查，不可直接当作应统一的目标值。",
        "- 本工具只读原始轮廓，不改字体；不读取或移用筑紫轮廓坐标。筑紫仍可用于后续视觉/结构分析。",
        "- 本样本集最初为宽度审计选取；长度基线复用它以便前后对照，不宣称它代表全字符集。",
        "",
        "逐字/逐样本项的数据见同目录 CSV。",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run(font_args: list[tuple[str, Path]], chars: str, px: int, out_csv: Path, out_md: Path) -> None:
    if px < 300:
        raise ValueError("--px 至少为 300；低分辨率可能明显改变骨架拓扑")
    if not chars:
        raise ValueError("--chars 不能为空")

    all_rows: list[dict] = []
    summaries: list[dict] = []
    for weight, font_path in font_args:
        if not font_path.is_file():
            raise FileNotFoundError(font_path)
        font = TTFont(font_path)
        if "glyf" not in font:
            raise ValueError(f"仅支持 TrueType glyf 字体：{font_path}")
        if "fvar" in font:
            raise ValueError(f"请传入静态字重实例，不支持可变字体：{font_path}")
        cmap = font.getBestCmap()
        glyph_cache: dict[str, dict] = {}
        weight_rows: list[dict] = []

        for sample_index, char in enumerate(chars, start=1):
            glyph_name = cmap.get(ord(char))
            if glyph_name is None:
                raise ValueError(f"{weight} 字体缺少字符 {char!r} U+{ord(char):04X}")
            if glyph_name not in glyph_cache:
                mask, units_per_pixel = rasterize_glyph(font, glyph_name, px=px)
                if mask is None:
                    raise ValueError(f"{weight} 字体字符 {char!r} 的字形无法栅格化")
                glyph_cache[glyph_name] = analyze_mask(mask, units_per_pixel)
            metrics = glyph_cache[glyph_name]
            row = {
                "weight": weight,
                "sample_index": sample_index,
                "char": char,
                "codepoint": f"U+{ord(char):04X}",
                "glyph_name": glyph_name,
                "branch_count": metrics["branch_count"],
                "total_centerline_fu": metrics["total_centerline_fu"],
                "branch_min_fu": metrics["branch_min_fu"],
                "branch_median_fu": metrics["branch_median_fu"],
                "branch_max_fu": metrics["branch_max_fu"],
                "branch_cv": metrics["branch_cv"],
                "short_branches_lt10_fu": metrics["short_branches_lt10_fu"],
            }
            for category in ORIENTATIONS:
                part = metrics["by_orientation"][category]
                row[f"{category}_count"] = part["count"]
                row[f"{category}_median_fu"] = part["median_fu"]
                row[f"{category}_cv"] = part["cv"]
            weight_rows.append(row)
            all_rows.append(row)

        summaries.append(_summarize(weight, weight_rows, chars))
        font.close()

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    _write_markdown(out_md, summaries, px, chars)
    out_json = out_md.with_suffix(".json")
    out_json.write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for summary in summaries:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    print(f"CSV -> {out_csv}")
    print(f"Markdown -> {out_md}")
    print(f"JSON -> {out_json}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--font", action="append", type=_parse_font_arg, required=True,
        metavar="WEIGHT=PATH", help="static TTF input; repeat for multiple weights",
    )
    parser.add_argument("--chars", default=DEFAULT_CHARS, help="sample sequence; duplicates retain weight")
    parser.add_argument("--px", type=int, default=1200, help="square raster canvas size (default: 1200px)")
    parser.add_argument("--out-csv", type=Path, required=True, help="per-sample CSV output")
    parser.add_argument("--out-md", type=Path, required=True, help="summary Markdown output")
    args = parser.parse_args()
    run(args.font, args.chars, args.px, args.out_csv, args.out_md)


if __name__ == "__main__":
    main()
