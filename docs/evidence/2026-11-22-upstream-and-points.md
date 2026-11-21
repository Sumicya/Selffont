# 上游查证与点数更正 2026-11-22

## 一、Zen Maru Gothic 上游有什么（查证结论）

`github.com/googlefonts/zen-marugothic`，18 个提交，最后一次 2024-08-02。

| 目录 | 内容 |
|---|---|
| `sources/` | `BASE-{Black,Bold,Light,Medium}.ttx`、`ZenMaruGothic.zip`（含 `.glyphs` 与 `.designspace`） |
| `fonts/ttf/` | 成品 TTF |
| `build.py` | 90 行，只做格式转换 |

`build.py` 全流程：
```
.glyphs → glyphs2ufo → ZenMaruGothic.designspace → ufo2ft.compileTTF
         (removeOverlaps=True, overlapsBackend="pathops") → ttf
```

**上游没有笔形生成代码，没有中线数据，没有描边算法。** 字形是人工设计的贝塞尔轮廓，
`build.py` 只做编译。所以「照抄上游的描边代码」不存在这条路。

上游唯一的机制是 **pathops 布尔去重叠**——`requirements.txt` 里的 `skia-pathops` 就是它。
这与 `docs/design-principles.md:13` 的结论一致：「合并笔画要用保留曲线的布尔运算（pathops），
不要重新采样」。

## 二、点数更正（上一轮报错了）

上一轮我报「本版点数是母版 5.24 倍」。**那个数算的是描边前的密点，不是最终轮廓点数。**

实际（`長`，逐笔）：

| 笔 | 描边密点 | 经 curve_fit 后 |
|---|---|---|
| 0 | 443 | 67 |
| 1 | 128 | 15 |
| 2 | 128 | 16 |
| 3 | 128 | 20 |
| 4 | 188 | 33 |
| 5 | 82 | 19 |
| 合计 | 1097 | **170** |

母版 `長` = **177 点**。拟合后 **170**，比母版还少 7 个。

所以「点数 1.49 倍」（README:379）不是最终轮廓点数问题。这一项作废。

## 三、本轮试过并否掉的改法

1. `_stations` 近直段不按长度切（`STRAIGHT_RATIO`）——`build.py --check` 的 `cjk_font`
   断言立刻拦下：`法` 收笔端直线段 2/3 超一半，端头成多边形。已撤回，0.001–0.05 五个阈值全失败。
   原因：把中线切稀之后 `curve_fit._max_off_line` 反而判成曲线，机制走反了。
2. `ENDPOINT_TANGENT=ring`——40 字点数 301→316，更多点，不要。
3. `CAP_SQUASH` / `CAP_SHARP`（上一轮记录）——三种子复核全线变差，默认保持关闭。

`curve_fit.py` 里 `_max_off_line(pts) <= LINE_TOL (0.12)` → 直接返回一条 `line`、
「一个点都不多给」的机制**本来就是对的**，不需要改。

## 四、当前状态
`build.py --check --only cjk_font` = **PASS**。
`tools/design_cjk.py` 未纳入 git（工作区文件），本轮的探针脚本都在 /tmp。
