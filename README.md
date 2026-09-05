# Selffont · 第一阶段

面向 **Android 16 / Oplus / KernelSU / LSPosed 2.2.0（7854）** 的个人字体方案，基于 MFGA 重构。

**目标是统一字体家族，不是删除排版语义。** 粗体、斜体、小型大写、语言与原始 Unicode 字符应保留。系统 UI 与 Firefox 网页是两条不同的字体加载路径。

> 状态：主机侧回归、Java 策略测试和诊断 APK 构建已通过 CI（提交 `16457fb`）；字体原版资源已校验。新 APK 的现代入口与 Firefox 的 Gecko 启动入口已有真机命中证据；当前因目标字体不可读而跳过首选项改写，网页绘制仍待验证。源码存在某个 Hook 入口、日志显示成功，不等于网页已使用目标字体。

## 当前范围

- 主字体首选 **文渊圆体 v1.010**，内部家族名 `WenYuan Rounded SC VF`。原始 TTF 的 `wght` 范围为 100–900，`ital` 范围为 0–1。
- SELFUSE 的 FZYJHK 作为用户提供的原有外观参考；本方案不下载、改造或重新分发它。资源圆体为次选。
- 删除整字体屏蔽、Unicode 区间屏蔽、上色及其 C 工具、脚本、WebUI 和 CI。
- 仅现代 Xposed API **102**；无内部应用白名单，LSPosed 勾选是唯一作用域来源。
- GMS 与阅读应用字体权限处理仅为**手动兜底**。安装、开机、打开 WebUI 不执行它们。
- 原来的 `fonts.xml` 保留为补充字体配置输入；打包器生成实际安装配置，将默认、衬线、等宽、花体等主要家族指向文渊，移除空壳 Roboto → 数字主字体的回退绕路。
- 未适配其他 Android/ROM/root 管理器；不能将这个个人方案的测试结果外推为通用兼容承诺。

## 构建字体模块

要求 Python 3.11+：

```sh
python3 -m venv .venv
.venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tools/prepare_font.py
# 下载受限时使用官方 v1.010 原版文件；同样严格校验哈希、家族名和轴。
.venv/bin/python tools/prepare_font.py --font /path/to/WenYuanRoundedSCVF.ttf

# 固定来源的完整基础包只供应补充字体（不继承代码）。
.venv/bin/python tools/prepare_base.py
.venv/bin/python tools/build_module.py --base build/base/MFGA-base.zip
# 如已有基础包，也可用 prepare_base.py --base /path/to/MFGA-SELFUSE.zip 校验。
```

**[下载本次字体模块构建产物](https://github.com/Sumicya/Selffont/actions/runs/33975295832/artifacts/9972129539)**：解开 CI 外层压缩包，实际安装文件为 `Selffont-phase1.zip`，同目录有校验文件与构建报告。

产物：`build/Selffont-phase1.zip`。**Build Selffont font module** 工作流负责资源下载、验证和打包，与 APK 工作流分开；提交 `10f9eef` 的完整构建已通过，真机安装与网页绘制仍待验收。KSU 模块 ID 保持 `MFGA`，避免与现有 MFGA 同时挂载冲突。不要把本仓库直接压缩成 ZIP 安装。

基础包**只提供字体资源和归属说明**，不会继承它的安装脚本、开机脚本、原生工具、Zygisk 或更新地址。数字主字体 `100.ttf`～`900.ttf` 不继承。补充字体遵守各自许可证；文渊原版文件不改字形、cmap 或内部名称，附带其 OFL。固定基础包的大小、SHA-256、release 与 asset ID 见 `config/base-source.json`；其校验与打包器输出 CRC／主字体哈希校验都通过后才发布构建产物。自选其他基础包的来源及许可仍须确认。

字体固定版本、SHA-256、内部家族名见 [`config/font-source.json`](config/font-source.json)。字体、基础包、APK、构建 ZIP 均不入 Git。构建器不访问设备，不下载或执行基础包中的代码。

## 构建 Xposed APK

需要 **JDK 17、Gradle 8.11.1、Android SDK 36**：

```sh
cd mfga-xposed
gradle --no-daemon assembleDebug
```

CI：**Build Selffont diagnostic APK**。这是开发签名的诊断 APK，不是稳定签名的正式发行版。旧 APK 签名不同或不同 CI 运行使用不同开发密钥时，需要先在 LSPosed 停用旧版，再卸载旧 APK、安装新版并重新勾选。本阶段不使用旧版测试结论。

## Firefox 专项适配

用户基线：Firefox **155.0.1 (2016182535)**，GV **155.0.1-20260903215306**，AS **155.0**，Android 16。

Gecko 有自己的字体选择路径；Java `Typeface` Hook 不是通用网页字体拦截器。本阶段在 Gecko 的 `RuntimeSettings.getPrefsMap()` 启动入口注入**内存中的默认字体首选项**：

- `browser.display.use_document_fonts = 0`；
- 将主要 generic family 的 Gecko 字体首选项指向文渊；
- 不修改 CSS、字号、字重、斜体、小型大写、Unicode 或浏览器配置文件；
- Firefox 进程中看不到 `/system/fonts/Selffont-WenYuanRoundedSCVF.ttf` 时，不注入；
- 不使用浏览器扩展或原生函数地址 Hook。

这是**源代码核对过、真机未验证**的适配。已有用户首选项、字体可见性限制、缓存、发布版优化／混淆或更早的初始化路径仍可能影响效果。不能保证覆盖所有网页、图标字体、SVG/canvas 或所有 Gecko 版本；强制网页字体家族可能损坏依赖专用字体的图标。

## 操作与验证

- 在 KSU 中安装准备好的模块，重启；安装新版 APK，在 LSPosed 中勾选目标应用，彻底停止并重开应用。
- 模块操作按钮默认执行**只读诊断**；WebUI 也只提供诊断和显式确认的手动兜底。
- 用目标手机 Firefox 打开 [`webroot/diagnostics.html`](webroot/diagnostics.html)（需与 `probe.ttf` 同目录），分别在停用／启用作用域后冷启动比较。
- 查看 LSPosed 中 `Selffont` 日志：`[attach]` → `[hook-installed]` → `[typeface-hit]` 或 `[gecko-prefs]`。`[gecko-skip]` 表示目标字体不可读，`[gecko-unsupported]` 表示入口不匹配。
- 对照页的测试字体会把普通 ASCII `A` 画成三角形；对照组应先能显示三角形，才能用实验组的普通 `A` 判断网页字体选择变化。

完整步骤、失败判据与回退方式见 [`docs/validation.md`](docs/validation.md)；职责、证据和设计约束见 [`docs/architecture.md`](docs/architecture.md)。

## 手动兜底与卸载边界

```sh
# 以下在手机 root shell 内运行；通常使用 WebUI 的确认按钮即可。
sh /data/adb/modules/MFGA/action.sh diagnose
sh /data/adb/modules/MFGA/action.sh logs
sh /data/adb/modules/MFGA/action.sh gms --confirm
sh /data/adb/modules/MFGA/action.sh app-fonts block --confirm
sh /data/adb/modules/MFGA/action.sh app-fonts restore --confirm
```

- **GMS**：停止 Chrome/Gmail、禁用字体组件、删除 `/data/fonts` 及每用户的 GMS 字体缓存。删除不可撤销；组件状态不会因卸载本模块自动恢复。这不是本阶段 Firefox 路径的默认修复手段。
- **阅读应用权限**：仅处理用户 0 的番茄小说／起点指定字体目录。修改前记录模式和文件身份，使用自动随进程退出释放的 `flock` 锁（命令不可用则拒绝修改）；恢复只处理记录中仍匹配且仍为 `000` 的文件，不猜测统一的 `600` 权限。
- 权限记录在 `/data/adb/selffont/app-permissions.tsv`，不会在更新模块时丢失；卸载会尝试恢复这些记录。失败记录保留。旧版未记录的 `chmod` 不自动恢复。
- 禁用 Xposed 并冷启动应用可停止运行时替换；KSU 禁用模块并重启可撤销挂载。两者与 GMS 的持久状态是不同恢复边界。

## 主机测试

```sh
.venv/bin/python -m unittest discover -s tests -v
node --test tests/commands.test.mjs
sh tests/run_java.sh   # JDK 17+
```

Shell 行为测试使用 BusyBox ash 和临时目录，不碰真实 `/data`。打包测试使用合成基础 ZIP，不代替真实完整基础包测试。原有 `tools/GPOS`、字体合并及 Emoji 工具不在这轮重构范围内。
