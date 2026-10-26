# 当前字体审阅

## 唯一当前轮 · 2026-10-26 覆盖补齐与二创四字

目录：[`2026-10-26-cjk-redraw/`](2026-10-26-cjk-redraw/README.md)

| 图 | 内容 |
|---|---|
| [`真字体渲染-24字形.png`](2026-10-26-cjk-redraw/真字体渲染-24字形.png) | 20 个未分配码位占位 + 4 个二创汉字，真字体渲染 |
| [`20个未分配码位-自绘占位.png`](2026-10-26-cjk-redraw/20个未分配码位-自绘占位.png) | 占位字形放大 |
| [`乙了子九-对Maruko.png`](2026-10-26-cjk-redraw/乙了子九-对Maruko.png) | 二创四字 vs Maruko 原版，同一窗口 |

覆盖账：文渊底 20 + 补充字件并集 298 = **315 / 315**，缺失 0。

## 已清出的历史轮

2026-10-24 的 40 张过程图（`2026-10-24-modern-maruko-pipeline/`）已于 2026-10-27 全部清出工作树，
那一轮的结论仍在同目录 `README.md` 里（纯文字），图用
`git show 3b8c8bd:docs/round-preview/2026-10-24-modern-maruko-pipeline/<文件名>.png` 取回。

上一轮的复核数据与结论（无图，纯文字）：

- [SC Regular 62 字笔宽原型 + 全映射曲线重拟合 + Hangul：复核数字、方法与限制](2026-10-24-maruko-stroke-refinement/full-map-sc-regular-korean-prototype.md)
- [8 个自交候选复核结论](2026-10-24-maruko-stroke-refinement/full-map-sc-regular-korean-prototype.md#8-个新候选的复核结果2026-10-24已逐项复现)
- [SC / TC / JP 来源覆盖审计](2026-10-24-maruko-stroke-refinement/regional-coverage-audit.md)
- [SC 覆盖基线](2026-10-24-maruko-stroke-refinement/coverage-audit.md)
- [工作台说明](../../tools/glyph-lab/README.md)

## 范围状态

- 已对一份 CJK SC Regular 静态字体全 cmap 做轮廓曲线重新拟合；另按已选择的共享笔宽目标对 63 项 / 62 个唯一字形样本作实际笔宽原型。两项范围不同，不能把全 cmap 点数变化说成全字库笔画简化。Hangul 音节区由该字重自有 Jamo 生成；SC 原本的 CJK 缺口仍在。
- Light / Regular / Medium 三档都已在 214 个部首上重跑（保形并集 + 磨平 + 曲线精简），但还没铺到全字集；CJK TC / JP 未处理，KR Hanja 地区字形未建立；上游没有 Maruko Light Jamo，因此 KR 三字重仍需单独设计和审阅。
- 未接 `build.py`、未打包、未改设备字体路由。SC / TC / JP 原始字体仍分离为静态字重；上一轮没有生成可变字体。
- 画面和自交筛查均不能替代逐字视觉校稿；未审阅的候选见对应报告。8 个新增自交候选已复核完毕（7 个上游零面积残留、1 个重拟合真自交已修），其余 6 个共同保留候选仍未复核。
