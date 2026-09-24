# Selffont · Maru

面向 **Android 16（API 36）/ Oplus / KernelSU / LSPosed** 的个人字体方案，基于 MFGA 重构。

**字体路线：** [Zen Maru Gothic](https://github.com/googlefonts/zen-marugothic)（OFL-1.1，固定提交）五个静态字重，构建期改名为派生家族 **`Selffont Maru`**，装成 `SelffontMaru-{Light,Regular,Medium,Bold,Black}.ttf`。Android 的 100–900 请求按就近映射到这五个面（600→700、800→900，平局取粗），斜体由平台合成，**不伪造 `fvar`**。

**简体扩展：** Zen Maru 没有简体专用字形，`tools/extend_font.py` 用它**自己的轮廓和笔画**拼出 16 个（贝 页 见 马 鸟 乌 岛 门 员 维 陈 护 进 迁 赵 飞，附赠 东），规则是可复读的小表，保存前断言"原有字形逐字节不变"；某个字重拼不出来就跳过并记进报告（如 Bold/Black 的 飞）。`glyph_audit.py` 报 **44 个目标字全部有字形**。详见 [`docs/simplified-extension.md`](docs/simplified-extension.md)。

**手写笔画：** 只通过**逐字、逐点、显式写出**的 patch 修改（`config/glyph-patches/<Style>.json`）。没有整字库批量改写、没有从照片自动描摹、没有平滑/圆头"算子"。工具会拒绝复合字形、带 hinting 的字形和任何越界或空改动。

> **状态（诚实版）**
> - 主机侧：100 项 Python 契约测试 + 3 项 node 测试 + ruff 全绿；真实 Zen Maru 五个面已完成"下载→校验→改名→度量归一→打包"全链路本地演练（合成 base ZIP）。
> - 真机：**未验收**。模块安装、网页绘制、角标等紧凑槽位都需要按 `docs/validation.md` 重新测一遍。
> - 已知边界：Zen Maru 是**日文字体**，简体专用字形缺失，已由 `tools/extend_font.py` 补出 16 个，`python3 tools/glyph_audit.py` 现在报 `editable=44 needsNewGlyph=0`（只有 Bold/Black 的 飞 明示跳过，回退系统字体）。手写笔画 patch 作用在派生之后的面上（`edit_font.py` 默认读 `build/fonts-simplified`）。

## 这一版改了什么（相对 v1.4.0）

| | |
|---|---|
| 字体 | 文渊圆体 → Zen Maru Gothic 五个静态面（派生名 `Selffont Maru`） |
| 手写编辑 | 删除整字库几何改写与其工具；只保留显式点 patch 编辑器 + 契约测试 |
| 死重 | 删掉 `tools/otfcc*`、`tools/merge-otd`、`NotoSansPro` 合并工作流、emoji 去重叠脚本、休眠的角标/字形探针类（约 2.6 MB 二进制 + 两条遗留 CI） |
| 单一真源 | 模块内生成 `font.conf`（面名/可见性文件），shell 不再硬编码字体名；`config/font-source.json` 是字体真源，`FontIdentity.kt` 由契约测试对齐 |
| 现代化 | Python 3.11 + fontTools 4.65；JDK 21 / Gradle 9.5.0 / AGP 9.3.0 / SDK 36 / 全 Kotlin；node 24 + ruff 门禁 |
| 原生化 | 只用 framework `Typeface` 工厂与 `fonts.xml`，不引入 JNI、不扫私有地址 |

## 构建模块

```sh
python3 -m venv .venv
.venv/bin/pip install -r tools/requirements-dev.txt

# 1) 取源面并改名为派生家族（下载失败时用本地源面目录）
.venv/bin/python tools/prepare_font.py
.venv/bin/python tools/prepare_font.py --font-dir /path/to/zen-maru/ttf

# 2)（可选）应用手写点 patch；没有 patch 时原样复制
.venv/bin/python tools/edit_font.py

# 3) 审计+预览手写目标
.venv/bin/python tools/glyph_audit.py
.venv/bin/python tools/preview.py --serve            # 浏览器审阅页

# 4) 打包（base ZIP 由 prepare_base.py 校验后提供补充字体）
.venv/bin/python tools/prepare_base.py
.venv/bin/python tools/build_module.py --base build/base/MFGA-base.zip
```

产物 `build/Selffont-Maru.zip`，KSU 模块 ID 保持 `MFGA`（避免与现有 MFGA 争挂载）。字体、base ZIP、APK、构建产物都不入 Git。模块内 `module-report.json` 记录每个面的哈希、就近字重表与度量归一结果。

## 手写笔画工作流

1. 先 `tools/extend_font.py` 做简体扩展（可复读的规则表），再 `glyph_audit.py` 看还剩哪些字没有字形（现在应为 0）。
2. `tools/preview.py --serve` 起一个审阅页：用**真实 TTF** 渲染五个面 + 目标字表 + 笔画约定，改成什么样当场看得见。
3. 仓库里已有一个由工具生成的**样例 patch**（`config/glyph-patches/Regular.json`，改 `力` 的去钩与圆头），照它的格式写 `config/glyph-patches/<Style>.json`：`{"faceSha256": "<源面哈希>", "glyphs": {"字": {"points": [{"index": 12, "dx": -6, "dy": 3}]}}}`。
4. `tools/edit_font.py` 校验（复合/hinting/拓扑/空改动全拒），发布到 `build/fonts-patched`，并断言**只有被点名的字形变了**。
5. 打包只从 `build/fonts-patched` 取面，构建期再断言"只有行度量变化"。

手写笔画约定（当前审阅标准，见 `config/glyph-targets.json` 的 `strokeRules`）：去钩、平辶、可见端头圆收、被压端头平切、点成圆、方日、同字等粗。规则只作人工审阅清单——**工具不会替你套用它们**。

## 边界

- 平台闸门默认只在 **Android 16 + Oplus + KernelSU** 安装并挂钩；`touch /data/adb/selffont_allow_unsupported` 可自担风险放行，删除即恢复。
- Firefox 走 Gecko 启动首选项注入（主字体前置 + 保留原回退链，不碰 emoji 首选项）；没有扩展、不改 profile、不 hook 原生地址。**网页是否真的用了目标字体仍需诊断页 + 日志链确认**。
- 度量归一（`tools/metric_normalize.py`）只把安装副本的 `hhea`/`OS/2` 行度量对齐 Roboto 载体名义度量，修通知角标数字偏低/切底；字形、cmap、家族名、字重逐字节不变，带防切保护。
- GMS 与阅读应用字体权限只做手动兜底（需显式 `--confirm`），安装/开机/WebUI 都不执行。
- 未适配其他 Android/ROM/root 管理器，本方案的真机结果不外推。

构件职责、证据与限制见 [`docs/architecture.md`](docs/architecture.md)；验收步骤见 [`docs/validation.md`](docs/validation.md)；字形编辑规则见 [`docs/font-editing.md`](docs/font-editing.md)；换字体见 [`docs/font-swap.md`](docs/font-swap.md)。
