# 简体扩展：用自己的轮廓造简体字

Zen Maru 是日文字体，没有简体专用字形（贝/页/马/鸟/门/陈/护…）。`tools/extend_font.py` 用**这个字体自己已有的轮廓**把它们拼出来：不引入任何其他字体的字形，不描摹，也不做几何美化。

## 规则怎么写的

一条规则 = 一个新字 → 若干 `(源字, 选择器, 造形器)`：

```python
recipe("马", ("馬", all_contours, body_only), ("一", all_contours, bar_over_feet()))
```

- **选择器**只按角色挑轮廓（主体 = 面积最大的那个；孔 = 反绕向的轮廓；脚 = 同绕向的小轮廓），**从不使用轮廓序号**——五个字重各自绘制，同一个字在 Light 有 6 个轮廓、Bold 只有 4 个。
- **造形器**把选中的轮廓变换成新字的轮廓：`translate`/`fit`/`mirror_left`/`without_feet`/`simplified_box`/`bar_over_feet`。
- 造形可以读上下文（`context["built"]`、`context["notes"]`），所以"马"的底横能放进"去掉的脚所占据的那条带子"里，而不是靠硬编码坐标。

## 这一批做了什么

| 字 | 来源 | 手法 |
|---|---|---|
| 贝 页 | 貝 頁 | 去掉 灬 脚（分开的轮廓直接丢；并入主体的按主体自己的地板线切开），再把最下面两个白槽合并成一格（贝 的匣子只有一条隔） |
| 马 鸟 乌 | 馬 鳥 烏 | 去脚 + 底横：横杠轮廓取自 一，放进脚原来的带子里 |
| 岛 | 島 | 岛 = 鳥 + 山 的简体本就成立，直接采用 |
| 门 | 門 | 取中线左侧的那片门框（连同白槽），推移到中线后镜像 |
| 陈 | 陳 | 阝（取中线左侧轮廓）+ 東 |
| 护 | 戸 持 | 扌 取自 持，戸 去掉顶横后把顶横缩成点 |
| 进 迁 | 辻 井 / 辻 千 | 辻 已有 辶（轮廓 0），换掉被包的部分 |
| 赵 | 走 乂 | 走 + 乂 缩放拼合 |
| 飞 | 飛 | 去掉四根小羽（Light/Regular/Medium；Bold/Black 把羽毛并进主体，跳过） |

**明确不做**：见（見 的匣子地板与两条腿连成一条轮廓，需要"切地板 + 两腿穿过开口"的编辑，当前引擎表达不了 → 不产出，继续用系统字体）。

## 跑法

```sh
.venv/bin/python tools/extend_font.py            # build/fonts -> build/fonts-simplified
.venv/bin/python tools/glyph_audit.py            # 看目标字表现在还缺哪些
.venv/bin/python tools/edit_font.py --prepared build/fonts-simplified \
    --patches config/glyph-patches --output build/fonts-patched
.venv/bin/python tools/build_module.py --base build/base/MFGA-base.zip
```

## 工具怎么保证没干坏事

- 新字必须是**已有轮廓的仿射组合**；引擎不产生新点，也不改点。
- 保存前逐字断言：原有每个字形**逐字节不变**、字形顺序不变、cmap 只多出这次派生出来的码点。
- 派生字已存在（面里本来就有）→ 报错拒绝覆盖。
- 某个字重表达不了这条规则 → **跳过并写进报告**，不产出猜测形状；缺字在手机上回退系统字体，比一个坏字形安全。
- 度量（`hmtx`/`vmtx`）取来源字形的中位数，不外造。

## 还没做

- 见 以及 14 个目标字里剩下的（员 维 等）还没写规则；`tools/glyph_audit.py` 会照实列出。
- 手写笔画 patch（`config/glyph-patches/`）现在应作用在**派生之后**的面上，顺序：prepare → extend → edit。
