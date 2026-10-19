"""渲染证据图用的小工具：给定若干个 TTF 字重实例 + 一串字符，画一张「字符(行) × 字重(列)」
的网格图，直接用 fontTools 的 glyf 轮廓转成 matplotlib Path 画出真实填充形状（不经过系统字体
渲染器，所以沙箱里没有 CJK 字体也能画——连行首的字符标签都是从字体自己的字形抠出来的，不依赖
matplotlib 默认字体库里有没有对应的 CJK 字形）。

背景：本仓库 `docs/evidence/README.md` 要求渲染层证据必须是截图/图像，不能只写"看起来没问题"；
这个脚本是"沙箱渲染证据"的标准生成方式之一，取代每次现场写一遍一次性渲染脚本。

用法：
    python3 tools/render_grid.py out.png NAME1=weight1.ttf NAME2=weight2.ttf ... -- 字符串

例：
    python3 tools/render_grid.py grid.png Light=w100.ttf Regular=w400.ttf Heavy=w900.ttf -- 乙也了回国

不传字符串时默认用本仓库常用的 13 字回归集（乙也了包囚回国子己已田电暖，带钩笔+方框两类代表字）。
"""
import sys
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.path import Path
from matplotlib.patches import PathPatch

DEFAULT_CHARS = "乙也了包囚回国子己已田电暖"


class MplPathPen(BasePen):
    """把 fontTools 的 draw() 调用转成 matplotlib 的 Path 顶点/指令序列。
    TrueType 的 qCurveTo 是二次贝塞尔（CURVE3），cubic 的 curveTo 是三次贝塞尔（CURVE4）；
    BasePen 已经把隐式 on-curve 中点展开好了，这里只管照抄点坐标，不用自己处理隐式点。
    """

    def __init__(self, glyphSet):
        super().__init__(glyphSet)
        self.verts = []
        self.codes = []

    def _moveTo(self, pt):
        self.verts.append(pt)
        self.codes.append(Path.MOVETO)

    def _lineTo(self, pt):
        self.verts.append(pt)
        self.codes.append(Path.LINETO)

    def _curveToOne(self, p1, p2, p3):
        self.verts.extend([p1, p2, p3])
        self.codes.extend([Path.CURVE4, Path.CURVE4, Path.CURVE4])

    def _qCurveToOne(self, p1, p2):
        self.verts.extend([p1, p2])
        self.codes.extend([Path.CURVE3, Path.CURVE3])

    def _closePath(self):
        self.verts.append((0, 0))
        self.codes.append(Path.CLOSEPOLY)


def glyph_path(font, gname):
    glyphSet = font.getGlyphSet()
    pen = MplPathPen(glyphSet)
    glyphSet[gname].draw(pen)
    return Path(pen.verts, pen.codes)


def draw_char(ax, font, ch, color="#222"):
    cmap = font.getBestCmap()
    if ord(ch) not in cmap:
        ax.text(0.5, 0.5, "?", ha="center", va="center")
        ax.axis("off")
        return
    gname = cmap[ord(ch)]
    path = glyph_path(font, gname)
    ax.add_patch(PathPatch(path, facecolor=color, edgecolor="none", lw=0))
    upm = font["head"].unitsPerEm
    ax.set_xlim(-100, upm + 100)
    ax.set_ylim(-250, upm - 50)
    ax.set_aspect("equal")
    ax.axis("off")


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        sys.exit(1)
    out_path = argv[1]
    rest = argv[2:]
    if "--" in rest:
        split = rest.index("--")
        specs = rest[:split]
        chars = "".join(rest[split + 1:]) or DEFAULT_CHARS
    else:
        specs = rest
        chars = DEFAULT_CHARS

    weights = []
    for spec in specs:
        name, path = spec.split("=", 1)
        weights.append((name, TTFont(path)))

    n_rows = len(chars)
    n_cols = len(weights) + 1  # 首列=字符标签（从参照字重自己的字形抠出来，不依赖系统 CJK 字体）
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(n_cols * 1.5, n_rows * 1.5))
    if n_rows == 1:
        axes = [axes]
    label_font = weights[0][1]
    for r, ch in enumerate(chars):
        ax = axes[r][0] if n_rows > 1 else axes[0]
        draw_char(ax, label_font, ch, color="#888")
        if r == 0:
            ax.set_title("char", fontsize=10)
        for c, (wname, font) in enumerate(weights):
            ax2 = axes[r][c + 1] if n_rows > 1 else axes[c + 1]
            draw_char(ax2, font, ch)
            if r == 0:
                ax2.set_title(wname, fontsize=10)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    print("saved ->", out_path)


if __name__ == "__main__":
    main(sys.argv)
