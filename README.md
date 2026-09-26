# Selffont

Android 个人字体模块:把 **文渊圆体**(WenYuan Rounded SC VF,`wght` 100–900 + `ital` 0–1)做成系统级统一字体家族。基于 MFGA 的资源,代码全部重写。

目标:统一字体家族,**不**抹平粗体、斜体、小型大写、语言与原始 Unicode 字符。系统 UI 与 Firefox 网页是两条不同的字体加载路径,各走各的原生机制。

## 四化

- **原生化**:系统字体走 `fonts.xml` 原生挂载——Android 本来就该这么配字体。只有系统管不到的两条路径(应用自带字体、Gecko 网页字体)保留 LSPosed Hook,只用公开 API,零 JNI。没有开机脚本、没有守护进程、没有应用数据干预。
- **自由化**:没有平台闸门。任何 Android 版本、任何厂商、任何管理器都能装——装在未测试设备上是你的自由,风险也是你的。`config/sources.json` 里的哈希只是默认下载源的提示,不是锁:`--font` / `--base` 指向任何文件或 URL 都能构建,家族名、可变轴、度量全部现场从字体读取,静态字体也能打包。
- **简单化**:一套仓库、一个构建脚本、一个 CI、一个自检文件。没有诊断探针、没有 WebUI 按钮矩阵、没有 GMS/应用权限把戏、没有 i18n 层、没有"测重构的测试"。
- **现代化**:AGP 9.3(内置 Kotlin)/ Gradle 9.5 / JDK 21 / Android SDK 36 / Python 3.11 / fontTools。Kotlin 共 2 个源文件。

## 结构

```
fonts.xml            输入:系统字体配置(MFGA 补充字体引用,不改动)
config/sources.json  默认下载源与提示哈希(非强制)
tools/build.py       打包器:任意字体 + 任意基础包 → KSU 模块 zip
module/              装进 zip 的运行时:customize.sh / action.sh / webroot / 许可
xposed/              LSPosed 模块:Entry.kt(挂钩)+ Policy.kt(纯策略)
tests/selfcheck.py   一个自检文件:归一、配置生成、端到端构建、脚本行为
```

## 构建

```sh
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tests/selfcheck.py

# 默认源(文渊 v1.010 + MFGA 基础包),自动下载并缓存:
.venv/bin/python tools/build.py

# 任意字体、任意基础包(本地路径或 URL),来源自由:
.venv/bin/python tools/build.py --font /path/to/AnyFont-VF.ttf --base /path/to/any.zip
```

产物 `build/Selffont.zip`。换字体时若要在 Firefox 里生效,把 `xposed/.../Policy.kt` 的 `FAMILY` 改成新字体的内部家族名(构建器会警告提醒)。APK:`cd xposed && gradle --no-daemon assembleDebug`(JDK 21 + SDK 36)。

CI:`.github/workflows/build.yml` 一个工作流同时产出模块 zip 和诊断 APK。

## 安装与验证

1. KSU 安装 `build/Selffont.zip`,重启。模块 ID 保持 `MFGA`,与旧版 MFGA 互斥覆盖。
2. 安装 APK,在 LSPosed 勾选目标应用(Firefox 等),彻底停止后冷启动。
3. 日志标记:`[attach]` → `[hook-installed]` → `[typeface-hit]` / `[gecko-prefs]`;`[gecko-skip]` = 该进程读不到字体文件。KSU WebUI 或 `action.sh diagnose` 只读诊断。

安装脚本把本模块 `fonts.xml` 整份替换到系统所有 `font*.xml` 位置(`fonts_customization.xml` 除外——那是用户自选配置,不同 schema)。打包时把安装副本的竖直行度量归一到 Roboto 空壳载体的名义度量,修角标数字偏低/切下沿;**只改行度量**,字形、cmap、家族名、轴逐字节保留,原版字体哈希不变。

## 卸载

KSU 删除模块,重启。系统字体立即恢复原状——模块不写任何系统外的持久状态。

## 边界(诚实条款)

- 真机验证过:Android 16 / Oplus / KernelSU / LSPosed 2.2.0(7854)这一台机器。其他平台自担风险,不外推。
- Firefox 对 Unicode 15.1/16 新 emoji 显示豆腐块,是 Gecko 自有字体后端限制,本模块不可修(已用字形探针 A/B 排除)。
- Hook 安装成功 ≠ 网页已使用目标字体。Gecko 用户首选项、缓存、发布版优化都可能覆盖注入值。
- 文渊缺的字(彩色 emoji、生僻码位)走系统回退;Gecko 首选项只前置不清空回退链,不碰 emoji。
- 上游 MFGA 历史与资源归属见 `LICENSES.md`;基础包只取字体资源,绝不执行其代码。
