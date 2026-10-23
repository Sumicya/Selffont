# 预览导航

当前可审阅的是 V8 研究候选，不是生产字体。这里的轮廓图、量化指标和单轮廓自交检查只说明相应数据与几何预检结果；**不代表主人已作审美验收**，也不是设备截图。

## 当前候选：筑紫 A D/400 全样本统一笔画粗细 V8

- [完整 63 项 / 62 个唯一字形总览：源字形、几何基底、V8](tsukushi-a-v8-63-sample-overview.png)
- [“鸟”“也”各自草图与对应字形的造型思路对照](tsukushi-a-v8-sketch-gesture-study.png)
- [授权字体笔宽参照：源字形、V8、Noto Sans SC 400](tsukushi-a-v8-stroke-width-reference.png)
- [22 处钩尾中的 8 处代表性放大及 U+7535「电」内框细节](tsukushi-a-v8-endpoint-electric-detail.png)
- [实现、量化、拓扑检查和限制记录](tsukushi-a-v8-validation.md)
- 用户确认的原始草图：[鸟](sketches/bird-reference.png)、[也](sketches/ye-reference.png)
- 构建、几何计划与渲染：[V8 构建器](../../tools/build_tsukushi_a_v8.py)、[笔宽归一化原型](../../tools/stroke_width_normalize_prototype.py)、[字形几何基底](../../tools/tsukushi_a_preview_simplify.py)、[预览渲染器](../../tools/render_tsukushi_a_preview.py)

### 本轮设计口径

- 覆盖全部 63 个样本项与 62 个唯一字形。所有唯一字形都进入共享笔宽重建；未作端头几何编辑的样本也没有跳过宽度审阅。
- 22 处经逐项指定的钩尾采用半圆端头；另有 11 处自由端圆头及 1 处安全尖端圆化。仅对“己”“已”的末笔分别加长 1.0、1.5 个闸门宽度，仍以圆头结束。
- “鸟”（U+9E1F）和“也”（U+4E5F）分别与正确字符对照。草图保持各自原始宽高比，只提炼“紧凑围合/交叉上扬”与“开放转折/较长下部扫势”等整体造型线索；没有描摹笔画、坐标叠加或按草图外接框缩放字形。
- 统一笔宽以 74 FU 为重建目标。Noto Sans SC 400 依据 [Google Fonts 固定源码提交](https://github.com/google/fonts/tree/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/notosanssc)，许可证为 [SIL OFL 1.1](https://github.com/google/fonts/blob/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/notosanssc/OFL.txt)；只研究字重/笔宽行为并用其样本中位数校准目标，**没有复制 Noto 轮廓或字形坐标**。
- “电”的中间田框骨架水平间距以实测竖隔断中线为轴缩至 0.94；之后重新按共同 74 FU 半径绘制，因此目标是收窄而不加粗。字面 advance 仍为 950 FU；实际墨迹边界会变化，见验证记录中的 bbox、LSB 与中线数值，不把 advance 等同于 ink bbox。
- 研究源筑紫 A D/400 仓库未找到正式字体许可。源 TTF 和派生 TTF 仅在本机 `/tmp` 中处理，不入库、不打包、不宣称可再分发；仓库只包含审阅图、工具与研究说明。生产字体、`build.py` 和发布包均未修改。

### 版本状态

- **V8：当前研究候选，待主人审阅。** 本目录四张图和验证记录描述的是同一份候选。
- **V7：已撤出当前预览。** 先前对“鸟”“也”使用整字 bbox 缩放的方案不符合本轮造型参照方式；旧图已清理，历史文字保留在 `CHANGELOG.md` 与 Git 历史中。V8 不复用该缩放方案。
- **V6 及更早版本：历史研究稿。** 具体取舍见 `CHANGELOG.md` 和历史文档；旧预览图不作为当前审阅材料。

本轮图片目录只保留当前四张 V8 研究图和仍在使用的两张用户原始草图。被覆盖的四张 V7 预览图已删除，V7 验证页也已移除；过程可从 Git 历史追溯，不保留指向已删除文件的当前链接。

## 历史材料（不作为当前候选）

- [`history-2026-10-13.md`](history-2026-10-13.md)：旧 Selfrounds 流水线文字记录。
- [`2026-10-19-maruko-track/`](2026-10-19-maruko-track/) 与 [`2026-10-19-zhuzi-diagnosis/`](2026-10-19-zhuzi-diagnosis/)：历史研究的文字和数值档案。
- [`tsukushi-a-v3.md`](tsukushi-a-v3.md) 及 V3/V4/V5 验证文本：旧候选的留档；不含当前预览图。
- [`../evidence/README.md`](../evidence/README.md)：证据目录说明。
