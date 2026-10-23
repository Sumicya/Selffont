# 筑紫 A D/400 V8 研究候选：实现与验证记录

> 状态：可逆研究稿，待主人审阅；没有审美通过结论。静态候选 TTF 只放在本机 `/tmp`，不入库、不进入 `build.py` 或发布包。

## 输入、许可与范围

- 研究源：[Totoro625/totoro625-font-family 固定提交](https://github.com/Totoro625/totoro625-font-family/tree/3ad8753c4bce763682174a41cd742fb344be3c36) `3ad8753c4bce763682174a41cd742fb344be3c36`；字体 blob `ed7e2afa0331494c24676db68204471cc2e8dd9e`。该来源没有找到正式字体许可证，所以源 TTF 与派生 TTF 均不提交、不打包，也不声称可再分发。
- 参照：Google Fonts 的 Noto Sans SC 400 静态实例；[源码固定提交](https://github.com/google/fonts/tree/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/notosanssc)，[SIL Open Font License 1.1](https://github.com/google/fonts/blob/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/notosanssc/OFL.txt)，版权声明为 Adobe 2014–2021。该字体仅用于研究共享笔宽/字重行为，74 FU 目标按样本宽度中位数校准；没有复用它的轮廓、点坐标或字形结构。
- 样本：`CHARS_63` 中 63 个条目、62 个唯一字符。U+9E1F“鸟”和 U+4E5F“也”是两个不同样本，草图各自对应其确认字符。所有 62 个唯一字形都经过共享笔宽重建；没有因原几何阶段未修改而跳过样本。
- 本轮只生成单一静态 D/400 研究候选；没有验证 A 的其他字重、全字库、可变字体拓扑、设备渲染或生产构建。

## V8 处理

1. 几何基底使用人工筛选的 22 处钩尾半圆端头，另有 11 处自由端圆头、1 处安全尖端圆化；“己”“已”末笔分别沿切线延长 1.0、1.5 个钩尾闸门宽度后圆收。草图只提供整体造型线索，不作路径映射或逐点临摹。
2. 62 个唯一字形随后按 74 FU 共享目标做骨架距离重建，内部栅格为 1400 px。轮廓重建使用 raw `glyf` 坐标，避免 `TTGlyphSet` 的 LSB 平移被二次写入。对栅格对角接触产生的无效轮廓作几何修复，候选在全样本单轮廓自交预检中无失败。
3. U+7535“电”的中间田框水平骨架绕测得的竖隔断中心线按 0.94 缩放，再以同一 74 FU 半径重绘。此操作改变框架间距，不以加粗隔断来换取更窄开口。
4. 所有样本的 advance width 保持不变；LSB 按新轮廓边界重算，以保持几何基底的绘制原点偏移。字形可见墨迹边界不等同于 advance width，具体差异在下方单列。

## 量化结果

### 样本笔宽代理（900 px 骨架距离估计）

| 字体/候选 | 唯一样本 | 各字中位宽的总体中位数 | 各字中位宽跨字 CV | 字内 CV 均值 | 字内 CV 最大值 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 筑紫 A D/400 源字形 | 62 | 76.739 FU | 0.07813 | 0.07454 | 0.17484（森） |
| V8 研究候选 | 62 | 74.921 FU | 0.00961 | 0.05294 | 0.15849（森） |
| Noto Sans SC 400 参照 | 62 | 73.889 FU | 0.06615 | 0.17626 | 0.29859（必） |

以上是同一脚本的光栅/骨架测量代理，不是像素级严格等宽证明，也不能判定接点处的视觉重量。V8 跨字中位宽离散度变小是可量化事实；字内仍有自然结构差异，图像需由主人审阅。

### U+7535“电”

- 1800 px 骨架采样得到的竖隔断中心线：几何基底约 462.47 FU，V8 约 461.83 FU，残差约 0.63 FU。
- 同一研究口径下框架侧向骨架跨度：约 650.47 → 611.58 FU（缩至约 94%）。外侧框线中心随框架一起内移，重绘使用共同 74 FU 半径；没有通过增加隔断粗细实现缩距。
- advance width 保持 950 FU。ink bbox 从几何基底约 819 FU 收至候选约 795 FU（减少约 24 FU / 2.9%）；对应 xMin/xMax 从约 111/930 变为 127/922，LSB 从 107 调整为 123。因而只报告 advance 不足以描述可见宽度变化，本轮不声称 ink bbox 宽度保持不变。

## 检查与复现

- `PYTHONPATH=. /tmp/selffont-venv/bin/python -m unittest discover -s tests -v`：19 项通过。
- `/tmp/selffont-venv/bin/python build.py --check`：9 项通过；这是仓库生产构建逻辑检查，不是候选字体生产构建。
- `tools/check_self_intersect.py` 对源字体、几何基底和 V8 各检查 63 个样本条目：189 条记录、0 个单轮廓自交失败。该工具不检查同一字形中不同轮廓之间的相交，也不证明审美质量。
- 同一源文件和参数独立构建两次，TTF 逐字节一致。最终候选 SHA-256：`c678cf0698e82ea707b55ac81848bc9d7e7a10f507a98d2d63001c7671c7c136`；文件仅为 `/tmp/zhuziawan-v8.ttf`。仓库中只保存四张预览 PNG、脚本和此记录，不保存字体文件。
- 本地生成时使用 `/tmp/zhuziawan-source.ttf`、`/tmp/NotoSansSC-400.ttf`；几何基底、候选和四张预览的命令为：

```sh
PYTHONPATH=. /tmp/selffont-venv/bin/python tools/tsukushi_a_preview_simplify.py \
  --font /tmp/zhuziawan-source.ttf \
  --output /tmp/zhuziawan-v8-geometry.ttf

PYTHONPATH=. /tmp/selffont-venv/bin/python tools/build_tsukushi_a_v8.py \
  --font /tmp/zhuziawan-source.ttf \
  --out /tmp/zhuziawan-v8.ttf \
  --shared-width 74 \
  --electric-frame-scale-x 0.94 \
  --px 1400

PYTHONPATH=. /tmp/selffont-venv/bin/python tools/render_tsukushi_a_preview.py \
  --baseline /tmp/zhuziawan-source.ttf \
  --geometry-base /tmp/zhuziawan-v8-geometry.ttf \
  --variant /tmp/zhuziawan-v8.ttf \
  --reference-font /tmp/NotoSansSC-400.ttf \
  --outdir docs/round-preview
```

源字体没有正式许可且未随仓库提供，因此其他人无法仅靠仓库文件重建相同的候选轮廓；上面的命令记录的是本机研究流程，不是可分发字体配方。