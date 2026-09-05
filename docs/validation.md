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

首次导出使用全文关键词匹配，会混入旧版 MFGA 记录、其他模块正文中的网址／Intent，以及模块日志与详细日志的重复行。已经改为按实测的 `LSPosedLogDaemon` 结构字段匹配：来源必须是 `[com.mfga.xposed,Selffont,...]`，不能仅在消息正文中提到这个名称。去重只去除完全相同的记录，不合并不同进程的相同事件，最多输出最后 300 条唯一记录。

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
- 新 APK 的现代入口与 Gecko 启动入口已由下方设备日志验证；完整字体模块打包／安装、首选项实际改写与 Firefox 绘制仍待验证。

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

后续资源构建与日志过滤回归：32 项 Python 测试、3 项 Node 测试通过；包括来源字段过滤、旧版本／其他模块正文引用排除、重复记录去重、固定基础包身份，以及打包后主字体哈希复核。真实基础包下载与完整模块构建仍待独立 CI 执行。
