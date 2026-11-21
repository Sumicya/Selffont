# 「合格」阈值：按母版实测线定（2026-11-03）

> ## 更正（2026-11-05，改前 → 改后）
>
> 本文下方**保留原文不删**（黑历史不删），但其中四处已被推翻，以本节为准：
>
> 1. **「130 里有 115 个是管线画的」→ 错。** 改前：并排两个总数就断言包含。改后：求交得
>    **共有 106 / 默认全开独有 24 / 默认全关独有 9**，净差 15 只说明个数差，推不出包含。
>    病根在管线（106），三个默认是新添两成（24），不是「15 个」。
> 2. **两套分母（154 vs 141）并排 → 改。** 改后：只在**共同 137 字**上逐字相减，
>    逐字差中位 **+0.11 px**、均值 +0.21、p95 +2.88、最差 +3.88。母版自比恒为 0。
> 3. **「丢笔 17 字」写在旁证里 → 挪进判据。** 改后：`丢笔 == 0` 是一条硬判据，当前 **17，不过**。
> 4. **判据 1–4 用母版 p95 画圈 → 停用。** 改后：判据落在①逐字差（中位 ≤ 0.25 px、p95 ≤ 1.00 px）
>    与②绝对量（自交 = 0、丢笔 = 0），不再用分位数画圈，也不再有「母版自己过不了」的线。
>
> 另外：本文说的「母版」是**上游源文件** `MarukoGothicCJKsc-Regular.ttf`（20,084,736 B），
> 不是仓里那个 121 MB 的 Actions artifact `maruko-mother-97e9dd4-10`。两者按
> `mother.yml` 的 sha256 应是同一份字节，但本文从未下载过那个 artifact——本沙箱取不到
> （303 → `productionresultssa4.blob.core.windows.net` → `SSL_ERROR_SYSCALL`，0 B）。
>
> 复算命令：`python tools/compare_fonts.py all <母版> <本版> --b <本版全关> --chars "$(head -1 tools/endcap_sample200.txt)"`

主人 2026-11-03 22:4x 点头第四项：**按母版实测线报上来**。本文就是那条线，以及本版现在过不过。

## 输入

| 对象 | 文件 | 身份 |
|---|---|---|
| 母版 | `MarukoGothicCJKsc-Regular.ttf` | `max32002/maruko-gothic@97e9dd4`，sha256 `e3709389bce13fa75af28cc2370b6175520d97f74dfbf3894ca24838f47241b7`（与 `.github/workflows/mother.yml:28` 一致） |
| 本版 | `work/preview/preview.ttf` | 分支 `arena/ce1ced3e-selffont@0bc16fe`，`tools/design_cjk.bin`，三个默认全开（`IMPLICIT_MERGE=8`、`HW_BIAS=0.8`、`STRAIGHT_TOL=1.5`+`FLATTEN=1`） |
| 本版（对照） | 同上，三个默认全关 | 同上，`SELFFONT_IMPLICIT_MERGE=0 SELFFONT_HW_BIAS=0 SELFFONT_STRAIGHT_TOL=0 SELFFONT_FLATTEN_STRAIGHT=0` |
| 样本 | `tools/endcap_sample200.txt` 第 1 行，200 字 | 仓内固定样本，换机器也一样 |

## 命令（照抄能重做）

```bash
M="/tmp/mg/CJK SC/MarukoGothicCJKsc-Regular.ttf"
CH=$(head -1 tools/endcap_sample200.txt)

python build.py --preview "$CH" --preview-out /tmp/j/prev          # 默认全开
SELFFONT_IMPLICIT_MERGE=0 SELFFONT_HW_BIAS=0 \
SELFFONT_STRAIGHT_TOL=0 SELFFONT_FLATTEN_STRAIGHT=0 \
  python build.py --preview "$CH" --preview-out /tmp/j/off          # 默认全关

python tools/check_straight.py "$M" "$M" --chars "$CH" --json m.json
python tools/check_straight.py "$M" /tmp/j/prev/preview.ttf --chars "$CH" --json p.json

python tools/check_self_intersect.py "$M" -- "$CH" | grep -c '^FAIL'
python tools/check_self_intersect.py /tmp/j/prev/preview.ttf -- "$CH" | grep -c '^FAIL'
```

阈值后面的「过关率」是逐字算的：每个字先取它所有墨带左边缘的中位，再与阈值比较；
分母是该字体重能测出长竖的字数（母版 154、本版 141，差 17 字见下）。

## 母版实测（基线）

| 指标 | 中位 | p95 | 说明 |
|---|---|---|---|
| `rms_med`（边缘相对中位 RMS） | 2.05 px | 6.64 px | 治「整根斜着走」 |
| `rms_fit`（相对直线拟合 RMS） | 1.29 px | 4.97 px | 治「弯」与毛刺 |
| `over2`（偏离 >2 px 的行占比） | 9.61% | 53.34% | 2 px 是 800 px 渲染下肉眼一档 |
| `slope`（px/百行） | 0.63 | 3.42 | 倾斜速度 |
| `width`（墨带宽度） | 46.50 px | 51.00 px | 治「不饱满」 |
| 自交 | **0 / 200 字** | — | 母版一条都没有 |

汇总行（工具自带、各墨带取中位）：母版 `2.05 / 1.29 / 9.61% / 0.63 / 46.50`；本版 `2.09 / 1.44 / 13.62% / 0.70 / 48.00`。

## 拟议「合格」线（母版 p95 + 余量，等点头）

| # | 判据 | 线 | 母版自过 | 本版（默认开） | 判 |
|---|---|---|---|---|---|
| 1 | 逐字 `rms_med` | ≤ 6.89 px（p95 6.64 + 0.25） | 146/154 = 94.8% | 135/141 = 95.7% | 过 |
| 2 | 逐字 `rms_fit` | ≤ 5.22 px（p95 4.97 + 0.25） | 149/154 = 96.8% | 133/141 = 94.3% | 过（擦线） |
| 3 | 逐字 `over2` | ≤ 56.3%（p95 53.34 + 3） | 150/154 = 97.4% | 137/141 = 97.2% | 过 |
| 4 | 墨带宽度中位 | 46.5 px ±4% = 44.6–48.4 | 46.5 | 48.0 | 过 |
| 5 | 自交 | **= 0** | 0/200 | **130/200** | **不过** |

默认全关时自交是 **115/200**，所以 130 里有 115 是管线本身就有的，三个默认再添 15 个。

## 旁证（同一批 200 字，400 px 渲染）

- 墨量比（本版/母版，逐字后取中位）：**1.004**（p10 0.987、p90 1.019）
- 字面外接框（本版/母版）：宽 **1.000**、高 **1.000**
- 母版测得出长竖、本版测不出的字：**17 个**（侠 勠 喸 尸 揰 攨 獠 碨 素 緰 缨 膘 螰 襐 賸 願 駸）——这不是阈值问题，是这些字的竖笔在本版里被切短或变窄到测不出。

## 图上看得见的东西

`2026-11-03-threshold-line.png` 左图两条累计分布几乎重合，说明**直度已经和母版同一档**；
右图六字并排，蓝母版红本版，同字号同基线。图上能看出的差别是笔画交接处的圆角，不是直度。

## 结论（一句话）

直度、粗细、字面这三项，本版已经在母版线上；**唯一不过的是自交，0 → 130/200**。
阈值表可以现在定，自交那一条定了就等于宣布当前产物不合格。
