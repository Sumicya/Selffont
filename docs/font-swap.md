# 更换主字体

v1.4.1 起，主字体身份（家族名、安装文件名、许可证文件、基线字符）是配置驱动的：`config/font-source.json` 是主机侧单一真源，`FontIdentity.kt` 是运行时镜像，打包器把它们生成到模块的 `font.conf`（shell 用）与 `webroot/font.json`（诊断页用）。换字体只按下表改；`tests/test_font_swap.py` 会在 CI 失败任何代码里的旧名硬编码，`tests/test_font_paths.py` 校验各镜像与配置一致。

## 0. 候选字体要求

1. **许可证**：OFL 或其他可再分发许可，并把许可文件放入 `licenses/`（当前文渊的 OFL 在 `licenses/WenYuan-OFL.txt`）。
2. **可变字体**：`fvar` 含 `wght` 100–900 与 `ital` 0–1。`tools/font_config.py` 按 9 字重 × 2 斜体生成轴阶梯，`tools/prepare_font.py` 严格校验该形状；候选轴不同则同步调整 `primary_fonts()` 的阶梯与 `verify_font()` 的断言。
3. **基线字形**：覆盖 `font-source.json` 的 `baselineCharacters`（默认 `你好中国圆体Abc0123456789`），可按新字体改写。
4. **行度量**：与 Roboto 载体名义度量差异越大，打包期归一（`tools/metric_normalize.py`）修正越多；构建期防切保护会校验数字墨迹不被新行盒切掉，失败即拒绝打包。
5. **内部家族名**（name ID 1）：Gecko 首选项注入与诊断页 `local()` 探针都以它为准，原样记录进 `family`。

## 1. 变更清单（只改这些）

| 文件 | 变更 |
|---|---|
| `config/font-source.json` | `project` / `version` / `family` / `file` / `installedFile` / `bytes` / `sha256` / `url` / `apiUrl` / `licenseFile` / `licenseUrl` / `baselineCharacters` |
| `licenses/` | 新字体许可文件，文件名与 `licenseFile` 一致 |
| `mfga-xposed/app/src/main/kotlin/com/mfga/xposed/FontIdentity.kt` | `FAMILY`、`FONT_PATH`（`CARRIER_PATH` 保持 Roboto 载体不变） |
| `config/module.json` | `name` / `description`，并 bump `version` / `versionCode` |
| `webroot/strings/locales/*.json` | `BASELINE_DESC` 等提及字体名/版本的文案（各语言必须保持相同键集） |
| `README.md` / `README-en.md` / `docs/*.md` / `changelog.md` | 文档中的字体名与版本 |

**不需要改**：`fonts.xml`（补充配置输入）、Roboto 度量载体、`tools/`（全部从配置读取）、`script/`（读模块 `font.conf`）、`webroot/diagnostics.html`（读模块 `webroot/font.json`，离线保留静态回退）、平台闸门、作用域策略、度量归一逻辑。

## 2. 校验与构建

```sh
.venv/bin/python tools/prepare_font.py --font /path/to/NewFontVF.ttf   # 本地原版文件
.venv/bin/python tools/prepare_base.py
.venv/bin/python tools/build_module.py --base build/base/MFGA-base.zip
.venv/bin/python -m unittest discover -s tests -v
(cd mfga-xposed && gradle test)   # FontIdentity 契约（gradle assembleDebug 出 APK）
```

- `prepare_font.py` 校验：大小、SHA-256、内部家族名、轴形状、基线字形。
- `build_module.py` 校验：配置轴值不越出真实 `fvar`（动态字重不被静默钳制）、归一后字形/cmap/family/轴逐字节保留、载体无可见字形；产物 `module-report.json` 记录 `installedFile` 与全部校验值。
- 模块内自动携带按新配置生成的 `font.conf` 与 `webroot/font.json`。
- CI 在 `config/**` 变更时触发 **Build Selffont font module**，产出新的 `Selffont-phase1.zip`＋SHA-256＋报告；APK 工作流在 `mfga-xposed/**` 变更时触发。

## 3. 真机验收

按 `docs/validation.md`：安装重启 → 勾选作用域 → 诊断页两次冷启动对比（本地家族探针会自动指向新家族）→ 核对 `[typeface-hit]` / `[gecko-prefs]` 日志链 → 检查角标等紧凑槽位。通过前新字体状态为 NOT_TESTED；把证据记入 `docs/validation.md` 与 `changelog.md`。

## 4. 回退

换字体不改变模块结构与恢复路径：KSU 禁用模块并重启可撤销挂载；诊断 APK 停用作用域并重启进程可停止运行时替换。若需退回旧字体，把 `config/font-source.json` 等改回旧值重新构建即可（旧版固定值见 Git 历史与 `config/base-source.json` 的既有校验）。
