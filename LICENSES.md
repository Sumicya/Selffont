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
- [Noto Unicode](https://github.com/MY1L/Unicode/releases/tag/NotoUni7)
- [MapleMono](https://github.com/subframe7536/maple-font)
- [Plangothic](https://github.com/Fitzgerald-Porthmouth-Koenigsegg/Plangothic)
- [Unicodia* & NewGardiner](https://github.com/Mercury13/unicodia/tree/main/Fonts) (作者声明/﻿JSesh Fonts Licenses/OFL)
 
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
- [Noto Unicode](https://github.com/MY1L/Unicode/releases/tag/NotoUni7)
- [MapleMono](https://github.com/subframe7536/maple-font)
- [Plangothic](https://github.com/Fitzgerald-Porthmouth-Koenigsegg/Plangothic)
- [Unicodia* & NewGardiner](https://github.com/Mercury13/unicodia/tree/main/Fonts) (Author's statement/﻿JSesh Fonts Licenses/OFL)
 
Unless otherwise specified, all fonts are licensed under OFL-1.1 by default.
 
Primary font usage is unrelated to the MFGA module.
## Selffont 第一阶段新增资源

- 主字体候选：[WenYuan Rounded SC VF v1.010](https://github.com/takushun-wu/WenYuanFonts/releases/tag/v1.010)，固定校验信息见 `config/font-source.json`，完整版权及 OFL/RFN 声明见 `licenses/WenYuan-OFL.txt`。
- 主字体作为外部构建输入，不提交大二进制文件。本阶段保持原版字体字节、字形、cmap 与内部名称不变，不以文渊的保留名称发布改造字体。
- SELFUSE 的 FZYJHK 仅作为用户提供的外观参考，不在新构建中继承数字主字体文件，也不推断其再分发许可。
- `webroot/probe.ttf` 为本项目生成的诊断几何图形字体；见 `licenses/Web-Probe.txt`（CC0 1.0）。
- 构建器显式输入的 MFGA 基础包只提供补充字体；各资源仍须遵循其自己的许可，基础包归属说明随包保留。现有上游字体说明不构成对任意输入包的许可保证。
