# 行为契约、职责与证据

## 已确认的边界

1. 只支持 Android 16（API 36）、Oplus 系、KSU、LSPosed；框架接口要求现代 API 102。
2. 统一字体家族，不抹平粗体、斜体、小型大写，也不改写 Unicode、DOM 或用户输入。
3. 基准字体是 OFL-1.1 的 Zen Maru Gothic 固定提交；派生家族名 `Selffont Maru`。不引入任何商业字体，也不把上游面原样当作自有字体发布。
4. 手写字形改动只能通过显式点 patch；没有整字库批量改写、上色或区间屏蔽。其他进程数据的干预只能是手动兜底。
5. LSPosed 作用域唯一，模块里不再加包名名单。
6. 未匹配系统 `font*.xml` 默认整体替换，保留明确的不同-schema 例外 `fonts_customization.xml`。这是一项用户选择的偏激进策略，不等于已验证所有配置路径。

## 职责划分

| 层 | 负责 | 不负责 |
|---|---|---|
| 字体真源 `config/font-source.json` | 项目/版本/五个面的哈希与安装名、许可、可见性文件 | 下载后擅自换源；改面内容 |
| `tools/prepare_font.py` | 校验上游面（大小/SHA/家族/字重），改名为派生家族，断言轮廓/cmap 逐字节不变 | 改字形、写设备 |
| `tools/edit_font.py` | 只应用显式点 patch，拒复合/hinting/越界/空改动，发布前断言"只有被点名的字形变了" | 扫字符集、猜笔画、平滑、删 gvar/hinting |
| `tools/font_config.py` | 生成 Android `fonts.xml`：五静态面 + 就近字重映射 + 保留 Roboto 度量家族 | 编造可变轴 |
| `tools/metric_normalize.py` | 只改安装副本的竖直行度量到载体名义度量，带防切保护 | 改轮廓/cmap/家族/字重 |
| `tools/build_module.py` | 从显式 base ZIP 取补充字体、生成 `fonts.xml`/`font.conf`/`module.prop`、打包与自校验 | 执行 base 里的脚本、操作设备 |
| KSU 安装 | 环境门槛、配置挂载准备、校验 `font.conf` 里的每个面存在 | 开机改权限、自动停应用、自动清缓存 |
| `FontForceCore` | 在 Android `Typeface` 工厂结果层替换家族、保留 weight/italic | 覆盖所有原生引擎、替换异常或 null |
| `GeckoFontPolicy` | 复制首选项 Map 并注入默认字体（主字体前置、保留原回退链） | 改 profile、CSS、原始文本、emoji 首选项 |
| `ModernEntry` / `HookTarget` | 作用域内按纯签名谓词安装 Hook、探测 Gecko 接口与字体可见性、分阶段日志 | 第二套应用名单、把安装成功当作渲染成功 |
| 手动 Shell / WebUI | 明确副作用与退出码、记录与恢复本版本修改的权限 | 从翻译字符串猜成功、开机自动干预 |

只为当前明确的两种加载路径建立接口，不预先创建覆盖所有 ROM 或所有渲染器的插件框架。Gecko 只依赖运行时类探测，不捆绑 GeckoView AAR。

## 核对过的外部证据

### 字体

- 上游：<https://github.com/googlefonts/zen-marugothic>，固定提交 `553c872b216d1290e2902a466edcdc9682f0df6a`，OFL-1.1（版权行无 Reserved Font Name 声明；派生仍改名以避免与上游混淆）。
- 五个静态面的大小/SHA-256 记在 `config/font-source.json`；本地实拉校验通过，改名后断言 glyphOrder、逐字形字节与 cmap 相同。
- 面里没有 `fvar`：**不伪造可变字体**。Android 的 100–900 用就近静态面覆盖（600→700、800→900，平局取粗）。
- Zen Maru 是日文字体：简体专用形（马/鸟/页/贝/进/迁/赵…）在面里不存在。`tools/glyph_audit.py` 把这类目标标为 `needs-new-glyph`，点 patch 不做、也不假装能做。
- 缺字继续依赖补充字体与引擎回退；不以单个字体的映射数量宣称 Unicode 全覆盖。

### Android 布局度量与实际字形分开（v1.4 的真机教训，仍然有效）

第一版把默认家族直接改成目标字体，并删掉了原配置里明确用于防偏移的 Roboto 度量载体；用户随后报告通知栏角标数字贴下沿、部分切底。根因是**测量用载体名义度量、绘制用回退字体更大的真实度量**，baseline 被顶低。

修订方案：`sans-serif` / `sans-serif-condensed` 保留无可见字形的 Roboto 度量家族，可见字形放在紧随其后的匿名回退家族；打包期把安装副本的行度量归一到载体名义度量（`tools/metric_normalize.py`），并断言数字墨迹不被新行盒切掉。字形、cmap、家族名、字重逐字节不变。**该修复在文渊时代经用户真机确认；换成 Zen Maru 后需要重新验收。**

### Firefox / GeckoView

用户报告基线：Firefox 155.0.1 (Build #2016182535)，GV 155.0.1-20260903215306，AS 155.0，Android 16。检查的是发布标签 `FIREFOX_155_0_1_RELEASE`（提交 `fb95137a04eb8fe1196cb12f26b100c1e060295c`）：

- `mobile/android/geckoview/.../RuntimeSettings.java`：`getPrefsMap()` 返回只读映射；`GeckoRuntime.java` 启动时取它并交给 `GeckoThread.InitInfo`。
- `GeckoRuntimeSettings.java`：`webFontsEnabled` 对应 `browser.display.use_document_fonts`。
- `GeckoLoader.java`：启动 Map 序列化为 `MOZ_DEFAULT_PREFS`，不改 profile 文件。
- `gfx/thebes/gfxFT2FontList.cpp` 有独立的系统/文件/内存字体路径——**Java Typeface 工厂不是网页渲染的充分入口**。

因此适配只在启动入口复制 Map 并注入默认字体首选项；目标文件不可读时不注入。已有 profile 用户首选项可能胜出，必须真机验证。

已知结论（文渊时代经 A/B 证明，与具体字体无关）：Gecko 对 Unicode 15.1/16 新增 emoji 显示豆腐块属其自有字体后端限制；`font.name-list` 前置保留不会掐断回退链。

### Xposed

`io.github.libxposed:api:102.0.0`（<https://github.com/libxposed/api/tree/102.0.0>）。最低 API 也是 102，不声明能在 API 100 上跑 API 102 入口。Hook 面由 `HookTarget` 的纯签名谓词决定，并有主机单元测试锁住覆盖集合（Builder/CustomFallbackBuilder#build、createFromAsset/File、create(Typeface,int[,boolean])；按名取家族的 `create(String,int)` 故意不 hook）。

## 不变量与失败行为

- 原方法抛出的异常传播；原方法返回 null 仍为 null。
- 只有替换操作自身失败才回到原 Typeface；重入保护在异常时也释放，不跨线程串扰。
- `deoptimize` 失败不阻止继续尝试安装 Hook；每个入口独立记录结果。
- 字体不可读不修改 Gecko 首选项；接口不存在只记录不支持，不扫描任意原生地址。
- 不记录页面文字、浏览记录或完整用户 profile。
- 权限先记账再修改，记录跨模块更新保存；只恢复身份匹配且仍为 000 的文件，后续用户/应用更改不强行还原。
- `errno` 是当前 KernelSU bridge 的返回契约；非零不因输出含"成功"而变成零。
- 主要家族包含 `monospace`，统一为同一比例圆体，不能同时保证原有代码列对齐——这是强制家族统一的明确代价。

## 尚不能承诺

- 完整模块在真机上的安装、Oplus 实际字体路径、KSU 在 Firefox 进程中的挂载可见性。
- Firefox 用户首选项、字体隐藏/指纹防护、缓存和内容进程是否影响字体选择。
- 网页专用图标字体或图形内容是否仍正确（强制族名可能让图标字体缺失）。
- 真实 154 MB 基础包的端到端装机结果，以及未来 Firefox/LSPosed 版本的接口兼容性。
