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
 
当前主字体为下方说明的 Selffont Maru（Zen Maru Gothic 派生）；基础包中的补充字体仍按各自许可处理

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
 
The current primary font is the Selffont Maru derivative documented below; supplemental fonts from the base archive keep their own licenses.
## Selffont Maru v2.0.0 新增资源

- **Zen Maru Gothic**：固定提交 [`553c872`](https://github.com/googlefonts/zen-marugothic/tree/553c872b216d1290e2902a466edcdc9682f0df6a)，五个静态 TTF 源面，许可 [SIL Open Font License 1.1](https://scripts.sil.org/OFL)，完整文本随包保存在 `licenses/ZenMaru-OFL.txt`。
- 构建期把五个源面改名为派生家族 `Selffont Maru`，安装名 `SelffontMaru-{Light,Regular,Medium,Bold,Black}.ttf`；没有把静态面伪装成可变字体。
- 改名为 OFL 允许的派生操作（上游版权行未声明 Reserved Font Name）；改名步骤断言轮廓、cmap 与逐字形字节不变。
- 手写字形改动只通过 `config/glyph-patches/<Style>.json` 的显式点 patch 进行，产出的仍是 OFL 派生字体，不复制其他字体（含商业字体）的轮廓。
- `webroot/probe.ttf` 为本项目生成的诊断几何图形字体；见 `licenses/Web-Probe.txt`（CC0 1.0）。
- 构建器显式输入的 MFGA 基础包只提供补充字体；各资源仍须遵循其自己的许可，基础包归属说明随包保留。现有上游字体说明不构成对任意输入包的许可保证。
