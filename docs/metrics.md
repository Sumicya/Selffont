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
