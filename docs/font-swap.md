# 更换基准字体

字体身份是配置驱动的：`config/font-source.json` 是主机侧真源，`FontIdentity.kt` 是运行时镜像，打包期由 `tools/build_module.py` 生成模块内的 `font.conf`（面名与可见性文件，shell 唯一来源）与 `webroot/font.json`（诊断页探针）。换字体只需按下表改，契约测试会拦住漏改。

## 0. 候选字体要求

1. **许可**：OFL 或其他可再分发许可，许可文本放进 `licenses/`，`licenseFile` 指向它。
2. **静态面**：一个或若干静态 TTF，给出 Android 字重（建议覆盖 300–900 中的若干档）。**不接受**伪造 `fvar` 把静态面伪装成可变字体。
3. **基线字形**：覆盖 `baselineCharacters`（默认 `好中国体Abc0123456789`）。
4. **家族名**：`prepare_font.py` 会改名为派生家族；上游若有 Reserved Font Name，改名是义务而不是偏好。
5. **缺字情况**：先用 `tools/glyph_audit.py` 对 `config/glyph-targets.json` 跑一遍，确认哪些目标字根本不存在——那类字不能用点 patch 解决。

## 1. 变更清单

| 文件 | 变更 |
|---|---|
| `config/font-source.json` | `project` / `version`（`main@<commit>` 形式）/ `sourceFamily` / `family` / `license` / `licenseFile` / `visibilityFile` / `faces[]`（每面的 `weight`、`style`、`file`、`installedFile`、`bytes`、`sha256`） |
| `licenses/` | 新许可文本，文件名与 `licenseFile` 一致；删除旧字体的许可文件 |
| `mfga-xposed/.../FontIdentity.kt` | `FAMILY`、`FONT_PATH`、`FACE_PATHS`（`CARRIER_PATH` 保持 Roboto 载体不变） |
| `config/module.json` | `name` / `description`，并 bump `version` / `versionCode` |
| `webroot/strings/locales/*.json` | `BASELINE_DESC` 等提及字体名/版本的文案（各语言键集必须一致） |
| `README*.md` / `docs/*.md` / `changelog.md` | 文档里的字体名与版本 |

**不需要改**：`fonts.xml`（补充配置输入）、Roboto 度量载体、`tools/`（全部从配置读取）、`script/`（读模块 `font.conf`）、`webroot/diagnostics.html`（读模块 `webroot/font.json`，离线保留静态回退）、平台闸门、作用域策略、度量归一逻辑。

## 2. 校验与构建

```sh
.venv/bin/python tools/prepare_font.py --font-dir /path/to/new-faces   # 本地原版文件
.venv/bin/python tools/glyph_audit.py                                  # 目标字覆盖情况
.venv/bin/python tools/prepare_base.py
.venv/bin/python tools/build_module.py --base build/base/MFGA-base.zip
.venv/bin/python -m unittest discover -s tests
(cd mfga-xposed && gradle test)
```

- `prepare_font.py` 校验：大小、SHA-256、上游家族名、`OS/2` 字重、基线字形；改名后断言 glyphOrder/逐字形字节/cmap 不变。
- `build_module.py` 校验：每个面的行度量归一后字形/cmap/家族/字重不变、载体无可见字形、打包后哈希与规范化输入一致。
- CI 在 `config/**` 变更时触发 **Build Selffont font module**，产出 `Selffont-Maru.zip` + SHA-256 + `module-report.json`；APK 工作流在 `mfga-xposed/**` 变更时触发。

## 3. 真机验收

按 `docs/validation.md`：安装重启 → 勾选作用域 → 诊断页两次冷启动对比 → 核对 `[typeface-hit]` / `[gecko-prefs]` 日志链 → 检查角标等紧凑槽位。通过前新字体状态为 `NOT_TESTED`，把证据记进 `docs/validation.md` 与 `changelog.md`。

## 4. 回退

换字体不改变模块结构与恢复路径：KSU 禁用模块并重启撤销挂载；停用作用域并冷启动进程停止运行时替换。退回旧字体只需把上表改回旧值重新构建。
