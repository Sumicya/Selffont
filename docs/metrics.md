# 五条判据的量具与基准

**基准 = 母版直通**。直通版本的 CJK 字件就是母版文件的同一串字节
（`MarukoGothicCJKsc-Regular.ttf`，20,084,736 B，`sha256 e3709389…f47241b7`，
来源 `max32002/maruko-gothic@97e9dd4` blob `63d79a45…6c0391147c`），不改轮廓、不改名，
只做挂载与配置。所以它的五条读数就是「母版 vs 母版」那一行：

| 判据 | 基准值 | 说明 |
| --- | --- | --- |
| 1 逐字轮廓距离（3,500 字，四方向 Hausdorff） | P50 0 · P90 0 · P99 0 | 同一份字节，距离恒 0 |
| 2 笔画宽度 \|比值−1\| | 竖 P50/P90/P95 = 0 / 0 / 0；横同 | 同上 |
| 3 侧距 \|diff\|≤20 单位占比 | lsb 100% · advance 100% | 同上 |
| 4 曲线连续性（接点切向跳变，>60° 角点排除） | 中位 4.361° · P90 5.816° · 差值 0.000° | 这就是母版自身的口径值 |
| 5 渲染对照 | `docs/evidence/2026-10-31-metrics-baseline-pass.png` | 12 / 16 / 24 px，20 字，3× 最近邻 |

尺子自洽的证明：同一把尺量同一份文件，五条全部落在 0（`--baseline`）。
任何改动都对着这一行报「改前 → 改后」，不对着观感词报。

## 复算命令

```sh
# 基准（母版 vs 母版）
.venv/bin/python tools/metrics.py --baseline \
    --mother build/mother/MarukoGothicCJKsc-Regular.ttf \
    --chars 3500字.txt --limit 3500

# 本版（先出 3,500 字子集，不跑全量）
.venv/bin/python build.py --preview "$(cat 3500字.txt)" --preview-out build/metrics/ours3500
.venv/bin/python tools/metrics.py \
    --ours build/metrics/ours3500/preview.ttf \
    --mother build/mother/MarukoGothicCJKsc-Regular.ttf \
    --chars 3500字.txt --limit 3500 \
    --render docs/evidence/<日期>-metrics-12-16-24.png --json build/metrics/ours.json

# 4× 局部放大图：按第 4 条逐字跳变均值挑最差 5 字，96 px 渲染、裁墨迹、4× 最近邻、宽 ≤900
.venv/bin/python tools/metrics.py \
    --ours build/metrics/ours3500/preview.ttf \
    --mother build/mother/MarukoGothicCJKsc-Regular.ttf \
    --chars 3500字.txt --limit 3500 \
    --worst-jumps 5 --pixel-zoom docs/evidence/<日期>-worst-pixel.png
```

字表：GB2312 一级字库前 3,500 字（`一丁七万丈三上下不与…`），按码位升序。

## 本版读数（3,500 字，2026-10-31 默认路径）

| 判据 | 本版 | 相对母版 |
| --- | --- | --- |
| 1 轮廓距离 P50 / P90 / P99 | 14.0 / 44.2 / 97.4 | +14.0 / +44.2 / +97.4 |
| 2 竖笔 \|比值−1\| P50 / P90 / P95 | 0.000 / 0.0625 / 0.0667 | — |
| 2 横笔 \|比值−1\| P50 / P90 / P95 | 0.000 / 0.0667 / 0.0714 | — |
| 3 lsb ≤20 / advance ≤20 | 99.57% / 100% | （lsb P50 3.0、P90 9.0） |
| 4 接点跳变 中位 / P90 | 9.554° / 10.854° | **+5.193° / +5.038°** |

渲染对照 `docs/evidence/2026-10-31-metrics-12-16-24.png`，
4× 局部放大 `docs/evidence/2026-10-31-metrics-worst-pixel.png`。

## 逐轮单变量：端点切向（2026-10-31）

一次只动一个变量。本轮动的就是端点切向的来源（`tools/curve_fit.py` 的
`ENDPOINT_TANGENT`，环境变量 `SELFFONT_ENDPOINT_TANGENT`）：

- **改前（`segment`）**：段内取三点定圆；段内点不足 6 个就退回**弦方向**。
- **改后（`ring`）**：在整条密点环上取端点两侧邻点定圆，与这一段被切成多长无关。

事先定死的合取判据：④ 中位下降 ≥1.0°、④ P90 不上升、① 变化 ≤±1.0、③ ≥99.5%。
“①变化”用 P50 判（P50 是本版与母版距离的中位，最稳）。

| 判据 | 判据线 | 改前 | 改后 | 变化 | 是否通过 |
| --- | --- | --- | --- | --- | --- |
| 4 接点跳变 中位 | 降 ≥1.0° | 9.554° | 8.127° | **−1.427°** | 通过 |
| 4 接点跳变 P90 | 不上升 | 10.854° | 9.410° | −1.444° | 通过 |
| 1 轮廓距离 P50 | \|Δ\| ≤1.0 | 14.000 | 14.293 | +0.293 | 通过 |
| 1 轮廓距离 P90（附带） | — | 44.202 | 46.275 | **+2.073** | 未计入判据，但方向是变差 |
| 3 lsb \|diff\|≤20 占比 | ≥99.5% | 99.57% | 99.40% | **−0.17 pp** | **不通过** |
| 2 竖笔 P95（附带） | — | 0.0667 | 0.1111 | +0.0444 | 变差 |
| 2 横笔 P95（附带） | — | 0.0714 | 0.1333 | +0.0619 | 变差 |

**结论：假设部分成立、作为变更作废。** 跳变确实降了 1.427°（且 P90 同降），但代价是
轮廓距离 P90 涨 2.07 单位、lsb 合格率跌破 99.5% 线、两条笔宽 P95 都变差。四条判据是
合取，③ 一条不过就不采用。代码里默认仍是 `segment`，`ring` 只作为可复算的开关保留；
上面这张表就是「不采用」的依据，不是「还没试」。

4× 局部放大图（改后版本，最差 5 字 兴/锌/辩/诛/篱）：
`docs/evidence/2026-10-31-metrics-true-worst-pixel.png`。

## 口径写死的地方

- 距离单位一律 **em 的 1/1000**；本版与母版各自按自身 `unitsPerEm` 归一到 1000 再比。
- 二次曲线展开按 TrueType 规范处理连续 off 控制点（相邻控制点中点即隐含 on 点）。
  2026-10-31 那轮 `te` 宽 46 单位，根因就是这一步写错——现在写进量具并有变异测试。
- 笔宽用 FreeType 栅格（256 px/em）量游程中位，不用自制渲染器：
  `docs/design-principles.md` 2026-10-28 那条。
- 曲线连续性排除 >60° 的接点（直角、锐角是设计）；母版与本版用同一口径，差值才有意义。

## 局部诊断：篱·竹头（2026-10-31）

主人原话「头不够圆（篱·竹头两端与折角偏方），其他未看出」。这一节把它拆成两个可算的量，
只量 `篱` 一个字、只看 bbox 上半部分，不改任何字形。

- **区域**：`篱` 的 bbox 上半部分 = x [58.6, 954.0]、y [383.2, 855.1]（字体单位 /1000 em，
  坐标取自本版 bbox）。
- **① 区域接点跳变**：第 4 条同口径（> 60° 当角点排除），但**只算同一条轮廓内**的接点——
  全库那把尺把所有环拼成一条点列，环与环之间的假接点会被算进去，区域内本来没有这种接点。
- **② 端头半径**：两横共 4 个端，左端合并进撇、没有端面（h≈0），实际的端头只有 2 个。
  量端面高度 h(d)（离端点 d 单位处墨迹的竖向高），按圆弧关系 **R = h(d)²/(8d)** 折成半径，
  取 d = 2 单位（笔厚的 1/27）。
- **③ 折角半径**：横与竖相接的凹角，数「空象限」里多出来的墨（折点右下方 34×34 单位的方块），
  按圆角面积 **A = r²(1−π/4)** 反解半径。尖角那里是纯空气，A ≈ 0。

| 量（篱·竹头） | 母版 | 改前（默认 `segment`） | 改后（`ring` 实验） | 改前→改后 |
| --- | --- | --- | --- | --- |
| 区域接点数 | 92 | 159 | 169 | +10 |
| ① 区域接点 中位 | 0.81° | **11.89°** | 8.24° | −3.65° |
| ① 区域接点 P90 | 12.99° | 23.13° | 23.05° | −0.08° |
| ① 与母版增量（中位） | — | **+11.08°** | +7.43° | −3.65° |
| ② 端头半径 P50 / P90（2 个自由端） | 25.9 / 29.3 | 25.6 / 26.2 | 25.6 / 26.2 | 0 / 0 |
| ② 端头半径（逐个） | 30.2 · 21.5 | 26.3 · 25.0 | 26.3 · 25.0 | — |
| ③ 折角半径 P50 / P90（2 个凹角） | 21.9 / 24.0 | **15.1 / 15.1** | 10.0 / 10.8 | −5.1 / −5.7 |
| ③ 折角半径（逐个） | 24.5 · 19.3 | 15.0 · 15.1 | 9.0 · 11.0 | — |

**读法**：

- **端头量不出来**。母版 25.9、本版 25.6，差 0.3 单位 = 笔厚的 0.55%——比这把尺的重复性还小。
  上一轮那张局部图是 96 px 渲染 + 4× 最近邻，圆角在 96 px 下只有 2–3 px，放大 4 倍看到的是
  像素方块。**所以局部图从本轮起一律 1× 出图**（`tools/hires_render.py`，整字墨迹高 ≥400 px、
  宽 ≤1200、零重采样）。
- **折角是真的**。本版 15.1 比母版 21.9 小 31%，也就是同样一个凹角，母版用半径 22 的圆角
  过渡，本版只用 15——这一处确实「方」。而 `ring` 实验把它变得更小（10.0），
  **第 4 条却变好了**：第 4 条把 >60° 的接点当角点排除，折角越圆、被计入的小角度接点越多，
  指标反而上升。**折角不能拿第 4 条验收。**

复算：

```sh
.venv/bin/python tools/zhutou.py --char 篱 \
    --mother build/mother/MarukoGothicCJKsc-Regular.ttf \
    --ours build/metrics/ours3500/preview.ttf \
    --alt build/metrics/ours3500-true/preview.ttf \
    --json build/metrics/zhutou.json

# 1× 高清对照（不放大）：整字 512 px em、竹头裁切 1024 px em
.venv/bin/python tools/hires_render.py --char 篱 --em 512 \
    --font build/mother/MarukoGothicCJKsc-Regular.ttf \
    --font build/metrics/ours3500/preview.ttf \
    --label 母版 --label 本版 --out docs/evidence/2026-10-31-metrics-hires-512.png
.venv/bin/python tools/hires_render.py --char 篱 --em 1024 --crop 58,383,954,856 \
    --font build/mother/MarukoGothicCJKsc-Regular.ttf \
    --font build/metrics/ours3500/preview.ttf \
    --label 母版 --label 本版 --out docs/evidence/2026-10-31-metrics-zhutou-crop.png
```

图：`docs/evidence/2026-10-31-metrics-hires-512.png`（950×523）、
`docs/evidence/2026-10-31-metrics-zhutou-crop.png`（951×976）。
