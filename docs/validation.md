# 真机验收清单

## 0. 状态声明

主机测试不等于装机测试。当前目标是用户报告的 Android 16 / Oplus / KSU / LSPosed 2.2.0（7854），Firefox 155.0.1（2016182535）。旧仓库删除前的 APK 测试不作为本轮证据。

## 1. 准备与回退

- 保留正在使用的完整字体模块安装包，以及关闭 KSU 模块后重启的可用路径。
- 新模块 ID 仍为 MFGA；不要另外安装一个同样覆盖字体目录的并行模块。
- 新 APK 如签名冲突，先停用并卸载旧 APK，再安装诊断 APK、重新勾选 Firefox。不要同时启用新旧字体 Hook。
- 不先执行 GMS 清理或阅读应用权限处理；这些不是本次 Firefox 实验的前置条件。
- 字体模块变更后重启系统；Xposed 作用域变更后彻底停止 Firefox 再打开。
- 回退分别处理：停用 APK 作用域并重启进程；停用 KSU 模块并重启系统。GMS 持久组件状态、缓存删除不随这两个操作撤销。

## 2. 先看“安装与可见性”

在 KSU WebUI 点击只读诊断，确认 API/品牌与目标一致、shell 能读取目标字体。

随后检查 Firefox 的 `Selffont` 日志。**shell 可读不等于 Firefox 可读**；KSU 的应用卸载模块设置或挂载命名空间可能不同。

| 日志 | 只证明什么 | 接下来 |
|---|---|---|
| `[attach]` | 模块已进入包的加载流程 | 查看安装 Hook 记录 |
| `[hook-installed]` | 框架接受了对应 Hook | 查看实际命中 |
| `[typeface-hit]` | Java 字体工厂实际经过替换 | 验证对应原生界面，不外推网页 |
| `[gecko-prefs]` | 根运行时首选项经过注入 | 比较网页的实际字形 |
| `[gecko-skip]` | Firefox 此时无法读取目标字体 | 排查字体准备、重启、KSU 挂载 |
| `[gecko-absent]` | 当前 classloader 没有 GeckoView 类 | 检查进程、时机与实际发行版本 |
| `[gecko-unsupported]` | 预期入口／签名不匹配 | 以该 APK 的新证据继续适配 |
| `[replacement-failed]` / `[gecko-failed]` | 适配器失败并保留原值 | 不计为成功，保存精简日志 |

只需要提供这些标签附近的信息；无需完整浏览记录、网页内容或用户 profile。

## 2.1 日志导出：按来源字段筛选并去重

首次导出使用全文关键词匹配，会混入旧版 MFGA 记录、其他模块正文中的网址／Intent，以及模块日志与详细日志的重复行。已经改为按实测的 `LSPosedLogDaemon` 结构字段匹配：来源必须是 `[com.mfga.xposed,Selffont,...]`，不能仅在消息正文中提到这个名称。修订解析器读取第一个进程／来源字段，不再要求固定的时间戳前缀，容许字段间空白；仍不向后搜索其他模块正文里引用的记录。去重只去除完全相同的记录，不合并不同进程的相同事件，最多输出最后 300 条唯一记录。

`script/filter_logs.awk` 与 `script/collect_logs.sh` 已加入模块打包。它们只读当前 `/data/adb/lspd/log/modules*.log` 和 `verbose*.log`，不读取配置数据库、props 或完整系统缓冲区；没有匹配会明确报告，不能据此判定未注入。

**本轮已有日志足以验证入口，不需要重新采集。** 后续安装包含这两个文件的新字体模块后，若需要一次性导出：

```sh
su -c 'sh /data/adb/modules/MFGA/action.sh logs > /sdcard/Download/selffont-log.txt'
```

上传 TXT 附件即可，不需要长按逐条复制；安装 APK 则使用正常下载链接和系统安装器，不需要 Termux 安装流程。日志目录已核对 LSPosed v1.9.2 和 Vector v2.2 的源码，以及本轮实际采集结果；不把不同项目的版本号等同起来。

## 3. 网页对照

使用项目的 `webroot/diagnostics.html`，同时提供 `styles.css`、`probe.ttf`。可以在电脑上临时启动静态服务器并从同一网络的手机访问：

```sh
python3 -m http.server 8080 --bind 0.0.0.0 --directory webroot
```

手机访问电脑可达地址，而不是手机上的 localhost。这个对照页面不调用 root bridge，也不会上传粘贴文字。正式测试应使用同一份页面和同一字号、缩放设置。

| 项目 | 对照：作用域关闭 | 实验：作用域开启 | 通过条件 |
|---|---|---|---|
| 系统设置／Firefox 设置页 | 记录现状 | 文渊或系统目标字体 | 无新增缺字、崩溃；不能据此证明网页成功 |
| 网页 serif / sans-serif / monospace / cursive / fantasy | 记录各族差异 | 主要文字族统一 | 特别观察 cursive 不再选择原花体 |
| 页面自制 web font 的 `AAAA` | 应为四个三角形 | 应为目标字体的四个 A | 对照先有效；不是只看下载成功／CSS 计算值 |
| 粗体和斜体 | 可辨认 | 仍可辨认 | 字重／斜体语义未被抹平 |
| CSS small-caps | 小型大写 | 仍是小型大写 | 保留此特性是正确结果，不是失败 |
| `Abc / 𝒜𝒷𝒸 / ᴀʙᴄ` | 不同码点 | 仍为不同码点 | 复制、搜索语义不变 |
| 常用中文、生僻字、Emoji | 记录回退表现 | 不新增明显缺失 | 缺字单独记为覆盖／回退问题 |
| 真实问题网页 | 保存非敏感 URL/小截图 | 对比同位置 | 不用一个测试页宣称全部网页兼容 |

若 `[gecko-prefs]` 命中但网页未统一，下一步核查引擎的真实字体匹配／用户覆盖首选项，而不是盲目再 Hook Java Typeface。若页面三角形在对照组也未显示，该对照无效，先排查测试字体加载或已有浏览器字体策略。

## 4. 手动权限兜底（与 Firefox 实验分开）

- 仅在确实需要番茄小说／起点绕过内置字体时使用。先停止对应应用再操作；不承诺与应用并发写文件或断电场景下的事务性。
- 应用字体权限修改前后各记录一次原模式；确认重复执行没有把原模式误记为 000。
- 恢复／卸载后，只恢复本版本记录的模式；不将所有文件猜测为 600。
- 后续新建或已由应用／用户改过权限的文件不强制覆盖。
- 原版本没有记录的变化需要用户自行确定原模式，本版本不伪造恢复成功。
- 该兜底只处理用户 0。失败时检查返回码与保留的权限记录，不把部分成功视为全部成功。

## 5. 本地可复现检查

```sh
.venv/bin/python -m unittest discover -s tests -v
node --test tests/commands.test.mjs
sh tests/run_java.sh
.venv/bin/python tools/prepare_font.py --font /path/to/original/WenYuanRoundedSCVF.ttf
```

完整 APK 构建另需 JDK 17、Gradle 8.11.1、SDK 36；本次 CI 运行结果记录如下。测试基础 ZIP 是合成输入，不是现有完整 MFGA 的装机证据。

## 本轮主机验证记录（2026-09-05）

- 22 项 Python 回归测试通过（字体配置、资源契约、合成 ZIP、安装门槛、权限日志与锁、功能删除）。
- 3 项 Node 测试通过（KernelSU 返回契约、固定命令与确认、语言回退）。
- Shell / JavaScript 语法检查、`git diff --check` 通过；WebUI、对照页和字体探针的 HTTP 请求均返回 200。
- 文渊原版实物已核对固定 SHA-256、family、变体轴与基础字符；大资源未加入 Git。
- 提交 `16457fb7ce18f15a7e82c64007d9dda4153dab15` 的 [主机契约 CI](https://github.com/Sumicya/Selffont/actions/runs/33972078226) 成功，包含 Python、Node 和 Java 策略测试。
- 同一提交的 [诊断 APK CI](https://github.com/Sumicya/Selffont/actions/runs/33972078207) 成功，已确认 SDK 安装、Java 策略测试、`assembleDebug`、产物上传步骤均成功。
- 产物 `selffont-phase1-debug-apk`，artifact ID `9971236132`，ZIP 大小 25,312 字节。GitHub 记录的 **ZIP** SHA-256 为 `21651edea1f77f56afc081cbe7f0047f0a45b2fb99b40d7d37a4e1f7d067ae9b`；这不是解压后的 APK 哈希。
- 本工作环境不能连接产物存储的下载地址，因此上述远端状态和元数据已核对，但尚未在这里检查 APK 二进制或签名。手机可以用 `gh run download` 直接获取产物。
- 用户的只读设备检查确认 `/system/bin/stat`、`realpath`、`flock` 存在；现有 MFGA 为 `17.0.1.08-31-alpha2` / `1717180003`。工具存在不等于所有 Shell 行为已真机测试。
- 新 APK 的现代入口与 Gecko 启动入口已由下方设备日志验证；完整字体模块打包已通过下方独立 CI；真机安装、首选项实际改写与 Firefox 绘制仍待验证。

### 先做 APK 入口验证，不把旧字体模块当作新模块

当前现有 MFGA 与新文渊模块是不同资源状态。只安装诊断 APK 时，先检查 LSPosed 是否识别现代入口，以及 Firefox 冷启动后的 `[attach]`、`[hook-installed]`、`[gecko-skip]` / `[gecko-prefs]` 日志。

如果进程中还没有 `/system/fonts/Selffont-WenYuanRoundedSCVF.ttf`，`[gecko-skip]` 是缺少资源时的预期保护行为；不能用这时网页没有变化来判定偏好适配无效，也不能把入口命中算作网页字体替换成功。完整网页对照应在准备、安装并确认新字体资源可见之后进行。

下载本次 APK（普通 Termux，无需 root）：

```sh
gh run download 33972078207 -R Sumicya/Selffont \
  -n selffont-phase1-debug-apk -D "$HOME/selffont-apk-16457fb"
```

## 首次设备入口验证（用户提供的 2026-09-05 日志）

只记录必要结论和本模块的诊断标签，不保存其他模块的 Intent、网址或完整原始日志。

| 时间 | 本模块证据 | 结论 |
|---|---|---|
| 22:51:24.429 | `[attach] phase1 modern-api102 package=org.mozilla.firefox` | 新 APK 已进入 Firefox 主进程 |
| 22:51:24.430–.434 | 5 个 Typeface 工厂及 `RuntimeSettings.getPrefsMap()` 的 `[hook-installed]` | 对应入口安装完成 |
| 22:51:24.543 | `[gecko-skip] target font not visible in this process; prefs unchanged` | Gecko 根运行时入口实际命中；字体不可读，首选项未改写 |
| 22:51:25.167 | `[typeface-hit] ...CustomFallbackBuilder.build()` | 至少这个 Java 工厂实际执行了替换路径，不能外推所有工厂或网页 |

Tab、GPU、utility、crashhelper 进程中的重复安装记录属于不同进程初始化，不单独视为 Hook 循环或崩溃。更早的 `MFGA v1.5` 日志不作为本轮新实现的证据，也不能仅凭历史记录推断新旧模块仍在同时运行。

当前明确阻断点是目标文件在 Firefox 中不可读。此日志本身不能区分未安装字体、挂载命名空间差异和读取权限问题；由于此前尚未交付新字体模块，下一步先完成文渊资源包，再验证可见性。不继续增加 Hook，也不把 `getPrefsMap()` 命中当作网页字体替换成功。

后续资源构建与日志过滤回归：32 项 Python 测试、3 项 Node 测试通过；包括来源字段过滤、旧版本／其他模块正文引用排除、重复记录去重、固定基础包身份，以及打包后主字体哈希复核。真实基础包下载与完整模块构建现已通过独立 CI，记录如下。

## 完整字体模块构建验证

- 源码提交：`10f9eefbab9c59670f87de6bf5b6f451c68d21f3`。
- [字体模块 CI #33975295832](https://github.com/Sumicya/Selffont/actions/runs/33975295832) 成功；已核对“下载并验证固定资源”“组装并验证 KSU 模块”“上传产物”三个步骤均成功。
- 同提交的 [主机契约 CI #33975295800](https://github.com/Sumicya/Selffont/actions/runs/33975295800) 成功。
- 文渊原版 SHA-256：`e9ebde68d6d45ad5998765505677d1fb95821318fc693982f873e73fc27a2122`。
- MFGA 基础包 SHA-256：`620789eab7a6e47b96cfb333bb50f44ee526abe1e2ab2f572e54c30b16a3649b`。只提取字体资源及归属说明，数字主字体和原包代码不继承。
- 构建器关闭 ZIP 后重新检查全部成员 CRC，并从包内重新计算主字体 SHA-256；检查通过后才替换最终输出。
- [CI 产物 #9972129539](https://github.com/Sumicya/Selffont/actions/runs/33975295832/artifacts/9972129539)：`selffont-phase1-font-module`，107,895,970 字节（约 108 MB）。GitHub 记录的**外层产物 ZIP** SHA-256 是 `2e1316a9dc54075db04fab74a7ccf4b54c6a13ae6eafff09f36b316e1778285a`。
- 外层产物内的安装文件是 `Selffont-phase1.zip`；其校验值见旁边的 `Selffont-phase1.zip.sha256`，不要把外层产物哈希当作内层安装包哈希。`module-report.json` 记录源码提交、主字体信息、基础包哈希和未打包的配置引用。
- 本环境仍不能直接下载产物存储中的二进制；这里核对的是远端执行步骤和产物元数据，不宣称已在本地解包检查或完成手机安装。配置中未打包的字体引用需要由设备上的系统字体满足，不能仅凭打包成功宣称所有回退字形可用。

下一步使用正常 KSU 安装流程安装内层 ZIP，重启后打开 Firefox 的原问题页面。现有 APK 保持不变。预期先从 `[gecko-skip]` 变为 `[gecko-prefs]`；后者仍只证明首选项注入，最终还要对比真实字形、粗斜体、小型大写和原始字符。

## 2026-09-06：基线与日志采集修订（1.4-phase1.1）

用户反馈：新字体模块下通知栏角标数字偏低，部分场景下沿略有截断；导出得到 `[logs-no-match]`。

- 文渊原版测量值：UPM 1000；hhea 1160/-288/0；OS/2 typo 880/-120/0，USE_TYPO_METRICS 未置位；数字 0 的可见 y 范围 -10…744。
- 以常见的 ascent/descent 居中公式计算，hhea 的基线中心为 436，数字墨迹中心为 367，差约 0.069em 向下。它支持度量回归假设，不是对具体 Oplus 控件绘制实现的实测。
- 恢复原配置的无可见字符 Roboto 度量载体，文渊作为首个字形回退；只调整 XML 的职责与顺序，不改文渊数据，不按机型硬编码像素上移。新增 carrier 覆盖检查阻止普通 Roboto 抢占可见字形。
- 日志解析改为与显示前缀无关的来源字段解析。空结果同时输出 `parsed_origins`、`own_module`、`other_tags`：可区分输入未解析出来源、未见本模块，以及仅见本模块其他 tag，仍不直接判定注入失败。
- 本次主机回归 36 项 Python、3 项 Node 通过；新增前缀／空白、空壳字体／可见字符拒绝测试。数字在具体控件中的最终对齐与这次空日志的实际原因，仍需设备反馈确认。

### 基线兼容修订 CI 结果

- 提交 `53c1a504df3edaabd151fab28430474ee2811a31` 的 [模块构建 #33980570752](https://github.com/Sumicya/Selffont/actions/runs/33980570752) 和 [契约检查 #33980570744](https://github.com/Sumicya/Selffont/actions/runs/33980570744) 均成功。
- 本次真实模块构建的检查注释确认：继承的 Roboto 无可见字符覆盖；UPM 2048；hhea 1900/-500/0；SHA-256 为 `a081911121b8fd39e90be6bac1c1150183f8cc8bc80e9cdd1710a06875b50caa`。这些是实际基础包的值，不是测试夹具的 UPM 1000 / hhea 930/-250。
- [产物 #9973622240](https://github.com/Sumicya/Selffont/actions/runs/33980570752/artifacts/9973622240)，107,898,660 字节；外层产物 ZIP SHA-256：`2e5e2473c3b35e0138aaf1c63b70717670978d0bc0bb9d075daed86705741786`。
- 内层模块版本 `1.4-phase1.1`，versionCode `1717180005`；原版文渊的固定 SHA-256 不变，APK 不变。
- 若日志仍无匹配，`parsed_origins=0` 表示这批输入没有解析出来源（可能为空或格式不同）；`parsed_origins>0, own_module=0` 表示识别了来源但未见本模块；`other_tags>0` 表示存在本模块的其他 tag。都不能单独用来判定当前注入状态。
- 此次仍未在用户设备上确认角标的具体绘制结果。若问题持续，需要偏低数字的裁剪图和所属界面，以区分默认字体度量、具体控件固定基线与其他字体家族。

## 2026-09-06：修订后仍偏低的截图与后续诊断

用户提供的通知计数角标截图中，数字 10 与 7 仍然偏下。第一张局部图的边缘裁切不能单独作为控件裁剪边界的证据。1.4-phase1.1 的实际对齐尚未通过，不能将“已恢复度量载体”写成“已解决”。

新日志报告 `parsed_origins=246 own_module=0 other_tags=0`，表示采集器识别了其他来源，但在这批日志中没找到本模块；不是没有输入，也不能直接判定 APK 被禁用。下一步不继续改过滤条件，而是核对实际安装／运行状态。

`tools/device_state.sh` 一次只读采集：模块版本与更新标记、仅本模块 APK 的版本／用户安装状态、Firefox 主进程、模块目录与系统视图中的两份字体哈希、Firefox 进程根目录中的目标字体、生成与实际字体 XML 的哈希／相关家族行，以及打包时记录的度量信息。读取进程根目录仍以 root 身份进行，不等同于证明 Firefox UID 有读取权限。不修改字体、作用域或系统设置，不停止应用，不清空日志，不读取模块配置数据库。

研究参考：公开反编译样本中的 `COUIHintRedDotHelper` 使用 `sans-serif-medium`，以 `(top + bottom - ascent - descent) / 2` 计算文字基线。样本来自其他 Oplus 应用，不能断言与用户系统组件一致；它仅支持先核对真实 Typeface／配置路由，而不是硬编码像素平移。
参考：<https://github.com/eduardo3677-ai/com-oplus-aimemory/blob/417268a0e09b6408e6c09f0042bc194d6d706c25/smali/com/coui/appcompat/reddot/COUIHintRedDotHelper.smali>

## 2026-09-06 08:13：安装与首选项链路已确认

本次只记录必要结论，不归档完整的应用用户状态或进程数据。

- 用户实际安装的字体模块为 `1.4-phase1.1 / 1717180005`，APK 为 `1.4-phase1 / 14`。
- 文渊文件在模块目录、系统路径和 Firefox 进程根目录中的 SHA-256 均为固定原版值；Roboto 载体的系统与模块副本也一致。
- `font_fallback.xml`、`fonts.xml`、Oplus 的 `fonts_base.xml`、`fonts_ule.xml` 与生成 XML 的 SHA-256 相同：`e07a28c21480b312ae74603d6bf75428e65f34d641c129423269ac8022a7c93c`。不能再把角标问题归因于这些文件没有挂载。
- 08:11:12.283 的 Firefox 主进程记录出现 `[gecko-prefs] injected`；由进程内检查确认目标字体可读且首选项经过注入。08:11:12.964 仍有 `CustomFallbackBuilder.build()` 的实际命中。
- APK 的 `stopped=true / notLaunched=true` 不是 Xposed 模块未运行的判据；本 APK 没有普通启动界面，且实际注入日志已经给出了正面证据。
- 此前空日志在本次采集中已经不再出现，不继续更改过滤策略。网页实际字形效果仍需要用户视觉反馈；角标偏低是单独的布局验收问题。

## 运行时字体测量工具（不安装 APK）

`com.mfga.xposed.diagnostics.FontMetricsProbe` 是独立 `app_process` 入口，不注册为 Xposed 模块入口，也不被现有 Hook 调用。它随诊断 APK 编译，但执行时以完整容器 APK 建立类路径，不安装或替换任何 APK／字体模块。

工具在自己的新进程中从当前预装 XML 初始化字体映射，比较默认、`sans-serif-medium`、condensed、serif，以及显式构造的“载体＋文渊”和直接文渊对照。只使用固定样本文字，输出 `Paint` 浮点／整数度量、文本边界、`TextRunShaper` 的实际字体文件／轴／字形边界，以及常见居中公式的墨迹中心偏差。正偏差表示向下。

这个工具测量的是手机上的真实 Android 字体引擎，但不是现有 SystemUI 控件的 Paint 实例或它的共享字体缓存。若新的独立进程结果正常而屏幕仍偏低，下一步应定位控件实际字体、缓存或布局实现，不能把独立进程测量结果冒充具体控件实测。

`tools/run_font_probe.sh` v2 将完整 APK 复制到独立临时目录，将这份副本设为只读后运行，并在退出时清理；限时 60 秒。诊断默认直接输出终端，不要求保存或上传文件。Android 16 的 `Typeface.loadPreinstalledSystemFontMap()` 只在这个诊断进程内调用，不更改其他进程或磁盘配置。初始化不支持或测量失败会明确报错，不生成假的测量成功结果。

### 运行时测量工具构建记录

- 源码提交 `eac95ecead1234a157c579ebcf6028626fbb8f2a`。
- [工具容器编译 #34001516111](https://github.com/Sumicya/Selffont/actions/runs/34001516111) 与 [主机检查 #34001516122](https://github.com/Sumicya/Selffont/actions/runs/34001516122) 成功。
- 容器沿用 APK 构建产物名，但本次用途是提取其中的诊断 DEX，**不是安装或升级 Xposed APK**。现有 APK 及字体模块保持不变。
- 产物 ID `9979637602`，外层 ZIP 30,522 字节；外层 ZIP SHA-256 为 `52160d161db7ebe5740b1aa5f39030944c963bd68a3067d8d32feb12d3bf197f`。
- 启动脚本 `tools/run_font_probe.sh` 的 SHA-256 为 `a42284694942bff1a164247973ac69864e077f3adf81d20254078974cfd7f2d9`。
- 主机测试覆盖临时 DEX 的只读权限、执行入口、退出清理和“不注册为模块入口”；不把这些测试或编译成功冒充设备上的 Paint 实测。

## 用户确认浏览器修复；补字与网络预检分开处理

- 用户确认 Firefox 原问题已修复、默认字体覆盖成功。这是本次目标页面的正面验收，不外推所有网页及字符覆盖。
- 用户另报“部分字体未补全”，尚需原始字符样本和发生位置，区分缺字／空白、回退字体缺失与仍使用不同家族。没有样本之前不改写 Unicode、不盲目新增 Hook 或替换更多字体。
- 本次测量命令在 `gh run download` 的 GitHub API 连接阶段失败；Android 测量进程尚未运行，不能把该错误当作字体或探针执行失败。
- Termux 用户给出的代理是 `http://127.0.0.1:7890`。`tools/termux_font_probe.sh` 明确设置大小写 HTTP/HTTPS 代理与本地 bypass，依次执行 API 网络预检、已有登录检查、固定产物下载、启动脚本校验，最后才申请 root 运行独立测量。
- 网络或登录失败时停止，不自动登录、不要求用户发送凭据，也不运行 root；产物最多下载两次，每次使用新目录，避免误用半下载文件。失败会显示具体阶段。
- 已登录不需要重复 `gh auth login`；`gh auth setup-git` 只涉及 Git 认证配置，不是下载 Actions 产物的前置步骤。只有登录确实无效时才在用户自己的 GitHub 授权页面处理。
- 本轮主机回归 43 项 Python、3 项 Node 通过，包含网络／认证／下载失败不进入 root 阶段的隔离测试；这不表示已验证用户手机代理连通性或完成 Android 运行时测量。

## 测量进程退出 134 且 stdout/stderr 报告为空

网络、已有登录、容器下载及启动脚本校验已通过，进入测量阶段后返回 134（通常为 SIGABRT），用户确认 `selffont-metrics.txt` 为空。不能据此认定字体损坏，也不能继续要求用户上传空报告；原生进程的 abort 信息可能仅进入 Android 日志／tombstone，而不是重定向的 stdout/stderr。

先读取已有的、命令行明确包含 `com.mfga.xposed.diagnostics.FontMetricsProbe` 的文本 tombstone。`tools/collect_probe_crash.sh` 只输出匹配报告中的时间、进程标识、signal、Abort message 和 backtrace 帧；不输出寄存器、内存、maps、protobuf 或其他应用报告，不重新运行探针，也不清空任何记录。找不到会明确报告缺失，而不以通用 app_process 崩溃替代本次证据。

当前没有任何成功的 Android Paint 运行时测量结果；角标偏低的原因仍不能从退出码反推。后续启动器需要补齐原生错误采集能力，再决定是否重跑，不继续凭未完成的测量改变字体数据。

## 原生中止已定位到测量工具类加载阶段

用户提供的 tombstone 指向 `java.lang.ClassNotFoundException: com.mfga.xposed.diagnostics.FontMetricsProbe`。主线程随后在 `AndroidRuntime::startReg` 注册 JNI 时遇到待处理异常而 SIGABRT。还没有进入探针 main 或 Paint 测量；不能据此修改字体、推断字体损坏或把其他等待线程当作新的故障。

旧启动器只提取 `classes.dex`，没有验证入口类所在的实际 DEX，因而不满足多 DEX 容器的启动契约。修订使用完整 APK 的只读临时副本作为 classpath，同时显式传递 `-Djava.class.path` 和 CLASSPATH，避免只加载首个 DEX。系统运行时不继承 Termux 的 LD_PRELOAD／LD_LIBRARY_PATH。启动阶段直接打印容器哈希、类路径、入口类及退出码，不再将诊断默认重定向到文件。

APK 构建新增最终检查：逐一检查 `classes*.dex`（包括 DEX 041 容器头），确认目标 class_def 和有代码的 public static main(String[])。仅仅找到字符串引用不算入口存在。检查不通过时构建失败，不能仅凭 assembleDebug 产出文件判定工具可执行。

该修订仍需要实际构建结果与手机验证；完整 APK classpath 是修正启动契约，不把尚未确认的具体 DEX 分布或手机运行结果写成已验证。

### 类路径修订的实际构建结果

- 提交 `09f145e2cdcf67ea60db8f20acdf6570cbda8bb9` 的 [APK 构建 #34006028276](https://github.com/Sumicya/Selffont/actions/runs/34006028276) 与 [契约检查 #34006028278](https://github.com/Sumicya/Selffont/actions/runs/34006028278) 成功。
- 构建后的 DEX 检查注释确认：入口定义在 **classes2.dex**，headerOffset=0，存在有代码的 public static main(String[])。原启动器只保留 classes.dex，遗漏了所需入口。
- 产物 ID `9980963550`，外层 ZIP 大小 30,522 字节，外层 SHA-256 `5cdd0c5b28f7059462eea1d8855b4e8cb5231d055a9376f63661774de15e251a`。
- v2 启动脚本 SHA-256：`456f85204e0796124b2de71769692df7ad67c1eee27a4a847ab6285a70b22f7e`。默认使用整个只读 APK，不再抽取单个 DEX；同时设置显式 VM 类路径和 CLASSPATH。
- Termux 传输脚本已更新固定运行号与启动器版本，保留代理／网络／认证预检，但直接将测量输出显示在终端。临时容器文件属于执行所需输入，不再额外生成需要用户寻找的诊断 TXT。
- 新增多 DEX、DEX 041 多头、仅字符串引用不算定义、main 权限与代码存在性、完整容器保留及终端输出测试。编译与入口检查成功仍不是手机测量成功；现有字体模块与已安装 Xposed APK不因此更新。

## 真实 Android 引擎测量成功：度量载体只改变名义度量

用户完成 v2 完整 APK 类路径测量，`failed_cases=0`，启动器及探针均退出 0。仅保存必要汇总，不复制整段设备路径／输出。

| 28px 的数字 10 / 7 | Paint 浮点居中模型 | Paint 整数居中模型 | 实际 glyph run 居中模型 |
|---|---:|---:|---:|
| DEFAULT / sans-serif / sans-serif-medium / condensed | -0.430px | -0.500px | +2.208px |
| 显式 carrier + WenYuan 500 | -0.430px | -0.500px | +2.208px |
| 直接 WenYuan / serif | +2.208px | +2.000px | +2.208px |

所有这些样本的实际字形都解析到固定原版文渊文件；weight=400/500 与轴相符，中英文 locale 不改变本组结果。1000px 数字样本的 carrier Paint ascent/descent 为 -927.734/244.141，而 run 为 -1160/288。

这证明在独立进程中，XML 与手工构造的 carrier/fallback 行为一致；载体没有丢失，也没有把数字换回 Roboto。但它不改变实际字形 run 的字体自身度量。不能把 standalone 的居中模型当作 SystemUI 角标对象实际使用的公式，更不能由此宣布已定位到具体控件。

用户选择 **保持原版字体，定位具体控件**，不生成度量派生字体。继续保持原版哈希、字形、cmap 与名字不变，也不做全局像素位移。

## SystemUI 只读绘制观察 APK

版本 `1.4-badge-diagnostic`（versionCode 16）仅在 LSPosed 已经将模块加载进 `com.android.systemui` 时安装绘制观察 Hook。它不自动添加作用域，也不把 SystemUI 加入推荐勾选列表。用户需自行选择 SystemUI；不由脚本杀死或重启系统界面。

- SystemUI 分支只观察，不安装原来的 Typeface 替换 Hook，避免在测量时改变待测对象。Firefox 与其他原有分支保持不变。
- 同时探测软件／录制 Canvas 的 drawText 和 drawTextRun 实现，只接受固定数字样本 `7`、`10`，最多记录 12 组去重结果；不读取或记录其他通知正文。
- 从真实绘制调用读取基线坐标、局部 clip、Paint 的度量／字体信息和调用类方法；测量使用 Paint 副本。原始参数与原始异常传播不变。
- 标签：`[badge-diagnostic-only]`、`[badge-observe-ready]`、`[badge-sample]`、`[badge-metrics]`、`[badge-font]`、`[badge-caller]`。达到预算后不再采样，绘制仍然继续。
- Canvas clip 并不必然等于角标背景矩形；文本运行测量也不等于调用者缓存的布局参数。需要结合调用类继续定位，不能拿 clip 中心盲目修正控件。
- 这是定位 APK，不是角标修复；不要求更新字体模块，不对既有浏览器结论重复采样。

### 只读角标 APK 构建结果

- 提交 `ed694632fa107e541aa4ebed53f53a49fe9128a9` 的 [APK 构建 #34010188489](https://github.com/Sumicya/Selffont/actions/runs/34010188489) 和 [契约检查 #34010188473](https://github.com/Sumicya/Selffont/actions/runs/34010188473) 均成功。
- [产物 #9982229620](https://github.com/Sumicya/Selffont/actions/runs/34010188489/artifacts/9982229620)：外层 ZIP 35,924 字节，SHA-256 `ec3e86ef779dc2f3c78fb2f24e46cc364c73796303231ff4d961d1e892f5e19a`。
- 主机 53 项 Python、3 项 Node 测试通过；Java 策略测试覆盖固定采样文本、非法范围和去重／预算上限；APK 编译与 DEX 入口检查通过。仍不能将这些结果视为已在用户 SystemUI 上命中绘制或修复布局。
- 安装使用正常 APK 流程。由用户保留已有 Firefox 作用域，并明确手动勾选 SystemUI；生效后展开存在 7 或 10 计数角标的通知界面。字体模块不更新。该版本不是之前的独立进程容器运行步骤。
- 直接查看相关日志，不生成报告文件：

```sh
su -c 'sh /data/adb/modules/MFGA/action.sh logs' | grep -F '[badge-'
```

先确认 `[badge-observe-ready]`，再看 `[badge-sample]`、`[badge-metrics]`、`[badge-font]` 与 `[badge-caller]`。没有样本可能是未出现固定数字、未覆盖实际绘制入口或作用域未生效，不用大量抓取通知正文来代替这些证据。

## 2026-09-06：首批只读观察命中——区分安全键盘与真实角标

用户在 SystemUI 勾选作用域后采到两组 `[badge-sample]`。观察器工作正常，字形都解析到固定原版文渊；但其中一组不是角标：

| 样本 | 调用者 | 字号 | canvas / align | 判断 |
|---|---|---|---|---|
| 13:51:59 `text=7` | `com.oplus.securitykeyboardui.SecurityKeyboardView.onDraw` | `px=70.0` | Canvas / CENTER | 密码数字键盘按键，不是角标 |
| 13:52:26 `text=7` | `android.widget.TextView.onDraw ← Layout.draw` | `px=30.0` | RecordingCanvas / LEFT | **真实通知角标** |

对真实角标那组做度量核对（正偏差表示向下）：

- 局部 clip（角标框）= `[0,0][18,35]`，高 35，垂直中心 y=17.5。
- Paint 名义度量（Roboto 载体）：ascent −28、descent 7，名义行高 35，正好等于框高——即框高由载体名义度量决定。
- 实际文渊 glyph run：ascent −34.8、descent 8.64，真实行高 43.4，比框高。
- baseline 落在 y=35 ≈ |真实 ascent 34.8|，不是 |名义 ascent 28|。数字墨迹 `[−22..+1]` → 绝对 13..36，墨迹中心 24.5。
- 24.5 − 17.5 = **偏低约 7px**；墨迹底 36 > 框底 35 = **底沿裁切约 1px**。若 baseline 改用名义 ascent 28，数字将居中（差值 7 = 35−28）。

结论：**该控件用文渊真实（更大）的 ascent 定行/基线，而角标框高来自名义载体度量**。载体只改名义 Paint 度量、不改 glyph run 自身度量，与此前独立进程测量一致；这是具体控件的行/基线放置问题，不是字体数据损坏，也不应做全局像素平移。

仍缺具体控件类：真实角标那组的栈在 `TextView.onDraw` 处被截断，未到具体 SystemUI/Oplus view。已调整观察器：跳过 `px>48` 的大字号与 `*eyboard*` 调用者（密码键盘），并把保留的应用栈帧从 10 增到 18，让下一批日志露出真实角标的宿主控件类。字号／键盘过滤与更深栈仍是只读，不改绘制参数与 Paint。下一步用同样命令在展开角标的界面再采一批，读 `[badge-caller]` 定位控件类后再决定修法。

### 观察器修订构建结果（1.4-badge-diagnostic2）

- 提交见本分支 `arena/01a07569-selffont`；[APK 构建 #34017489516](https://github.com/Sumicya/Selffont/actions/runs/34017489516) 与 [契约检查 #34017489424](https://github.com/Sumicya/Selffont/actions/runs/34017489424) 均成功。
- 产物 `selffont-phase1-debug-apk`，artifact ID `9984380013`，外层 ZIP 36,004 字节。versionCode 17 / versionName `1.4-badge-diagnostic2`。
- 主机契约新增“跳过键盘与大字号”断言；仍不改绘制参数与 Paint，编译与 DEX 入口检查通过。这些不等于已在设备上定位到具体角标控件；需要用户再采一批日志确认。
- 安装与之前相同：正常 APK 流程，保留 Firefox 作用域，手动勾选 SystemUI，展开带 7/10 计数角标的界面后：

```sh
su -c 'sh /data/adb/modules/MFGA/action.sh logs' | grep -F '[badge-'
```

这次应只出现小字号角标样本（键盘按键被过滤），且 `[badge-caller]` 会给出更深的宿主控件类。

## 2026-09-06：新增 `10` 角标样本仍来自旧 APK；深化调用栈（1.4-badge-diagnostic3）

用户第三批日志新增一条 `text=10` 角标：`clip=[0,0][31,35]`、ink `[0,-23][30,1]`、baseline=35、align=LEFT，run ascent/descent −34.8/8.64。数字墨迹中心≈24 对框中心 17.5，同样偏低约 6–7px，墨迹底 36 > 框底 35，底沿裁切。与 `7` 结论一致，且 `10` 的框更宽（31），确认横向 LEFT 起笔、纵向偏低。

但这批仍是**旧 APK（v16）**输出，未装 `diagnostic2`：`[badge-observe-ready]` 时间戳仍是最初的 13:51:57（重装/SystemUI 重启后应有新的 observe-ready）；70px 安全键盘样本仍在（v17 已过滤）；栈仍含 `VMStack.getThreadStackTrace` 且约 10 帧截断。因此键盘过滤与深栈都尚未在设备生效。

同时发现 v17 的固定 18 帧深栈仍可能不够：角标从 `TextView` 继承 `onDraw`，其运行时类不会作为栈帧出现，需要一直向上抓到具名的 SystemUI/Oplus 容器帧。v18 改为：保留最初的绘制上下文帧，之后只保留非 `android.*` 的应用帧,最多 12 个应用帧（或 40 帧上限），越过 v16 截断处的 `ViewGroup.drawChild`，露出真正拥有角标的 Oplus/SystemUI 容器类。仍全程只读，不改绘制参数与 Paint。

**务必先彻底换装 v18**：在 LSPosed 停用并卸载旧诊断 APK，安装 `1.4-badge-diagnostic3`，重新勾选 SystemUI，彻底重启 SystemUI（或重启设备）后再展开带 7/10 角标的界面，确认 `[badge-observe-ready]` 时间戳是新的，再看 `[badge-caller]`。

### v18 构建结果

- [APK 构建 #34018033001](https://github.com/Sumicya/Selffont/actions/runs/34018033001) 与 [契约检查 #34018032973](https://github.com/Sumicya/Selffont/actions/runs/34018032973) 均成功。
- 产物 `selffont-phase1-debug-apk`，artifact ID `9984555248`，外层 ZIP 36,106 字节。versionCode 18 / versionName `1.4-badge-diagnostic3`。字体模块与 Firefox 分支不变。

## 2026-09-06：v18 生效，角标控件已定位到 NotificationChildrenContainer

用户装 v18 后出现新的 `[badge-observe-ready]`（15:08:21，session `24fc`），且样本不再含 70px 键盘、栈无 `VMStack`。15:08:34 的 `7` 角标给出完整具名栈：

```
android.text.Layout.draw <- android.widget.TextView.onDraw <- View.draw
  <- com.android.systemui.statusbar.notification.stack.NotificationChildrenContainer.drawChild
  <- ...row.ExpandableOutlineView.drawChild
  <- ...row.ActivatableNotificationView.dispatchDraw
  <- ...row.ExpandableNotificationRow.dispatchDraw
  <- ...stack.NotificationStackScrollLayout.drawChild/dispatchDraw
  <- androidx.constraintlayout.widget.ConstraintLayout.dispatchDraw
  <- com.android.systemui.shade.NotificationPanelView.dispatchDraw
```

结论：偏低的 `7`/`10` 是**分组通知的折叠计数**，由 `NotificationChildrenContainer` 内的一个普通 `TextView`（组溢出计数）经 `StaticLayout`/`Layout.draw` 绘制，不是应用图标红点，也不是安全键盘。

度量复核（正偏差向下）：
- `7`：clip=[0,0][18,35]，`10`：clip=[0,0][31,35]；框高恒为 35。
- Paint `getFontMetricsInt` = −28/7（Roboto 载体名义值），名义行高 28..(−7) → 35，正好等于框高 → **框由名义度量测量**。
- 但 baseline 画在 y=35（框底），≈ 文渊真实 run ascent（−34.8→−35），**baseline 由实际回退字体度量放置**。
- 数字墨迹相对 baseline [−22..1] → 绝对 [13..36]，中心 24.5 vs 框中心 17.5 → **偏低约 7px**；墨迹底 36 > 框底 35 → **底沿裁切 1px**。若 baseline 用名义 ascent 28，墨迹 [6..29] 恰好居中。

机制推断：TextView 以载体名义度量**测量**出高 35 的框，而 `StaticLayout` 在**绘制**时按回退字体（文渊）更大的 ascent 放置 baseline（典型于开启 fallback line spacing 的通知布局）。载体只统一了名义 Paint 度量，统一不了 glyph run 与 StaticLayout 的回退行距——与此前独立进程、以及 `7`/`10` 两组样本一致。这是该控件“测量用名义、绘制用回退”的行距/基线不一致，不是字体数据损坏，也不是全局问题。

至此具体控件已确认。用户此前选择“保持原版字体、定位具体控件、不做全局像素平移、不生成度量派生字体”。是否对这一个控件做作用域受限的定点基线修正，需用户决定后再从只读观察改为定点修复。

## 2026-09-06：用户改选激进根治——度量归一（1.4-phase2-metrics）

用户指出“部分情况出下沿”，并要求更激进、一次治好而非逐控件补。判定同一根因：**测量用名义度量、绘制用回退真实度量**。凡竖直居中且定高吃紧的紧凑文字槽都会中招——分组通知折叠计数（已确认）、应用图标红点角标（`COUIHintRedDotHelper`）、状态栏时钟/电量小数字、快捷磁贴/Chip 等。宽松多行正文一般不明显。

采纳方案 A（推翻原“不生成度量派生字体”约束）：在**打包阶段**把文渊自身的竖直行度量归一到载体名义度量，使两条路径一致、baseline 不再被顶低。

- 新增 `tools/metric_normalize.py`：将 `hhea` ascent/descent/lineGap、`OS/2` typo asc/desc/linegap 设为**载体名义度量按文渊 UPM 等比缩放**的值；`USE_TYPO_METRICS` 跟随载体（需要时抬 OS/2 版本到 4）；`usWinAscent/Descent` 仍取真实字形 bbox 与墨迹的较大值，保证不裁剪 CJK/带音符墨迹。
- **只改行度量**：字形轮廓、cmap、family 名、`wght/ital` 轴逐字节保留（`assert_glyphs_preserved` 在打包后逐字形二进制核对，任何轮廓/cmap/family/轴变化都使构建失败）。粗体、斜体、小型大写、语言 shaping、原始码点全部不变。
- **构建期防切保护**：归一后若数字墨迹会超出新行盒（ascent/descent），抛 `ClipError`、构建失败，绝不出“治好偏低却切正文”的字体。
- 上游原始 `WenYuanRoundedSCVF.ttf` 及其固定 SHA-256 完全不动；归一只作用于**生成的安装副本**，其 SHA 记入 `module-report.json` 的 `metricNormalization`。

主机数值验证（用真实基础包载体 UPM 2048 / hhea 1900/−500 复算）：文渊 ascent 1160→928，baseline **抬升 6.96px@30px**，与设备实测 `7`/`10` 偏低约 7px 吻合；数字墨迹 −10..744 仍落在归一行盒内，不裁切。下沿裁切属同一 7px 偏移的边缘效应，抬升后一并消除。

主机回归：新增 `tests/test_metric_normalize.py`（行度量匹配载体、UPM 缩放、轮廓/cmap/轴保留、USE_TYPO_METRICS 跟随、usWin 覆盖真实墨迹、上/下溢出拒绝、篡改检测）；打包测试改用真实结构的 `primary_font` fixture 并核对“仅度量变化”。共 62 项 Python、3 项 Node 通过。

这是主机层的度量与打包验证，**尚未装机**。需要用户装新字体模块（`1.4-phase2-metrics / 1717180006`）后，回看分组计数、红点角标、时钟等紧凑槽是否居中且不再切底，并确认正文、粗斜体、小型大写、CJK 回退无回归。诊断 APK 保持只读，不再逐控件 Hook。

### 度量归一构建结果（1.4-phase2-metrics）

- [字体模块 CI #34020726659](https://github.com/Sumicya/Selffont/actions/runs/34020726659) 与 [契约检查 #34020726662](https://github.com/Sumicya/Selffont/actions/runs/34020726662) 均成功。CI 用**真实 48MB 文渊原版**执行归一与打包，构建期防切保护通过。
- 产物 `selffont-phase1-font-module`，artifact ID `9985406225`，约 108 MB。内层安装文件仍为 `Selffont-phase1.zip`，其 `module-report.json` 记录 `metricNormalization`（原始/归一 hhea、digitInkY、usWin、归一副本 SHA-256）。
- 上游原版 `WenYuanRoundedSCVF.ttf` 固定 SHA-256 不变（仅安装副本的行度量被归一）；诊断 APK 不更新。
- 装机步骤：正常 KSU 安装内层 ZIP，重启；随后回看分组通知计数、应用红点角标、状态栏时钟/电量等紧凑槽是否居中、是否仍切下沿，并确认正文、粗斜体、小型大写、CJK 回退无回归。

## 2026-09-06：火狐缺字（新 emoji 豆腐块）——恢复 Gecko 回退链

角标居中已由用户确认解决。用户报火狐中 README/changelog 下方符号 `🛙🪋🪌🪍🫌🫝🫫🫹🫺` 为豆腐块，仅个别字符，其他 App（含彩色）正常。

诊断：这 9 个码位是 **Unicode 15.1/16 新 emoji**（U+1F6D9、U+1FA8B–U+1FAFA）。"其他 App 彩色正常、仅火狐豆腐块" → 系统有覆盖它们的彩色字体，是 **Gecko 字体路由被本模块 pref 掐断**，非系统缺字。

根因在 `GeckoFontPolicy`：旧实现对每个 generic/语言把 `font.name-list.*`（回退候选列表）**整个覆盖成只有文渊**，并对本无该项的语言也**新造一个"只有文渊"的窄列表**。Gecko 语义中 `font.name` 是首选、`font.name-list` 是缺字时的回退顺序；列表被清空后，文渊没有的字符（新 emoji、生僻码位）没有任何回退，直接豆腐块，系统彩色 emoji 字体也被排除。

修法（保住已确认的"网页统一成文渊"，同时恢复回退）：
- `font.name.*` 仍设文渊（首选不变）。
- `font.name-list.*` 改为把文渊**前置**到 Gecko 原有列表最前（`prependFamily`：去重、幂等、空值不动），保留其后全部下游回退（CJK、符号、彩色 emoji、生僻码位）。
- Gecko 未暴露该 list 项时**不再造窄列表**，保留其内建默认。
- **不触碰任何 emoji 首选项**，让系统彩色 emoji 回退继续生效（用户要彩色；仓库里覆盖这些码位的 `Unicode18-new.ttf` 为黑白，不注入以免把 emoji 变黑白）。
- 仍不改 CSS、字号、字重、synthesis、variant、Unicode；字体不可读时不注入。

主机回归：`tests/java/PolicyTest.java` 新增前置保留、已前置幂等、去重、空列表、无 list 项不新增、emoji 首选项零改动等断言；`prependFamily` 逻辑另以脚本复核通过（本环境无 javac，Java 编译/运行由 CI JDK 17 执行）。

装机验证：安装诊断 APK `1.4-gecko-fallback / 19`（字体模块不变），冷启动火狐后回看那行新 emoji 是否恢复（预期彩色，来自系统 emoji 字体），同时确认正文仍统一为文渊、粗斜体/小型大写/CJK 无回归。这是很窄的回退修复，不宣称覆盖所有网页与全部字符。
