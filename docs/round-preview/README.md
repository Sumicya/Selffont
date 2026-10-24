# 当前字体审阅

## 唯一当前新稿 · 2026-10-24 晚

[打开当前审阅图：Maruko 可变字体候选 V1 现状总览（VF 实例 × 上游静态对照 × 中间档放大 × 实测数字）](2026-10-24-maruko-vf-candidate/maruko-vf-v1-state.png)

旧图（`current-maruko-review.png` 与两张自交候选对照图）已按主人指令全部清空，git 历史可追溯；现在仓库里只有这一张当前图。

- [插值扫视：300→500 五档连续](2026-10-24-maruko-vf-candidate/maruko-vf-candidate-v1-sweep.png)
- [分段密度对照：seg-len 28 vs 60，同一批字三档字重并排](2026-10-24-maruko-vf-candidate/maruko-vf-v1-seg-compare.png)
- [可变字体候选 V1：做法、实测限制与图上真实问题](2026-10-24-maruko-vf-candidate/README.md)

上一轮的复核数据与结论（无图，纯文字）：

- [SC Regular 62 字笔宽原型 + 全映射曲线重拟合 + Hangul：复核数字、方法与限制](2026-10-24-maruko-stroke-refinement/full-map-sc-regular-korean-prototype.md)
- [8 个自交候选复核结论](2026-10-24-maruko-stroke-refinement/full-map-sc-regular-korean-prototype.md#8-个新候选的复核结果2026-10-24已逐项复现)
- [SC / TC / JP 来源覆盖审计](2026-10-24-maruko-stroke-refinement/regional-coverage-audit.md)
- [SC 覆盖基线](2026-10-24-maruko-stroke-refinement/coverage-audit.md)
- [工作台说明](../../tools/glyph-lab/README.md)

## 范围状态

- 已对一份 CJK SC Regular 静态字体全 cmap 做轮廓曲线重新拟合；另按已选择的共享笔宽目标对 63 项 / 62 个唯一字形样本作实际笔宽原型。两项范围不同，不能把全 cmap 点数变化说成全字库笔画简化。Hangul 音节区由该字重自有 Jamo 生成；SC 原本的 CJK 缺口仍在。
- 未处理 Light / Medium、CJK TC / JP，也未建立 KR Hanja 地区字形；上游没有 Maruko Light Jamo，因此 KR 三字重仍需单独设计和审阅。
- 未接 `build.py`、未打包、未改设备字体路由。SC / TC / JP 原始字体仍分离为静态字重；上一轮没有生成可变字体。
- 画面和自交筛查均不能替代逐字视觉校稿；未审阅的候选见对应报告。8 个新增自交候选已复核完毕（7 个上游零面积残留、1 个重拟合真自交已修），其余 6 个共同保留候选仍未复核。
