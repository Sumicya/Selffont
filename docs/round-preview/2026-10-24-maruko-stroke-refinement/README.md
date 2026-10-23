# Maruko Gothic 审计与原型记录

**当前唯一视觉稿从 [预览入口](../README.md) 打开，图像文件是 [`../current-maruko-review.png`](../current-maruko-review.png)。** 早期 63 项 / 62 唯一字的曲线拟合小样已从工作树移除，归档于提交 `9ee022d`；不再将其误标为实际笔画简化或与新稿并列。

## 当前原型

- [SC Regular：62 字实际笔宽原型 + 全映射曲线重新拟合 + 自制 Hangul](full-map-sc-regular-korean-prototype.md)
- [SC / TC / JP 多地区覆盖与轮廓签名审计](regional-coverage-audit.md)
- [SC cmap 基线](coverage-audit.md)、[SC 逐码位差异](coverage-gaps.tsv)、[三地区 / 字重差异](regional-coverage-gaps.tsv)

## 范围边界

- 实际笔宽归一只处理 63 项审计集的 62 个唯一字形；它只落实“跨字粗细一致性”这一已选目标，不表示全字库笔宽改造或其他类别（端头突出、圆端完整性、笔画圆润）已解决。
- 曲线重新拟合覆盖 SC Regular 全部唯一 cmap glyph，但只改变边界曲线表示；点数下降不表示语义笔画被删除或合并。
- Hangul 全部 11,172 音节来自同一 Maruko Regular 的 L/V/T Jamo；候选没有 KR Hanja 地区字形，不含 Light / Medium、TC / JP，不接入生产构建。
- 自动自交筛查不是视觉判定。8 个新增单轮廓筛查候选尚未逐字人工复核，不能据此称为缺陷或修字许可。
