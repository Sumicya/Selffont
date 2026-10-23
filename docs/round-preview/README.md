# 预览导航

当前可审阅的是 V9 静态研究候选，不是生产字体；图像与量化证据不等于主人审美验收，也不是设备截图。范围仍固定在筑紫 A D/400 的 63 个样本项 / 62 个唯一字形，没有扩展到其他字重或全字库。

## 当前候选：筑紫 A D/400 全样本统一笔宽 V9

- [63 项 / 62 字完整总览：源字形、几何基底、V9](tsukushi-a-v9-63-sample-overview.png)
- [重点字形放大：颜、暖、电、己、已、巳、也、鸟等](tsukushi-a-v9-focused-glyphs.png)
- [“鸟”“也”分别对应确认草图的造型思路](tsukushi-a-v9-sketch-gesture-study.png)
- [可见共享笔宽与授权参照：源字形、V9、Noto Sans SC 400](tsukushi-a-v9-stroke-width-reference.png)
- [圆钩端头及 U+7535「电」中框细节](tsukushi-a-v9-endpoint-electric-detail.png)
- [48 px/em 下拓扑有差异的 15 个字：源字体与 V9 的 FreeType 光栅对照](tsukushi-a-v9-small-size-topology-review.png)
- [V9 全样本高分辨率拓扑、映射、advance、边界与笔宽审计](tsukushi-a-v9-raster-audit.md)
- [63 项逐字 CSV（含重复项、边界、孔洞/连通域、低尺寸诊断与 IoU）](tsukushi-a-v9-sample-audit.csv)
- [189 条单轮廓自交检查结果](tsukushi-a-v9-self-intersection.txt)
- [实现、结果、复现方法与限制](tsukushi-a-v9-validation.md)
- 用户确认的原始草图：[鸟](sketches/bird-reference.png)、[也](sketches/ye-reference.png)
- 工具：[V9 构建器](../../tools/build_tsukushi_a_v9.py)、[候选审计器](../../tools/audit_tsukushi_a_candidate.py)、[共享笔宽重建原型](../../tools/stroke_width_normalize_prototype.py)、[几何基底](../../tools/tsukushi_a_preview_simplify.py)、[预览渲染器](../../tools/render_tsukushi_a_preview.py)

### 本轮设计与审计口径

- 62 个唯一字形全部进入共享 74 FU 笔宽重建；逐项审阅 63 条样本记录。几何层为 21 处人工指定半圆钩尾、11 处自由端圆化、1 处安全尖端圆化及 2 个局部轮廓组间距修复；“己”“已”端头沿真实二次曲线投影保留长度，并在源路径投影之外再延长 8 FU，末端保持圆润；“巳”保留原生钩尾，不再做会损失辨识度的切除。
- 共享笔宽是候选中的**可见轮廓重建**，不是只写在说明里的目标。900 px/em 骨架距离代理显示：62 字各自中位宽的跨字 CV 从源字形 0.07813 降至 V9 0.00952；V9 的字内 CV 均值 0.05101、最大 0.15849（森）。这些是代理值，不等于所有连接处的主观重量完全相同。
- Noto Sans SC 400 仅作授权笔宽参照，依据 [Google Fonts 固定源码提交](https://github.com/google/fonts/tree/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/notosanssc) 与 [SIL OFL 1.1](https://github.com/google/fonts/blob/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/notosanssc/OFL.txt)；未复制其轮廓、坐标或字形结构。“鸟”(U+9E1F)与“也”(U+4E5F)始终分开处理，草图只提供整体比例/风格线索，不逐点描摹。
- “电”中框在实测竖隔断中心线周围采用平滑渐变的水平间距调整，峰值缩放 0.97；上下边界逐渐回到原尺度，再按同一 74 FU 目标重绘，避免通过加粗隔断来收窄空腔。advance 保持 950 FU；候选中心线残差约 0.44 FU。可见 ink bbox 为源/几何基底 819 FU、候选 814 FU：仍有 5 FU 差异，**不声称外接墨迹宽度被精确保留**。细节见审计记录。
- 新增独立 Pillow/FreeType 1000 px/em 拓扑审计；最终候选 source→geometry 与 geometry→candidate 均为 0 个组件/孔洞差异，advance、UPM/weight、样本映射失败均为 0。48 px/em 有 15 个唯一字的像素拓扑计数不同，已逐字放大审阅并单列为提示而非向量拓扑硬门槛，因为源字体含 hinting、研究候选不含。
- 曾在 V9 中间构建发现“颜”“暖”保存后的真实连通域/孔洞变化；不是原型误报。经过间距修复后，高分辨率独立渲染恢复源拓扑：`颜` 8/0，`暖` 4/3。完整自交检查为源、几何基底、候选各 63 项，共 189 条、0 失败；该检查不覆盖同一字形的轮廓间相交或审美质量。
- 筑紫研究源未找到正式字体许可。源 TTF、候选 TTF 仅在本机 `/tmp`；仓库不包含字体二进制，不打包、不声称可再分发。未修改生产字体或 `build.py`。

### 版本状态

- **V9：当前研究候选，待主人审阅。** 六张 V9 PNG、CSV、审计报告和验证记录针对同一份可重复构建的候选。
- **V8：已从当前预览撤下。** 全样本高分辨率复审确认其曾有真实组件/孔洞损坏；修复和证据见 V9 审计记录。被替换的 V8 图片与验证页已从工作树清理，仍可从 Git 历史追溯。
- **V7：已撤出当前预览。** 曾用整字 bbox 缩放“鸟”“也”，不符合草图仅作整体风格参照的要求；当前方案不复用该方法。
- V6 及更早稿仍是历史研究材料，见 `CHANGELOG.md` 与历史文档；不代表当前候选。
