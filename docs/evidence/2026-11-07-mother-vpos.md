# 2026-11-07 · 竖向定位：补上一直没修的那一半

上一轮只做了横向（`fix_hpos.py`）。竖向一个字没动，所以「有的字浮高、有的沉」还在。
这一轮补竖向，母版包与自版字体两条路一起修。

## 一、量出来的事实（母版 `97e9dd4` 原字节，去残墨的字面框）

满宽满高（墨宽 ≥850、墨高 ≥850）汉字 **25,909** 个，设计中线取它们墨心的中位数 **377.5**：

| 读数 | 只修横向 | 横竖都修 |
| --- | ---: | ---: |
| 中位 \|dcy\| | 4.5 | **4.0** |
| 最大 \|dcy\| | **47.0** | **20.5** |
| \|dcy\|>20 的字数 | **1,594（6.15%）** | **147（0.57%）** |
| \|dcy\|≤20 占比 | 93.85% | **99.43%** |
| 平移过的字 | — | 1,447（位移中位 24，最大 +47） |

偏得最多的：`幵 +47`、`珥 +47`、`羽 +46`、`平 +42`、`琿 +42`、`研 +42`、`雨 +42`。
另有 189 个字 \|dcy\|>30、8 个字 >40。

## 二、为什么「只平移」

主人 2026-11-05 原话「修水平高度加定位」，并明令不许 `box_align` 那种拉伸。所以竖向也只做
一件事：整字沿 y 平移 `dy = 设计中线 − 墨心`。轮廓点相对彼此一个不动，`advance` 与 `lsb`
都不碰（竖向没有字宽概念）。验收三条：

- 每个被动过的字，所有点的 **y 位移处处相等**（容差 0）→ 纯平移；
- 这些点的 **x 一个都没动**；
- 全库 `advance` / `lsb` **一个没变**。

实测三条全 0。

## 三、设计中线为什么不是 500

汉字不撑满 0..1000 的字格，母版自己的设计重心在 377.5。强行对齐 500 等于把整库抬起 122 单位，
那是改设计不是修定位。所以中线取「原字体满宽满高字墨心的中位数」，并在图上写死这个数。

## 四、自版字体同步修（这一条是上一轮漏掉的）

`tools/cjk_vf.py` 的逐字对齐用 `tools/master_box.bin`，而那张表量的是**未修正母版**。
于是自版把母版的竖向偏差原样抄了过去——实测 12 字预览：`平 −41.5`、`幵 −47.0`、`珥 −47.0`、
`羽 −45.5`、`雨 −41.5`、`研 −41.5`，与母版逐单位相同。

改法：`box_align.apply()` 里套同一条竖向修正规则（`fix_vpos.corrected_box`）。表不用重生成，
横向口径一个字节没变。修后 12 字预览：

| 字 | 修前 dcy | 修后 dcy |
| --- | ---: | ---: |
| 平 | −41.5 | **+0.5** |
| 幵 | −47.0 | **0.0** |
| 珥 | −47.0 | **0.0** |
| 羽 | −45.5 | **+0.5** |
| 雨 | −41.5 | **+0.5** |
| 研 | −41.5 | **+0.5** |
| 田 | −20.5 | −20.5（阈值内未动） |

IoU（同基线 200px，12 字）：中位 **0.879 → 0.894**，最低 **0.233 → 0.534**。

## 五、图

- `2026-11-07-mother-vpos-grid.png`：母版，上行只修横向、下行横竖都修；格下写 `dcy`。
- `2026-11-07-mother-vpos-overlay.png`：母版叠影，灰=只修横向、黑=横竖都修。
- `2026-11-07-mother-vpos-text.png`：母版整段文字对照。
- `2026-11-07-mother-vpos-dist.png`：全库分布，1,594 → 147。
- `2026-11-07-self-vpos-grid.png`：自版 12 字预览，与母版同一把尺子（中线 377.5）。
- `2026-11-07-self-vpos-overlay.png`：自版叠影。

## 六、包

**母版定位修复包（横竖都修）**：`build-26.11.7.1.337`，120,950,493 B，5 天。

- 运行：https://github.com/Sumicya/Selffont/actions/runs/42318742123
- 下载：https://github.com/Sumicya/Selffont/actions/runs/42318742123/artifacts/13551574965
- 步骤 9「修水平与竖向定位」、步骤 12「验收（纯平移、字宽不变、横竖墨心归位）」都是 success。
  验收新加两条竖向断言：`|dcy|≤20` ≥99%，且必须比改前高。

## 七、复算

```bash
gh api "repos/max32002/maruko-gothic/contents/CJK%20SC/MarukoGothicCJKsc-Regular.ttf?ref=97e9dd4" \
  -H "Accept: application/vnd.github.raw" > work/MarukoGothicCJKsc-Regular.ttf
python tools/fix_hpos.py work/MarukoGothicCJKsc-Regular.ttf -o work/hpos/MarukoGothicCJKsc-Regular.ttf
python tools/fix_vpos.py work/hpos/MarukoGothicCJKsc-Regular.ttf -o work/vpos/MarukoGothicCJKsc-Regular.ttf
python tools/fig_vpos.py --before work/hpos/MarukoGothicCJKsc-Regular.ttf \
  --after work/vpos/MarukoGothicCJKsc-Regular.ttf --mode dist --centre 377.5 \
  --label-font work/hpos/MarukoGothicCJKsc-Regular.ttf --out docs/evidence/2026-11-07-mother-vpos-dist.png
```

## 八、未验证

- 真机观感：没有设备、没有 adb，所有读数都是单位级（em/1000），不是系统渲染后的像素级。
- artifact 字节：本机对 `*.blob.core.windows.net` 是 TLS EOF，取不回包；包内容只能由流水线
  自己的断言（`packed == work/vpos/...` 逐字节）作证。
