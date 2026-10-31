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
```

字表：GB2312 一级字库前 3,500 字（`一丁七万丈三上下不与…`），按码位升序。

## 口径写死的地方

- 距离单位一律 **em 的 1/1000**；本版与母版各自按自身 `unitsPerEm` 归一到 1000 再比。
- 二次曲线展开按 TrueType 规范处理连续 off 控制点（相邻控制点中点即隐含 on 点）。
  2026-10-31 那轮 `te` 宽 46 单位，根因就是这一步写错——现在写进量具并有变异测试。
- 笔宽用 FreeType 栅格（256 px/em）量游程中位，不用自制渲染器：
  `docs/design-principles.md` 2026-10-28 那条。
- 曲线连续性排除 >60° 的接点（直角、锐角是设计）；母版与本版用同一口径，差值才有意义。
