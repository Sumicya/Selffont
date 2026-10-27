# 字体来源与许可 / Font Sources and Licenses

## CN

本模块包含的字体及其许可证如下：
 
- [Unicode*-New](https://github.com/Numbersf/MakeFontsGreatAgain/tree/main/fonts)：此字体的部分字形提取自 Unicode PDF，如有侵权请立即向我们提出
- [NotoSansPro.otf](https://github.com/Numbersf/MakeFontsGreatAgain/blob/main/fonts%2FNotoSansPro.otf)：此字体是由多个 Noto 家族及其他 OFL-1.1 许可的字体合并
- [Iosevka](https://github.com/be5invis/Iosevka)
- [UFSTemp Alpha](https://github.com/Losketch/UnicodeFontSet-magisk-module/blob/main/font-source%2FUFSTempAlpha.fcp)
- [TempSeal](https://github.com/Losketch/Fonts/tree/main/TempSeal)：Do What the Fuck You Want to Public License
- [SatisarSharada](https://github.com/virtualvinodh/satisarsharada)
- [Noto Emoji](https://github.com/googlefonts/noto-emoji)
- [Noto Music](https://github.com/google/fonts/tree/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/notomusic)：SIL OFL 1.1；固定版本许可证随包（`licenses/NotoMusic-OFL.txt`）
- [Noto Unicode](https://github.com/MY1L/Unicode/releases/tag/NotoUni7)
- [MapleMono](https://github.com/subframe7536/maple-font)
- [Plangothic](https://github.com/Fitzgerald-Porthmouth-Koenigsegg/Plangothic)
- [Unicodia* & NewGardiner](https://github.com/Mercury13/unicodia/tree/main/Fonts) （作者声明/﻿JSesh Fonts Licenses/OFL）
- [Maruko Gothic](https://github.com/max32002/maruko-gothic)（**主字体**，SIL OFL 1.1）：`CJK SC` 的 Regular / Medium 两份直接作为模块主字体分发，只归一行度量、剪空壳映射、改家族名，轮廓与 cmap 逐字节不动；许可证全文随包（`licenses/MarukoGothic-OFL.txt`）
 
无特殊说明则默认其为 OFL-1.1 许可
 
主字体调用与MFGA模块无关

## EN

The fonts included in this module and their licenses are as follows:
 
- [Unicode*-New](https://github.com/Numbersf/MakeFontsGreatAgain/tree/main/fonts)：Some glyphs in this font are extracted from Unicode PDFs. If there is any infringement, please inform us immediately.
- [NotoSansPro.otf](https://github.com/Numbersf/MakeFontsGreatAgain/blob/main/fonts%2FNotoSansPro.otf): This font is a merged compilation of multiple Noto family fonts and other fonts licensed under OFL-1.1.
- [Iosevka](https://github.com/be5invis/Iosevka)
- [UFSTemp Alpha](https://github.com/Losketch/UnicodeFontSet-magisk-module/blob/main/font-source%2FUFSTempAlpha.fcp)
- [TempSeal](https://github.com/Losketch/Fonts/tree/main/TempSeal)：Do What the Fuck You Want to Public License
- [SatisarSharada](https://github.com/virtualvinodh/satisarsharada)
- [Noto Emoji](https://github.com/googlefonts/noto-emoji)
- [Noto Music](https://github.com/google/fonts/tree/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/notomusic): SIL OFL 1.1; the pinned license text is included in the module (`licenses/NotoMusic-OFL.txt`).
- [Noto Unicode](https://github.com/MY1L/Unicode/releases/tag/NotoUni7)
- [MapleMono](https://github.com/subframe7536/maple-font)
- [Plangothic](https://github.com/Fitzgerald-Porthmouth-Koenigsegg/Plangothic)
- [Unicodia* & NewGardiner](https://github.com/Mercury13/unicodia/tree/main/Fonts) (Author's statement/﻿JSesh Fonts Licenses/OFL)
- [Maruko Gothic](https://github.com/max32002/maruko-gothic) (**primary font**, SIL OFL 1.1): the `CJK SC` Regular / Medium files are shipped as the module's main font with only metric normalisation, blank-mapping pruning and a family rename; outlines and cmap are byte-identical. The full license text ships in the module (`licenses/MarukoGothic-OFL.txt`).
 
Unless otherwise specified, all fonts are licensed under OFL-1.1 by default.
 
Primary font usage is unrelated to the MFGA module.
## Selffont 新增资源

- 主字体（默认源）：[Maruko Gothic](https://github.com/max32002/maruko-gothic)（`CJK SC` 目录的 Regular / Medium 两份），SIL OFL 1.1，**没有保留字体名**；固定提交 `97e9dd4`，完整声明随包（`licenses/MarukoGothic-OFL.txt`）。换任意字体请自行确认其许可，声明随源自带。
- Noto Music（补回 U+1D100..U+1D1FF 中约 200 个缺失音符字形）：固定于 Google Fonts 提交 `e7db6ca603fd4862010383ff17ffd6cc4ffac1c0`，SIL OFL 1.1；只在构建时下载，不提交字体二进制，许可证随包。
- 主字体是外部构建输入，不提交大二进制；安装副本归一行度量、剪除空壳映射、内部名改为 'Selffont SC'（归一与剪除均属 OFL 意义上的修改，按 OFL 要求保留原版权声明并随包附许可全文）。
- 2026-10-27 起**不再自绘 CJK 字件**：上一版的 `SelffontCJK-Regular.otf`（按母版骨架重画）与 `tools/design_cjk.bin` 一并删除，模块直接分发母版本体——自绘收 19,352/20,977 字、40.6 MiB，母版 20.1 MiB 覆盖全部 20,977 字。原「二创」只作为过程记录留在 `docs/round-preview/`。
- 曾试过的寒蝉全圆体/半圆体自 v2.7.0 起不在产线：其 OFL 声明也随之删除，不再随包。构建含空壳映射剪除防线。
- 基础包只提供补充字体资源；各资源遵循其自己的许可，基础包归属说明随包保留。`build.py` 里的默认源哈希只是提示，自选来源的许可由你确认。
