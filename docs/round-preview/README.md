# 预览导航

**当前可审阅版本是 V10 静态研究候选，不是生产字体，也尚未获主人审美验收。** 范围固定为筑紫 A D/400 的 63 个样本项 / 62 个唯一字形；候选仍可逆，源 TTF 与派生 TTF 只在本机 `/tmp`，不入库、不进 `build.py`、不打包。图像和工程检查不能替代正常字面及放大细节审阅，也不是设备截图。

## 交互试调

- [打开字形工作台](../../tools/glyph-lab/index.html)：本地加载字体，对单字实时试调栅格笔重、字面宽高与位置；逐字记录修改意图、审阅状态和备注，并导出 PNG/JSON。字体不会上传。
- 工作台是审阅原型，不直接编辑或导出 TTF/OTF；笔重滑杆为栅格形态学预览。操作说明与限制见[工作台 README](../../tools/glyph-lab/README.md)。
- 可选授权参照：[霞鹜文楷（OFL 1.1）](https://github.com/lxgw/LxgwWenKai)适合观察手写风格，[Noto Sans SC（OFL 1.1）](https://github.com/google/fonts/tree/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/notosanssc)可作笔重对照；只提炼原则，不描摹字形。

## 当前候选：筑紫 A D/400 V10（V9 基线上的定点矢量修正）

### 直接看图

- [完整 63 项 / 62 字对照：原字形 vs V10](tsukushi-a-v10-63-sample-overview.png)
- [重点字完整轮廓：颜、暖、电、己、已、巳、也、乙、包、鸟、色、龙、子](tsukushi-a-v10-focused-glyphs.png)
- [钩尾与端头放大细节（同一行 source/V10 用相同裁切范围）](tsukushi-a-v10-terminal-detail.png)
- [“鸟”“也”各自对应自己的确认草图](tsukushi-a-v10-sketch-gesture-study.png)
- 用户确认的原始草图：[鸟](sketches/bird-reference.png)、[也](sketches/ye-reference.png)

### 这版具体改了什么

- V10 以 V9 74-FU 共享宽度候选为基线，只覆盖 12 个指定字形；其余字形保留 V9 结果。所有 glyph advance 不变。被覆盖字形保留其各自矢量局部笔宽，不声称每一笔都恰为 74 FU。
- “颜”恢复点形和重量；“暖”恢复原左侧部件/撇画。八字九个端点按人工核对闸门改为圆弧端头：“己、已、巳、也、包”（两端）、“色、龙、子”。“己”“已”不再采用 V9 额外增加的 8 FU 延长；巳/也/乙去钩直化，包左右钩都去掉。
- “鸟”以三段宽阔笔势独立重绘，只提炼“鸟”草图整体造型；“乙”作为开放单笔扫势去回钩并圆弧收尾。“鸟”源轮廓 3/0 → 几何候选 1/0 是明确的重绘变化，不藏在拓扑例外里。两张草图不混用、不逐点描摹。
- “龙”“色”“子”恢复源矢量骨架后修端头，避免延续 V9 栅格轮廓的变形；“电”沿用 V9 的 0.97 中框水平间距调整，不压整字外框、不加粗隔断。可见 bbox 仍比源窄 5 FU，未宣称外宽完全保持。

### 审计与复现记录

- [V10 高分辨率拓扑、映射、advance、边界与笔宽审计](tsukushi-a-v10-raster-audit.md)
- [63 项逐字 CSV（含重复项、边界、拓扑与 IoU）](tsukushi-a-v10-sample-audit.csv)
- [189 条源/几何/候选单轮廓自交结果](tsukushi-a-v10-self-intersection.txt)
- [V10 方法、SHA-256、复现步骤与证据限制](tsukushi-a-v10-validation.md)
- 工具：[V10 构建器](../../tools/build_tsukushi_a_v10.py)、[V10 图像渲染器](../../tools/render_tsukushi_a_v10.py)、[独立候选审计器](../../tools/audit_tsukushi_a_candidate.py)、[V9 共享宽度基线构建器](../../tools/build_tsukushi_a_v9.py)

审计结果：1000 px/em 组件/孔洞硬检查 0 失败（唯一允许的 source→geometry 结构变化为“鸟”3→1）；advance、UPM/weight、cmap 映射失败 0；单轮廓自交 189 项、0 失败。48 px/em 有 11 个尺寸敏感性诊断差异，不是向量拓扑硬门槛。V10 跨字笔宽代理 CV 为 0.02585，低于源字形 0.07813，但高于纯 V9 共享宽度候选的 0.00952；数字是形态代理而非“完美等粗”或审美通过。细节与局限见[验证报告](tsukushi-a-v10-validation.md)。

## 上一版本：V9（V10 的共享宽度基线）

V9 图片和报告继续保留，供差异复核；它不再是当前候选。

- [V9 完整 63 项总览](tsukushi-a-v9-63-sample-overview.png)
- [V9 重点字形](tsukushi-a-v9-focused-glyphs.png)
- [V9 鸟/也草图研究](tsukushi-a-v9-sketch-gesture-study.png)
- [V9 共享笔宽参照](tsukushi-a-v9-stroke-width-reference.png)
- [V9 端头与电框细节](tsukushi-a-v9-endpoint-electric-detail.png)
- [V9 48 px/em 15 字小尺寸诊断](tsukushi-a-v9-small-size-topology-review.png)
- [V9 高分辨率审计报告](tsukushi-a-v9-raster-audit.md)、[63 项 CSV](tsukushi-a-v9-sample-audit.csv)、[验证记录](tsukushi-a-v9-validation.md)

## 历史状态

- **V8 及更早版本**是历史研究稿，不是当前预览；V8 的真实组件/孔洞损坏与替换原因见 V9 审计记录。
- **V7** 曾使用整字 bbox 缩放“鸟”“也”，不符合当前的独立草图原则，已撤出。
- V3 曾被用户明确反馈“丑”，未接受；其余历史决策见 `CHANGELOG.md` 与 `TODO.md`。

所有结论只覆盖这一份静态 D/400 与固定样本。尚无其他字重、全字库、安装包、生产构建、真机截图或外部设计师签核。筑紫源字体正式再分发许可未确认，源与派生 TTF 均不入库、不打包。
