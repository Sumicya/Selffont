# 预览导航

先看本页，再看当前候选；日期子目录都是历史研究，不作为当前验收结果。

## 当前候选：筑紫 A D/400 钩尾 V4（尚未获视觉验收）

- [63 项样本总览：基准 vs V4](tsukushi-a-d-63-hook-only-v4-overview.png)
- [7 个改动字的完整字形对照与叠加](tsukushi-a-v4-full-glyph-review.png)
- [8 处端头细节：完整字形定位框 + 同尺度局部裁切](tsukushi-a-v4-endpoint-detail.png)
- [来源、改动范围、检查结果与限制](tsukushi-a-v4-validation.txt)
- 实现与渲染：[`tools/tsukushi_a_preview_simplify.py`](../../tools/tsukushi_a_preview_simplify.py)、[`tools/render_tsukushi_a_preview.py`](../../tools/render_tsukushi_a_preview.py)

V4 仅在单一静态 D/400 研究来源上对 7 个唯一字形的 8 处钩尾生成对称双弧圆头候选。整体字形上下文和局部变化均有图可审；几何预检不代表美观或用户认可。没有修改生产字体，也未声称多字重、全字库、全流水线或真机验证。

## 版本状态

- **V4：当前候选，未验收。** 采用共用平分轴的对称双弧端头；针对完整字形重新排版预览，便于判断上下文中的观感。
- **V3：已被用户明确反馈“丑”，不接受。** 仅作回退/比较记录：[V3 说明](tsukushi-a-v3.md)、[V3 总览](tsukushi-a-v3-overview.png)、[V3 局部图](tsukushi-a-v3-detail.png)、[V3 验证](tsukushi-a-v3-validation.txt)。
- **V2：已被否决。** 自动拐角和短弯批量处理不在 V3/V4 里；历史裁决见 [`docs/decisions-笔画简化.md`](../decisions-笔画简化.md)。

## 历史材料（不是当前设计入口）

- [`history-2026-10-13.md`](history-2026-10-13.md)：Selfrounds 早期圆角流水线记录。页面中的生产字体文件、旧截图和部分结论是历史状态，不应当作当前 A-D 预览。
- [`2026-10-19-maruko-track/`](2026-10-19-maruko-track/)：马路口笔画、宽度与中轴研究；文件较多，按研究记录保留。
- [`2026-10-19-zhuzi-diagnosis/`](2026-10-19-zhuzi-diagnosis/)：筑紫候选诊断；社区 B 候选“包”字重量不符，已撤回，不作有效基准。
- [`2026-10-18-le-hook-tip/`](2026-10-18-le-hook-tip/)：早期“了”字钩尖对比图。

根目录的 `index.html` / `round.designspace` 属于早期 Selfrounds VF 预览链路；`index.html` 引用的 TTF 不在当前树中，它们不是本轮筑紫 A 的预览入口。
