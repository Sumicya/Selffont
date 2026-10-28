"""几何正确性自检：给定若干 TTF 字重实例 + 一串字符，逐轮廓检测有没有自交（同一条轮廓自己
穿过自己）。自交在可变字体插值/光栅化时会产生意料之外的镂空或毛刺，是"笔画简化"类改动（挪动
锚点、削圆角、合并拐角）最容易引入的真实回归，不能只靠"看起来没问题"。

注意：只检查"单条轮廓自身是否自交"，不检查"同一字形内多条轮廓是否互相重叠"——本仓库的字形
构造手法里，笔画之间刻意用多条轮廓重叠（配合 TrueType 的非零环绕填充规则）来拼出一笔到底的
连续转折（例如 `tools/le_slant.py` 处理过的"了"字顶部转角），这是设计意图，不是 bug。

两类结果分开报，不混为一谈（2026-10-24 修）：
- `FAIL`：轮廓真的自交（shapely 报 `Self-intersection[坐标]`），是改字引入的真实回归。
- `degenerate`：不同点数少于 3 的零面积残留轮廓，shapely 报的是 `Too few points`，
  根本连一个环都构不成，跟自交无关。上游自动描摹字体里就存在这种残留（实测 Maruko SC
  Regular 33,751 个有轮廓字形里有 7 个字形各带一条 2 点轮廓）；此前把这类也算成 FAIL，
  导致曲线重拟合的审计里凭空多出 7 个"新自交候选"。它只打印、不算失败，但必须打印出来
  ——静默跳过会让"源字体本来就带零面积残留"这件事在审计里看不见。

用法：
    python3 tools/check_self_intersect.py w1.ttf w2.ttf ... -- 字符串

不传字符串时默认用本仓库常用的 13 字回归集。退出码非 0 只由真自交决定；零面积残留轮廓
打印 `degenerate` 行但不让退出码变红。
"""
import sys
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen
import shapely.geometry as sg
from shapely.validation import explain_validity

DEFAULT_CHARS = "乙也了包囚回国子己已田电暖"


class FlattenPen(BasePen):
    """把轮廓压平成折线点序列，贝塞尔曲线按固定步数采样，供 shapely 做自交检测。"""

    def __init__(self, glyphSet, steps=24):
        super().__init__(glyphSet)
        self.contours = []
        self._cur = []
        self._steps = steps

    def _moveTo(self, pt):
        self._cur = [pt]

    def _lineTo(self, pt):
        self._cur.append(pt)

    def _curveToOne(self, p1, p2, p3):
        p0 = self._cur[-1]
        n = self._steps
        for i in range(1, n + 1):
            t = i / n
            mt = 1 - t
            x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
            y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
            self._cur.append((x, y))

    def _qCurveToOne(self, p1, p2):
        p0 = self._cur[-1]
        n = self._steps
        for i in range(1, n + 1):
            t = i / n
            mt = 1 - t
            x = mt**2 * p0[0] + 2 * mt * t * p1[0] + t**2 * p2[0]
            y = mt**2 * p0[1] + 2 * mt * t * p1[1] + t**2 * p2[1]
            self._cur.append((x, y))

    def _closePath(self):
        if self._cur:
            self.contours.append(self._cur)
        self._cur = []


def check_glyph(font, gname):
    """返回 ``(自交轮廓序号, 零面积残留轮廓序号)``，两类分开，见文件头说明。"""
    glyphSet = font.getGlyphSet()
    pen = FlattenPen(glyphSet)
    glyphSet[gname].draw(pen)
    problems = []
    degenerate = []
    for ci, pts in enumerate(pen.contours):
        if len(pts) < 3 or len(set(pts)) < 3:
            degenerate.append(ci)
            continue
        try:
            poly = sg.Polygon(pts)
        except ValueError:
            degenerate.append(ci)
            continue
        if not poly.is_valid:
            # `Too few points` 是"构不成环"，不是穿越；其余（Self-intersection 等）才算自交。
            if explain_validity(poly).startswith("Too few points"):
                degenerate.append(ci)
            else:
                problems.append(ci)
    return problems, degenerate


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        sys.exit(1)
    rest = argv[1:]
    if "--" in rest:
        split = rest.index("--")
        specs = rest[:split]
        chars = "".join(rest[split + 1:]) or DEFAULT_CHARS
    else:
        specs = rest
        chars = DEFAULT_CHARS

    any_fail = False
    for spec in specs:
        name = spec
        font = TTFont(spec)
        cmap = font.getBestCmap()
        for ch in chars:
            if ord(ch) not in cmap:
                print(f"{name}: {ch} missing from cmap, skip")
                continue
            gname = cmap[ord(ch)]
            problems, degenerate = check_glyph(font, gname)
            if problems:
                any_fail = True
                print(f"FAIL {name}: {ch} ({gname}) self-intersects in contour(s) {problems}")
            elif degenerate:
                print(f"degenerate {name}: {ch} ({gname}) zero-area contour(s) {degenerate}")
            else:
                print(f"ok   {name}: {ch} ({gname})")
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main(sys.argv)
