# Selffont · 第一阶段

面向 **Android 16（API 36）/ Oplus / KernelSU / LSPosed 2.2.0（7854）** 的个人字体方案，基于 MFGA 重构。统一系统字体家族为 **文渊圆体 v1.010**（可变字体 `wght` 100–900 + `ital`），保留粗体、斜体、小型大写与原始 Unicode 文本；不做上色、整字体/区间屏蔽或改写。

> **状态**：主机测试与 CI（Kotlin 策略单元测试、诊断 APK、字体模块构建）全部通过；真机已确认目标字体挂载、Gecko 首选项注入与度量归一（角标数字偏低/切底经用户真机确认修复）。仍待真机验收：完整模块安装与网页渲染。Firefox 对 Unicode 15.1/16 最新 emoji 的豆腐块经 A/B 证明属 Gecko 后端自身限制，与本模块无关。

## 设计边界

- 统一字体家族，不抹平排版语义；LSPosed 勾选是唯一作用域来源，模块内无应用白名单。
- 仅现代 Xposed API 102；Hook 覆盖框架字体工厂入口（`Typeface.Builder`／`CustomFallbackBuilder`、asset／file 工厂、`Typeface.create` 静态工厂）。
- 只把**安装副本**的行度量归一到 Roboto 载体名义度量（修正通知角标数字偏低/切底）；字形、cmap、family、轴逐字节不变，带构建期防切保护。见 `tools/metric_normalize.py`。
- `fonts.xml` 为补充配置输入；打包器生成实际安装配置；默认/condensed 家族保留 Roboto 度量载体。
- Firefox：Gecko 启动时注入内存中的默认字体首选项（主字体首选＋前置保留回退链，不触碰 emoji 首选项）；无扩展、不改 profile、无原生地址 Hook。
- GMS 与阅读应用字体权限仅为手动兜底（需显式确认）；安装、开机、WebUI 不执行。
- 平台闸门：默认仅在上经验证的组合安装并挂钩；`touch /data/adb/selffont_allow_unsupported` 可自担风险放行，删除即恢复严格闸门。
- 未适配其他 Android/ROM/root 管理器，测试结果不外推。

## 构建

字体模块（Python 3.11+）：

```sh
python3 -m venv .venv
.venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tools/prepare_font.py   # 或 --font /path/to/WenYuanRoundedSCVF.ttf
.venv/bin/python tools/prepare_base.py
.venv/bin/python tools/build_module.py --base build/base/MFGA-base.zip
```

诊断 APK（JDK 21 / Gradle 9.5.0 / Android SDK 36 / AGP 9.3.0，全 Kotlin）：

```sh
cd mfga-xposed && gradle --no-daemon assembleDebug
```

CI：**Build Selffont font module**（产物 `Selffont-phase1.zip`＋SHA-256＋构建报告）、**Build Selffont diagnostic APK**（开发签名）、**Check Selffont contracts**（主机测试）。基础包只提供字体资源与归属说明；其脚本、开机钩子、原生工具与数字主字体均不继承。字体、基础包、APK 与构建产物不入 Git；不要把仓库直接压缩安装。模块 ID 为 `MFGA`。

主机测试（与 CI 相同）：

```sh
.venv/bin/python -m unittest discover -s tests -v
node --test tests/commands.test.mjs
(cd mfga-xposed && gradle test)   # Kotlin 策略单元测试
```

## 验证与回退

- 安装模块 → 重启 → LSPosed 勾选目标应用 → 彻底停止并重开应用。
- 用目标手机 Firefox 打开 `webroot/diagnostics.html`（与 `probe.ttf` 同目录），分别在启用/停用作用域后冷启动比较；对照组普通 `A` 应显示为三角形。
- LSPosed 日志链：`[attach] → [hook-installed] → [typeface-hit] | [gecko-prefs]`；`[gecko-skip]` 表示该进程字体不可见。
- 手动兜底（root shell）：`sh /data/adb/modules/MFGA/action.sh diagnose | logs | gms --confirm | app-fonts block|restore --confirm`。
- 完整步骤、失败判据与回退：`docs/validation.md`；职责与证据：`docs/architecture.md`。

## 更换主字体

只需改 `config/font-source.json`＋`FontIdentity.kt`＋`licenses/`（另加 `config/module.json` 的名称/描述）；契约测试保证其他代码不含旧字体名硬编码，模块自动生成 `font.conf` 与 `webroot/font.json`。见 `docs/font-swap.md`。
