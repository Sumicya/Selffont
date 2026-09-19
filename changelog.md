# 更新日志

## v1.4.1（2026-09-17）

继续三化重构与主字体更换准备。字体资源不变：文渊原版与其 SHA-256 同 v1.4.0 逐字节一致；变更在打包、契约测试与文档。

- 现代化：新增 `Typeface.create(Typeface,int,boolean)`（API 28+）与 `Typeface.create(Typeface,int)` 两个静态入口 Hook，对齐 MFGA 上游 2026-09-15 `fix: some basics`（`32c0ed6`），补齐直调路径；重入由既有 `ReplacementGuard` 保护，`create(String,int)` 刻意不 Hook（名字解析留给框架/familyset）。Hook 面提取为纯谓词 `HookTarget`，PolicyTest 增加主机侧覆盖断言。上游同批的 compileSdk/targetSdk 37 与静态字重分档不采用：目标设备在 API 36 验证，字重分档与 `wght` 100–900 可变字体策略冲突。
- 自由化：模块新增生成的 `font.conf`（`SELFFONT_INSTALLED_FONT`），`customize.sh`／`diagnose.sh`／`device_state.sh` 不再硬编码安装文件名；`prepare_font.py` 从 `font-source.json` 读许可文件与基线字符（新增 `licenseFile`／`baselineCharacters`）；打包器另生成 `webroot/font.json`，诊断页 local() 探针读取其中家族名（离线保留静态回退）；代码注释不再硬编码字体名；新增契约测试 `tests/test_font_swap.py`——家族名/安装文件名/许可证名只允许出现在配置、FontIdentity、许可证与文档，代码出现即 CI 失败。
- 原生化：策略不变（仅原生平台 API，不强塞 JNI）；新增 Hook 同为框架原生入口。
- CI 修复：`android-actions/setup-android@v4` 默认仍请求 Google 已于 2026-09-15 停服的 `tools` 包，导致该步骤自当日起全部失败（上游 android-actions/setup-android#537）；显式指定 `packages: platform-tools`（与 MFGA `32c0ed6` 同改）。
- 字体更换准备：新增 `docs/font-swap.md`（候选字体要求、变更清单、校验与真机验收路径）；README 中/英精简，细节移入 docs/；模块版本 v1.4.1。

## v1.4.0（2026-09-12）

面向 Android 16 / Oplus(oplus/oppo/oneplus/realme) / KernelSU 的文渊圆体系统字体模块 + 只读诊断 APK。真机安装、完整字体模块与网页覆盖标注为待验证（见 docs/validation.md）。

- 主字体为文渊圆体可变字体（WenYuan Rounded SC VF，`wght` 100–900 + `ital` 0–1）；`fonts.xml` 为每个字重生成 `<axis>` 指向同一 VF 文件，构建期用真实字体 `fvar` 校验轴值不越界（`dynamicWeightAxes`）。
- 模块减重：仅打包 `fonts.xml` 实际引用的补充字体，未引用者作为死重丢弃并记入 `module-report.json`（`unreferencedFontsDropped`）。
- 三化重构（现代化/自由化/原生化）：
  - 现代化：CI 与构建统一到 node24 + JDK 21（当前 LTS）；`mfga-xposed` 全量迁移到 Kotlin（10/10 类，移除 `src/main/java`），升级 AGP 9.3.0 / Gradle 9.5.0 并改用 AGP 9 内置 Kotlin（无需单独 Kotlin 插件）；策略断言从 `run_java.sh` 迁入 Gradle 单元测试 `PolicyTest.kt`。逻辑不变。
  - 自由化：新增 `FontIdentity` 作为字体家族名/路径的单一真源（消除 `GeckoFontPolicy`、`FontMetricsProbe` 的重复硬编码）；平台闸门新增用户自选放行标记 `/data/adb/selffont_allow_unsupported`，默认严格不变、仅额外开放"自担风险"的绕过口(安装期 `customize.sh` 与运行期 `TargetPlatform.allowed` 同步支持,含测试)。
  - 原生化：确认现状已达标（`FontForceCore` 用原生 `Typeface.create`、Hook 仅用平台 API），不强塞 JNI。
- Gecko `font.name-list` 前置保留（1.4-gecko-fallback）：由"覆盖成只有文渊"改为"前置保留原回退链"，不再对无 list 项造窄列表，不触碰 emoji 首选项。注：设备 prefsMap 无 `font.name-list`/emoji 键，故此改动对火狐缺字为空操作；火狐 Unicode 15.1/16 新 emoji 豆腐块经 A/B 证明属 Gecko 后端限制，非本模块可修（见 docs/validation.md）。
- 打包期度量归一（1.4-phase2-metrics）：将安装副本文渊的竖直行度量对齐 Roboto 载体名义度量，根治通知计数/红点角标/时钟等紧凑槽的数字偏低与切下沿；只改行度量，字形/cmap/family/轴与原版 SHA-256 不变，带构建期防切保护。
- 文渊圆体固定资源与配置生成、KSU/Oplus/Android 16 支持边界。
- 删除上色及字体屏蔽；额外干预仅手动。
- 现代 API 102 单入口；Gecko 155.0.1 启动字体首选项适配及分层诊断。
- 主机契约检查（Python + node + Kotlin `gradle test`）及诊断 APK 构建已由 CI 通过；真机安装、完整字体模块与网页覆盖仍待验证，参见 docs/validation.md。

---

以下是上游历史记录，不是当前功能清单。

CN
 
17.0.1.08-31-alpha2(1717180003)
 - 1.适配HyperOS4
 - 2.同步/新增部分字体，调整部分私用区符号颜色
 - 3*.新增Xposed版本MFGA覆盖一些内置了字体的应用
 - 4.增加了对部分Unicode18彩色Emoji的初步支持(早期预览版)
```
🛙🪋🪌🪍🫌🫝🫫🫹🫺
```
 
17.0.0.06-27-alpha(1717180001)
 - 1.同步Roboto到3.0.16(SU)
 - 2.WebUI新增主字体上色，需支持COLRv0，Android10及以上
 - 3.调整主字体中部分组合类符号，修复缺失、在高安卓版本显示异常的情况
 

-------
EN
 
17.0.1.08-31-alpha2(1717180003)
 - 1.Added support for HyperOS 4
 - 2.Synced/Added some fonts and adjusted the colors of some Private Use Area symbols
 - 3*.Added an Xposed version of MFGA to override fonts in some apps with built-in fonts
 - 4.Added preliminary support for some Unicode 18 colored emoji (early preview)
```
🛙🪋🪌🪍🫌🫝🫫🫹🫺
```
 
17.0.0.06-27-alpha(1717180001)
 - 1.Synchronized Roboto font to version 3.0.16(SU).
 - 2.Added main font colorization in WebUI; requires COLRv0 support, Android 10 and above.
 - 3.Adjusted some composite symbols in the main font, fixing missing glyphs and display issues on higher Android versions.
 

Telegram channel:

https://t.me/AndroidCoreLayer

Power by:

Yiyunlengyu(酷安@Numbersf)