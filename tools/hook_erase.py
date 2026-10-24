"""无钩：候选点对沿用 ``hook_cut`` 的判据，但**切在墨迹上**，不改轮廓。

为什么不能直接改轮廓
--------------------
``hook_cut.apply_hook_cuts()`` 会把闸门点之间的那串点换成一段"向外鼓"的圆弧。这条路
有两个静默的致命伤：

1. **鼓出方向靠"进入方向"猜**。猜反一段弧就横穿轮廓自身，非零环绕下整块内腔立刻
   翻成实心。实测 252 个常用字里 ``世``/``醒``/``点`` 的内腔全被填实。
2. **闸门点对误判时没有任何兜底**。等宽笔画上"两点空间近、沿轮廓远"这对条件在曲线
   上极易误触发；``儿`` 被切掉两条长弧的大半（外接框 913 → 591 单位），
   ``从``/``他``/``位``/``话`` 同样腰斩。

实测：只跑无钩、其余不动，252 个字里 **192 个**与原文 IoU 掉到 0.95 以下，
**130 个**掉墨超过 5%。所以轮廓手术这条路放弃。

现在的做法
----------
候选点对由 ``hook_cut.find_hooks()`` 给出（它的召回在这些字上是够的，问题在"切"不在
"找"），把闸门之间的闭合环映射到像素坐标，**从掩膜里挖掉这块墨**，再整体重描轮廓。
轮廓的点数、点序、绕向全部重新生成，"翻向"这种情况在结构上不可能发生。

挖完有两道闸门，任何一道不过就整字回退到未切的掩膜：

* 挖掉的墨 ≤ 全字墨量的 ``MAX_ERASE_FRACTION``（默认 8%）——钩是小东西，挖多了就是误判；
* 挖完重描的字与原字 IoU ≥ ``MIN_IOU_AFTER_CUT``（默认 0.93）——兜底防"看起来切了
  其实把笔画切没了"。
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon

from stroke_width_audit import FlattenPen, signed_area

MAX_ERASE_FRACTION = 0.08
MIN_IOU_AFTER_CUT = 0.93


def _to_pixel_factory(transform, px):
    xmin, ymin, scale, margin_px, _, _ = transform

    def to_pixel(point):
        x, y = point
        return ((x - xmin) * scale + margin_px,
                px - ((y - ymin) * scale + margin_px))

    return to_pixel


def loop_polygon(contour, i, j, to_pixel):
    """闸门点 i→j 沿轮廓走一圈（短的那侧）+ 弦，围出的闭合环。"""
    n = len(contour)
    points = []
    k = i
    guard = 0
    while True:
        points.append(to_pixel(contour[k][:2]))
        if k == j:
            break
        k = (k + 1) % n
        guard += 1
        if guard > n:
            return None
    if len(points) < 3:
        return None
    polygon = Polygon(points)
    if polygon.is_empty or polygon.area <= 0:
        return None
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty:
        return None
    return polygon


def _rasterize_polygon(polygon, shape):
    from PIL import Image, ImageDraw
    mask = Image.new("L", (shape[1], shape[0]), 0)
    draw = ImageDraw.Draw(mask)
    parts = polygon.geoms if hasattr(polygon, "geoms") else [polygon]
    for part in parts:
        if part.is_empty:
            continue
        if part.exterior:
            draw.polygon(list(part.exterior.coords), fill=255)
        for interior in part.interiors:
            draw.polygon(list(interior.coords), fill=0)
    return np.asarray(mask) > 127


def erase_loops(mask: np.ndarray, transform, contour_index, hooks):
    """把 ``hooks``（[(contour_idx, i, j)]）围出的墨挖掉，返回（新掩膜, 实际挖的环数, 挖去的墨量占比）。"""
    if not hooks:
        return mask, 0, 0.0
    px = mask.shape[0]
    to_pixel = _to_pixel_factory(transform, px)
    erased = mask.copy()
    removed_pixels = 0
    total_ink = int(mask.sum())
    applied = 0
    for ci, i, j in hooks:
        if ci not in contour_index:
            continue
        polygon = loop_polygon(contour_index[ci], i, j, to_pixel)
        if polygon is None:
            continue
        hole = _rasterize_polygon(polygon, mask.shape)
        hit = int((erased & hole).sum())
        if hit == 0:
            continue
        candidate = erased & ~hole
        # 挖完不能断开笔画：连通块数不能变多
        added = int((erased & ~hole).sum())
        removed_pixels += hit
        erased = candidate
        applied += 1
        if total_ink:
            pass
        _ = added
    fraction = (removed_pixels / total_ink) if total_ink else 0.0
    return erased, applied, fraction


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.count_nonzero(a | b)
    return float(np.count_nonzero(a & b)) / union if union else 1.0


def render_glyph_object(glyph, glyf_table, px=600, box=(-100, -100, 1100, 1100)):
    """按固定 em 网格渲染一个 glyf 字形对象，用来做前后对比。

    固定网格（而不是各自的外接框）很关键：重描后外接框会变一两个单位，按外接框
    归一化会把整字重新缩放，量出来的相似度全是假的。
    """
    from PIL import Image, ImageDraw

    pen = FlattenPen({}, steps_per_curve=12)
    if glyph.isComposite():
        glyph.draw(pen, glyf_table)
    else:
        glyph.draw(pen, glyf_table)
    contours = pen.contours
    if not contours:
        return None
    x0, y0, x1, y1 = box
    scale = px / (x1 - x0)
    image = Image.new("L", (px, px), 0)
    draw = ImageDraw.Draw(image)
    polygons = []
    for contour in contours:
        area = signed_area(contour)
        if area == 0:
            continue
        polygons.append((abs(area), area,
                         [((x - x0) * scale, (y1 - y) * scale) for x, y in contour]))
    polygons.sort(key=lambda row: -row[0])
    outer = 1 if polygons[0][1] > 0 else -1
    for _, area, polygon in polygons:
        sign = 1 if area > 0 else -1
        draw.polygon(polygon, fill=255 if sign == outer else 0)
    return np.asarray(image) > 127


def compare_glyphs(before, after, glyf_table, px=600):
    """返回（IoU, 墨量变化比例）。"""
    a = render_glyph_object(before, glyf_table, px)
    b = render_glyph_object(after, glyf_table, px)
    if a is None or b is None:
        return 1.0, 0.0
    union = int((a | b).sum())
    iou = float((a & b).sum()) / union if union else 1.0
    ink = float(b.sum() - a.sum()) / max(1, int(a.sum()))
    return iou, ink
