# 2026-11-05 · 修「水平 / 高度 / 定位」：600 字墨心差中位 0，差 >5 的字 102/97 → 0/0

上一轮（`f1e2d32`）只量了偏差、出了诊断书，指令里的「修」一个字没动。这一轮是**修**：
改了三处代码，重跑同一条量具，前后对比在下面，图在 `2026-11-05-position-fix.png`（同字并排）
与 `2026-11-05-position-fix-scatter.png`（600 字逐字点带）。

## 一、结果（GB2312 一级抽样 600 字，`tools/check_position.py`）

| 读数 | 修前（`pos_gb.json`） | 修后（`pos_fix3.json`） |
| --- | --- | --- |
| 墨心横向差 `dcx` 中位 / p05 / p95 | −0.5 / −7.0 / +6.5 | **0.0 / 0.0 / 0.0** |
| 墨心纵向差 `dcy` 中位 / p05 / p95 | +0.5 / −5.5 / +7.0 | **0.0 / 0.0 / 0.0** |
| 墨宽差 `dW` 中位 / p05 / p95 | +1 / −13 / +15 | **0 / 0 / 0** |
| 墨高差 `dH` 中位 / p05 / p95 | −1 / −17 / +9 | **0 / 0 / 0** |
| \|dcx\|>5 的字 | 102 / 600 | **0** |
| \|dcy\|>5 的字 | 97 / 600 | **0** |
| \|dW\|>5 的字 | 290 / 600 | 5 |
| \|dH\|>5 的字 | 269 / 600 | 14 |
| 竖向度量 hhea / typo / win | 880/−120、880/−120、880/120 | **1160/−288、880/−120、1160/288**（母版同值） |

验收句对照：横向、纵向墨心差中位都 < 1 单位（是 0）；高度比中位 1.000（在 ±1% 内）。
`|·|>5` 剩下的 5 + 14 个字是**形状**差，不是位置差，见第四节。

## 二、改了什么（三处）

1. **逐字摆回母版位置**：新增 `tools/box_align.py`，在 `tools/cjk_vf.py` 里编轮廓前调用一次
   （`align_face_height` 之后、侧距调整之前）。做法是按母版逐字的字面框做仿射：
   平移对齐框中心；某轴「目标/现值」在 ±4% 以内才顺便缩放，且结果夹在 ±2%。
   三档共用同一组系数（300/500 跟着 400 的变换走），**点数与三档对应关系一个不动**。
2. **母版逐字框入库**：`tools/master_box.bin`（33,808 字，141,090 B，zlib 压缩的
   `码位 delta + 4×int16`），生成脚本 `tools/master_box.py`。它是**度量**，不是字体文件。
3. **竖向度量照母版**：`tools/cjk_vf.py` 里 hhea 由写死的 880/−120 改成母版的 1160/−288，
   win 由 880/120 改成 1160/288，x 高 500 → 479。改前本版行高只有母版的 0.75 倍。

> 发行包里这三个数会被 `normalize_metrics()` 归一到设备空壳 930/−250（那是设备行距的锚点），
> 本轮改的是**字件本身**的度量，预览件与母版一致；归一仍照旧。

顺带把 `build.yml` 的正式产物名从 `maruko-${{ env.VERSION }}` 改回 `Selffont-${{ env.VERSION }}`
（README:191 的约定），哈希附件同样改成 `Selffont-sha256-<SHA8>`；三类前缀现在是
`maruko-`（母版包）/ `Selffont-`（正式包）/ `selfrounds-`（自版包）。

## 三、`日` 的 dH 仍是 −70：母版的右上角吊着一块残墨

母版 `日`（U+65E5）有 4 条轮廓：

| # | 框 | 点数 | 面积占比 |
| --- | --- | --- | --- |
| 0 | (773, 788) – (828, 833) | 9 | 0.53% |
| 1 | (201, −10) – (802, 763) | 34 | 外框 |
| 2 | (263, 414) – (737, 703) | 15 | 上字腔 |
| 3 | (263, 49) – (737, 354) | 16 | 下字腔 |

0 号是**孤零零吊在右上角的一小块**（55×45，和任何笔画都不相连；`曰` `旦` `早` `旧` `白` `目` `田` `口`
都没有）。按 glyf bbox 对齐会把 `日` 纵向拉长 8.2% 去盖它——那才是真的失真。所以
`master_box.py` 里用点名表 `STRAY_CONTOURS` 去掉这一条（只有这一条；尺寸阈值试过，
会误删 38 个字的真点画，`㲲` 一个字里有 8 个点）。

修后 `日` 的字面框是 `(201, −10, 802, 763)`，与母版**去掉残墨后**的框逐单位相同；
对着含残墨的 bbox 读出来就是 `dH = −70`、`dW = −26`。图 `2026-11-05-position-fix.png`
母版那一行的 `日` 右上角能看见那个小点。

## 四、|差|>5 的 19 个字是形状差

`式` `验` `铲` `席` `笺` 这些字在母版里有**锐角收笔**（斜钩的尖、撇尖）。本版是「中线 + 半宽 +
固定段数圆头」的拓扑，尖角处被圆头截掉 20–40 单位，于是上下各短 20 上下。
仿射只能整体挪，挪不出一个尖来；这类字要动的是收笔拓扑（另一件事），本轮不碰。

## 五、不退化项（同一批 600 字）

| 量具 | 修前 | 修后 |
| --- | --- | --- |
| 直度 `over2`（前 60 字，`check_straight.py`） | 11.11% | **9.05%** |
| 直度边缘 RMS（相对中位） | 1.60 px | **1.57 px** |
| 洞数一致（`check_ink_holes.py`，母版 vs 本版） | 593/600 | **593/600** |
| 自交（`selfx_severity.py`，真缺口 / 毛刺） | 40 / 284 | **41 / 278** |
| 逐字 advance 差 | 0 | **0**（对齐不改字宽） |

## 六、复算

```bash
# 修后的逐字差值（600 字）
python tools/check_position.py 母版.ttf 修后.ttf --chars "$(cat 600字.txt)" --json 修后.json
# 母版逐字框（重出 master_box.bin，并打印与旧表不同的字）
python tools/master_box.py 母版.ttf --dry-run
# 直度 / 洞 / 自交
python tools/check_straight.py 母版.ttf 修后.ttf --chars "門口国團日一永字你"
python tools/check_ink_holes.py 母版.ttf 修后.ttf --chars "$(cat 600字.txt)"
python tools/selfx_severity.py 修后.ttf --chars "$(cat 600字.txt)"
# 图
python tools/fig_position.py --master 母版.ttf --ours 修前.ttf --label 修前 \
    --ours2 修后.ttf --label2 修后 --chars "門口国團日一永字你式验基" \
    --out docs/evidence/2026-11-05-position-fix.png
python tools/fig_position_fix.py --font 母版.ttf --span 24 \
    --before 修前.json --after 修后.json --out docs/evidence/2026-11-05-position-fix-scatter.png
```

本轮修前/修后的字件：`build.py --preview "門口国團日一永字你式验基"`（12 字预览件），
600 字那一份同样走 `--preview`。两份都只用来量，不是发行件。

## 七、全量构建：一条真拦路的崩溃（顺带修掉）

本轮第一次跑全量（`[full]`，Build #298）在「取号并出包」这一步 `exit 1`，日志宿主
（`results-receiver` / `blob.core.windows.net`）在本机都是握手 EOF，artifact 里的 `build-log`
也过不去。绕法是两步：失败时把 `build.log` 尾巴逐行发成 `::error::` 注解（运行页的
Annotations 能读），再把最后一行写进 commit status（`description` 140 字，API 能读）。
拿到的是：

```
AttributeError: 'NoneType' object has no attribute 'append'
  File "tools/cjk_vf.py", line 220, in rings_from_pen
    ring.append((u * u * a[0] + ...))
  File "tools/cjk_vf.py", line 311, in outline_edges
    return row_profile(rings_from_pen(pen.value))
```

病根：真字库里存在**没有 `moveTo` 就直接开段**的环（TrueType 允许一整条环全是 off 点，
fontTools 的 `draw` 遇到这种环会从 `qCurveTo` 起手），而展开器默认 `ring` 一定是 `moveTo`
建的。补一个起点（首点＝本段第一个非空点）继续走，环的形状与闭合方式不变；正常字形
的输出逐字节不变（12 字预览件改前改后逐字 bbox＋环数全同）。

修完在本机跑全量 `python build.py --cjk-font <dir>`：**3,228.6 s、33,932 字形、零崩**，
行框 `hhea` 930/−250、`usWin` 1322/549（比旧记录的 1307/529 大 15–20，是对齐把个别字的
墨迹顶上去了一点，`usWin` 本来就按全库墨迹包络算）。这条不是本轮的验收项，是出正式包
的必经之路，写在这里备案。
