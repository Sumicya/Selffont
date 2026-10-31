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
- [Maruko Gothic](https://github.com/max32002/maruko-gothic)（母版，SIL OFL 1.1）：二创汉字字库（`SelfroundsCJK-VF.ttf`）的笔画中线全部由它的 `MarukoGothicCJKsc-Regular.ttf` 量出，属于 OFL 意义上的修改作品；改名为 `Selfrounds CJK`，不使用保留名，许可证随包（`licenses/MarukoGothic-OFL.txt`）
 
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
- [Maruko Gothic](https://github.com/max32002/maruko-gothic) (source design, SIL OFL 1.1): every stroke centreline of the self-made CJK font (`SelfroundsCJK-VF.ttf`) is measured from its `MarukoGothicCJKsc-Regular.ttf`; the result is a Modified Version under the OFL, renamed to `Selfrounds CJK`, no Reserved Font Name used, license shipped in the module (`licenses/MarukoGothic-OFL.txt`).
 
Unless otherwise specified, all fonts are licensed under OFL-1.1 by default.
 
Primary font usage is unrelated to the MFGA module.
## Selffont 新增资源

- 主字体（默认源）：[文渊圆体 v1.010 可变字体](https://github.com/takushun-wu/WenYuanFonts/releases/tag/v1.010)(takushun-wu),OFL-1.1，保留字体名 'WenYuan'/'文渊'，完整声明随包（`licenses/WenYuan-OFL.txt`）。换任意字体请自行确认其许可，声明随源自带。
- Noto Music（补回 U+1D100..U+1D1FF 中约 200 个缺失音符字形）：固定于 Google Fonts 提交 `e7db6ca603fd4862010383ff17ffd6cc4ffac1c0`，SIL OFL 1.1；只在构建时下载，不提交字体二进制，许可证随包。
- 主字体是外部构建输入，不提交大二进制；安装副本归一行度量、剪除空壳映射、内部名改为 'Selffont Rounded SC VF'（归一与剪除均属 OFL 意义上的修改，不以保留名 'WenYuan'/'文渊' 发布改造字体）。
- 二创汉字字库（`SelfroundsCJK-VF.ttf`）：母版 Maruko Gothic（`max32002/maruko-gothic` 固定提交 `97e9dd4` 的 `MarukoGothicCJKsc-Regular.ttf`），SIL OFL 1.1。仓库里存的是**笔画中线与逐笔半宽数据**（`tools/design_cjk.bin`，26 MB），字体二进制在构建时按固定拓扑描边（中线等参数采样 + 沿法向偏移 ±半宽 + 固定段数半圆）后现编，不入库。发布名为 'Selfrounds CJK'，不用母版保留名；许可证全文随包（`licenses/MarukoGothic-OFL.txt`）。
- 曾试过的寒蝉全圆体/半圆体自 v2.7.0 起不在产线：其 OFL 声明也随之删除，不再随包。构建含空壳映射剪除防线。
- 基础包只提供补充字体资源；各资源遵循其自己的许可，基础包归属说明随包保留。`build.py` 里的默认源哈希只是提示，自选来源的许可由你确认。
