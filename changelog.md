# 更新日志

## 2026-10-10 · 同步规范第二十四版：版本取数换口径，清理写权限收到默认分支

- `GLOBAL.md` 已到**第二十四版（2026-10-10）**，新增两节强制通用步骤：「版本取数通用步骤」「清理通用步骤」。`AGENTS.md` 上次同步戳改到第二十四版。
- **总序号换口径**：旧 = 本次 `run_number`（含失败与 PR，已到 106）；新 = **本仓库历史成功出包的构建数 + 1**，失败与取消不增加总序号（当时实测：全部运行 85 条，其中成功 75、取消 9、失败 1）。直接切会从 106 回退到 76，规范明令不许回退，所以取 `max(历史成功出包数, 已出包产物最大总序号) + 1` —— **衔接规则：从 run 107 起按新口径**，写进 `AGENTS.md`。
- **当日序号**：改成「当天在本次运行之前已触发的运行数 + 1」，含失败与取消；排序用（创建时间, `run_number`）双键，同一时刻并发触发不会抢同一个号。旧口径数的是「不晚于本次」，两者数值相同，但新写法把「本次自己」和「+1」分开了，并发分先后的依据也明确下来。
- **重试不再靠同一身份自然复用**：`GITHUB_RUN_ATTEMPT > 1` 时从本 run 已上传的 artifact 名读回第一次 attempt 的版本号（`reuse_attempt()`），读不到就报错停住。旧实现靠 `run_number` 不变来复用，换了 +1 计数口径后那样会重复加号。
- **输入锚定收紧**：`created_at` 从本 run 对象取（`gh api .../actions/runs/$GITHUB_RUN_ID`），禁止 list 后取最新；`current_run()` 不再需要 `GITHUB_RUN_NUMBER` 存在才认身份。
- **本地不再自己算号**：删掉「本地退到最近一次运行」的口径，`--query-github` 没有 `GITHUB_RUN_ID` 直接报错；本地出包必须显式传 `--date/--day/--build`（本地序号规则按规范要求单独写进 `AGENTS.md`）。
- **清理 job 只在默认分支跑**：`if: github.event_name != 'pull_request' && github.ref == 'refs/heads/main'`（清理通用步骤步骤 1：写权限只给可信的默认分支构建 job）。`permissions` 仍只有 `actions: write`——规范写的是「最小 `contents: write` + `actions: write`」，本仓库 Release 数为 0 且 CI 不发版，用不到 `contents`，按最小化不申请。**代价**：只在分支上推送时清理不触发，artifact 会暂时超过 5 个，由下一次 `main` 构建收口。
- 实现留在 `build.py`（规范说「实现语言与脚本形式自选，但计算顺序与锚定规则固定」），这样日期换算、当日序号、成功计数的断言能继续被 `--check` 覆盖。
- **验过的**：自检 9 项全过，其中 `version_numbers` 换成覆盖新口径的用例（当日序号含失败/取消、并发同时刻按 `run_number` 分先后、总序号只数 success、artifact 名解析拒四段与异项目名）。两处变异测试都被抓到（`day_index` 的 `<` 改 `<=` → FAIL；`success_total` 去掉 conclusion 过滤 → FAIL）。拿真仓库数据跑通三条路径：以 run 105 身份取数得 `26.10.10.1.107`（当日序号 1 与该 run 实际产物 `26.10.10.1.105` 一致，总序号 = max(75, 106)+1）；以 run 106 身份 attempt 1 得 `26.10.10.2.107`；attempt 2 得 `26.10.10.2.106`，与第一次 attempt 的实际产物名逐字相同（复用生效，没重复加号）。
- **未验证**：`cleanup` job 的默认分支条件要等一次 `main` 构建才会真正执行到；本次分支构建里它会被 `if` 跳过。

## 2026-10-10 · 文档瘦身：AGENTS.md 不再抄 GLOBAL.md 条文；changelog 压掉历史叙述

- **AGENTS.md 54 → 45 行**：原「全局规范同步」一节把 `GLOBAL.md` 第二十二版逐条抄了 17 行，其中 9 条与本文件下面三节重复（CI 不发版、保留数 Release 1 / artifact 5、归属核验、写权限只在 `cleanup`、五段版本、文件名统一、规范自检不设工作流、只做新包与不降级）。改成一句指针 + 四条真正只在这里出现的常驻规则（改动落地、分支、Arena 检讨、CI 禁旧）。删前逐条核过落位：每个被删条文在下面三节都有命中（`grep` 逐条查过）。
- **changelog.md 412 → 261 行**：2026-09-30 及更早的 20 条压成 6 条，只留还在产线上的机制（`x-math` 三条、构建期尾链、`customize.sh` 刷新火狐配置拷贝、度量归一、空壳映射剪除、支撑面取舍）与结论性事实（Gecko 只认字件内部家族名；ChillRoundM 34% 空壳；主字体换过一圈定型在文渊 VF）。`TODO.md` 指向的「v2.x 自研 Selffont Round SC」那条连同全部数字（五字重、24–32 万端头、30,889 码位、CFF→TrueType、保留名改名、`tools/round.py` 被删）保留在压缩后的条目里，指针不断。
- 顺手记下一条反转关系：2026-09-30 把 `sans-serif-smallcaps` 纳入接管（当时判断 CarroisGothicSC 该被挤出清单），2026-10-07 按「本来是什么字体就保持什么字体」反转——压缩时把这条因果补进旧条目，免得日后只看到结论看不到反复。
- 自检 9 项仍全部通过（文档改动不进构建链，跑一遍是确认没误伤 `--check` 读到的任何文件）。
- **日界线口径顺带拿到一次真实跨日验证**：本次提交触发 run 105，产物 `Selffont-26.10.10.1.105` —— 日期段从上一轮的 `26.10.7` 翻到 `26.10.10`，当日序号从 10 回到 **1**（10 月 7 日三次运行是 8 / 9 / 10）。`count_day_runs` + `day_start` 的 Asia/Shanghai 零点换算在真实跨日场景下工作正常，这此前只有自检里的构造用例（`day_start(2026-10-05 00:30 +08) == 2026-10-04 16:00 UTC`）作依据。

## 2026-10-07 · 真机复验通过（8 / 0 / 3）；本轮收尾

- 主人装 `b2311f4` 之后的构建，**正常开机（不再重启循环）**，三条自查实测 **8 / 0 / 3**：`grep -c Selffont /system_ext/etc/fonts_base.xml` = **8**（与构建期「主字体被 8 族引用：匿名回退区 + `serif` + CJK 语言区」一致）、`grep -ci misans` = **0**、`grep -aic mfga /proc/mounts` = **3**（模块已挂载）。设备 `OnePlus/PLC110/OP60EDL1:16/BP2A.250605.015`（ColorOS / Android 16 / KernelSU）。
- 至此本轮四项在真机上一起验过：卡开机修复（`f3a93ff`）、混族不变量全覆盖（`3f81229`）、火狐「本来字体优先」（`41e2c65`）、系统层五个命名族恢复本来字体（`b2311f4`）。
- 顺带清掉设备上另一个模块 `zz_bootlog`（`author=me`，开机把 `logcat -b all` 灌进 `/data/local/tmp/bootlog`，不轮转、每次开机把上一次的挪成 `prev.log`，会一直长）：`ksud module uninstall zz_bootlog` → 在模块目录落一个 0 字节 `remove` 标记 → 重启后目录消失，实测已消失。对着 KernelSU 源码核过行为：`userspace/ksud/src/module.rs:805` 的 `uninstall_module()` 只「打标记」（`defs.rs:43` `REMOVE_FILE_NAME = "remove"`），提示走 `info!` 不进 stdout，所以命令**没有输出就是成功**；id 写错才会报 `Module <id> not found`。
- 自救网仍在设备上（`/data/adb/post-fs-data.d/sf-guard.sh` 402 B + `/data/adb/boot-completed.d/sf-ok.sh` 74 B，均 755）：正常开机净效果为零，只在模块致崩时接管。要拆：`su -c 'rm -f /data/adb/post-fs-data.d/sf-guard.sh /data/adb/boot-completed.d/sf-ok.sh /data/adb/sf-boot-ok /data/adb/sf-fail-count'`。
- 仍未验证（都只影响观感，不影响开机）：生僻字是否仍渲染成圆体；终端 / 代码类 App 的等宽是否回到 Droid Sans Mono；WebView 的 `font-variant: small-caps` 会不会去查 `sans-serif-smallcaps`；这次刷机用的是 `.102`（旧格式，解一层）还是 `.103`（包直出）未记录——两者字体配置相同，所以 8 / 0 / 3 的结论对两者都成立。
- 待办（主人：「哪天有空了再做」）：自制字体。另有此前挂着的重构三项未做：`AGENTS.md` 压缩、版本取数下沉到 workflow、`changelog.md` 压缩。

## 2026-10-07 · artifact 包直出（不再 zip 套 zip）；module.prop 作者字段不再自指

- 主人：「让包直出不再 zip 套 zip」「selffont 不应该 by selffont 吧」。
- 之前 `upload-artifact` 的 `path` 是 `build/Selffont*.zip`，artifact 容器里装着模块 zip：网页下载下来要先解一层才能刷（`gh run download` 会自动解，所以走命令行看不出这个问题）。改成：构建后 `unzip` 到 `build/root`，上传**目录内容**——按 upload-artifact 官方 README「搜索路径的最近公共祖先作为包内根目录」，artifact 包内根就是 `module.prop`，下载即可直接刷。上传前 CI 会 `test -f build/root/module.prop` 与 `build/root/customize.sh`，并打印目录清单。
- 代价：`gh run download` 会把内容摊进目标目录，得用 `-D` 指一个空目录（README 的下载示例已同步改）。
- `module/module.prop`：`author=Selffont` → `author=Sumicya`。原值让管理器显示成「Selffont by Selffont」，自指没有信息量。基础包的归属说明仍在 `licenses/MFGA-base-LICENSES.md`，没丢。
- 未验证：artifact 的包内布局只能靠 CI 实跑确认（本机取不到 Actions 的 blob 主机，TLS 握手超时）；`.sh` 的可执行位在「解包再重打包」之后是否保留未验证——KSU 是 `. customize.sh`、`sh action.sh` 这样调的，不依赖 +x，不影响安装。

## 2026-10-07 · 系统层：本来有自己字体的五个命名族不再被整族换成文渊

- 接火狐那条的同一原则：「本来就是什么字体就应该是什么字体，被篡改的才恢复」。系统层同样有五族被本模块整族换成了文渊——那不是恢复谁，是我们自己改的。
- 前提先查过：`DroidSansMono.ttf` / `CutiveMono.ttf` / `ComingSoon.ttf` / `DancingScript-Regular.ttf` / `CarroisGothicSC-Regular.ttf` 五个字件真机确认都在 `/system/fonts`（不是把文渊换成空气）。
- 改法（`build.py`）：`PRIMARY_FAMILIES` 从 8 个缩到 `{sans-serif, sans-serif-condensed, serif}`。`serif` 必须换（它本来放旧数字主字件 `100.ttf…900.ttf`，那些字件不打包，不换就是一族指不到东西的引用）；`sans-serif` / `sans-serif-condensed` 仍走度量空壳；其余五族逐字不动。
- 自检：删掉旧的「小型大写家族也接管」断言（`sans-serif-smallcaps` / `cursive` / `monospace` 必须被接管），换成反向断言——被接管的命名族**只有 serif**，五族逐字等于模板且本来字件在位；另加一条通用不变量：凡不在接管名单、也不含旧主字件的命名族，产出必须逐字等于模板。`build_end_to_end` 同步改成「serif 在接管名单里、五族不在」。
- 变异测试：把 `monospace` 放回 `PRIMARY_FAMILIES` → `fonts_xml` 与 `build_end_to_end` **双双 FAIL**。**第一版断言把期望从 `PRIMARY_FAMILIES` 推出来，变异只被 `build_end_to_end` 抓到（同义反复，`fonts_xml` 放过），已改成独立写死期望。**
- 产物：192 族、70492 字节；引用主字体的族从 **16 降到 8**（命名族只剩 `serif`，另 7 个是匿名回退区与 CJK 语言区）；混族仍 0。
- 影响（外观）：等宽场景（终端 / 代码 / `courier` 别名）从文渊变回真等宽字体；`cursive` 变回 Dancing Script、`casual`（CSS fantasy）变回 Coming Soon；`sans-serif-smallcaps` 变回 Carrois Gothic SC。中文不丢：这五族本来就没有中文，缺字照旧往语言区 / 默认区的文渊落。
- 火狐不用动：`41e2c65` 已把火狐的 monospace / cursive / fantasy 改成本来字体在前，这次改完两边一致（此前系统里是文渊、火狐里是本来字体）。
- 未验证：整包未真机验证；WebView 的 CSS `font-variant: small-caps` 会不会去查 `sans-serif-smallcaps` 家族（从而从文渊变成 Carrois Gothic SC）没实测。
- 已知既有矛盾（模板自带，本轮未动）：`fonts.xml` 里有 `<alias name="fantasy" to="serif"/>`，而 `serif` 被文渊接管 → Android 应用按名字要 `fantasy` 拿到文渊，WebView 的 CSS `fantasy` 走 `casual`（Coming Soon）。

## 2026-10-07 · 火狐名单：本来是什么字体就保持什么字体，被火狐篡改的才恢复

- 主人：「本来就是什么字体就应该是什么字体。但火狐篡改字体就应该恢复被篡改的字体。」
- 对照模板 `fonts.xml` 的命名家族，各泛型在系统里本来是：`sans-serif`=度量空壳（实际显示系统主字体）、`serif`=旧数字主字件、`monospace`=`DroidSansMono.ttf`、`cursive`=`DancingScript-Regular.ttf`、`casual`=`ComingSoon.ttf`（Android 的 fantasy 对应 casual）。所以 `sans-serif` / `serif` / `emoji` 前置文渊是**恢复**火狐的篡改；`monospace` / `cursive` / `fantasy` 前置文渊是**本模块自己改的**，之前连英文花体也被换成了文渊。
- 改法：`module/geckoview-config.yaml` 里 monospace / cursive / fantasy 共 22 行（`x-unicode` / `x-western` / `x-math` / `zh-CN` / `zh-TW` / `zh-HK` / `ja` / `ko`）改成「本来字体, 文渊, 原回退链」，本来字体在原链里出现过的去重（`monospace.ja` 尾部的 `Droid Sans Mono` 因此上移）。`sans-serif` / `serif` / `emoji` 不动，文渊仍在最前。
- 代码：`build.py` 新增 `NATIVE_FIRST`（泛型 → 本来字体）与 `name_list_ok()`；三处「必须以文渊开头」的断言（`firefox_bridge` 一处、`build_end_to_end` 两处）统一走它，另加「文渊在一条名单里只出现一次」（构建期尾链只往末尾追加，不该再加一遍）。
- 自检：9 项全部通过。变异测试两条——把 `monospace.x-western` 改回文渊在前、把 `cursive.ja` 的文渊写两遍——`firefox_bridge` 与 `build_end_to_end` 都 FAIL；还原后全过。`geckoview-config.yaml` 用 PyYAML 解析合法（40 个键）。`README.md` 里「每条首选项都是前置文渊」那句已按新规则改写。
- 未验证：「Gecko 按名单逐字找字体，所以 CJK 会落到紧随的文渊」是推断，没在火狐上实测。装机核对：火狐里 `font-family: cursive` 的英文应是 Dancing Script、中文应是文渊。
- 未处理（等主人定）：系统层同类问题——生成的 `font_fallback.xml` 把 `monospace` / `serif-monospace` / `casual` / `cursive` / `sans-serif-smallcaps` 五个命名族整族换成文渊，它们本来是 Droid Sans Mono / Cutive Mono / Coming Soon / Dancing Script / Carrois Gothic SC。按同一原则也该保持本来字体；本轮没动，因为影响所有 App，且改的正是刚出过卡开机事故的那份配置。

## 2026-10-07 · 真机卡开机修复：CJK 语言区不许混主字体与 .ttc 字件

- 真机（ColorOS 16 / 一加）刷入 `26.10.7.4.98` 后卡第一屏开机动画、整机重启；换回 main 构建无此现象。pstore 无 panic / watchdog，dropbox 无 system_server 崩溃记录，失败那次的 logcat 因重启丢失。
- 二分（改设备上模块目录里的三份配置副本，原文件已备份）：只删掉 3 个「混合族」里前置的主字体（NotoSansCJK 的 `ja` / `ko` 两族、Hentaigana 族），6 个纯主字体单字件语言区保留，**正常开机**，系统预加载 `Selffont-WenYuanRoundedSCVF.ttf`。结论：同一语言区族里混 `supportedAxes` 字件与带 `index` / `weight` 的 `.ttc` / 普通字件会卡开机；具体是哪条解析规则没抓到日志，未验证。
- 修法（`build.py` `swap_fonts`）：CJK 语言区删旧主字体与空壳后，**清空的族换成主字体单字件，仍有其他字件的族原样不动**。覆盖不丢：单字件族在文件里排在 Noto 同语言族之前，同语言缺字仍先落主字体。
- 自检：`fonts_xml` 新增不变量「语言区族要么全是 supportedAxes 字件、要么全不是」，CJK 族改为断言 `kept or [主字体]`；`build_end_to_end` 断言包内配置有主字体单字件、Noto 族仍在、没有混族。9 项全部通过。
- 同日收尾：删除已无调用者的 `prepend_fonts()`（它实现的正是被禁止的「前置混写」，留着会诱人复用）；混族自检去掉 `lang/variant` 条件，覆盖全部族（真实模板 192 族、14 个带 `supportedAxes`、混族 0，自检仍全过）。事实：只有语言区混族被真机证实卡开机；对其他族是保守推断，护栏文字已如实写明。
- 未验证：补丁后的完整包未真机验证（上面的二分手改版已验证开机）；日韩标注文本缺字是否确实先落文渊，未在真机逐字核对。

## 2026-10-06 · 不要 MiSans：配置与火狐名单里的引用一并清掉

- 主人：「MiSans 我不喜欢」（同时选定语言区方案 A：CJK 语言区前置主字体，区内原字件留后）。
- 做法（`build.py`，构建期，无开关）：新增 `UNWANTED_FONTS = re.compile(r"misans", re.I)`，`configure_fonts` 先把匹配的 `<font>` 引用整条删掉（模板里就一处：`<family lang="zh">` 的 `MiSansL3.otf`，带 `postScriptName="MiSans-L3"`），再删掉标注它的那条注释（`<!-- MiSans 作为回退 -->` 留在产物里会指不到东西），主循环照常走，最后把清空的家族节点删除（空 `<family>` 没有意义）。火狐模板 `module/geckoview-config.yaml` 里 `monospace.zh-CN` 的 `MiSans VF, MiSans`、`monospace.zh-TW` / `zh-HK` 的 `MiSans TC VF, MiSans TC` 直接删掉。
- 现场核对：产物里 `MiSans` 出现 **0 次**，其余 37 条注释保留；`lang="zh"` 语言区现在是 `[主字体]`（原来 `[主字体, MiSansL3.otf]`）；家族总数仍 192、带 `lang` 的家族仍 153、空家族 0、CJK 语言区仍各以主字体打头。
- 覆盖影响：`MiSansL3.otf` 本来就是**设备自带**（小米系）而非基础包成员，非小米设备上这条引用一直是空的；清掉后中文缺字继续往默认区的补充字库（天珩 / Unicode 新平面等）落，链子没断。自检 `build_end_to_end` 加了**字面**断言 `"MiSans" not in xml`（变异测试：把 `UNWANTED_FONTS` 改成永不匹配，该断言 FAIL），`firefox_bridge` 逐条名单也不许出现。`.venv/bin/python build.py --check` **9 项全部通过**。
- 未验证：仍无真机数据。装机核对加一条：`grep -ci misans /system_ext/etc/fonts_base.xml` 应为 0。

## 2026-10-06 · 缺字回退「语言区」修正：CJK 语言区必须自带主字体（此前被整族删除）

- 主人指正：「部分场景有字体回退默认区的情况」。核对上游后确认这是真问题——AOSP `font_fallback.xml` 头注写明家族分三类（默认家族 / 命名家族 / **locale fallback family**），缺字时按「完整 BCP-47 标签（含 script）→ 仅语言 → **顺序**」匹配，语言区优先于默认区的文件顺序；`source.android.com/docs/core/fonts/custom-font-fallback` 也点明 Android 15 起可变字体配置写在 `font_fallback.xml`（示例就是 `<family lang="und-Ethi" supportedAxes="wght,ital">`）。
- 旧实现的漏洞：`configure_fonts` 把「字件全是旧数字主字体 / 空壳」的**匿名家族整族删除**，这条规则把 5 个 CJK 语言区（`lang="zh,zh-Hans,zh-Hant"`、`zh-Hans`、`zh-Hant,zh-Bopo`、`ja`、`ko`）一起删了——它们原本装着旧主字体。删掉后中文场景缺字会先在语言区命中厂商字体（模板里 `lang="zh"` 是 `MiSansL3.otf`、`ja` / `ko` 是 `NotoSansCJK-Regular.ttc`），主字体根本轮不到；而主字体在默认区排第一，看着像「已经接管」。
- 修法：语言区不再整族删。新增 `swap_fonts()`——CJK 语言区（`zh` / `ja` / `ko` 系标签）删掉旧主字体与空壳字件、把主字体（一条 `supportedAxes="wght,ital"`）前置到最前，区内其余字件原样留在后面（**覆盖只加不减**）；非 CJK 语言区（`und-Arab` 等）与 emoji 区（`und-Zsye`）逐字不动。
- 现场核对（真实 `fonts.xml` 模板，主字体记作 `V.ttf`）：模板 193 个家族 → 输出 192；**带 `lang` 的家族 153 个，一个不少**（旧实现输出只剩 148）；`lang="zh"` 现在是 `[V.ttf, MiSansL3.otf]`，`lang="ja"` / `ko` 是 `[V.ttf, NotoSansCJK-Regular.ttc ×…]`，`zh-Hans` / `zh-Hant,zh-Bopo` / `zh,zh-Hans,zh-Hant` / `ja` / `ko` 各为 `[V.ttf]`；非 CJK 语言区 144 个家族逐字未改（自检逐条比对）；残留旧数字主字体 0 条；默认区第一条仍是紧随默认家族的匿名主字体家族。
- 自检（`fonts_xml`）新增：语言区家族数与顺序不变、CJK 语言区首个字件必是主字体且带 `supportedAxes`、区内原有非主字体字件一个不许少、非 CJK 语言区逐字未改。`.venv/bin/python build.py --check` **9 项全部通过**。
- 未验证：本机没有设备，语言区改动**未真机验证**。装机核对：中文界面下挑一个主字体没有、`MiSansL3` 有的字（或反向），看是否渲染成圆体；`grep -c Selffont /system_ext/etc/fonts_base.xml` 应比旧包多（多了 CJK 语言区的字件）。要退回旧行为就把 `configure_fonts` 里 `elif locale and is_cjk_locale(...)` 那条分支去掉。

## 2026-10-06 · 版本号锚定本次运行：五段格式不可豁免，取消四段退化与非发行出包

- 规范要求（第二十二版）：「CI 锚定本次运行创建时间与身份，不取查询时的最新运行冒充本次；同次重试复用版本」「计数规则不得豁免五段格式」「版本数据缺失、取数失败或校验不通过，就停止出包和上传」。
- 旧口径确实撞号，仓库里有实证：`Selffont-26.10.5.26.92` 有两条**不同内容**的 artifact（id `11349882843` = 105147518 字节，来自 push 运行 `37321147235`，`run_number` 91；id `11350566111` = 105147562 字节，来自 PR 运行 `37321152703`，`run_number` 92）——同一提交并行的 push 与 PR，push 那次查到的「最近运行号」已经是 92。
- 修法：`github_version_numbers()` 在 CI 里读 `GITHUB_RUN_ID` / `GITHUB_RUN_NUMBER`，用 `gh api repos/{owner}/{repo}/actions/runs/<id>` 取本次运行记录（校验返回的 id 与环境一致）：总序号 = 本次 `run_number`，日期 = 本次 `created_at` 换算 UTC+8，当日序号 = 当天不晚于本次运行的运行数（`until` 上界）。重试复用同一身份 → 版本不变。本地没有这两个环境变量时退到「最近一次运行」口径。
- 用真实运行号现场复核（`gh api` 实跑）：运行 91 → `26.10.5.47.91`，运行 92 → `26.10.5.48.92`——**不再撞号**；93 → `26.10.5.49.93`、94 → `26.10.5.50.94`。
- 同日把降级路径一并删干净（规范：五段不可豁免、缺数据就停）：`stamp_version()` 三段（日期 / 当日序号 / 总序号）缺一不可，缺就报错；`VERSION_RE` 只认五段；`default_output()` 没有五段版本不给产物名（`build/Selffont.zip` 这条非发行出口取消）；`build()` 里「取数失败只警告、按非发行版本继续」和「退化成四段」两条路径删除；`--query-github` 与手工 `--date/--day/--build` 混用直接报错（版本号只认一个来源）。
- 当日序号口径随之改：PR 运行也计入（PR 同样出包），唯一性由总序号保证；`AGENTS.md`「计数口径」与 README 同步改写（原「PR 检查不计入」「取不到当日序号退化写四段」两条已删）。
- 自检：`version_stamp` 改成断言「缺任一段就拒绝 + 四段不再被接受 + 非发行版本不给产物名」，`version_numbers` 断言 `until` 上界与本地口径。9 项全部通过。
- 本轮 CI 打脸一次（run `37509417094` / #95，Selfcheck 步骤 exit 1）：新加的断言写了「`GITHUB_RUN_ID` 不该在自检环境里」，而自检**就跑在 Actions 里**，这两个变量必然存在——本地跑不出来的环境依赖断言。修法：断言前临时摘掉这两个变量、验完还原（自检不联网，所以只验「没有 CI 身份」这条路径）。本地两种环境（有 / 无这两个变量）都 9 项通过后才重推。

## 2026-10-06 · 同步规范第二十二版：Release 1 个 / artifact 合计 5 个 + 归属核验与删后复核

- 规范从第二十一版升到第二十二版（2026-10-06）；`AGENTS.md` 版本戳与继承条目同步重写，删掉相反表述（旧的「Actions artifact 保留最近 5 个」升级为「跨分支、跨触发事件合计 5 个 + 归属核验 + 删后复核」，并补 Release 上限 1）。
- 现场核对（`gh api`）：本仓库 **Release 0 个**（规范上限 1，无积压要清）、Actions artifact **5 个**（正好在上限，dry-run 复核 0 个待删）、历史 tag 2 个（`v3.0.0` / `v26.9.30.39`，按规范保留）。
- `cleanup` job 按「前缀只筛候选、归属结合工作流与运行记录核验」改造：先取本仓库 `repository_id`（实测 `1356719722`），artifact 的 `workflow_run.repository_id` 与 `head_repository_id` 都必须是本仓库才算本项目；**归属不明的对象保留并打印**；删完再查一次复核，超过上限就 `exit 1`；顺带只读打印 Release 数，超过 1 个打 WARNING（CI 不拿 `contents` 写权限，获准人工发布时由发布者做发布后清理）。
- 出包前加命名一致性核对：产物名必须匹配 `^Selffont-<五段版本>$` 才写 `ARTIFACT_NAME`、才上传（`if-no-files-found: error` 与 `retention-days: 5` 不变）。
- PR 事件仍不跑 `cleanup`（工作流定义来自 PR 的合并 ref，给写权限等于执行未信任代码）；PR 产物照样计入清理范围，由下一次 push / 手动触发运行的清理 job 处理——这是安全边界，不是放弃数量清理。
- 未验证：`cleanup` 与新取数的**实际运行**要等这次 push 的 CI；沙箱里只做了 dry-run（同一套 `gh api` 调用与判定逻辑，未执行 DELETE）。

## 2026-10-06 · 删除旧会话分支 `arena/01a10a49-selffont`（PR #6 已合并）

- 主人明确要求删旧分支（覆盖上一轮「未删分支」的做法）。删前核对：该分支相对 `main` 只差 `changelog.md` 的一条记录（`git diff --stat 4e7f6b1 main` = `changelog.md | 6 ------`），其余内容已在 `main`（PR #6 的 merge commit `204b238`）。
- 那条记录先带进本分支（见下条「PR #6 并入 main」），再 `git push origin --delete arena/01a10a49-selffont`——不靠删除藏内容。删后 `git ls-remote --heads origin` 只剩 `main` 与本会话分支。
- 本地克隆是 depth 1 的浅克隆（`.git/shallow` 里是 `204b238`），所以「是否已合并」不能用 `merge-base --is-ancestor` 判（会误报 NOT ancestor）；改用 PR 状态（`gh pr list` 显示 #6 MERGED）+ 内容差异比对。

## 2026-10-05 · PR #6 并入 main（204b2380）

- 合并方式：merge commit（保留分支上 22 个提交的历史），当时未删分支（2026-10-06 已按主人要求删除，见上）。
- 合并后默认分支第一次运行：`37321612591` success，`Selfcheck / build / upload artifact` 与 `Keep newest 5 artifacts` **两个 job 都在默认分支上实跑**（此前只有 PR 分支可验证）；artifact 总数维持 5，最新 `Selffont-26.10.5.27.93`。
- 「清理必须挂在默认分支构建工作流里」的规范要求至此落实。

## 2026-10-05 · 别名字件实验判定无效并删除

- 真机探针（OnePlus / ColorOS 16 / Firefox for Android，随机测试页）：20 个空格在 `"cursive"`/`"fantasy"`/`"casual"`/`"serif-monospace"`/`"sans-serif-smallcaps"`/`"sans-serif-condensed"` 六个别名家族下宽度全部 = 478.3px（= 默认链），别名字件特有的 0.5em 空格（应为 ≈1000px）从未出现 → **Gecko 的字体清单不含未写进系统配置的字件**，别名字件解析不到。
- 同页拉丁串宽度三行（`"Selffont Rounded SC VF"` / `Roboto` / 不存在家族）全部 = 1049.8px：这是预期内的「收敛」——每条 `font.name-list.*` 都被前置文渊，家族命中与回退链首项指向同一副字体，网页侧无法区分（该结果不能用作「接入生效」的证据）。
- 结论：别名字件既不可见（解析不到）也无收益（命中与否都渲染文渊），**删除**：`build.py` 去掉 `ALIAS_FAMILIES`/`alias_font()`/`alias_members()`/`--no-alias-fonts` 与相关自检（自检 10 项 → 9 项），README/AGENTS 同步（不再有「别名字件未验证」条目）。
- 方法论留档：CSS `local()` 匹配的是字体**全名/PostScript 名**（我们主字体全名为 `Selffont Rounded SC VF Regular`、PS 为 `Selffont-Rounded-SC-VF`），且 Android 上 `local()` 查不到这些设备字体——用它测家族可见性是错仪器（第一版探针作废）。

## 2026-10-05 · 收尾：火狐开关真机生效；体积维持现状（不减覆盖）；建 TODO（自制圆体，下个会话）

- 真机（一加 / ColorOS 16 / Android 16 / KernelSU）补测：**火狐网页字体开关（运行时「操作」按钮 / `web-fonts.sh keep|block|toggle`）切换生效**；系统字体生效此前已验证。剩余未验证项收窄为「别名字件」与「纯 AOSP（非 ColorOS）机器上的 `font_fallback.xml` 路径」。
- 体积决策：**不为体积牺牲字库覆盖**（主人 2026-10-05 决定），102 MiB 的 zip 维持现状；构成与三条可选减重路线（减字库 / 换主字体 / 换 OTF）记在 README「产物构成」，仅备查、不执行。
- 新增 `TODO.md`：下个会话做「自制圆体主字体（类筑紫 A 丸ゴシック）」——含硬约束（VF 且含 `wght` 轴、OFL 合规、度量归一、不减覆盖）、历史线索（v2.x 曾自研 Selffont Round SC、圆角化脚本 `tools/round.py` 已删）、五个待确认问题与「只做方案 + 试点」的范围；`AGENTS.md` 加了指向。
- 本会话至此具备收尾条件：本地 = 远端、工作树干净、CI 双绿、artifact 出包正常。PR #6 保持 OPEN 等主人合并。

## 2026-10-05 · 真机验证成功（ColorOS 16 / 一加）：字体生效，三份配置全部替换

- 设备实测（2026-10-05，OnePlus / ColorOS 16 / Android 16 / KernelSU，`MFGA` 版本 `26.10.5.23.86`）：`/system/etc/font_fallback.xml`、`/system_ext/etc/fonts_base.xml`、`/system_ext/etc/fonts_ule.xml` 三份 `grep -c Selffont` 均为 7，系统字形变圆——**「只做新包 + 按设备实际配置替换」路线在真机成立**。
- 此前失败的教训链（写在这里防回归）：只换 AOSP 的 `font_fallback.xml` 时，ColorOS 读的是 `/system_ext/etc/fonts_base.xml` / `fonts_ule.xml`（日志 `SystemFonts: Loading font config from /system_ext/etc/fonts_base.xml` 实证），配置没被读到 → 字体不变；模块本身一直是挂载成功的（`/system/etc/font_fallback.xml Selffont=7`）。
- 明确体积构成（回应「去掉静态怎么还是 100+ MB」）：zip 约 100 MiB = 主字体 VF 副本约 46 MiB（源文件 `WenYuanRoundedSCVF.ttf` 48,755,224 字节）+ 补充字库约 54 MiB + 配置脚本不到 0.1 MiB；「去掉静态」删的是配置里的逐档展开（几 KB），字体数据始终只有一份 VF，不按字重复制。
- 未验证项收窄：仅剩火狐接入、别名字件、网页字体开关的真机表现，以及纯 AOSP（非 ColorOS）机器上的 `font_fallback.xml` 路径。

## 2026-10-05 · 真机根因定位：ColorOS 读 fonts_base.xml / fonts_ule.xml，我们只换了 font_fallback.xml

- 现象：真机（OnePlus / ColorOS，Android 16）装好后字体不变；模块目录里 `system/etc/font_fallback.xml` 字节数正常，系统侧 `/system/etc/font_fallback.xml Selffont=7`——**说明模块已正确挂载、配置已替换**，问题不在挂载。
- 根因（设备日志实证）：`logcat` 出现 `SystemFonts: Loading font config from /system_ext/etc/fonts_base.xml`。AOSP `SystemFonts.java` 是 `FONTS_XML = getFontsXmlDir() + "font_fallback.xml"`，ColorOS 把配置目录改到 `/system_ext/etc` 并改用厂商文件名 `fonts_base.xml`（另有界面实际使用的 `fonts_ule.xml`）；我们换的 `/system/etc/font_fallback.xml` 在这台机器上不被读，所以「没生效」。
- 修法：安装脚本按设备实际存在的配置逐个替换，内容永远是包里同一份新语法（`supportedAxes`）：`font_fallback*.xml`（AOSP）+ `fonts_base.xml` / `fonts_ule.xml`（ColorOS），扫描分区 `system` / `system_ext` / `product`；库存 `fonts.xml` 与 `fonts_customization.xml` 不碰。模块内容统一落 `$MODPATH/system/<分区>/etc/…`——KernelSU 的 `vendor` / `product` / `system_ext` 是指向 `system/` 下同名的符号链接，直接建顶层分区目录会顶掉符号链接（社区有卡开机案例）。
- 依据：AOSP android16-release `graphics/java/android/graphics/fonts/SystemFonts.java`（`FONTS_XML = ... font_fallback.xml`）与本机日志；ColorOS 三套配置的对应关系见 lxgw 字体模块模板的兼容性说明与 `coloros-font-switcher` v1.1.0 的说明。
- 自检：`runtime_scripts` 的假系统改成 `system/etc/font_fallback*.xml` + `system_ext/etc/fonts_base.xml` + `system_ext/etc/fonts_ule.xml`，断言替换 4 份、模块路径为 `system/etc/...` 与 `system/system_ext/etc/...`、库存 `fonts.xml` 不碰、一份都没有时中止。
- 未验证：ColorOS 的解析器是否接受带 `supportedAxes` 的新语法（其系统基于 Android 16，AOSP 解析器自 Android 15 起支持；若被拒，表现应是字体仍不生效，不会坏系统——要退就在管理器里停用模块）。装完复测方法：`grep -c Selffont /system_ext/etc/fonts_base.xml` 应非 0。

## 2026-10-05 · 真机「字体未应用」两处修正：分区覆盖 + font_fallback.xml 根节点裸 <familyset>

- 背景：真机（Android 16 / OnePlus）装上后字体没变。核对 AOSP 源码与官方文档后确认方向没错——android16-release 的 `data/fonts/fonts.xml` 头注写着「DEPRECATED：不再是系统装字体的来源，vendor 请把配置加到 `font_fallback.xml`」；android15-release 的 `font_fallback.xml` 本身就带 `sans-serif` 等命名家族（第一个 family 即默认族）。
- 修正一（覆盖）：`customize.sh` 原先只找 `/system` 下的 `system_ext` / `product` / `etc`，厂商把配置放在 `/my_product` / `/my_stock` / `/my_bigball` / `/vendor` / `/odm` 时框架读到的还是旧文件。现在逐分区找 `font_fallback*.xml` 并投放到模块的对应路径，任一命中都算；自检加了 `my_product` 用例（替换 3 份）。
- 修正二（根节点）：AOSP `font_fallback.xml` 头注写明「No attributes are allowed to `familyset` node」（15 的手写文件与 16 的生成器输出都是裸 `<familyset>`），我们的产物继承模板的 `version="23"`——严格解析下可能整份被拒。生成器现在去掉根属性，自检断言输出必须是裸 `<familyset>`。
- 未验证：这两处是否就是真机不生效的根因；设备侧还需要确认模块是否真的挂载（KernelSU 的 metamodule）与框架日志有没有解析错误——取证命令见下一轮交付。

## 2026-10-05 · README 安装命令修正（Termux 路径坑：先 cp 到 /data/local/tmp 再 ksud install）

- 现象：按 README 在 Termux 里 `su -c 'ksud module install /sdcard/Download/….zip'` 报 `No such file or directory`——解出的 zip 在 Termux 家目录，`/sdcard/Download/` 下没有；`ksud` 本身正常（打了 KernelSU 横幅）。
- 修法：安装命令改为「用 `ls -t "$PWD"/Selffont-*.zip | head -1` 定位 → `unzip -l` 验根有 `module.prop` → `su -c cp` 到 `/data/local/tmp` → `su -c ksud module install` → 删副本 → 重启」，并给 SELinux 拦截时的共享存储回退；下载与解压命令不变（实测：100.2 MB、解出 `Selffont-26.10.5.20.80.zip` 105567199 字节）。
- 未验证：本次修正后的命令尚未在真机重跑（等主人重试）。

## 2026-10-05 · 同步规范第二十一版：CI 出包必传（push 与 PR）+ 滚动清理默认启用 + 禁旧

- 按第二十一版把「CI 出包」与「CI 发版」彻底分开：`build.yml` 的 push 与 PR 构建都上传 `build/Selffont-<版本>.zip` 为 Actions artifact（`name=Selffont-<版本>`、`retention-days: 5`、`if-no-files-found: error`）；上传不需要写权限，Release / 正式 tag / 正式 asset 一概不碰。
- 滚动清理自第二十一版起默认启用、不需逐仓批准：`build.yml` 新增 `cleanup` job（`actions: write`、`needs: build`、非 PR 才跑、`concurrency` 串行），保留最近 5 个 artifact，按 `selffont-` 前缀（不分大小写，含旧积压 `selffont-module`）完整分页筛选，删除前打印完整清单；出包与清理同流，不新增工作流。
- 禁旧：`actions/setup-python` 从 v6 升 v7、`actions/upload-artifact` 用 v7（`actions/checkout@v7` 保持）；runner 继续钉 `ubuntu-24.04`。
- 规范自检不设工作流（第二十一版：由 agent 在会话中完成），`spec-check.yml` 不恢复；`AGENTS.md` 版本戳升到「本仓库上次同步 = 第二十一版」并补记第十八至二十一版要点（含 Arena 会话检讨条款）。
- 未验证：沙箱内无法下载 artifact（资产域被拦），下载命令只核到元数据（id / 名字 / 字节数）；清理 job 的实际删除效果以合并后 main 运行为准。

## 2026-10-05 · CI 出包：非 PR 运行上传 Actions artifact；按主人精简去掉 spec-check / cleanup

- 读规范更正：规范禁的是自动建 Release、自动建正式 tag、自动上传正式 Release asset；Actions artifact 本身是规范点名的真实下载入口。此前「CI 不上传」把两者混为一谈，产物没有下载入口——本轮更正。
- `build.yml` 在非 PR 运行（push / 手动触发）把 `build/Selffont-<版本>.zip` 传成 Actions artifact：名 = 产物名去 `.zip`、`retention-days: 5`、`if-no-files-found: error`；上传不需要写权限，权限块保持 `contents: read` + `actions: read`，不发版、不写 Release。
- 主人 2026-10-05 精简流程：`spec-check.yml` 与 `cleanup.yml` 已删除，不再恢复；规范自检由 agent 每轮交付前按第十七版手动执行（本轮已执行），规范「至少一个只读规范检查工作流」与现状的差异记录在案，待主人定。
- README 换成「从 CI 取包 / 手动删 artifact」命令块；AGENTS.md 的 CI 权限、产物与 artifact 条目同步。

## 2026-10-05 · 文档标点全角化收尾 + AGENTS 去重（必要维护）

- 中文文案按规范收尾全角标点：补上此前遗漏的加粗标签后冒号与逗号、内联代码后逗号、英文双引号等（例：`**标签**:` → `**标签**：`、`**标签**,下一句` → `**标签**，下一句`、`"中文"` → `「中文」`）；代码、URL、版本号、数字千分位（`12,162`）与标识符原样保留。
- `AGENTS.md`：删掉与第十七版规范条目重复的「三条硬规则」小节，项目落点并进「项目取舍」；版本戳与 `spec-check.yml` 校验串保持第十七版。

## 2026-10-05 · 只做新包：只投放 font_fallback.xml + 输入侧删掉全部降级

按主人裁决落地三条规则（只做新包 / 先查证 / 不做冗余降级）：

- **只做新包**：`build.py` 只生成一份配置（新语法 `supportedAxes`），删掉 legacy 逐档展开；`customize.sh` 只替换系统的 `font_fallback*.xml`，**库存 `fonts.xml` 不再替换**（Google 已废弃它，AOSP 的 JSON 作者层是构建期管线、不上设备）。设备没有 `font_fallback*.xml`（Android 15 以下）→ 安装直接中止，不假装成功。代价：放弃 Android 15 以下、以及没有该文件的 ROM（文档写明）。
- **不做冗余降级**：删掉「静态主字体全档同文件」（`weight_ladder` 无 `wght` 轴直接报错）与「缺空壳跳过归一继续打包」（缺 `Roboto-Regular.ttf` 或它不是可用空壳都直接报错）；`configure_fonts` 去掉现代/legacy 双开关与无空壳分支。
- **先查证**：本轮回补了 AOSP 侧证据——`font_fallback.xml` 存在于 AOSP 15 分支、官方「Android 15 起 vendor 必须把可变字体写进 font_fallback.xml」；最坏失败模式是「模块未生效」而不是坏系统（库存 `fonts.xml` 不动）。
- 自检同步：`fonts_xml` 断言主字体一律一条 `supportedAxes`、空壳条目只做「留下的一字不改」子集检查、静态字体与缺轴组合被拒；端到端断言包里没有 `fonts.xml`/`font_fallback_cjkvf.xml`、静态字体与不可用空壳被拒；安装脚本自检覆盖「只投放 font_fallback、库存 fonts.xml 不碰、没有新配置时中止」。
- 未验证：Android 15/16 真机上新配置是否被 `FontManagerService` 实际加载（现有真机是 Android 16，符合预期但未实测本次改动）。

## 2026-10-05 · 跟上新语法：font_fallback.xml（supportedAxes，Android 15+ 运行时实例化）

- `fonts.xml` 已废弃但仍必须与 `font_fallback.xml` 保持同步（AOSP 官方说明），且设备上跑的仍是 XML——AOSP 的 JSON 作者层（`font_config.json` / `alias.json` / `fallback_order.json` + `script/generate_fonts_xml_main.py`）是**构建期**管线，不上设备，模块没有 JSON 入口可挂。
- 新语法只有一处：字件节点可写 `supportedAxes`（AOSP 校验器枚举仅 `wght` / `wght,ital`，带它时可省 `weight`/`style`），由系统运行时按请求的字重 / 斜体现场实例化。
- `build.py` 现在生成两份同源配置：`fonts.xml` 维持 legacy 逐档展开（18 条带 `axis`），`font_fallback.xml` 主字体只出一条 `supportedAxes="wght,ital"`（静态主字体没有该轴，两侧都退回逐档展开）。
- `customize.sh` 按目标文件名投放：`font_fallback*.xml` → 新语法，其余 `font*.xml` → legacy；`fonts_customization.xml` 仍不碰。
- 顺带修正认知：设备 dump 的 `fonts.xml` 里 Roboto 空壳本来就带 `supportedAxes`，说明 Android 15/16 接受该语法；别名字件与主字体在两边写法不同、接管家族集合一致（自检断言）。
- 自检：`fonts_xml` 覆盖新语法节点（一条、无 weight/style/axis）、静态退化、`supported_axes` 枚举边界；`build_end_to_end` 断言两文件同源且接管家族一致；`runtime_scripts` 断言 5 份配置按名字分别拿到 legacy / 新语法。
- 真机未验证（无 Android 15+ 装机数据）；现网表现与旧版一致（legacy 文件仍照旧投放）。

## 2026-10-05 · 网页字体开关做成管理器按钮（运行时覆盖）+ 构建期默认值

- 新增 `module/web-fonts.sh`：`status` / `keep` / `block` / `toggle` / `refresh`，状态存 `FIREFOX_DATA_DIR`（默认 `/data/local/tmp/selffont-web-fonts.state`，在模块目录之外，模块更新不丢）。
- 新增 `module/action.sh`：KernelSU 管理器里模块的「操作」按钮，点一下在「压 / 放行」之间切换；只改火狐配置副本与状态文件，不动系统字体。
- `firefox.sh install` 与 `customize.sh` 的更新刷新都改走 `web-fonts.sh refresh`：按当前状态重新生成配置副本，不再用模板默认硬覆盖；`web-fonts.sh` 不可用时退回旧行为（cp 模板）。
- 表示法与构建期统一：生效 = pref 行原样（压），放行 = 该行加 `Selffont:keep` 标记注释；`build.py` 的 `apply_web_font_switch` 幂等，并改用同一套标记（原来整块替换的写法废弃）。
- 自检：`runtime_scripts` 覆盖 status / 幂等 / 按钮 toggle / 更新与重接入不覆盖运行时选择 / 开关行缺失报错；端到端构建断言 `web-fonts.sh`、`action.sh` 进包且配置标记正确。

## 2026-10-05 · 网页字体开关做成构建期开关（--keep-web-fonts）+ 真机核对清单

- `--keep-web-fonts`：默认仍把网页自带字体压成文渊；传了这个开关，打包时整块替换配置里的开关块（模板标记 `Selffont:web-fonts`，标记不在就报错，不静默出一个没开关的包）。选择烧进 zip——`customize.sh` 刷新配置拷贝时也跟着走，不会再被覆盖。
- 自检：`firefox_bridge` 覆盖默认压 / 放行 / 标记缺失三种情形；端到端构建断言放行后配置里没有 pref 且名单仍完整前置文渊。
- README 新增「未验证项的真机清单」：四条逐项核对（模块生效 → 火狐接入 → 别名字件 → 网页字体），以及两条回退路径。

## 2026-10-05 · 规范同步到第十六版（段位编号修正）

第十六版只改段位编号：`yy.m.d.当日序号.总序号` 里**第四段 = 当日序号、第五段 = 总序号**（此前规范误写第三段 / 第四段）。实现本来就是这个顺序（`version_core` 拼 `日期.当日序号.总序号`，`versionCode` = 第五段），所以本轮只同步版本戳与文案：

- `AGENTS.md`：升到「本仓库上次同步 = 第 16 版」，版本来源条目写明第四段 / 第五段。
- `spec-check.yml`：校验的规范版本与版本戳同步改成第十六版。
- `build.py --day` 帮助文案改「第四段」；README 补第四段 / 第五段的说明。
- 顺带核对：文档与代码里没有写死 run 号现值（版本查法只写 `gh api` 查询命令与 `--query-github`）。

## 2026-10-05 · 五段版本号 + CI 只读合规 + 火狐别名字件（未真机验证）

**1. 版本号换五段（规范第十五版）**：`yy.m.d.当日序号.总序号`，展示不含 `v`，`versionCode` = 总序号。

- 取数在仓库唯一构建工作流 `Build Selffont` 的运行历史里现场查（`build.py --query-github`）：总序号 = 该工作流最近一次运行的 `run_number`；当日序号 = 当天（Asia/Shanghai）该工作流 `push` / `workflow_dispatch` 且已开始的运行数，PR 检查不计入；日期按 UTC+8 一次取定，构建只读这三个值。
- 手工路径保留：`--build` / `--day` / `--date`（或 `SELFFONT_BUILD` / `SELFFONT_DAY` / `SELFFONT_DATE`），离线可用。
- 取不到当日序号 → 退化四段 `yy.m.d.总序号` 并警告（README 写明原因）；两个都取不到 → 不盖戳，`module.prop` 用非发行默认 `version=dev` / `versionCode=0`（旧默认 `v26.9.30.0` 退休，不再假装有正式序号）。
- 产物名跟版本走：`Selffont-<版本>.zip`；非发行版本仍是 `Selffont.zip`。
- 自检：`version_stamp` 覆盖五段 / 退化 / 非法值，新增 `version_numbers` 用假运行数据钉死「总序号取最近、PR 不计入当日、UTC+8 跨日」的取数口径，新增 `alias_fonts` 钉死别名字件的家族名、空字形与体积。

**2. CI 合规与清理（只读约束 + 手动清理）**：

- `build.yml`：加 `actions: read`（只为读本工作流的运行历史算版本号），构建步骤改用 `--query-github`；仍是校验性构建，**不发版、不上传 artifact**。
- 新增 `cleanup.yml`：仓库唯一有写权限的工作流（`actions: write`），**只手动触发**、默认干跑（`apply=false` 只打印清单）；按 `selffont-` 前缀筛选、完整分页、结构化字段、按 `created_at` 倒序保留最近 5 个，只删 artifact，不碰 Release / tag。
- `spec-check.yml` 扩检：规范版本与 `AGENTS.md` 版本戳、写权限白名单行、`pull_request_target` / `write-all` / 自动发版禁令，自身保持 `contents: read`。
- `AGENTS.md` 落「本仓库上次同步 = 第 15 版」、项目核对清单、CI 权限与清理说明、写权限白名单行。
- 旧体系积压（80 个历史 artifact，约 4.3 GB，来自已删除的旧工作流）：按「保留最近 5 个」核对出应删 75 个、应留 5 个（2026-09-29 与 09-30 的 `selffont-module`）。**本会话沙箱凭据没有 `actions: write`（删除请求回 403），未执行**；合并后手动触发 `cleanup.yml` 即按同一清单完成（`gh workflow run cleanup.yml -f apply=true`）。两个历史 tag（`v3.0.0`、`v26.9.30.39`）按规范默认保留。

**3. 火狐激进修复（未真机验证）**：

- 新增**别名字件**：`cursive` / `fantasy` / `casual` / `serif-monospace` / `sans-serif-smallcaps` / `sans-serif-condensed` 各一枚只有家族名、没有字形的极小字体（合计约 15 KB），放进 `system/fonts` 但不写进 `fonts.xml`——Gecko 按名解析命中它，逐字回退再按模块名单落到文渊；系统侧（Minikin 只读 fonts.xml）行为不变。`--no-alias-fonts` 可关。
- `browser.display.use_document_fonts: 0` 改为**默认开**：网页自带 webfont 不读系统清单，这是唯一能压它的开关；代价是图标字体（如 FontAwesome）会显示异常，README 写明关法。

**4. 文档**：README 重写（五段版本与查法、CI 行为与清理、火狐别名字件与网页字体默认、验证与回退、边界）；全仓库中文文案标点按规范统一为全角（代码内的路径、版本号、URL 不动）。

## 2026-09-30 · 火狐花体/小型大写：根因是 Unicode 逐字回退，修链对齐 fonts.xml

- 这类字符（𝓐𝓑𝓒 数学字母数字区、ᴀʙᴄ 小型大写区）不选字体，走 Gecko **逐字回退**：先按字符语言组查 `font.name-list.*`，再全清单乱序扫描，**不读 fonts.xml 顺序**——所以同一字符在系统与火狐是两副面孔。数学区语言组是 `x-math`，Gecko 在 Android 的默认名单全是设备上没有的桌面数学字体 → 直接乱序扫描。
- 修：① 配置补 `x-math` 三条（抄自 `all.js` Android 段，前置文渊）；② **构建期尾链**——把补充字库内部家族名（现场从基础包读）按 fonts.xml 顺序追加到每条 `font.name-list.*` 末尾；③ 配置拷贝在模块更新时自动刷新。自检 e2e 用真字体验尾链、`firefox_bridge` 断言 `x-math` 三条在位。**①② 至今在产线上。**
- 同一轮还把 `sans-serif-smallcaps` 纳入接管（当时判断 CarroisGothicSC 该被挤出清单）——这条 2026-10-07 按「本来是什么字体就保持什么字体」**反转**了。

## 2026-09-30 · CI 收回纯校验；模块更新自动刷新火狐配置（真 bug）

- **火狐配置陈旧坑**：`firefox.sh` 装进 `/data/local/tmp` 的是配置**拷贝**，模块更新不会自动换新——更新后没重跑 `firefox.sh`，火狐用的还是旧名单，怎么改配置都「未修复」。`customize.sh` 现在在安装/更新时检测：拷贝存在（= 已接入）就顺手刷新，不存在不碰；自检覆盖两种情形。
- **Gecko 只认字件内部家族名**（`gfxFT2FontList` 经 harfbuzz 读 name 表建清单，`AndroidFont` 包装只有 `GetFontFilePath()`），fonts.xml 别名永远进不去——这条结论后来判死了「别名字件」路线。
- CI 一度改成「直出裸 zip 挂 Release」，当天收回为纯校验（CI 不产任何东西、zip 一律本地产出）；出包重新回到 CI 是 2026-10-05 同步第二十一版之后的事。

## 2026-09-30 · 四化重写 IV：两个 Python 文件并成一个，行为逐字节不变

等价性有证明：同一输入下新旧打包器产出的 `fonts.xml` 与包内主字体 **sha256 逐字节相同**，模块 zip 的成员差异恰好等于删除项。删掉：`action.sh`、随包 `report.json`（连同 CI 的 Report 步骤与 `--revision`）、`emojiCoverage` 及其 cmap 管线、`--font` 的多文件静态字重映射（收敛为单 VF）、`tests/selfcheck.py`（并进 `build.py --check`）、`tools/` 目录（两个文件挪到仓库根）、`MAX_DOWNLOAD` 上限、`firefox.sh` 的 `command -v` 探测（55 → 27 行）、`layout_metrics` 的 `typo`/`win` 键。问完不删：度量归一、空壳映射剪除、OFL 整体改名、构建期字形守卫、基础包信任边界校验、`customize.sh` 整份替换、火狐原生接入、版本盖戳。净变化 991 行/2 文件 → 823 行/1 文件，仓库 15 → 13 个文件。（`action.sh` 后来因网页字体开关回来了，见 2026-10-05。）

## 2026-09-29 · 版本 = 日期 + 总构建数；上游同步；CI 提示清零

- 版本改 `vYY.M.D.<总构建数>`、`versionCode` = 总构建数，构建时盖戳，仓库里的 `module.prop` 是未盖戳默认；自检核对版本号末尾构建数与 `versionCode` 一致。（这套 2026-10-05 换成五段。）
- `runs-on` 钉 `ubuntu-24.04`（不再 `ubuntu-latest`），CI 运行页注释 1 warning + 1 notice → 0。
- 上游同步：fork 显示落后上游 1 个提交（`32c0ed6`，只改它自己的 `mfga-xposed/**`），用 `git merge -s ours upstream/main` 记录祖先关系——「落后」提示消失而 Xposed 代码一行没进来。当时我们的 `fonts.xml` 与上游 main 逐字节相同（sha256 `dd15902a…`）。

## 2026-09-28 及更早 · 主字体换过一圈，产线定型在文渊 VF

- **v4.1.0（09-28）火狐做回来**：改用 GeckoView 官方机制（`/data/local/tmp/<包名>-geckoview-config.yaml` + `am set-debug-app`），零 Kotlin / Gradle / APK / LSPosed；名单逐条抄 `all.js` Android 段、只前置不截断，emoji 也进名单。v3.0.0 记的「Firefox 修复疑似失效」与 README 的「不可修」都被源码推翻——问题不在能不能修，在于 **Gecko 不按 `fonts.xml` 选家族**。
- **v4.0.0 / v3.0.0（09-26～28）四化重写 II/III**：删 LSPosed 模块整条、`tools/round.py` 实验引擎、`webroot/` WebUI、`config/sources.json`、7z 分支、陈旧许可文件；构建链收敛成单语言 Python + fontTools，CI 两 job → 一 job。唯一「问完不删」的是度量空壳——Minikin 用默认家族的名义度量排版，删空壳等于拿渲染赌一次重构。
- **主字体换过一圈**：自研 Selffont Round SC（v2.2.0：Noto Sans SC OFL 五字重全量圆角化、24–32 万端头/字重、30,889 码位、CFF→TrueType、按保留名条款改名发布）→ Zen Maru Gothic（v2.3.0）→ 回归文渊（v2.3.1，「端头能仿，设计感仿不了」）→ 寒蝉圆黑体（v2.4.0）→ 寒蝉半圆体（v2.5.0）→ 寒蝉全圆体（v2.6.0；同系半圆体 ChillRoundM 实测 **34% 映射为空壳字形**、真机通知栏大面积缺字，弃用；此版新增**空壳映射剪除**防线）→ **v2.7.0 回归文渊圆体 v1.010 VF**（当时全场唯一持续维护、一个文件含 100–900 真字重、**真机验证过**），产线定型至今。
- **v2.0.0（09-26）四化重写**：删开机脚本 / GMS 组件干预 / app-fonts 权限把戏 / 全部平台闸门；10 个 Kotlin 类 → 2 个、5 个 Python 工具 → 1 个、4 个 CI → 1 个。保留至今的真机修复：安装副本竖直行度量归一到 Roboto 空壳载体（治角标数字偏低 / 切下沿）+ 构建期字形/轮廓/cmap/家族/轴守卫。
- **v1.4.0（09-12）**：三化重构首版（平台闸门 + override 标记 + SHA-256 死锁式校验），该策略路线已在 v2.0.0 被推翻。
- 支撑面取舍：MFGA 全量补充字库随包（约 54 MiB），**不为体积砍兜底**，v2.6.0 起一路沿用至今。
