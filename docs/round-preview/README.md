# 当前字体审阅

## 唯一当前新稿 · 2026-10-24

[打开当前审阅图：Maruko SC Regular 62 字笔宽样本 + 全映射曲线重拟合 + 自制 Hangul 原型](current-maruko-review.png)

这张图是唯一当前主图。它同时明确区分两项操作：固定 Maruko CJK SC Regular 字体 63 项 / 62 个唯一字形样本上的实际笔画粗细原型，以及全 45,007 个唯一映射字形的曲线/控制点重新拟合；另由 Maruko 自有 conjoining Jamo 组合出 11,172 个 Hangul 音节。曲线控制点减少不等于笔画简化；样本笔宽处理也不是全字库覆盖。候选是静态研究原型，不是生产字体或完整 KR 字体。

- [复核数字、方法与明确限制](2026-10-24-maruko-stroke-refinement/full-map-sc-regular-korean-prototype.md)
- [8 个自交候选复核（三态对照 + 局部放大）](2026-10-24-maruko-stroke-refinement/full-map-sc-regular-korean-prototype.md#8-个新候选的复核结果2026-10-24已逐项复现)
- [SC / TC / JP 来源覆盖审计](2026-10-24-maruko-stroke-refinement/regional-coverage-audit.md)
- [SC 覆盖基线](2026-10-24-maruko-stroke-refinement/coverage-audit.md)
- [工作台说明](../tools/glyph-lab/README.md)

## 范围状态

- 已对一份 CJK SC Regular 静态字体全 cmap 做轮廓曲线重新拟合；另按已选择的共享笔宽目标对 63 项 / 62 个唯一字形样本作实际笔宽原型。两项范围不同，不能把全 cmap 点数变化说成全字库笔画简化。Hangul 音节区由该字重自有 Jamo 生成；SC 原本的 CJK 缺口仍在。
- 未处理 Light / Medium、CJK TC / JP，也未建立 KR Hanja 地区字形；上游没有 Maruko Light Jamo，因此 KR 三字重仍需单独设计和审阅。
- 未接 `build.py`、未打包、未改设备字体路由。SC / TC / JP 原始字体仍分离为静态字重；本轮没有生成可变字体。
- 画面和自交筛查均不能替代逐字视觉校稿；未审阅的候选见对应报告。8 个新增自交候选已复核完毕（7 个上游零面积残留、1 个重拟合真自交已修），其余 6 个共同保留候选仍未复核。
