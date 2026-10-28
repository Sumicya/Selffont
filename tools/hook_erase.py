"""无钩：把钩收到"看着是直的"为止，主笔画全长不动。

为什么是这个口径
----------------
钩切到钩根会让竖弯钩短掉 2–3 倍笔宽（`乙` 底横、`也`/`电` 的竖弯钩都会明显短一截），
主人选定的是"钩只收到看着是直的、不要把笔画切短"。所以这里只剪掉卷回去的那一小段
（默认 1.35 倍笔宽），切口补圆头，笔身长度保留。

为什么要两条规则
----------------
Maruko 的钩有两种骨架形态，实测（Regular，2000 px 栅格）：

**A. 闭合折返**：钩尖卷得太紧，墨迹自己贴在一起，骨架在那里分叉。
`乙`（钩根 4 度交叉点，挂 0.43W 与 1.21W 两根短刺）、`了`（1.25W）、`子`（1.11W）。
这类只有 `乙`/`了`/`子` 这几个字，笔尖方向相对笔身只转 21–26°，单看转角抓不到，
必须看"交叉点 + 短刺"。

**B. 开口卷**：钩是笔身末端的平滑上翘，骨架无分叉。笔尖方向在 2.2 倍笔宽内相对
自身方向转 49–81°（`电` 62 / `也` 79 / `九` 67 / `见` 72 / `几` 81 / `巴` 65 /
`己` 57 / `已` 56 / `巳` 58 / `包` 79 / `心` 60 / `必` 49，以及 `丁` 56 / `小` 64
这两个本来就有竖钩的字）。

对照组（`十`/`口`/`日`/`木`/`人`/`八`/`大`/`川`/`三`/`上`/`天`/`干`/`工`/`土`/`王`）
实测 3–30°（`大` 16、`川` 23、`下` 27、`天` 30），门槛 38° 落在两者之间。

之前证伪的四条路线（末端骨架累计转角、末端墨迹横向偏摆、边界最大凹转角、细长回卷环）
都记在 `docs/round-preview/2026-10-24-modern-maruko-pipeline/README.md`，不要再回头试。
"""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage
from skimage.morphology import skeletonize

FORK_SPUR_MAX_RATIO = 1.8   # 规则 A：短刺最长 1.8 倍笔宽
FORK_SPUR_MIN_RATIO = 0.35  # 更短的是骨架毛刺，不算钩
FORK_ANGLE_MIN = 45.0       # 短刺与笔身的最小夹角
TIP_CURL_ANGLE = 38.0       # 规则 B：笔尖 2.2W 内的最小转角
TIP_CURL_WINDOW = 2.2
TRIM_LENGTH_RATIO = 1.35    # 从笔尖往里剪掉多少（倍笔宽）

_NEIGHBORS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _graph(skeleton):
    rows, cols = np.nonzero(skeleton)
    pixels = set(zip(rows.tolist(), cols.tolist()))
    return pixels, {
        p: [(p[0] + dy, p[1] + dx) for dy, dx in _NEIGHBORS if (p[0] + dy, p[1] + dx) in pixels]
        for p in pixels
    }


def _edges(adjacency):
    nodes = {p for p, v in adjacency.items() if len(v) != 2}
    done = set()
    edges = []
    for node in nodes:
        for nb in adjacency[node]:
            if (node, nb) in done:
                continue
            path = [node]
            previous, current = node, nb
            done.add((node, nb))
            while True:
                path.append(current)
                if current in nodes:
                    break
                nxt = [q for q in adjacency[current] if q != previous]
                if not nxt:
                    break
                previous, current = current, nxt[0]
            if len(path) > 1:
                done.add((path[-1], path[-2]))
            edges.append(path)
    return nodes, edges


def _tangent(path, index, window):
    a = path[max(0, index - window)]
    b = path[min(len(path) - 1, index + window)]
    dy, dx = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dy, dx)
    return (dy / length, dx / length) if length > 1e-9 else None


def _angle(u, v):
    return math.degrees(math.acos(max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))))


def _junction_clusters(nodes, shape):
    mask = np.zeros(shape, dtype=bool)
    for row, col in nodes:
        mask[row, col] = True
    labels, _ = ndimage.label(mask, structure=np.ones((3, 3), dtype=bool))
    groups = {}
    for row, col in nodes:
        groups.setdefault(int(labels[row, col]), []).append((row, col))
    return list(groups.values())


def tip_curl_angle(path, width_px):
    """``path[0]`` 是笔尖；返回（最大转角, 出现在几倍笔宽处）。"""
    window = max(4, int(0.22 * width_px))
    tip = _tangent(path, 0, window)
    if tip is None:
        return 0.0, None
    best, at = 0.0, None
    for i in range(max(2, int(0.4 * width_px)), min(len(path) - 1, int(TIP_CURL_WINDOW * width_px))):
        tangent = _tangent(path, i, window)
        if tangent is None:
            continue
        angle = _angle(tip, tangent)
        if angle > best:
            best, at = angle, i / width_px
    return best, at


def find_hooks(mask, skeleton=None, distance=None):
    """返回 [(cut_point, removed_path, width_px)]，每条含一处钩的剪除信息。"""
    skeleton = skeletonize(mask) if skeleton is None else skeleton
    distance = ndimage.distance_transform_edt(mask) if distance is None else distance
    width_px = float(np.median(distance[skeleton]) * 2)
    if not np.isfinite(width_px) or width_px <= 1.0:
        return []
    pixels, adjacency = _graph(skeleton)
    nodes, edges = _edges(adjacency)
    hooks = []

    # 规则 A：交叉点上挂的短刺
    for group in _junction_clusters(nodes, mask.shape):
        cluster = set(group)
        incident = []
        for edge in edges:
            if edge[0] in cluster:
                incident.append(edge)
            elif edge[-1] in cluster:
                incident.append(list(reversed(edge)))
        body_dirs = []
        for edge in incident:
            if len(edge) > FORK_SPUR_MAX_RATIO * width_px:
                direction = _tangent(edge, 0, max(2, int(0.3 * width_px)))
                if direction:
                    body_dirs.append(direction)
        if not body_dirs:
            continue
        for edge in incident:
            if not (FORK_SPUR_MIN_RATIO * width_px <= len(edge) <= FORK_SPUR_MAX_RATIO * width_px):
                continue
            if len(adjacency[edge[-1]]) != 1:
                continue
            direction = _tangent(edge, 0, max(2, int(0.3 * width_px)))
            if direction is None:
                continue
            if min(_angle(direction, body) for body in body_dirs) < FORK_ANGLE_MIN:
                continue
            trimmed = min(len(edge) - 1, max(2, int(TRIM_LENGTH_RATIO * width_px)))
            cut = edge[trimmed - 1]
            hooks.append((cut, list(reversed(edge[:trimmed])), width_px))

    # 规则 B：笔尖在 2.2W 内的开口卷。
    # 附带两条硬约束，否则会把「点」这种独立短笔画当成钩剪掉：
    #   * 这条笔画必须挂在另一条更长的笔画上（独立短笔画不是钩）；
    #   * 它自己也得够长（至少 3W），「广」上面那个点只有 2.71W，剪了就是掉笔画。
    for edge in edges:
        standalone = (len(adjacency[edge[-1]]) == 1 and len(adjacency[edge[0]]) == 1)
        if standalone:
            continue  # 两端都是笔尖的独立笔画（点/撇/捺），不碰
        for path in (edge, list(reversed(edge))):
            if len(path) < 10 or len(adjacency[path[0]]) != 1:
                continue
            if len(path) < 2.0 * width_px:
                # 太短的一律不动：「广」上面那个点只有 2.71W，剪掉就是掉笔画。
                continue
            # 附着约束：这条笔画从笔尖走到 attach。要么 attach 是分叉点，要么它是某个
            # 闭合环上的点（电/也/九 的钩挂在闭合回路上，两端都不是笔尖，不能当成
            # 独立笔画忽略）。真正要排除的只有"两端都是笔尖"的独立短笔画。
            attach = path[-1]
            if len(adjacency[attach]) == 1:
                continue
            # 附着点必须接近笔画末端，而不是笔画中段。
            # 「广」上面那个点挂在横的中间：交汇点除它之外还有两条长边，是"中段分支"；
            # 真正的钩从笔画末端卷回来：交汇点除它之外只有一条长边，另一侧是笔画自己
            # 收尾的短残段。这是结构与语义的分界，光照局部弯曲分不开。
            incident = sum(
                1 for other in edges if other is not edge
                and (other[0] == attach or other[-1] == attach))
            if incident < 2:
                # 交汇点只有它和笔身两条边 —— 这是"短笔画挂在笔身末端"，也就是点和短撇，
                # 不是钩。钩是笔画末端卷回来，交汇点上必然还有笔画自己的收尾残段，
                # 所以至少三条边（`乙` 是 1 长 2 短，`了` 是 2 长 1 短，`广` 的点是 1 长 1 短）。
                continue
            angle, _ = tip_curl_angle(path, width_px)
            if angle < TIP_CURL_ANGLE:
                continue
            trimmed = min(len(path) - 1, max(2, int(TRIM_LENGTH_RATIO * width_px)))
            cut = path[trimmed - 1]
            hooks.append((cut, path[:trimmed], width_px))
    return hooks


def _cap(mask, cut, direction, radius, distance):
    """在缺口补半圆头：圆心沿笔身方向后移半径，圆只取笔身那一侧。"""
    r0, c0 = cut
    dy, dx = direction
    cy, cx = r0 + dy * radius, c0 + dx * radius
    pad = int(radius) + 2
    y1, y2 = int(max(0, cy - pad)), int(min(mask.shape[0], cy + pad + 1))
    x1, x2 = int(max(0, cx - pad)), int(min(mask.shape[1], cx + pad + 1))
    if y2 <= y1 or x2 <= x1:
        return
    yy, xx = np.mgrid[y1:y2, x1:x2]
    disc = (yy - cy) ** 2 + (xx - cx) ** 2 <= radius * radius
    mask[y1:y2, x1:x2] |= disc


def _body_axis(skeleton, cut, radius_px, removed=None, width_px=None):
    """求切面法线：优先用"钩路径在切点处的切线"，退回骨架环带 PCA。

    切点在钩的根部，那里笔身常常本身就在转弯（`乙` 的竖弯钩整段都是弧），不存在
    单一"笔身方向"。这时唯一站得住的口径是沿钩自己的切线平切——切口垂直于钩的走向，
    出来是干净的平头，而不是斜穿笔身的斜口。骨架环带 PCA 只在拿不到切线时兜底。
    """
    if removed is not None and len(removed) >= 3:
        window = max(3, int(0.2 * (width_px or 100)))
        a = np.array(removed[max(0, len(removed) - 1 - window)], dtype=float)
        b = np.array(removed[-1], dtype=float)
        vec = b - a
        norm = float(np.linalg.norm(vec))
        if norm > 1e-9:
            return float(vec[0] / norm), float(vec[1] / norm)
    rows, cols = np.nonzero(skeleton)
    dist2 = (rows - cut[0]) ** 2 + (cols - cut[1]) ** 2
    keep = (dist2 >= (0.9 * radius_px) ** 2) & (dist2 <= (2.2 * radius_px) ** 2)
    pts = np.stack([rows[keep], cols[keep]], axis=1).astype(float)
    if len(pts) < 12:
        return None
    centered = pts - pts.mean(axis=0)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    axis = vt[0] / (np.linalg.norm(vt[0]) or 1.0)
    return float(axis[0]), float(axis[1])


def trim_hooks(mask, skeleton=None, distance=None):
    """剪掉检出的钩并把端头补成圆头，返回（新掩膜, 剪除处数）。

    切法：过切点、按"存活笔身方向"的法线切一刀，只切笔尖侧、且限制在钩路径 1.4W 内
    （防止连带切掉同一字里挨得近的别的笔画）。补头用半圆头而不是整圆——整圆会在
    切点外侧鼓出一块，和笔身叠成蒜状，实测留下一串小圆点。

    不用"最近骨架像素归属"分墨：笔尖卷回来时钩那段的 Voronoi 区域会越过切点侵进主
    笔画，切出来的口子是个歪豁口（`心`/`必` 实测把收尾切断了）。
    """
    skeleton = skeletonize(mask) if skeleton is None else skeleton
    distance = ndimage.distance_transform_edt(mask) if distance is None else distance
    hooks = find_hooks(mask, skeleton, distance)
    if not hooks:
        return mask, 0
    rows, cols = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
    nearest = ndimage.distance_transform_edt(
        ~skeleton, return_indices=True, return_distances=False)
    erased = mask.copy()
    applied = 0
    for cut, removed, width_px in hooks:
        if len(removed) < 3:
            continue
        axis = _body_axis(skeleton, cut, 1.6 * width_px, removed, width_px)
        if axis is None:
            continue
        body_dir = axis

        # 钩的墨 = 最近骨架点落在被剪路径上（这样闭合折返的钩尖也跑不掉），
        # 但约束在切点附近，防止把笔身的墨一起算进来。
        tag = np.zeros(mask.shape, dtype=bool)
        for row, col in removed:
            tag[row, col] = True
        hook_ink = tag[nearest[0], nearest[1]]
        near = (rows - cut[0]) ** 2 + (cols - cut[1]) ** 2 <= (2.2 * width_px) ** 2
        # 笔身侧留一条半径宽的缓冲，避免切到笔身本体
        body_side = (rows - cut[0]) * body_dir[0] + (cols - cut[1]) * body_dir[1]
        # 切面就是过切点的法线平面：笔尖侧一律不留，笔身侧不动。这里留 0 而不是留
        # 缓冲，是因为钩在转角内侧时，留缓冲会把内角填平，出来是个"钝角 + 缺口"。
        erase = (body_side < 0.0) & near
        if not (erased & erase).any():
            continue
        erased = erased & ~erase
        # 圆头收尾（design-principles 2026-10-22：钩尾必须形成圆弧收头而不是平切）
        _cap(erased, cut, body_dir, float(distance[cut]), distance)
        applied += 1
    labels, count = ndimage.label(erased, structure=np.ones((3, 3), dtype=bool))
    if count > 1:
        sizes = ndimage.sum(erased, labels, range(1, count + 1))
        largest = float(sizes.max())
        keep = [i + 1 for i, size in enumerate(sizes) if size >= max(120.0, 0.06 * largest)]
        erased = np.isin(labels, keep)
    return erased, applied


def render_glyph_object(glyph, glyf_table, px=600, box=(-100, -100, 1100, 1100)):
    """按固定 em 网格渲染一个 glyf 字形，供前后对比。

    必须用固定网格而不是各自的外接框：重描后外接框会差一两个单位，按外接框归一化
    会把整字重新缩放，量出来的相似度全是假的。
    """
    from PIL import Image, ImageDraw

    from stroke_width_audit import FlattenPen, signed_area

    pen = FlattenPen({}, steps_per_curve=12)
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
    return (float((a & b).sum()) / union if union else 1.0,
            float(b.sum() - a.sum()) / max(1, int(a.sum())))
