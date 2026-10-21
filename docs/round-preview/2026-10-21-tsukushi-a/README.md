# 筑紫 A 回退对照：原样与钩尾简化预览（2026-10-21）

## 当前结论

用户指出此前 `Zolyn/TsukuBRdGothic-Std` 的筑紫 B 候选“包”字字重不符，已撤销其作为有效 B 参考的资格。Fontworks 的[筑紫 B 产品页](https://fontworks.co.jp/fontsearch/tsukubrdgothicstd-b/)与[LETS 字体页](https://lets.fontworks.co.jp/fonts/58)证明官方产品存在，但本地没有与目标字重匹配、来源可核验且具备用途许可的 B 字体文件；因此按用户给出的回退条件，本轮改用筑紫 A。旧 B 候选图已从当前树移除，不能再当作本轮样张。

## 两版对照

- [63 项 × 两版总览](01-tsukushi-a-d-63-baseline-vs-hook-simplified.png)：同一筑紫 A D 静态源字重的原始轮廓，与只对检测到的钩尾做简化的预览；每项同字号、同字面框。橙框标出 7 个改动字形，重复样本“国”仍按 63 项清单保留。
- [7 个改动字形放大与轮廓叠加](02-hook-end-detail-overlay.png)：蓝色为原 A 轮廓，橙色为提案轮廓；叠色仅用于看差异，不是第三版。
- [源文件、点数差异与逐轮廓自交检查记录](04-validation.txt)：记录 63/62 样本、两份本机字体的元数据/哈希、7 个改动字形和检查命令输出。

“简化”在此明确限于钩尾/端头：用现有 `tools/hook_cut.py` 的切钩路径生成研究预览，不是通用曲线控制点压缩，也不声称完成了四类笔画问题的全量修复。A D 与简化版保持相同 `usWeightClass=400`，没有通过缩放或替换字重制造差异。样本内实际改动为 7 个唯一字形、8 处钩（“包”检测出 2 处）；“乙”没有检出钩，未改。改动字形的轮廓点数：`U+4E86 了 68→61`、`U+7535 电 92→87`、`U+5B50 子 85→80`、`U+5DF2 已 78→70`、`U+5DF1 己 82→75`、`U+4E5F 也 105→98`、`U+5305 包 121→109`。这些数字只描述点数变化，不等于质量评分。

## 字体来源与字重边界

本轮基准文件为社区仓库 [`Totoro625/totoro625-font-family`](https://github.com/Totoro625/totoro625-font-family) 的 `zhuziawan/zhuziawan.ttf`，仓库提交 `3ad8753c4bce763682174a41cd742fb344be3c36`，Git blob `ed7e2afa0331494c24676db68204471cc2e8dd9e`，本机文件 SHA-256 `1b5b1c00c0bccf6feda1c55434879016d4c8ced78677d2b83ed2ae756e19c11c`。字体名称为 `FOT-TsukuARdGothic Std D`，UPM 1000、`usWeightClass=400`、静态 TTF、无 `fvar`；63 项均有映射，仓库 CSS 也把此字体标为 `font-weight:400`。该仓库的树中只有这一份 `zhuziawan.ttf`（另有同一字重的网页子集），README 虽提到系列有五字重，但这一个 TTF 文件本身只是一份 D 静态字重；不能把它说成五字重套装，也不能从中伪造 Light / Regular / Medium 或做三档拓扑兼容结论。

该社区仓库没有找到正式字体许可证。这里只保存少量研究对照 PNG，不把原字体或派生 TTF 加入仓库、不打包、不声称取得再分发授权；字体来源身份与许可边界仍需以权利人/正式授权为准。

## 验证与限制

- 样本清单是 63 项、62 个唯一字；完整覆盖，无缺字。
- 原版与临时简化版均对这 62 个唯一字通过 `tools/check_self_intersect.py` 的单轮廓自交检查。它不检查同字形轮廓之间的设计性重叠，也不代替逐字语义、字号或设备渲染审核。
- 简化只处理钩尾端头；粗细统一、框形端头突出和其它圆角问题未在此版处理。此版是讨论稿，不是用户已批准的最终设计。
- 不改生产字体、不接 `build.py`、不提交 TTF。Light / Regular / Medium 三档与可变字体拓扑要求因缺少可信的 A 多字重源而尚未满足。

## 可复现输入

```text
源 TTF：/tmp/ZhuZiAWan.ttf
简化预览 TTF（不入库）：/tmp/zhuzi-a-hook-selected.ttf
清单：docs/round-preview/2026-10-19-maruko-track/09-笔画宽度中轴试验-3档字重-63项.txt 中的 CHARS_63
图形工具：tools/render_grid.py 的 fontTools 轮廓绘制方式；两版排版图为本轮临时组合脚本生成
```

本轮重找字体、A 回退、规范文件缺失和十点复盘见[检讨](03-ten-point-review.md)。此前错误 B 参考记录见[作废说明](../2026-10-21-tsukushi-b/README.md)。
