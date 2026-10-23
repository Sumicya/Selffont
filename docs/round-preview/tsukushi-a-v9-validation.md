# 筑紫 A D/400 V9：全样本研究候选、审计与限制

> **状态：可逆研究候选，待主人审阅；未获审美验收。** V9 是本机临时静态 D/400 TTF，不进入安装包、`build.py` 或生产字体。源筑紫字体未找到正式再分发许可，源 TTF 与候选 TTF 不入库、不打包、不声称可再分发。

## 范围、原始材料与参照

- 固定审阅集为 `CHARS_63`：63 条样本记录、62 个唯一字形（其中“国”有重复记录）。没有跳过未改过几何的样本；所有62个唯一字形都进入共享宽度重建、独立栅格审计及总览图。
- 原始形状来自本机 `/tmp/zhuziawan-source.ttf` 中筑紫 A D/400 的原始 TrueType `glyf` 轮廓。草图来自仓库中用户确认的“鸟”与“也”，分别只作整体比例/风格思路参照；未描摹坐标、未混淆字符、未用整字 bbox 缩放。
- 授权参照为 Noto Sans SC 400：Google Fonts 固定提交 `e7db6ca603fd4862010383ff17ffd6cc4ffac1c0`，SIL OFL 1.1。只用62个样本的宽度分布校准共享目标；没有复制 Noto 轮廓、点坐标或字形结构。
- 只研究一个静态字重。没有验证其他字重、完整字库、可变字体插值、系统安装包、设备截图或生产构建。

## V9 几何处理

- 21 处人工指定钩尾改为平衡双弧半圆端头；另有11处自由端圆化、1处安全尖端圆化。`巳`的原生圆钩保留，不再切成容易与“己”混淆的长直尾。
- `己`、`已`的末端依各自真实二次曲线计算源端点投影，并在该投影之外沿 cap 轴各加8 FU，再用圆头收尾；没有使用旧版按闸门宽度猜测的1.0×/1.5×延长比例。
- 针对74 FU共享半径可能造成的真实近接，`颜`、`暖`各自只做刚性轮廓组小位移以留出负空间；移动时外轮廓与对应反白轮廓一起移动，不缩细局部笔画。共享宽度重建另保留组件间距保护，作为保存后拓扑防线。
- 62个唯一字形最终以共同74 FU目标重建。重建使用 raw `glyf` 坐标，避免把 `TTGlyphSet` 的 LSB 平移二次写回；advance 保持源值，LSB 按新边界重算以保持几何基底的绘制原点偏移。
- `电`：围绕实测竖隔断轴，对中段采用峰值0.97的水平间距缩放，并在上下边界平滑回到1.0；随后以同一74 FU目标重建。目的为轻度缩窄中框，不通过加粗隔断收窄开口。

## 全样本独立审计

独立审计器 `tools/audit_tsukushi_a_candidate.py` 将保存后的三个 TTF（source、geometry、candidate）交给 Pillow / FreeType 渲染。版本为 Pillow 13.0.0、FreeType 2.14.3、FontTools 4.66.0；二值化阈值为 alpha≥128，连通域采用8邻接，孔洞数按“连通域数−Euler 数”计算，掩码相似度用二值 IoU；拓扑硬检查为1000 px/em，另有48 px/em尺寸诊断。

- 63条样本记录 / 62个唯一字形：全部覆盖。
- 高分辨率 source→geometry、geometry→candidate：**0个组件/孔洞拓扑失败**；`cmap`样本映射、UPM/weight、advance检查：**0失败**。
- 48 px/em 有15个唯一字形的 FreeType 像素连通域/孔洞计数不同（完整码点见[审计报告](tsukushi-a-v9-raster-audit.md)，逐字图见[小尺寸对照](tsukushi-a-v9-small-size-topology-review.png)）。此项单独作为 hinting/尺寸敏感性诊断，不当作向量拓扑失败；15字已逐项放大审阅。源字体含 hinting，候选不含，低像素网格的组件计数会受渲染器量化影响。
- 过渡版 V9 的保存后 FreeType 审计曾确认“颜”从8组件/0孔洞变为6/1、“暖”从4/3变为3/4；这是实际损坏，不是原型误报。修复负空间与组件保护后，最终两字均恢复源拓扑。原型对“美”“绣”“走”的早期预测没有在独立 FreeType 栅格中复现，因此没有据此减细或改动这些字。
- 单轮廓自交检查分别运行于源字体、几何基底和最终候选：共189条记录、0失败。该检查不测试同一字形不同轮廓之间的相交，也不代表审美或设备验收。
- 逐样本 CSV 保存 advance、LSB、完整 x/y 边界、连通域、孔洞、48 px/em 诊断和 geometry→candidate IoU。另存一张63项总览、一张重点字放大、一张15字小尺寸诊断、草图研究、笔宽参照及端头/电框细节图，便于视觉复核。

### 笔宽代理（900 px/em 骨架距离估计）

| 字体/阶段 | 唯一样本 | 每字中位宽的总体中位数 | 跨字 CV | 字内 CV 均值 | 字内 CV 最大值 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 筑紫 A D/400 源 | 62 | 76.739 FU | 0.07813 | 0.07454 | 0.17484（森） |
| 几何基底 | 62 | 76.979 FU | 0.07886 | 0.07890 | 0.19756 |
| V9 共享宽度候选 | 62 | 74.913 FU | 0.00952 | 0.05101 | 0.15849（森） |
| Noto Sans SC 400 授权参照 | 62 | 73.889 FU | 0.06615 | 0.17626 | 0.29859（必） |

V9 的跨字中位宽离散度显著降低，且统一笔宽可在全样本对照图中直接观察；CV仍只是骨架距离代理，不证明所有接点处的视觉重量相同。候选的字内最大CV仍为“森”的0.15849，不将量化目标写成“完美等粗”。

### U+7535「电」：保留 advance，不伪称可见外宽完全不变

- 实测 divider centerline：几何基底462.0646 FU，最终候选461.6250 FU，残差约0.44 FU；框架中线带约为191–651 FU。
- 在带中心±10 FU处量得横向骨架跨度约650.63→633.30 FU（约缩2.66%）；候选仍按共同74 FU目标重建，未以加厚隔断换取缩距。
- advance source / geometry / candidate 均为950 FU。ink bbox 宽度为819 / 819 / 814 FU；候选边界 xMin/xMax 为108/922 FU，源与几何基底为111/930 FU。候选可见宽度仍少5 FU，中心端也有约0.44 FU残差；这是已量出的剩余差异，**不说外侧可见宽度或中线完全不变**。

## 复现与测试

输入字体只存在本机 `/tmp`，以下命令是本机研究记录，不是可分发的字体配方：

```sh
PYTHONPATH=. /tmp/selffont-venv/bin/python -m unittest discover -s tests -v
/tmp/selffont-venv/bin/python build.py --check

PYTHONPATH=. /tmp/selffont-venv/bin/python tools/tsukushi_a_preview_simplify.py \
  --font /tmp/zhuziawan-source.ttf \
  --output /tmp/zhuziawan-v9-geometry.ttf

PYTHONPATH=. /tmp/selffont-venv/bin/python tools/build_tsukushi_a_v9.py \
  --font /tmp/zhuziawan-source.ttf \
  --out /tmp/zhuziawan-v9.ttf \
  --shared-width 74 \
  --electric-frame-scale-x 0.97 \
  --px 1400

PYTHONPATH=. /tmp/selffont-venv/bin/python tools/audit_tsukushi_a_candidate.py \
  --source /tmp/zhuziawan-source.ttf \
  --geometry /tmp/zhuziawan-v9-geometry.ttf \
  --candidate /tmp/zhuziawan-v9.ttf \
  --csv docs/round-preview/tsukushi-a-v9-sample-audit.csv \
  --markdown docs/round-preview/tsukushi-a-v9-raster-audit.md

CHARS=$(PYTHONPATH=. /tmp/selffont-venv/bin/python -c \
  'from tools.tsukushi_a_preview_simplify import CHARS_63; print(CHARS_63)')
PYTHONPATH=. /tmp/selffont-venv/bin/python tools/check_self_intersect.py \
  /tmp/zhuziawan-source.ttf /tmp/zhuziawan-v9-geometry.ttf /tmp/zhuziawan-v9.ttf \
  -- "$CHARS"
```

- 单元测试：32项通过；仓库生产逻辑 `build.py --check`：9项通过（不是 V9 字体生产构建）。
- 以相同源 TTF 与参数独立构建两次，产物逐字节一致；候选 SHA-256：`b12338d955faf6f3ad5b7750a72ffaf3b93aa6d05eba540ecb08a6c6d9a28a0b`，仅为本机 `/tmp/zhuziawan-v9.ttf`。
- 所有结论只覆盖当前固定样本、单一静态字重与这些自动化/图像检查。没有外部字体设计师签核、真机截图或完整生产字库测试；研究图不是视觉通过凭证。
