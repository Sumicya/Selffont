"""实验：检测并削掉"框形部首腿脚越出底横"的小凸脚（国/回/田/日/目/西 这类字实测都有，
越出量约 50-68 单位，是源字体里系统性的设计，不是圆角化引入的）。

结构：外框的竖笔（含转角）是一个大轮廓，一路通到比底横更低/更高的位置；底横是另一个
独立的小矩形轮廓（4 点，轴对齐）。检测：找一条长直竖边，它的端点恰好落在整个字形的
y 极值上（说明它是"伸到最远"的那条边），再找一个与它 x 范围重叠的独立小矩形轮廓，如果
矩形在同一方向的边界比这条竖边的端点更保守（没伸那么远），就判定竖边"越出"了，把它
缩回到矩形的边界。
"""
import math
from fontTools.ttLib import TTFont


def split_contours(coords, ends, flags):
    contours = []
    start = 0
    for end in ends:
        pts = [(float(coords[k][0]), float(coords[k][1]), bool(flags[k])) for k in range(start, end + 1)]
        contours.append(pts)
        start = end + 1
    return contours


def is_axis_rect(contour, tol=2.0):
    """4 个 on-curve 点，边轴对齐的矩形。"""
    onpts = [p for p in contour if p[2]]
    if len(onpts) != 4 or len(contour) != 4:
        return False
    xs = sorted(set(round(p[0]) for p in onpts))
    ys = sorted(set(round(p[1]) for p in onpts))
    if len(xs) != 2 or len(ys) != 2:
        return False
    return True


def find_overshoot(contours, min_edge_len=150, max_dx=5, min_overshoot=15, max_overshoot=150):
    """返回 {(contour_idx, point_idx): new_y} 的回缩计划。

    2026-10-15 续：原来要求"长竖边的端点必须碰到整个字形的全局 y 极值"——这个条件
    对"电"这类复杂字会漏判（电的箱体左边那一小截竖条脚，只比箱体底边多伸出 62 单位，
    但它不是全字形最深的点，全字形最深的是钩笔——卡在全局极值这道门槛上被漏掉了）；
    同时又会错判——"电"顶上那一竖本来就该伸到最高（字形里那一笔的正常设计，不是什么
    "脚"），但因为它确实是全局极值，又跟中间横杠 x 范围重叠，被误判成"越出"削掉了一截
    （360 单位的误判，比真正的脚越出量 50-68 单位大一个数量级）。
    改成两条更可靠的判据：① 只要求这条边的端点是它自己所在轮廓的局部极值（不用跟
    全字形比）；② 越出量必须落在 min_overshoot~max_overshoot 这个经验区间内（真正的
    脚越出 50-68 单位，电的顶竖误判出来是 360 单位——拉开上限就能把这类"路过、不是
    靠上去"的假阳性过滤掉，不靠"是不是全局最深"这种跟字形复杂度绑死的判据。
    """
    # 2026-10-15 再续：试过把参照物从"独立矩形轮廓"放宽成"任意轮廓里的水平墙边"，
    # 想顺带接住"电"箱体那种被穿过的竖笔打断成 8 点"C"形的情况——结果这个放宽太松，
    # "困"字内部"木"字根的顶点被误配到外框的内墙上，字形直接面目全非（变成了"不"）。
    # 退回只认"独立简单矩形轮廓"当参照，安全但会漏掉"电"这类复杂框——"电"的箱体脚
    # 先记为已知缺口，留到以后专门处理，不要为了接住一个字而让其它字冒风险。
    rects = []
    for ci, c in enumerate(contours):
        if is_axis_rect(c):
            xs = [p[0] for p in c]
            ys = [p[1] for p in c]
            rects.append((ci, min(xs), max(xs), min(ys), max(ys)))

    # 2026-10-15 三续：试过把"碰极值"的判据从"全字形"收窄成"轮廓自己"，想顺带接住
    # "电"箱体那只局部脚——结果引入了另一类假阳性："困/固/围"里"木"字根的竖笔本来就
    # 比旁边的横笔更高（竖笔顶在轮廓自己范围内自然是极值，但在全字形范围内并不极端），
    # 被误判成"越出"削掉一截，字形变形（"困"变成了"不"）。这类"穿过去的笔画"跟真正
    # 的"脚"在"轮廓自己的极值"这个判据下无法区分，但在"全字形极值"判据下能区分——
    # 真正的脚本来就是全字形里伸得最远的那批笔画。改回按全字形极值判，配合越出量上限
    # （见 max_overshoot）一起过滤假阳性，"电"箱体那只局部脚先记为已知缺口。
    all_y = [p[1] for c in contours for p in c]
    glyph_min_y, glyph_max_y = min(all_y), max(all_y)

    plan = {}
    for ci, c in enumerate(contours):
        n = len(c)
        for k in range(n):
            x1, y1, on1 = c[k]
            x2, y2, on2 = c[(k + 1) % n]
            if not (on1 and on2):
                continue
            dx, dy = abs(x2 - x1), abs(y2 - y1)
            if dx > max_dx or dy < min_edge_len:
                continue  # 不是长直竖边
            # 看这条边是否触达整字形的 y 极值（上下各判一次），30 单位容差：同一个
            # 字形左右两条腿伸出深度不一定完全相等。
            for extreme, idx_at_extreme in (
                (glyph_min_y, k if y1 < y2 else (k + 1) % n),
                (glyph_max_y, k if y1 > y2 else (k + 1) % n),
            ):
                py = c[idx_at_extreme][1]
                if abs(py - extreme) > 30:
                    continue  # 30 单位容差：同一轮廓里两条腿伸出深度不一定完全相等
                px = c[idx_at_extreme][0]
                is_bottom = (extreme == glyph_min_y)
                # 找一个 x 范围重叠、且在该方向上比这条边保守的独立矩形
                best_bound, best_dist = None, None
                for rci, rxmin, rxmax, rymin, rymax in rects:
                    if rci == ci:
                        continue
                    if not (rxmin - 5 <= px <= rxmax + 5):
                        continue
                    bound = rymin if is_bottom else rymax
                    overshoot = (bound - extreme) if is_bottom else (extreme - bound)
                    if not (min_overshoot < overshoot < max_overshoot):
                        continue  # 越出量不在"小脚"的经验区间内，大概率是穿过去的
                        # 笔画而不是靠上去的脚（电的顶竖误判出来是 360 单位，远超
                        # 这个上限），不当越出处理。
                    dist = abs(bound - extreme)
                    if best_dist is None or dist < best_dist:
                        best_bound, best_dist = bound, dist
                if best_bound is not None:
                    plan[(ci, idx_at_extreme)] = (best_bound, py)  # py: 这个点自己的原始 y
                    # （不是全局极值 extreme）——后面"扩展到同一轮廓里同一高度的
                    # 其它点"要按这个点自己的实际高度去配对兄弟点，用全局极值配对
                    # 会在左右腿伸出深度不完全相等时把另一条腿漏掉（"日"字左右腿
                    # 分别伸到 -69/-64，相差 5 单位，复现过）。
    # 同一轮廓里，跟已确认越出脚的那个点共享同一条原始极值 y 的其它点（比如同一条
    # 脚两侧的外沿/内沿），即使它们自己的 x 没有落在参照矩形范围内，也当成同一个
    # "脚"的一部分一起缩回去——脚的两条边理应一起动，不能只缩一侧留一侧参差不齐。
    extended = dict(plan)
    for (ci, idx), (new_y, orig_extreme) in list(plan.items()):
        c = contours[ci]
        for pi, (x, y, on) in enumerate(c):
            if not on or (ci, pi) in extended:
                continue
            if abs(y - orig_extreme) < 1:
                extended[(ci, pi)] = (new_y, orig_extreme)
    return {k: v[0] for k, v in extended.items()}


def find_cap_skip_points(contours, plan):
    """2026-10-15 六续：贴平只解决了"坐标对不对得上"，没解决"这个端头还会不会被
    vf_round.py 的自由端头圆化逻辑当成独立笔画鼓一个包"——复现过（电）：contour3
    这整条左侧竖条其实贯穿箱体整个高度（是箱体左墙的一部分，只是单独成一个轮廓），
    上下两头原本就各自贴着箱体的上下边界（下端贴平前有越出，上端本来就是 0 越出，
    一直都贴着），但 vf_round.py 的"是否已被同一字形里别的轮廓盖住"探测只探"紧贴着
    这一步"，这条竖条比箱体本身更往外凸出一截，探测点正好落在箱体之外的缝隙里，于是
    判定"没被盖住、是自由端头"，上下两头各自独立鼓了一个包——贴平只修了坐标，没有
    同时告诉圆角逻辑"这两头不是自由端头,原样留着"。

    这里只对"已经被 find_overshoot/find_overshoot_extra 确认过是脚"的轮廓，额外检查
    它另一头是不是也贴着（或贴平后已经贴着）某个参照矩形——贴着就一并标成"端头圆化
    排除点"，连同已经贴平的那一头一起，交给 vf_round.py 跳过自由端头圆化。不对任何
    没被原判据碰过的轮廓做新的匹配尝试，范围跟原判据完全一致，不引入新的误判面。
    """
    touched_cids = {ci for (ci, _pi) in plan.keys()}
    if not touched_cids:
        return set()

    rects = []
    for ci, c in enumerate(contours):
        if is_axis_rect(c):
            xs = [p[0] for p in c]
            ys = [p[1] for p in c]
            rects.append((ci, min(xs), max(xs), min(ys), max(ys)))
        else:
            nr = _is_notched_rect(c)
            if nr is not None:
                rects.append((ci, nr[0], nr[1], nr[2], nr[3]))

    skip = set(plan.keys())
    near_zero = 8  # 容差：贴平后应该正好对齐，留一点浮点/取整余量
    found_this_pass = set()
    for ci in touched_cids:
        c = contours[ci]
        n = len(c)
        if n != 4 or not is_axis_rect(c):
            continue  # 范围跟 find_overshoot_extra 一致：只处理独立简单矩形轮廓
        for k in range(n):
            x1, y1, on1 = c[k]
            x2, y2, on2 = c[(k + 1) % n]
            if not (on1 and on2) or abs(x2 - x1) > 5 or abs(y2 - y1) < 150:
                continue
            for idx_at_extreme, is_bottom in (
                (k if y1 < y2 else (k + 1) % n, True),
                (k if y1 > y2 else (k + 1) % n, False),
            ):
                if (ci, idx_at_extreme) in skip:
                    continue  # 已经在贴平计划里，不用再查
                px, py = c[idx_at_extreme][0], c[idx_at_extreme][1]
                for rci, rxmin, rxmax, rymin, rymax in rects:
                    if rci == ci or not (rxmin - 5 <= px <= rxmax + 5):
                        continue
                    bound = rymin if is_bottom else rymax
                    if abs(bound - py) <= near_zero:
                        found_this_pass.add((ci, idx_at_extreme, py))
                        break
    # 跟 find_overshoot()/find_overshoot_extra() 同样的道理：同一条端边的另一侧点，
    # 哪怕自己的 x 没落在参照矩形范围内（比如这条竖条比箱体更往外凸出一截，外侧那
    # 一点的 x 够不着箱体），也要跟着一起排除——端边两头理应同生共死，不能一头排除
    # 圆化、另一头还留着独自鼓包。
    for (ci, idx, py) in found_this_pass:
        skip.add((ci, idx))
        c = contours[ci]
        for pi, (x, y, on) in enumerate(c):
            if not on or (ci, pi) in skip:
                continue
            if abs(y - py) < 1:
                skip.add((ci, pi))
    return skip


def _is_notched_rect(contour, tol=2.0):
    """识别"被穿过的竖笔打断成一个缺口"的外框轮廓（电的箱体、困/固/围等字外框那种
    8 点轮廓：本该是个简单矩形，但有一条边被劈成两段、中间让出一截给穿过去的竖笔）。
    只认最常见的这种拓扑：8 个点，全部轴对齐直线相连，整体是一个"凸矩形缺一个角的
    豁口"形状。命中就返回它的外接矩形（当成一个"虚拟简单矩形"，给下面这道新的安全
    判据当参照用）——不改变、不影响 find_overshoot() 原来那条已经验证过安全的主判据，
    只是多给它提供一个可以匹配的参照对象。"""
    onpts = [p for p in contour if p[2]]
    if len(onpts) != 8 or len(contour) != 8:
        return None
    xs = [round(p[0]) for p in onpts]
    ys = [round(p[1]) for p in onpts]
    for k in range(8):
        x1, y1 = xs[k], ys[k]
        x2, y2 = xs[(k + 1) % 8], ys[(k + 1) % 8]
        if abs(x1 - x2) > tol and abs(y1 - y2) > tol:
            return None  # 不是轴对齐折线，不是这个拓扑
    return (min(xs), max(xs), min(ys), max(ys))


def find_overshoot_extra(contours, base_plan, min_overshoot=15, max_overshoot=150,
                          cross_reject=100, min_edge_len=150, max_dx=5):
    """2026-10-15 五续：find_overshoot() 要求"长竖边必须碰到整个字形的全局 y 极值"，
    这条安全线对"电"这类字会漏判——电的箱体被竖笔穿过打断成 8 点缺口轮廓（不是简单
    矩形，进不了参照矩形表），箱体左下角那一小截竖条脚本身也不是全字形最深的点（全
    字形最深的是钩笔）。两道门槛叠在一起，这一个真实存在的小脚就被漏掉了。

    这里作为独立的第二遍补充检测，只做一件很窄的事，不碰 find_overshoot() 一个字符：
    只看"本身就是独立简单矩形轮廓"的那些轮廓（比如电的左侧竖条，electron 本身 4 点
    成一个窄矩形）——复杂轮廓（比如困里"木"的竖笔所在轮廓，或者任何带转角的外框）一律
    不碰，从拓扑上就跟"困"字那次假阳性（轮廓本身不是独立矩形，是带转角的笔画主体）
    划清界限，不需要再找别的办法去区分"真脚"和"穿过去的笔画"。

    参照对象只用 _is_notched_rect() 识别出的"缺口外框"外接矩形（专门为电这类箱体补的）。

    2026-10-16 续：原来参照对象里还包含了普通独立矩形（跟 find_overshoot() 的参照表
    共用），本意是"以防万一"多一层覆盖，注释里写"这类误判的真实样本目前还没出现过"——
    结果在固字 Heavy 字重上真的出现了：固的部首"古"里，"十"的横笔和竖笔各自都是独立
    4 点矩形，竖笔下端本来就该比横笔下端更低一些（十字交叉笔画的正常写法，两笔分别
    露出一截），但竖笔矩形跟横笔矩形的 x 范围重叠、越出量在粗字重下恰好落进 15~150
    这个"小脚"经验区间，被误判成"脚越出"，把竖笔下端整个削掉一截，字形崩坏（复现：
    固 Heavy 权重，(1,2)/(1,3) 两点被错误地从 y=329 改到 y=458）。跟"困"字那次假阳性
    同一类问题：普通矩形笔画互相交叉是常态，用"普通矩形"当参照物区分不出"交叉"和
    "脚"。这道额外检测本来就只为"电"这种被穿过的箱体（notched rect）补漏，参照对象
    收紧成只认 notched rect，不再用普通独立矩形互相参照，能保留电的修复，同时排除
    固这类交叉笔画的误判。"""
    rects = []
    simple_rect_cids = set()
    for ci, c in enumerate(contours):
        if is_axis_rect(c):
            simple_rect_cids.add(ci)
        else:
            nr = _is_notched_rect(c)
            if nr is not None:
                rects.append((ci, nr[0], nr[1], nr[2], nr[3]))

    def best_match(exclude_ci, px, extreme_y, is_bottom, lo, hi):
        """返回 (bound, matched_rci)：离 extreme_y 最近、越出量落在 (lo,hi) 区间内的
        参照矩形，连同是"哪一个"矩形一起返回——交叉检查要用同一个矩形去查对面那头，
        不能随便抓一个不相干的矩形就说"越出了"（电实测复现过：中间那道横杠(contour0)
        恰好跟箱体脚的两头都够得上"越出"的判据，被当成了不相干的"交叉证据"，把真正的
        脚也一起否掉了——必须锁定"同一个矩形"才算数）。"""
        best = None
        for rci, rxmin, rxmax, rymin, rymax in rects:
            if rci == exclude_ci:
                continue
            if not (rxmin - 5 <= px <= rxmax + 5):
                continue
            bound = rymin if is_bottom else rymax
            overshoot = (bound - extreme_y) if is_bottom else (extreme_y - bound)
            if not (lo < overshoot < hi):
                continue
            dist = abs(bound - extreme_y)
            if best is None or dist < best[2]:
                best = (bound, rci, dist)
        return (best[0], best[1]) if best else (None, None)

    def overshoot_against(rci, px, extreme_y, is_bottom):
        for rci2, rxmin, rxmax, rymin, rymax in rects:
            if rci2 != rci:
                continue
            if not (rxmin - 5 <= px <= rxmax + 5):
                continue
            bound = rymin if is_bottom else rymax
            return (bound - extreme_y) if is_bottom else (extreme_y - bound)
        return None

    plan = {}
    for ci in simple_rect_cids:
        c = contours[ci]
        n = len(c)
        if n != 4:
            continue
        for k in range(n):
            x1, y1, on1 = c[k]
            x2, y2, on2 = c[(k + 1) % n]
            if not (on1 and on2) or abs(x2 - x1) > max_dx or abs(y2 - y1) < min_edge_len:
                continue
            bottom_idx = k if y1 < y2 else (k + 1) % n
            top_idx = k if y1 > y2 else (k + 1) % n
            bottom_y, bottom_x = c[bottom_idx][1], c[bottom_idx][0]
            top_y, top_x = c[top_idx][1], c[top_idx][0]
            if (ci, bottom_idx) in base_plan or (ci, top_idx) in base_plan:
                continue  # 已经被原来那条安全判据处理过，不重复/不冲突
            for extreme_y, extreme_x, idx_at_extreme, is_bottom in (
                (bottom_y, bottom_x, bottom_idx, True),
                (top_y, top_x, top_idx, False),
            ):
                bound, matched_rci = best_match(ci, extreme_x, extreme_y, is_bottom, min_overshoot, max_overshoot)
                if bound is None:
                    continue
                # 交叉检查：只看"这条边的另一头"相对"同一个刚匹配上的矩形"越出了多少，
                # 不去看别的不相干矩形——越出一大截（> cross_reject）说明这条边其实是
                # 穿过这同一个矩形的笔画主体，不是靠在它外面的脚。
                opp_y, opp_x = (top_y, top_x) if is_bottom else (bottom_y, bottom_x)
                opp_overshoot = overshoot_against(matched_rci, opp_x, opp_y, not is_bottom)
                if opp_overshoot is not None and opp_overshoot > cross_reject:
                    continue
                plan[(ci, idx_at_extreme)] = (bound, c[idx_at_extreme][1])
    # 同一窄矩形轮廓里，跟已匹配上的那个点共享同一条原始 y 的另一侧点（比如电那根窄
    # 竖条，两条边里只有靠箱体那一侧的 x 落在箱体范围内，另一侧 x 在箱体外面、匹配
    # 不上，但两侧理应一起缩回去，不能只削一边留一边参差不齐）——用法跟 find_overshoot()
    # 里同一段注释说的是同一个道理。
    extended = dict(plan)
    for (ci, idx), (new_y, orig_y) in list(plan.items()):
        c = contours[ci]
        for pi, (x, y, on) in enumerate(c):
            if not on or (ci, pi) in extended:
                continue
            if abs(y - orig_y) < 1:
                extended[(ci, pi)] = (new_y, orig_y)
    return {k: v[0] for k, v in extended.items()}


def apply_trim(glyph, glyf_table, plan):
    if not plan:
        return 0
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    contours = split_contours(coords, ends, flags)
    made = 0
    for (ci, pi), new_y in plan.items():
        x, y, on = contours[ci][pi]
        contours[ci][pi] = (x, new_y, on)
        made += 1
    # flatten back
    from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
    flat = []
    new_ends = []
    for c in contours:
        flat.extend(c)
        new_ends.append(len(flat) - 1)
    glyph.coordinates = GlyphCoordinates([(int(round(x)), int(round(y))) for x, y, on in flat])
    glyph.flags = [bool(on) for _, _, on in flat]
    glyph.endPtsOfContours = new_ends
    glyph.recalcBounds(glyf_table)
    return made


if __name__ == "__main__":
    import json
    import sys
    f = TTFont(sys.argv[1])
    glyf = f["glyf"]
    cmap = f.getBestCmap()
    skip_caps_path = sys.argv[3] if len(sys.argv) > 3 else None
    skip_caps_out = {}
    total = 0
    for ch in "电国回田日目西固困园圆围":
        if ord(ch) not in cmap:
            continue
        gname = cmap[ord(ch)]
        g = glyf[gname]
        coords, ends, flags = g.getCoordinates(glyf)
        contours = split_contours(coords, ends, flags)
        plan = find_overshoot(contours)
        extra = find_overshoot_extra(contours, plan)
        plan.update(extra)
        if plan:
            skip = find_cap_skip_points(contours, plan)
            if skip:
                skip_caps_out[gname] = sorted(list(p) for p in skip)
            made = apply_trim(g, glyf, plan)
            print(f"{ch} ({gname}): trimmed {made} point(s): {plan}")
            total += made
        else:
            print(f"{ch} ({gname}): no overshoot found")
    f.save(sys.argv[2])
    print("total trims:", total, "-> saved", sys.argv[2])
    if skip_caps_path:
        with open(skip_caps_path, "w") as fp:
            json.dump(skip_caps_out, fp, ensure_ascii=False, indent=1)
        print("skip-caps written ->", skip_caps_path)
