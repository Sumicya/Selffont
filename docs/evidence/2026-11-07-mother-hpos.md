# 2026-11-07 · 母版定位修复：重定位图 + 可直接刷的包

这一轮只回答两件事：**定位到底修成了什么样**（图），**包在哪**（artifact）。读数全部可复算，
命令写在第五节，逐字表写在第四节。

## 一、修的是谁、修了什么

- 母版：`maruko-gothic` `97e9dd4` 的 `CJK SC/MarukoGothicCJKsc-Regular.ttf`
  （20,084,736 B，sha256 `e3709389…41b7`，与 `build.yml` 里的 `MOTHER_SHA256` 同一个钉子）。
- 修法：`tools/fix_hpos.py`，**只沿 x 平移**。判据是「每个被动过的字，所有点位移处处相等」——
  不是缩放、不是重画、不改轮廓相对关系，`advance` 一个字都不变。
- 不动：非汉字、墨宽 < 600 的窄部件、`|dcx| ≤ 20` 的字（2% em 在 16px 下看不见，动它只是让母版偏离自己的设计）。

## 二、读数（26,560 个满格字，逐字墨心 = (xMin+xMax)/2 − 500）

| 读数 | 母版原样 | 只平移后 |
| --- | --- | --- |
| 中位 \|dcx\| | 5.5 | **4.0** |
| 最大 \|dcx\| | **54.5** | **20.5** |
| \|dcx\|≤20 占比 | 89.66% | **99.57%** |
| \|dcx\|>20 的字数 | 2,746 | **113** |
| 平移过的字 | — | 2,890（位移中位 26 单位，最大 −112） |
| advance 变了的字 | — | 0 |
| 点位移不相等的字 | — | 0（纯平移的证明） |
| lsb ≠ xMin 的字 | — | 0 |

剩下 113 个字是 `+20.5`：`fix_hpos` 用 `tools/master_box.bin` 的字面框量（去残墨），
验收脚本用 glyf bbox 量，两把尺子在残墨字上差 0.5 单位，正好压在 20 的线上。修前最差 ±54.5，
现在全部落在 ±20.5 以内，肉眼不可分。

## 三、图（都在 `docs/evidence/`，同字同尺寸并排）

1. **`2026-11-07-mother-hpos-grid.png`**（主图，2924×804）——每格一个字身格 + 500 中线（灰虚线）+
   墨迹左右界（红竖线）+ 墨心（绿点），上一行母版原样、下一行修复后，格下写 `dcx` 原值。
   读法：绿点压在中线上就是归位；`匕 +91 → 0`、`名 −82 → 0`、`爿 −86 → +0`、`乁 +112 → 0`、`扁 −54 → −0`。
2. **`2026-11-07-mother-hpos-overlay.png`**（1676×540）——同一格里叠影：灰=母版原样，黑=修复后，
   格下写 `改前 → 改后`。一眼看出往哪边挪了、挪了多少。
3. **`2026-11-07-mother-hpos-text.png`**（5332×704）——整段文字（含 `扁 個 則 侶 蹽 畸 窗 國`），
   修复前后同字号、不画辅助线，看的是整行观感而不是单字数字。
4. **`2026-11-07-mother-hpos-zoom.png`**（1940×1264）——`匕 乁 扁 平` 放大 2 倍，给细节。
5. **`2026-11-07-mother-hpos-dist.png`**（1660×720）——全库 26,560 个满格字的 `|dcx|` 直方图，
   灰=母版原样、蓝=只平移后；右边两行是总数与最大值。这是四张实字图之外唯一的全量视图：
   前四张证明「改对了」，这张证明「改到哪儿为止」。

`日`（U+65E5）在图上 `dcx +14` 且修复后没动，这是对的：母版给它右上角吊了一块 55×45 的残墨，
`fix_hpos` 用去残墨的字面框量，所以判它没偏；按 glyf bbox 量才读出 +14.5。这张图不裁墨迹，
残墨照样画出来——这一点和 `docs/evidence/2026-11-05-position-fix.md` 第三节同一个事实。

## 四、逐字表（图上那 12 个字，单位：em/1000）

| 字 | 改前 dcx | 改后 dcx | 位移 | 改前 xMin/xMax | 改后 xMin/xMax |
| --- | ---: | ---: | ---: | --- | --- |
| 匕 | +91.0 | 0.0 | −91 | 268 / 914 | 177 / 823 |
| 名 | −82.0 | 0.0 | +82 | 10 / 826 | 92 / 908 |
| 爿 | −85.5 | +0.5 | +86 | 92 / 737 | 178 / 823 |
| 㔾 | +84.0 | 0.0 | −84 | 208 / 960 | 124 / 876 |
| 乁 | +112.0 | 0.0 | −112 | 276 / 948 | 164 / 836 |
| 扁 | −54.5 | −0.5 | +54 | 8 / 883 | 62 / 937 |
| 門 | −1.5 | −1.5 | 0 | 93 / 904 | 93 / 904 |
| 國 | −1.5 | −1.5 | 0 | 86 / 911 | 86 / 911 |
| 團 | 0.0 | 0.0 | 0 | 86 / 914 | 86 / 914 |
| 日 | +14.5 | +14.5 | 0 | 201 / 828 | 201 / 828 |
| 田 | 0.0 | 0.0 | 0 | 122 / 878 | 122 / 878 |
| 回 | 0.0 | 0.0 | 0 | 89 / 911 | 89 / 911 |

## 五、复算

```bash
# 母版（sha256 钉在 build.yml 里）
gh api "repos/max32002/maruko-gothic/contents/CJK%20SC/MarukoGothicCJKsc-Regular.ttf?ref=97e9dd4" \
  -H "Accept: application/vnd.github.raw" > work/MarukoGothicCJKsc-Regular.ttf
sha256sum work/MarukoGothicCJKsc-Regular.ttf     # 应为 e3709389…41b7

# 只平移
python tools/fix_hpos.py work/MarukoGothicCJKsc-Regular.ttf -o work/hpos/MarukoGothicCJKsc-Regular.ttf

# 图（四张）
python tools/fig_hpos.py --master work/MarukoGothicCJKsc-Regular.ttf \
  --fixed work/hpos/MarukoGothicCJKsc-Regular.ttf --mode grid \
  --chars "匕名爿㔾乁扁門國團日田回" --out docs/evidence/2026-11-07-mother-hpos-grid.png
python tools/fig_hpos.py … --mode overlay --chars "匕名爿㔾乁扁" --out …-overlay.png
python tools/fig_hpos.py … --mode text --chars "春眠不觉晓…窗國" --out …-text.png
python tools/fig_hpos.py … --mode grid --cell 460 --chars "匕乁扁平" --out …-zoom.png
python tools/fig_hpos.py … --mode dist --out docs/evidence/2026-11-07-mother-hpos-dist.png
```

`tools/fig_hpos.py` 是本轮新增的：上一张定位图（`2026-11-06-hpos-text.png`）只有 1 倍整段文字，
看得到「发飘」，读不出「偏几个单位、往哪边」——没有字身格、没有中线、没有墨心点。

## 六、包

母版定位修复包由 `build.yml` 出，流水线里三步连做：取母版原字节 → `fix_hpos.py` 只平移 →
`--passthrough-mother` 打进 Magisk 模块，然后**验收步**逐条断言：

- 包内 `system/fonts/<母版名>` 与 `work/hpos/` 那一份**逐字节相同**（`packed == fixed_bytes`）；
- 被动过的字逐点位移处处相等（纯平移），`advance` 全 1000，`lsb == xMin` 0 例外；
- 满格字 `|dcx|≤20` 从 89.66% 抬到 99.57%（脚本内当场算，不达 99.5% 直接失败，不上传）。

**现有可刷的包**：`build-26.11.6.1.334`（120,950,276 B，5 天，2026-11-11 08:37 +08 过期）

- 运行：https://github.com/Sumicya/Selffont/actions/runs/42137826847
- 产物直链（登录 GitHub 后直接下载）：
  https://github.com/Sumicya/Selffont/actions/runs/42137826847/artifacts/13465929132
- 十二条步骤全绿，其中 `修水平定位` 与 `验收（纯平移、字宽不变、墨心归位）` 都是 success。

装法（手机）：下载 zip 不解压 → Magisk/KernelSU 里「从本地安装」选它 → 重启。
它的模块 id 是 `selffont-bench`，与正式包分开，刷它不挡正式包更新。

**未验证的一条**：artifact 的**字节**没在本机核对过——下载会被 302 到
`productionresultssa13.blob.core.windows.net`，本机对该域的连接是 TLS EOF。所以包内字件是否等于
本机 `work/hpos/` 那一份，只有流水线自己那条断言（`packed == fixed_bytes`）为证，我没有第二份证据。
