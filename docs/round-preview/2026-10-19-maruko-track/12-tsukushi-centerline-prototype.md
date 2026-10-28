# 筑紫中轴 → 马路口轮廓原型（2026-10-21）

## 为什么这次改轮廓

用户指出现有字体轮廓“根本没有筑紫和马路口的样子”。这个判断属实：仓库当前生产默认仍是 `build.py` 中的 WenYuan Rounded VF；前面的中心线长度审计只读原轮廓，完全没有改字体。此次不再停留在长度统计，生成了一个实际轮廓重建预览。

## 方法

- 结构参考：筑紫 A 圆 D 的静态 TTF `FZFWZhuZiAYuanJWD.TTF`（仓库 `Aphcity/aphcity-assets`，提交 `452beaced71140f2b10c5dace25266cfbbd933a8`，路径 `fonts/FZFWZhuZiAYuanJWD.TTF`；字体名称表为 `FZFW ZhuZi A YuanS D / 方正FW筑紫A圆 简 D`）。文件 SHA-256：`b82a8d44e1e75dcc9aa83292ec4bcd00c2b9e89838244a33b7d1a480287166b0`。仓库没有声明该文件的授权；它只在本机 `/tmp` 作为研究参考，不进仓库、不随包分发。
- 轮廓基底：马路口固定提交 `97e9dd4a2fdde58084dde8d022de253f8d8415e9` 的 Light / Regular / Medium 静态 TTF（OFL，来源与哈希见本目录 README）。
- 对 62 个唯一字符，将参考字形栅格化到 1200px，提取中轴骨架；骨架归一到马路口 Regular 的字面框，再按马路口原三档的全样本全局中位笔宽重建成填充轮廓。三档目标笔宽为 Light `37.03 FU`、Regular `62.01 FU`、Medium `87.94 FU`。输出保留马路口的字宽/度量，不搬运筑紫的原始外轮廓点序列；轮廓由共享中轴和笔宽重新生成。
- 轮廓以栅格边界追踪后自适应弧长重采样，单个轮廓最多 512 个 on-curve 点；小于 8 FU 周长的栅格碎片过滤。当前用 `--topology-policy independent` 生成三档静态研究预览。

实现工具：`tools/stroke_centerline_rebuild_prototype.py`。它只支持研究预览，未接入 `build.py`。

## 可视结果（历史图像已清理，文字留档）

2026-10-22 按用户要求清理了本节当时生成的沙箱 PNG；以下只描述历史图页内容，不是当前图像证据或本轮设计入口：

- 曾有一页“包”字五方对照：筑紫 A 圆 D、筑紫 B 丸公开样张、当时 WenYuan 流水线、马路口原 Regular、以及筑紫中轴 + 马路口笔宽原型。两种筑紫来源不是同一款。
- 曾有 14 字放大对照（原 13 字视觉集加“包”），横向对照筑紫 A 圆 D、马路口原三档和三个重建静态预览。
- 曾有 Light/Regular/Medium 三页全样本检查，各覆盖 63 项（62 个唯一字），逐字对照筑紫 A 圆 D、相应马路口源字重和重建结果。

当时目视记录认为，“包”及箱体、折弯、斜向代表字已从 WenYuan 的硬黑体轮廓转向筑紫的骨架/曲线路径，同时仍保留马路口的字面框和字重级差。它只是方向性原型的历史观感记录，不是全字体审美验收或“已完全像筑紫”的结论；A 圆 D 与 B 丸样张有不同设计，不能混称。

## 核验与边界

- 62 个唯一字 × Light / Regular / Medium = 186 个输出字形；`tools/check_self_intersect.py` 单轮廓自交检查 `0/186`。这不替代多轮廓重叠、栅格渲染或不同字号人工复核。
- 此输出使用 `independent` 拓扑：三档静态字形的轮廓数/点数不保证相同。尝试 `compatible` 模式并将笔宽修正限制在 ±25% 时，`暖` 的 Light 仍无法与 Regular 对齐。扩大修正到约 +58% 才能保住同一轮廓拓扑（Light 目标笔宽会从约 37 FU 被推到约 59 FU），会显著压扁字重差异。因此**没有生成可变字体**，也不能把三档静态预览当作可插值主控。
- `build.py` 和生产输出未改；默认仍是 WenYuan VF。新静态 TTF 仅留在 `/tmp/maruko-tsukushi-centerline-63-independent/`，未提交或打包。全字库覆盖、语义笔画逐笔核对、可变字重兼容、生产构建与真机验收都未完成。

复现（筑紫 TTF 需先在本机放到 `/tmp/FZFWZhuZiAYuanJWD.TTF`；该文件不在仓库）：

```sh
chars='一二三十口日回国了乙人入八木林森永心必水走建进这远道你好中语言文字书写规范长美丽颜色锦绣风雨雪龙马鸟虫鱼电子已己巳也包囚暖田'
.venv/bin/python tools/stroke_centerline_rebuild_prototype.py \
  --font Light=/tmp/selffont-maruko/Light.ttf \
  --font Regular=/tmp/selffont-maruko/Regular.ttf \
  --font Medium=/tmp/selffont-maruko/Medium.ttf \
  --reference Regular \
  --centerline-font /tmp/FZFWZhuZiAYuanJWD.TTF \
  --chars "$chars" --mode shared --px 1200 \
  --points-per-contour 512 --topology-policy independent \
  --out-dir /tmp/maruko-tsukushi-centerline-63-independent
```
