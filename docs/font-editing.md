# 手写字形编辑规则

只有一条路径：**显式点 patch**。上一轮把"照着几张手写照调笔画"做成了整字库几何改写（`--all` 扫 GB2312、批量圆头化、去钩、平滑），还顺手删掉了被改字形的 hinting 与变体数据——那套东西已经不在仓库里，也不允许回来。

## 不允许的行为

- 不支持字符区间、字符集、`--all`，也没有"自动识别笔画"。
- 不从照片描摹，不把照片里的一个字推广成整套规则。
- 不增删轮廓、点或 on/off-curve 标记（拓扑必须逐点保持）。
- 不碰复合字形（改一个引用会连带改掉所有使用者）。
- 不编辑带 hinting 指令的字形（指令按旧轮廓寻址，移点就等于让指令说谎）。
- 不静默改 cmap、家族名、字重，也不改动未被点名的字形。

## Patch 格式

每个面一份 `config/glyph-patches/<Style>.json`，绑定**源面 SHA-256**（`config/font-source.json` 里该面的 `sha256`）：

```json
{
  "faceSha256": "a0c0b53543e0993ae2225e629c833f3d51495ad31720694ff112ce4ce11111ef",
  "glyphs": {
    "我": {
      "points": [
        {"index": 123, "dx": -4, "dy": 2},
        {"index": 124, "x": 412, "y": 688}
      ]
    }
  }
}
```

- 单位是该面自己的 UPM 网格；`dx`/`dy` 是相对位移，`x`/`y` 是绝对坐标，同一个点里**不能混用**。
- 点序号是整个简单字形的全局点序（含二次曲线的控制点与 on/off 标记）。
- 编辑全部通过校验后才写入；写入前还要求：glyph 顺序、cmap、家族名、字重与**其余每个字形**逐字节不变。

## 样例

`config/glyph-patches/Regular.json` 是工具生成的**样例**：把 `力` 右下角的钩改成直线收笔加半圆端头（对应 `strokeRules` 的"去钩"和"圆头"），只动 Regular 一个面。它是格式示范与审阅起点：删掉它，构建出来的就是未改动的基准面；照它给别的字写 patch 之前，先在 `tools/preview.py --serve` 的页面上看改前/改后。

`edit_font.py` 改到的字形若出现在别的字形的组件引用里（例如某个扩展字借用 `力` 的轮廓），会在 stderr 和报告 `componentUsers` 里点名，并在页面上一起显示——这是刻意的连带副作用，不静默发生。

## 运行

```sh
.venv/bin/python tools/edit_font.py \
  --prepared build/fonts \
  --patches config/glyph-patches \
  --output build/fonts-patched \
  --report build/glyph-patch-report.json
```

## 该改哪些字

`python3 tools/glyph_audit.py` 按 `config/glyph-targets.json` 输出两类结果：

- **可改**：面里已有该字形，点 patch 能改笔画；
- **缺字**：面里根本没有（Zen Maru 是日文字体，简体专用形大多缺失），点 patch 帮不上——需要另行设计轮廓，属于另一个量级的工作，不要混在 patch 里假装完成。

## 笔画约定（审阅清单）

写在 `config/glyph-targets.json` 的 `strokeRules`，只作人工判断标准：去钩、平辶、可见端头圆收、被压端头平切、点成圆、方日、同字等粗。工具不会自动套用；每个字的改动都由人写进 patch 并在 `tools/preview.py` 的审阅页上确认。
