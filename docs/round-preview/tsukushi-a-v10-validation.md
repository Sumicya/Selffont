# 筑紫 A D/400 V10：可逆研究候选、全样本审计与限制

> **历史记录：筑紫 A D/400 V10，不是当前设计方向，也未获审美验收。** 当前方向只基于 Maruko；唯一当前图见 [`docs/round-preview/README.md`](README.md)。V10 曾是单一静态 D/400 的本机研究候选，不是生产字体、不进入安装包或 `build.py`。筑紫源字体的正式再分发许可尚未确认；源 TTF 和派生 TTF 均只留在 `/tmp`，不入库、不打包、不宣称可再分发。旧版 PNG 已于 2026-10-24 从工作树清理；可用 `git show 3583a8a:docs/round-preview/tsukushi-a-v10-63-sample-overview.png` 从历史提交读取。

## 输入、基线与范围

- 原始字体：`/tmp/zhuziawan-source.ttf`，静态 UPM 1000、`usWeightClass=400`、无 `fvar`；SHA-256：`1b5b1c00c0bccf6feda1c55434879016d4c8ced78677d2b83ed2ae756e19c11c`。来源是 `Totoro625/totoro625-font-family` 固定提交 `46c4b0061fb5ab3efb4042c087453b39f6b866b7` 的 `zhuziawan/zhuziawan.ttf`；再分发许可未确认。
- 基线是已复建且与此前记录哈希一致的 V9：`/tmp/zhuziawan-v9.ttf`，SHA-256 `b12338d955faf6f3ad5b7750a72ffaf3b93aa6d05eba540ecb08a6c6d9a28a0b`。
- V10 候选：`/tmp/zhuziawan-v10.ttf`，SHA-256 `33d7911fa772d58b8e4679e85b87317f2b098068322c73ee5c3505499f04cede`；V10 几何审计基底：`/tmp/zhuziawan-v10-geometry.ttf`，SHA-256 `55a9c5adc371f42ce267607766159e516b8b2935edaa6033661153d120addaa2`。独立重复构建的候选与几何基底均逐字节一致；两份派生 TTF 均未进入仓库。
- 样本固定为 `CHARS_63` 的 63 条记录、62 个唯一字形（含重复记录“国”）。只研究此样本和一个静态 D/400 字重；不代表全字库、其他字重、VF 插值、安装包、生产构建或真机渲染。
- “鸟”和“也”的两张用户草图分别只用于对应字符的整体比例/笔势方向；不混字、不逐点描摹、不把草图坐标转成字形坐标。授权字体没有用作轮廓来源。

## V10 的可逆改动

V10 以 V9 74-FU 共享宽度候选为底，只用 V10 几何替换以下 12 个字；其余样本字形继续保留 V9 结果。所有 glyph advance 保持不变。被替换字形保留各自矢量局部笔宽，不宣称它们每一笔都精确等于 74 FU。

- **恢复源矢量轮廓**：“颜”恢复点形和重量；“暖”恢复原左侧部件/撇画。避免对这两字再做栅格骨架重描。
- **按人工核对闸门改端头**：在“己、已、巳、也、包（两处）、色、龙、子”的 9 个端点去掉钩尾/回钩并按各自测得方向重建圆弧端头；“已、巳、也、色”按己的末端轴校准方向。保留整体轮廓与既有布局，不用统一笔宽替代造型修复；V10 不再沿用 V9 对“己/已”末端额外增加的 8 FU 延长。
- **“鸟”独立三段笔势重绘**：只根据“鸟”草图提取一组宽阔走势，不描点；输出的拓扑从源的 3 个外轮廓变为 1 个外轮廓，是明确的造型重绘而非隐藏的审计例外。
- **“乙”开放单笔重绘**：以一个开放扫势去掉回钩，末端直向并作圆弧收尾。`find_hooks` 未命中并不等同于“乙”无需修整。
- **“电”**没有被 V10 矢量覆盖；继续沿用 V9 的实测 0.97 中框水平间距调整，未压缩整字外框，也未通过加粗隔断收窄内框。
- “龙”“色”“子”以保留的源矢量骨架和目标端头重做，避免继续使用 V9 对这三字的栅格重建轮廓；“包”左右两处端头都分别处理。

## 可直接审阅的 PNG

V10 曾有四张 PNG 样图（全样本、重点字、端头细节、草图思路对照）。为避免与当前 Maruko 新稿混淆，旧图已从工作树清理；研究记录仍保留在本文件，旧图可用 `git show 3583a8a:docs/round-preview/tsukushi-a-v10-63-sample-overview.png` 等路径从归档提交读取。

这些是基于未 hint 的矢量轮廓渲染，不是操作系统 / 真机截图；图像用于主人正常字面和放大细节审阅，不能代替主人审美签核。量化通过也不代表视觉通过。

## 独立量化审计

审计器将保存后的 source、V10 geometry、V10 candidate 交给 Pillow 13.0.0 / FreeType 2.14.3 渲染；大尺寸检查为 1000 px/em，二值阈值 alpha≥128、8 邻接连通域，孔洞按连通域数减 Euler 数计算；另以 48 px/em 只作尺寸敏感性诊断。

- 63 项 / 62 唯一样本全部覆盖。
- source→geometry 有且只有一个**明确允许的**拓扑变化：“鸟”U+9E1F 从 3 组件/0 孔洞变为 1/0；其余 source→geometry 拓扑保持。geometry→candidate 的组件/孔洞拓扑失败 **0**。
- advance、UPM/weight、样本 cmap 映射失败 **0**。
- 保存后的源、几何基底、V10 候选各 63 项，共 **189 条单轮廓自交检查，0 失败**。此检查不覆盖同一字形多个轮廓之间的相交，也不证明审美或真机效果。
- 48 px/em 有 11 个唯一字的 FreeType 光栅拓扑计数与源不同：U+56FD、U+8FDB、U+8FDC、U+4E66、U+89C4、U+4E3D、U+9526、U+7EE3、U+98CE、U+96E8、U+9E1F。单列为低尺寸诊断，不算向量拓扑硬失败；源字体含 hinting，V10 候选不含 hinting。
- 900 px/em 骨架距离笔宽代理：源 / 几何基底 / V10 候选的每字中位数总体中位值为 76.739 / 76.826 / 74.946 FU；跨字 CV 为 0.07813 / 0.07834 / 0.02585；V10 字内 CV 均值 0.05477、最大值 0.15849。这是形态代理；由于 12 字保留各自矢量笔画，V10 的跨字 CV 高于纯共享宽度 V9 的 0.00952，不将 74-FU 目标宣传为每字完美等粗。
- “电” advance source / geometry / candidate 均为 950 FU；ink bbox 宽度为 819 / 819 / 814 FU，V10 沿用 V9 因 0.97 处理留下的 5 FU 可见宽度差异，不声称整字外宽精确保留。

逐项结果见[高分辨率审计报告](tsukushi-a-v10-raster-audit.md)、[63 项 CSV](tsukushi-a-v10-sample-audit.csv) 与[189 条自交结果](tsukushi-a-v10-self-intersection.txt)。

## 本机复现

字体输入与构建产物在本机 `/tmp`，不随仓库提供。下面的命令仅复现研究候选，不是可分发的字体配方：

```sh
PYTHONPATH=. /tmp/selffont-research/bin/python tools/build_tsukushi_a_v9.py \
  --font /tmp/zhuziawan-source.ttf \
  --out /tmp/zhuziawan-v9.ttf \
  --shared-width 74 \
  --electric-frame-scale-x 0.97 \
  --px 1400

PYTHONPATH=. /tmp/selffont-research/bin/python tools/build_tsukushi_a_v10.py \
  --font /tmp/zhuziawan-source.ttf \
  --baseline /tmp/zhuziawan-v9.ttf \
  --out /tmp/zhuziawan-v10.ttf \
  --geometry-out /tmp/zhuziawan-v10-geometry.ttf \
  --shared-width 74 \
  --px 1400

PYTHONPATH=. /tmp/selffont-research/bin/python tools/audit_tsukushi_a_candidate.py \
  --source /tmp/zhuziawan-source.ttf \
  --geometry /tmp/zhuziawan-v10-geometry.ttf \
  --candidate /tmp/zhuziawan-v10.ttf \
  --csv docs/round-preview/tsukushi-a-v10-sample-audit.csv \
  --markdown docs/round-preview/tsukushi-a-v10-raster-audit.md \
  --redrawn-geometry-chars 鸟 \
  --candidate-label V10

CHARS=$(PYTHONPATH=. /tmp/selffont-research/bin/python -c \
  'from tools.tsukushi_a_preview_simplify import CHARS_63; print(CHARS_63)')
PYTHONPATH=. /tmp/selffont-research/bin/python tools/check_self_intersect.py \
  /tmp/zhuziawan-source.ttf /tmp/zhuziawan-v10-geometry.ttf /tmp/zhuziawan-v10.ttf \
  -- "$CHARS"

PYTHONPATH=. /tmp/selffont-research/bin/python tools/render_tsukushi_a_v10.py \
  --source /tmp/zhuziawan-source.ttf \
  --candidate /tmp/zhuziawan-v10.ttf \
  --out-dir docs/round-preview
```

## 本轮仓库检查

- `PYTHONPATH=. /tmp/selffont-research/bin/python -m unittest discover -s tests -v`：35 项通过。
- 三个 V10 Python 脚本与新增测试文件通过 `py_compile`；`git diff --check` 通过。
- 没有把 V10 候选接入 `build.py`，没有执行生产字体构建、安装或真机验收。

V10 remains a reviewable draft. The user decides whether the full-size forms, point weight, terminal shapes and sketch-derived gestures are stylistically acceptable; no production or release decision is implied.
