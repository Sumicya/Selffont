# 真机验收清单

主机测试不等于装机测试。当前目标是 **Android 16 / Oplus / KSU / LSPosed 2.2.0（7854）+ Firefox 155.0.1**，字体为 **Selffont Maru v2.0.0**（Zen Maru Gothic 派生，五个静态面）。

> `Selffont Maru` 路线的真机结果**尚未采集**。文渊时代的设备证据（字体挂载可见、Gecko 首选项注入、度量归一修好角标、emoji 豆腐块属 Gecko 限制）保留在 Git 历史（`d0f9ae7` 及更早）供追溯，但**不能当作当前字体的结论**。

## 1. 准备与回退

- 记录当前模块版本、APK `versionCode/versionName`、LSPosed 作用域勾选情况。
- 回退手段：KSU 禁用模块并重启撤销挂载；停用 Xposed 作用域并冷启动撤销运行时替换；APK 签名变化需先卸载再装并重勾作用域。
- GMS 缓存删除不可逆，阅读应用权限改动有日志可恢复（见第 5 节）。

## 2. 安装与可见性

- 安装 `build/Selffont-Maru.zip`（CI 产物解开外层压缩包后的安装包），重启。
- 确认模块目录里五个面都在，且 `font.conf` 内容与 `config/font-source.json` 一致。模块内 `font.conf` 是面名的唯一真源，shell 脚本不再硬编码。
- `sh /data/adb/modules/MFGA/action.sh diagnose` 应打印平台信息与 `[shell-font-visible] <面名>`；`[shell-font-missing]` 说明挂载或路径有问题。
- 期望（尚未验证）：`/system/fonts/SelffontMaru-*.ttf` 可读；`fonts.xml` 的默认家族仍是空壳 Roboto，可见字形家族紧随其后。

## 3. 网页对照（Firefox）

- 用 Firefox 打开 `webroot/diagnostics.html`（与 `probe.ttf` 同目录，模块里另有构建期生成的 `webroot/font.json`）。
- 对照组：本项目自制测试字体把普通 `A` 画成三角形；若停用作用域后都不是三角形，则不能用本页判断字体替换。
- 实验组：启用作用域、彻底停止并冷启动 Firefox，本地家族探针应显示 `Selffont Maru` 字样。
- LSPosed 日志链：`[attach] → [hook-installed] → [typeface-hit]` 或 `[gecko-prefs]`；`[gecko-skip]` 表示 Firefox 进程看不到目标文件。
- **源码里有入口、日志显示成功，都不等于网页已使用目标字体。**

## 4. 紧凑槽位（角标/时钟/计数）

- 看通知分组计数、红点角标、时钟：数字应居中、不切下沿。这是度量归一的目标；若仍偏低，记录截图与 `module-report.json` 里的 `metricNormalization`。
- 正文检查：粗体、斜体、小型大写应保留；CJK 生僻字与 emoji 走回退（Zen Maru 缺的字会回退到系统字体，这是预期行为，不是模块故障）。

## 5. 手动兜底（默认不执行）

```sh
sh /data/adb/modules/MFGA/action.sh diagnose
sh /data/adb/modules/MFGA/action.sh logs
sh /data/adb/modules/MFGA/action.sh gms --confirm
sh /data/adb/modules/MFGA/action.sh app-fonts block --confirm
sh /data/adb/modules/MFGA/action.sh app-fonts restore --confirm
```

GMS 缓存删除不可逆；阅读应用权限只处理用户 0 的指定目录，改前记录模式与文件身份，恢复只处理仍匹配且仍为 `000` 的文件，不猜统一 `600`。旧版未记录的 `chmod` 不自动恢复。

## 6. 主机可复现检查（与 CI 相同）

```sh
.venv/bin/python -m unittest discover -s tests   # 100 项契约测试
node --test tests/commands.test.mjs
.venv/bin/python -m ruff check .
(cd mfga-xposed && gradle test)                  # Kotlin 策略单元测试（JDK 21+）
```

字体全链路可在本机演练（不碰设备）：`prepare_font.py`（可用 `--font-dir` 指本地源面）→ `edit_font.py` → `glyph_audit.py` → `build_module.py --base <base.zip>`。打包测试用合成 base ZIP，不代替真实 154 MB 基础包的端到端验证。

## 7. 记录新证据

采集到的设备结果写进本节（版本、日期、观察、结论），并同步 `changelog.md`。没有设备证据时，`module-report.json` 里的 `deviceInstallation`/`webpageRendering` 保持 `NOT_TESTED`。
