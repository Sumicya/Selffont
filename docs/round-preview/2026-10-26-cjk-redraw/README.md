# 2026-10-26 覆盖补齐与二创四字

## 一、覆盖去哪了（实测）

主字体是文渊圆体 `WenYuanRoundedSCVF.ttf` v1.100（48,779,368 B），不是 Maruko。

| 对象 | 码位总数 | 主人贴的那批 |
|---|---|---|
| 文渊主字体 | 33,032 | **0 / 315** |
| 构建 `prune_blank_mappings` 后 | 33,032 → 33,032 | 剪掉 **0** |

文渊基底停在 Unicode 14 之前：连 U+11F00（Kawi）、U+1E030（西里尔修饰）都没有。
主人贴的 315 个码位里 298 个是 Unicode 15–18 新分配，17 个到 Unicode 18.0 仍未分配。

## 二、按上游做法补（不自己画）

上游 MakeFontsGreatAgain 的做法是投放分版本补充字件、由 fonts.xml 补字区兜底。
照此接进 `build.py` 的 `SUPPLEMENTAL_FONT_SOURCES`：

| 字件 | 来源 | 覆盖 |
|---|---|---|
| `Unicode18-new.ttf` | MFGA git blob `4314ad3`，OFL | 162 |
| `Unicode17-new.ttf` | MFGA git blob `e877906`，OFL | 29 |
| `NotoSansPro.otf` | MFGA git blob `a37c8e3`，OFL | 47 |
| `UnicodiaFunky.ttf` | Mercury13/unicodia，OFL | 69 |
| `NotoEmoji.ttf` | google/fonts，OFL | 85 |
| `Noto-COLRv1.ttf` | googlefonts/noto-emoji，OFL | 104 |

并集 **298 / 315**。余下 17 个码位在 Unicode 18.0 仍未分配，任何字库都没有标准字形：
U+10EEF、U+1CED5..U+1CEDC、U+1FAC7/C9/CA/CB/DE、U+1FAEC/ED/EE。

## 三、二创四字

不再修补原版轮廓，按规则生成（见 `tools/design_symbols.py`）：

- 笔宽 82（`HW_CJK=41`），取自文渊「一」的竖切实测；
- 字面 y 30..960、x 60..940，对齐文渊实测的 x 44..960 / y 162..999；
- 端头一律半径 41 标准半圆，折角为切线圆弧，内外双侧都圆。

上图为文渊原版（四字皆带钩），下图为二创（四字无钩）。

![对照](乙了子九-去钩对照.png)

## 四、仍未做

- 二创只覆盖 4 字（乙了子九），`也/包/必/電` 等仍未重画。
- `子` 的斜撇与竖的转接处，比文渊原版更靠下一点，观感待主人判断。
