# 中心线长度审计：栅格分辨率敏感性

基线脚本 `tools/stroke_length_audit.py` 在相同原字形、字符序列（63 项、62 个不同字）和三档字重上分别以 800px、1200px 栅格运行。此对照检验的是骨架统计的分辨率稳定性，不是字体视觉质量。

| 字重 | 分支数变化项 | 总中心线长度逐字相对变化中位数 | H 跨字 CV (800 / 1200) | V 跨字 CV (800 / 1200) | D 跨字 CV (800 / 1200) |
|---|---:|---:|---:|---:|---:|
| Light | 21/63 | 0.18% | 0.9275 / 0.9957 | 1.2826 / 1.3190 | 0.8001 / 0.6694 |
| Regular | 25/63 | 0.47% | 0.8818 / 0.9076 | 1.1909 / 1.1643 | 0.6011 / 0.6882 |
| Medium | 32/63 | 0.36% | 0.9605 / 0.9512 | 1.3117 / 1.2553 | 1.0301 / 1.0609 |

## 结论边界

- 总骨架路径长度的中位变化较小，但**分支拓扑在 21–32/63 个样本项上发生变化**；按分支切分的字内统计不能视为分辨率不变。
- 跨字 H/V/D 汇总 CV 有些接近、有些变化明显；即使汇总值接近，逐字的分支数和分类仍可能不同，因此不能据此推断某种真实汉字笔画长度不和谐。
- H/V/D 是 PCA 主轴方向分组，非语义笔画分类。用于改字或定目标前，需先获得稳定、可复核的笔画中心线/语义分段方法。
- 800px 结果输出在 `/tmp/maruko-length-800.csv`；1200px 明细见同目录 `11-centerline-length-baseline-63-items.csv`。可用以下命令复现 800px 结果（将输出放到 `/tmp`，避免覆盖 1200px 基线）：

```sh
.venv/bin/python tools/stroke_length_audit.py \
  --font Light=/tmp/selffont-maruko/Light.ttf \
  --font Regular=/tmp/selffont-maruko/Regular.ttf \
  --font Medium=/tmp/selffont-maruko/Medium.ttf \
  --px 800 \
  --out-csv /tmp/maruko-length-800.csv \
  --out-md /tmp/maruko-length-800.md
```
