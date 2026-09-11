# Selffont 第一阶段（未发布诊断版）

- 三化重构（现代化/自由化/原生化）：
  - 现代化：CI 与构建统一到 node24 + JDK 21（当前 LTS）；Java 源码改用 `Set.of`/`List.of` 等 Java 21 惯用写法，逻辑不变。
  - 自由化：新增 `FontIdentity` 作为字体家族名/路径的单一真源（消除 `GeckoFontPolicy`、`FontMetricsProbe` 的重复硬编码）；平台闸门新增用户自选放行标记 `/data/adb/selffont_allow_unsupported`，默认严格不变、仅额外开放"自担风险"的绕过口(安装期 `customize.sh` 与运行期 `TargetPlatform.allowed` 同步支持,含测试)。
  - 原生化：确认现状已达标（`FontForceCore` 用原生 `Typeface.create`、Hook 仅用平台 API），不强塞 JNI。
- Gecko `font.name-list` 前置保留（1.4-gecko-fallback）：由"覆盖成只有文渊"改为"前置保留原回退链"，不再对无 list 项造窄列表，不触碰 emoji 首选项。注：设备 prefsMap 无 `font.name-list`/emoji 键，故此改动对火狐缺字为空操作；火狐 Unicode 15.1/16 新 emoji 豆腐块经 A/B 证明属 Gecko 后端限制，非本模块可修（见 docs/validation.md）。
- 打包期度量归一（1.4-phase2-metrics）：将安装副本文渊的竖直行度量对齐 Roboto 载体名义度量，根治通知计数/红点角标/时钟等紧凑槽的数字偏低与切下沿；只改行度量，字形/cmap/family/轴与原版 SHA-256 不变，带构建期防切保护。
- 文渊圆体固定资源与配置生成、KSU/Oplus/Android 16 支持边界。
- 删除上色及字体屏蔽；额外干预仅手动。
- 现代 API 102 单入口；Gecko 155.0.1 启动字体首选项适配及分层诊断。
- 主机／Java 契约检查及诊断 APK 构建已由 CI 通过；真机安装、完整字体模块与网页覆盖仍待验证，参见 docs/validation.md。

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