# 当前字体审阅

## 唯一当前轮 · 2026-10-27 自绘字体下线，主字体换成 Maruko SC 两档

目录：[`2026-10-26-cjk-redraw/`](2026-10-26-cjk-redraw/README.md)

这一轮把上一版的自绘 CJK 字体整条删掉，模块直接分发母版 Maruko Gothic `CJK SC` 的
Regular / Medium 两档静态字件（20,977 / 20,977 字，各约 20 MiB）。

| 图 | 内容 |
|---|---|
| [`覆盖-CJK基本区.png`](2026-10-26-cjk-redraw/覆盖-CJK基本区.png) | 自绘版当时的逐码位覆盖（19,352 / 20,977，绿=进字体，橙=剔除） |
| [`并排24字-对Maruko.png`](2026-10-26-cjk-redraw/并排24字-对Maruko.png) | 左母版 / 右自绘，IoU 0.904–0.962 —— 同一副面孔，这是删除理由 |

判据一句话：自绘唯一的立足点是「另一副设计」，而它与母版 IoU 中位 0.948，
覆盖率还低 7.7%、体积大一倍，于是整条下线。过程数字见目录内 `README.md`。

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
