# Maruko SC Regular：62 字实际笔宽原型 + 全映射曲线重拟合 + Hangul

**当前唯一主图：[`../current-maruko-review.png`](../current-maruko-review.png)。** 这是研究候选，不是生产字体；没有视觉验收。

## 重要区分

这次有两种不同范围的操作，不能混称：

1. **实际笔画处理：笔画粗细归一。** 按既有决定优先降低跨字平均笔宽差异，在 63 项 / 62 个唯一字形的审计样本上用骨架半径重建轮廓。共享目标为 62.01 FU；`文` 因纯共享目标筛查出现自交候选，回退到本字 63.50 FU。62 个样本字形都经过 raster / skeleton 重建，其中 61 个目标宽度发生变化，`文` 保留本字宽度作为回退。它只处理“跨字粗细一致性”这一类问题，**不是全 CJK 笔宽处理**，也没有删除或合并语义笔画。
2. **全映射曲线重新拟合。** `tools/curve_simplify.py --all-mapped --tolerance 4.0 --seg-len 1.5` 重拟合 45,007 个唯一映射字形的轮廓曲线。控制点数量减少只描述轮廓表示，不是笔画简化、合笔或视觉质量结论。

## 可复核结果

| 项目 | Maruko SC Regular 源 | 当前静态候选 |
|---|---:|---:|
| cmap entries | 33,944 | 45,116 |
| glyph 总数 | 33,889 | 45,061 |
| 唯一映射 glyph | 33,835 | 45,007 |
| Hangul 音节 `U+AC00..U+D7A3` | 0 | 11,172 / 11,172 |
| 原 glyph 的 hmtx / vmtx 差异 | — | 0 / 0 |
| UPM / OS/2 weight | 1000 / 400 | 1000 / 400 |
| GSUB / GPOS / vmtx | 有 | 有 |

**笔宽审计（同一 63 项序列，含一次重复 `国`）**：跨字平均笔宽 CV 源 / 候选在 360 px 下为 `0.040 -> 0.020`，在 1200 px 下为 `0.040 -> 0.011`。共享目标实验会改变单字平均粗细：62 个样本中 61 个宽度目标改变，目标偏移范围约 `-7.3%..+12.7%`；`文` 使用 63.50 FU 本字回退。CV 只表示这套栅格/骨架统计，不等同目视改善、字形比例正确或真机效果。

**曲线点数**：在笔宽原型输出（含光栅追踪的 62 个样本字形）上，45,007 个唯一映射 glyph 的展开轮廓点数为 `8,139,367 -> 7,197,609`（`-11.6%`）。前值是“实际笔宽重建后的输入”，不是原始 TTF 的点数；点数变化不能单独评价字形好坏。处理顺序现使用未变更的源字体快照读取复合字形，避免先处理组件后再读取复合轮廓导致结果依赖字形顺序。

## 拓扑筛查与 Hangul 范围

同一单轮廓自交筛查：原始 SC Regular **24** 个候选，当前候选 **14** 个；18 个原候选未再出现、6 个共同保留、8 个新候选：`aeacute`、`edotaccent`、`uni0205`、`uni0207`、`uni1E15`、`uni1E17`、`uni1E1D`、`uni5ADB`。这 8 项仍未人工目视；它们是曲线展平 + Shapely 的候选标记，不是已确认缺陷，也不是修字授权。筛查也不能证明多轮廓叠合、光栅尺寸与设备渲染正确。11,172 个新 Hangul 音节中未发现单轮廓自交标记（0/11,172）。

Hangul 字形从固定上游提交 [`97e9dd4a2fdde58084dde8d022de253f8d8415e9`](https://github.com/max32002/maruko-gothic/tree/97e9dd4a2fdde58084dde8d022de253f8d8415e9) 的 Maruko SC Regular 自有 L/V/T Jamo 组合，不含外部 Hangul 轮廓。输入 TTF SHA-256：`e3709389bce13fa75af28cc2370b6175520d97f74dfbf3894ca24838f47241b7`。最终 `/tmp` 候选 SHA-256：`281036f0428c59e2d5ce725d01e9432efd2b5df69c29257d887364b844d99f8b`。

**不是完整 KR 字体**：当前仅一个 SC Regular 静态字重；上游 SC CJK 缺字未补，KR 地区 Hanja 未制作，Light / Medium 与 TC / JP 未处理。上游 Light 不含可用现代 Jamo。没有改生产回退、`fonts.xml` 或 `build.py`。

## 复现

所有源 TTF、阶段文件和最终候选仅放在 `/tmp/maruko-audit/`，没有字体二进制入库。研究依赖见 `requirements-research.txt`。

```sh
SRC=/tmp/maruko-audit/source/Regular.ttf
HANGUL=/tmp/maruko-audit/korean/SC-Regular-HangulProto.ttf
WIDTH=/tmp/maruko-audit/stroke-width/SC-Regular-HangulProto-width62.ttf
FINAL=/tmp/maruko-audit/stroke-width/SC-Regular-HangulProto-stroke-width-sample-simplified.ttf
CHARS_UNIQUE='一二三十口日回国了乙人入八木林森永心必水走建进这远道你好中语言文字书写规范长美丽颜色锦绣风雨雪龙马鸟虫鱼电子已己巳也包囚暖田'

.venv/bin/python tools/compose_maruko_hangul.py "$SRC" "$HANGUL"
.venv/bin/python tools/stroke_width_normalize_prototype.py \
  --mode global --global-strength 0 --fallback-chars 文 \
  --font "$HANGUL" --out "$WIDTH" --chars "$CHARS_UNIQUE"
.venv/bin/python tools/curve_simplify.py \
  "$WIDTH" "$FINAL" --all-mapped --tolerance 4.0 --seg-len 1.5
.venv/bin/python tools/render_maruko_refinement.py \
  --source-regular "$SRC" --width-stage "$WIDTH" --final-regular "$FINAL" \
  --output docs/round-preview/current-maruko-review.png
```

复合 glyph 的曲线拟合从独立打开的不可变源快照读取；相关回归测试验证字形处理顺序不会改变复合轮廓。
