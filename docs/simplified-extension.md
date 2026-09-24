# 简体扩展：用自己的笔画造简体字

Zen Maru 是日文字体，没有简体专用字形（贝/页/马/鸟/门/陈/护…）。`tools/extend_font.py` 用**这个字体自己已有的轮廓和笔画**把它们拼出来：不引入任何其他字体的字形，不描摹，也不做几何美化。

目标表里的 44 个字现在全部有字形：`tools/glyph_audit.py` 报 `editable=44 needsNewGlyph=0`（`飞` 的 Bold/Black 除外，见下）。

## 规则怎么写的

一条规则 = 一个新字 → 若干 `(源字, 选择器, 造形器)`：

```python
recipe("马", ("馬", all_contours, body_only), ("一", all_contours, bar_over_feet()))
```

- **选择器按角色挑轮廓**，从不使用轮廓序号——五个字重各自绘制，同一个字在 Light 有 6 个轮廓、Bold 只有 4 个。常用的是：`main_contour`（主体）、`everything_but_main`（孔和脚）、`left_half` / `right_half`（部件在中心线哪一侧）、`left_radical` / `right_radical`（占满大半高度、贴着某一侧的部件）、`highest` / `except_highest`、`above_main`、`leftmost` / `rightmost`。
- **造形器**把选中的轮廓变成新字的轮廓：`fit`（放进一个盒子）、`translate`、`then`（依次施加）、`flip_x`、`frame`、`without_feet`、`simplified_box`、`without_feathers`、`bar_over_feet`。
- **镜像/翻转要反绕向**：TrueType 靠绕向决定实心还是挖空。镜像会把绕向一起翻过来，于是「框」变「洞」；`Contour.reversed()` 把镜像出来的副本倒回来（门 曾经渲染成两个实心块，就是这个原因）。
- **空选择不是「什么都没选」**：`everything_but_main` 可以是空的（Bold 的 飛 就是一条合并的轮廓），标了 `optional`；别的选择器选空 = 这个字重证不出这条规则 → **报错并跳过**，而不是产出一个少一条胳膊的字。

![派生简体，五个字重](images/simplified-extension.png)

## 14 个缺字各自的手法

| 字 | 来源 | 手法 |
|---|---|---|
| 贝 页 | 貝 頁 | 去掉 灬 脚（分开的轮廓直接丢；并入主体的按主体自己的地板线切开），再把最下面两个白槽合并成一格 |
| 马 鸟 乌 岛 | 馬 鳥 烏 島 | 同一条规则：去脚 + 底横。底横轮廓取自 一，放进脚原来占的那条带子里；岛 的 鳥 本来就画得比 鳥 小，不去缩它 |
| 门 | 冂 戸 | 门 = 冂（这个字体自己就有冂）+ 左上一点，点取 戸 的顶横压扁 |
| 见 | 冂 元 | 见 = 冂 + 儿（取 元 的主体轮廓，那正是儿的两条腿） |
| 员 | 員 | 員 上面的口（连同白槽）+ 下面按 贝 同样简化过的貝 |
| 维 | 幺 糸 隹 | 幺 的两折就是纟的两折；糸 的左下点本身就是「提」的走向，正好当纟的第三笔；右边放 隹 |
| 陈 | 限 + 东 | 阝 取自 限（陳 的字重里阝 会和右件并成一条轮廓，那样选出来的是碎片，规则会拒绝），右边是**重新排布的 东** |
| 护 | 打 所 丶 | 扌 取自 打；户 = 所 的左件（戶 = 尸 + 顶上那一笔）去掉顶横，再补 丶 当点——丶 的斜向就是 户 第一笔的斜向 |
| 进 迁 | 辻 井 / 辻 千 | 辻 已有 辶（轮廓 0），换掉被包的部分 |
| 赵 | 走 乂 | 走 + 乂 缩放拼合 |
| 飞 | 飛 | 去掉四根小羽（Light/Regular/Medium；Bold/Black 把羽毛并进主体，跳过） |

**故意跳过**：`飞` 的 Bold/Black——这两个字重把四根羽毛并进了主体轮廓，选不出来，硬切就是猜。报告里照实记 `skipped`，那两个字重继续用系统字体。

## 东：拿笔画拼，而不是把 東 缩小

简体 东 不是「東 挖掉一块」：它没有 日 的右壁和内横，两脚变成点。这个引擎不做路径手术（切一条轮廓里的某几段），所以 东 是**用这个字体自己的单笔画拼的**——这个字体把单笔画也画成了字：`一` `丨` `亅` `丿` `丶`，还有片假名 `ニ`（两条不同长的横）和 `冫`（一点一提）：

```python
recipe("东", ("一", all_contours, fit((55, 730, 945, 800), keep_aspect=False)),   # 上横
             ("冫", highest, then(flip_x(), fit((330, 340, 600, 745), keep_aspect=False))),  # 撇折的撇
             ("ニ", highest, fit((330, 340, 800, 400), keep_aspect=False)),         # 撇折的折
             ("亅", all_contours, fit((450, -75, 640, 800))),                      # 竖钩
             ("冫", highest, then(flip_x(), fit((140, -75, 360, 190), keep_aspect=False))),  # 左下点
             ("冫", highest, fit((640, -75, 860, 190), keep_aspect=False)))         # 右下点
```

为什么是「拼」而不是「缩」：**这个字体的笔画粗细不随部件宽窄变化**（一 63、丨 63、亅 62、丿 61、丶 65、小 的点 58~64、彡 59——都是同一个笔重）。把 東 整体等比压进 陈 的右列，笔画会跟着变细（60 → 36），和旁边的 阝 明显不搭；所以 陈 的右件是同样的笔画**按右列的宽度重新排布**，不是缩小的 东：

```python
recipe("陈", ("限", left_radical, fit((60, -90, 430, 850))),
            ("ニ", highest, fit((450, 736, 960, 801))),
            ...同样的笔画，放在 x 450~960 这一列里)
```

（`东` 这个字本身也顺手有了：它在目标表里没提，但做 陈 的过程中就齐了。）

## 跑法

```sh
python3 tools/prepare_font.py --font-dir <Zen Maru 的 5 个 TTF>   # -> build/fonts
python3 tools/extend_font.py                                    # -> build/fonts-simplified
python3 tools/edit_font.py                                      # -> build/fonts-patched
python3 tools/glyph_audit.py --font-dir build/fonts-patched     # 目标字表现况
python3 tools/make_extension_sheet.py                           # 重画文档里那张图
python3 tools/build_module.py --base build/base/MFGA-base.zip
```

## 工具怎么保证没干坏事

- 新字必须是**已有轮廓的仿射组合**；引擎不产生新点，也不改点，更不做路径手术。
- 保存前逐字断言：原有每个字形**逐字节不变**、字形顺序不变、cmap 只多出这次派生出来的码点。
- 派生字已存在（面里本来就有）→ 报错拒绝覆盖。
- 某个字重证不出这条规则 → **跳过并写进报告**，不产出猜测形状；缺字在手机上回退系统字体，比一个坏字形安全。
- 度量（`hmtx`/`vmtx`）取来源字形的中位数，不外造。

## 顺序与手写笔画

手写笔画 patch（`config/glyph-patches/`）作用在**派生之后**的面上：prepare → extend → edit。`tools/edit_font.py` 的默认输入已经是 `build/fonts-simplified`，输出 `build/fonts-patched`。

patch 里的点是按**钉住的原始面**（`config/base-source.json` 里的 sha256）的轮廓下标写的，所以 edit 阶段会比对哈希：一旦它编辑的不是那张钉住的面，就打印一条 notice——「这次编辑的是派生面，下标必须对得上这张面真正画的那个字形」。
