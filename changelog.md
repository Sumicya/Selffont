# 更新日志

## 2026-09-29 · 版本 = 日期 + 总构建数;上游同步;CI 提示清零

**1. 版本号换成 `vYY.M.D.<总构建数>`,versionCode = 总构建数**。构建时盖戳(`SELFFONT_BUILD=<n>` 或 `--build <n>`,CI 传 `github.run_number`),日期按 UTC+8 取;仓库里的 `module.prop` 是未盖戳的本地默认(`versionCode=0`),不再是"上次发布"的残留。自检核对版本号末尾的构建数与 versionCode 一致——只改一处就失败。

**2. 拿到 `workflows` 权限后的 CI 改动**:

- `runs-on: ubuntu-24.04`:不再用 `ubuntu-latest`,顺带消掉 GitHub 那条"ubuntu-latest 将于 10 月迁移"的提示;
- 构建步骤带 `SELFFONT_BUILD: ${{ github.run_number }}`;
- 新增 Report 步骤:把版本、主字体家族、补充字体数、emoji 覆盖上限前三名写进 GitHub Step Summary(emoji 数据第一次出现在 UI 里,不用下 100 MiB 的包才能看),构建警告同时转成 `::warning::` 注释。

结果:CI 运行页的注释从 1 条 warning + 1 条 notice → **0 条**。

**3. 上游同步**。fork 之前显示"落后上游 1 个提交"(`32c0ed6`,只改它自己的 `mfga-xposed/**` 与文档)。用 `git merge -s ours upstream/main` 记录祖先关系:fork 的"落后"提示消失,而它的 Xposed 代码一行没进来(我们只取字体资源)。要上游的补充字库,换 `--base` 即可。

## v4.2.0(2026-09-29)· 版本带日期与构建数,CI 回到零警告

三件事,每一件都先查清再动手:

**1. 版本日期 / 构建数**:`module.prop` 以前只有 `v4.1.0` 加一串看不出规则的 `2026092801`。现在 `version=v4.2.0 (2026-09-29)`、`versionCode=2026092901`(`YYYYMMDD` + 当日两位构建序号),自检核对两者日期一致——版本号一改而 versionCode 忘改,CI 直接失败。

**2. 上游领先的那一个提交**:本仓库是 `Numbersf/MakeFontsGreatAgain` 的 fork,GitHub 上显示 fork 的 main 落后上游 1 个提交——就是 `32c0ed6 "fix: some basics"`(2026-09-15,168 行),**只改它自己的 Xposed 模块**(`mfga-xposed/**` 的 Java/Kotlin/Gradle + `scope.list`)。`fonts/` 与 `fonts.xml` 自 release `1717180003` 起没有任何改动,我们的 `fonts.xml` 与上游 main 逐字节相同(sha256 `dd15902a…`)。所以不追平:合并它会把我们早已删掉的 Xposed 目录再拖回来,而我们的模块只取字体资源。README 边界里记下了这条判断。

**3. 警告**:CI 上唯一一条警告是 `fonts.xml 引用但基础包没有的字体(不打包):…` 两百多个名字。它不是问题:基础包只带设备没有的补充字库,Noto 全套与 OEM 字体(如 MiSansL3、NotoColorEmojiLegacy/Flags)本来就在设备上;引用两边都没有的字体只会让该条目失效,不中断渲染,而设备字体集在构建期不可知——所以它没法变成"可行动"的警告,只会训练人忽略警告。改法:警告降级——日志里一行摘要(`fonts.xml 引用 N 个字体名:模块带 M 个,其余 K 个由设备自带`),完整名单留在 `report.json` 的 `unbundledFontReferences` 里备查。CI 注释随之归零(只剩 GitHub 自己的 ubuntu-latest 迁移提示)。

## v4.1.0(2026-09-28)· 火狐做回来:换成原生机制,断言换成数据

火狐那条路 v3.0.0 被删掉时留了句话——"Firefox 修复疑似失效"。重新查 Gecko 源码后,那句和 README 的"不可修"都站不住:问题不在能不能修,在于**Gecko 根本不按 `fonts.xml` 选家族**。

**机制**(源码为证,不是猜):

- Gecko 的字体清单在 Android API 29+ 走 `AndroidSystemFontIterator`(即系统字体配置),但**选谁**取决于 `font.name-list.*` 里硬编码的家族名(`all.js` 的 Android 段)。所以只要家族名对得上,文渊就会被用;对不上,Gecko 就回到自己的默认名单——字体装了也没用。
- 老实现(LSPosed hook `RuntimeSettings.getPrefsMap`)做的正是这件事,但代价是整条 Kotlin/Gradle/APK/LSPosed 产线;而且 `font.name.*`/`font.name-list.*` 名单它动了,`font.name-list.emoji` 它没碰。
- GeckoView **官方**支持从 `/data/local/tmp/<包名>-geckoview-config.yaml` 读启动首选项,前提是该应用是 Android「调试应用」(`Settings.Global.DEBUG_APP`)。root 一句 `am set-debug-app --persistent org.mozilla.firefox` 就能给它这个身份,重启后仍在。

**改动**:

- `module/firefox.sh`(约 40 行 shell):`install` 写配置 + 设调试应用 + 回读 `debug_app` 验证;`remove` 全撤。零 Kotlin、零 Gradle、零 APK、零 LSPosed——同一条 LSPosed 路线在 v3.0.0 被判定"过度建造",现在用原生机制把能力做回来,而不是把代码搬回来。
- `module/geckoview-config.yaml`:默认名单逐条抄自 Gecko 的 `all.js`(Android 段),每条**前置**文渊、后面原样保留。emoji 也进了名单(Gecko 对 emoji 表现字符优先选带彩色的字体,前置不会挡彩色 emoji)——旧实现当年特意回避的那一项,现在有源码依据地补上。
- 断言换成数据:`report.json` 新增 `emojiCoverage`,逐个读包内字体 cmap 的 emoji 段上限并排序。以后再出现"只有火狐豆腐",先看包里到底有没有那个码位,再谈 Gecko。README 删掉"属 Gecko 限制,不可修"。
- 自检 6 → 7 项:`firefox_bridge` 盯着"只前置不截断"和 install/remove 行为(`am`/`settings` 用 PATH 替身),家族名与 `tools/build.py` 的 `RENAME` 不一致时报错。

## v4.0.0(2026-09-28)· 四化重写 III(ponytail):先提问,再删

按 ponytail 梯子(YAGNI → 复用 → stdlib → 原生 → 已有依赖 → 一行 → 最小实现)逐件质问现有设计,砍到只剩"设备真的需要的文件 + 让它们正确所需的代码"。留下的没变:原生 `fonts.xml` 挂载、无平台闸门、任意来源、真机验证的度量归一。

**提出的问题与答案**(每条都落到了代码里):

- `config/sources.json` 比命令行多给了什么?——只有两个默认值。默认值就是 `tools/build.py` 顶部的常量,**删文件**,少一层 JSON 解析和键错误面。
- `--font` 为什么要一个目录加固定文件名?——没理由。改成"文件或 URL,可重复",安装名取文件名本身。
- `extras` 机制谁在用?——自 v2.7.0 起恒为空。**删**;要加兜底字体就换 `--base`。
- `module.prop` 为什么要生成?——生成器只是把数据从 JSON 搬到字符串。KSU 惯例是静态文件,**删生成器**:版本号在 `module/module.prop` 里直接改。
- `--refresh` 谁用?——没人。`rm -rf build/cache` 就是 refresh,**删**。
- `action.sh` 需要一个子命令分发器吗?——它只有一个动作,**删分发器**;诊断改成文件名无关的计数(主字体安装名现在是自由的)。
- `report.json` 的消费方是谁?——CI 的四个键。压成 `revision`/`primary`/`metricCarrier`/`bundledSupplementalFonts`/`unreferencedFontsDropped`/`warnings`,删掉装饰性字段。
- 度量空壳(Roboto carrier)还需要吗?——**需要,而且是这次唯一"问完不删"的东西**:Minikin 用集合首字体(默认家族)的名义度量排版,虽然主字体已被归一到同一组数值,但删空壳等于拿渲染赌一次重构。真机校准不属于 ponytail 的删减范围。
- `--revision` 还要吗?——要,CI 靠它把 zip 钉到 commit。
- 静态多字重支持还要吗?——要(自由化),但去掉"目录 + 文件名约定"这层框架,静态单文件也直接可用。
- ChillRound 的 OFL 为什么在包里?——那字体自 v2.7.0 起不在产线,**删文件**。
- 测试测够了但测在了已删的机制上?——删掉对 extras/配置漂移的测试,保留 6 项会真失败的行为检查。

**净变化**:`tools/build.py` 564 → 473 行、`tests/selfcheck.py` 409 → 379 行;仓库文件 14 → 13(删 `config/sources.json`、`module/licenses/ChillRound-OFL.txt`,增静态 `module/module.prop`)。原生化:模块布局回到 KSU 惯例(静态 module.prop + install 脚本 + action 按钮)。现代化:丢掉 `from __future__ import annotations`,CI 仍是 Python 3.14 + fontTools 4.66.0。

**CI 无需改动即可跑通**:`report.json` 里 CI 读的四个键形状不变。更精简的工作流(去掉重复的 report 解析,45 → 15 行)需要 GitHub `workflows` 权限,agent 推不了,命令见 PR 描述。

## v3.0.0(2026-09-26)· 四化重写 II(ponytail):纯原生,纯 Python

先回退:v2.8.0/v2.8.1 圆头化产线(前分支 PR #2)整条作废,树回到 v2.7.0 基线。再按 ponytail 梯子(YAGNI → 复用 → stdlib → 原生 → 已有依赖 → 一行 → 最小实现)重写:

- **删优先**:`tools/round.py` 实验引擎(不在产线,2.8.x 过度建造的源头);`xposed/` LSPosed 模块整条(Firefox 修复疑似失效,该路径失去存在理由);`generate_noto_font`(v2.2.0 遗留死代码,依赖引擎);7z/py7zr 分支(未声明依赖,从未使用);Noto/ZenMaru 陈旧许可文件;`webroot/` 单按钮 WebUI(唯一功能 `action.sh diagnose` 已有,UI 冗余);report.json 的 v2.1 前兼容键 `font`/`weightLadder`(唯一消费者 CI 已迁移到 `primary`)。
- **工具链收敛**:仓库不再有 Kotlin/Gradle/Android SDK——构建链单语言 Python + fontTools;CI 两 job → 一 job(自检 → zip),30 分钟 Android job 消失。
- **简单化**:打包器清死分支;自检 7 项 → 6 项(去引擎冒烟);`action.sh` 去 LSPosed 日志子命令;README 同步 2.7.0 事实(修正"单字重"/"寒蝉"陈旧段)。
- **自由化/原生化不变**:无平台闸门,`--font/--base` 任意来源,`fonts.xml` 原生挂载,零 JNI 零开机脚本,零伴侣应用。
- **版本拉满**:CI Python 3.11 → 3.14,fontTools 4.65.0 → 4.66.0。
- MFGA 全量 81MB 支撑面保留(v2.6.0 有意取舍,不推翻)。

## v2.7.0(2026-09-26)· 回归文渊 VF

候选盘点(活跃度/真字重/简体覆盖/空壳扫描全维度)后回归**文渊圆体 v1.010 可变字体**——全场唯一持续维护的(2026-07 v1.000 → 2026-08 v1.010),一个 VF 文件内含 100–900 真字重(+ital),细粗正常,真机验证过。安装副本内部名按 OFL 保留名规则改为 Selffont Rounded SC VF。寒蝉全圆体保留为备选(一个 URL 的距离);圆头化(在文渊上做端头处理)留作后续实验。

## v2.6.0(2026-09-26)· 寒蝉全圆体

同系半圆体 ChillRoundM 实测 **34% 映射为空壳字形**(缺「这们你说发还样种」等常用字,cmap 声称有但字形空白,吞回退)——真机通知栏大面积缺字,弃用。主字体切换到**寒蝉全圆体 Chill Round F**(小杉丸骨架,12,162 码位,空壳仅 13 且多为空格变体):照搬字形仅归一行度量;构建新增**空壳映射剪除**防线(非空白码位映射到空白字形时剪除,让其落到回退链;只剪映射不删字形)。

支撑字体维持 **MFGA 全量支撑面**(平面二/三绝版字兜底全随包,产物约 81MB)——不为体积砍兜底,这是有意取舍。

## v2.5.0(2026-09-26)· 寒蝉半圆体

主字体切换到**寒蝉半圆体 Chill Round M**(Warren2060):Zen Maru Gothic 骨架的 GB2312 简体优化圆体,半圆弧端头,禅丸缺的简体字全有。照搬字形仅归一行度量;OFL 保留字体名,安装副本内部名改为 Chill Round M(合规),OFL 文本随包附带。

## v2.4.0(2026-09-26)· 寒蝉圆黑体

主字体切换到**寒蝉圆黑体 ChillRoundGothic**(Warren2060,OFL 无保留名,main 最后更新 2023-10):7 真字重(ExtraLight 200 / Light 300 / Regular 400 / Medium 500 / Bold 700 / Heavy 900),27,183 码位,龘字在列;全部真实字重无合成。照搬原版字节,仅归一行度量。

## v2.3.1(2026-09-26)· 回归文渊

自研圆体与禅丸方案都止步于实验:端头能仿,设计感仿不了。主字体回归**文渊圆体 v1.010 原版**(真机验证过、专业设计、可变字体),照搬字节仅归一行度量。`tools/round.py` 作为实验工具保留在仓库。

## v2.3.0(2026-09-26)· Zen Maru Gothic

主字体短暂切换到禅丸原版(照搬)。

## v2.2.0(2026-09-26)· 自研圆体字库

主字体由外部字体换为**自研 Selffont Round SC**:

- 圆角引擎 `tools/round.py`:结构化自由端头检测(短封口 + 平行长边 + 近垂直交角)→ 半圆替换;接口、拐角、口框零改动——根除资源圆体一类「逢角必圆」流派的接口凸起。
- Noto Sans SC(OFL)五字重全量圆角化:24–32 万端头/字重,30,889 码位;CFF→TrueType;衍生字库按保留名条款改名发布。
- 资源圆体扩展字库方案作废(自研字库覆盖同级,无外来 extras);禅丸 Gothic 方案作废。
- build.py:多文件静态字重阶梯(每档取最近声明字重,并列取较重)、主字体本地生成 + `--font` 目录输入、extras 机制保留。
- CI 现场从 Noto 生成五字重再打包,仓库零二进制;自检加圆角引擎冒烟。

## v2.0.0(2026-09-26)· 四化重写

全仓库推倒重来。方向:自由化、简单化、现代化、原生化。

- **原生化**:系统字体只走 `fonts.xml` 原生挂载 + KSU 只读安装;删除开机脚本、GMS 组件干预、应用字体权限把戏(app-fonts)、emoji 重叠处理及其全部原生工具。LSPosed 只剩两条系统管不到的路径:应用自带字体(Typeface 工厂)与 Gecko 启动首选项。只用公开 API,零 JNI。
- **自由化**:删除全部平台闸门(Android 16/Oplus/KSU 检查、override 标记、平台支持测试)。SHA-256/版本/家族名断言全部降级为提示性警告;`--font`/`--base` 接受任意本地文件或 URL,家族名、可变轴、度量现场从字体读取,静态字体可打包,轴越界夹取不拒绝。
- **简单化**:10 个 Kotlin 类 → 2 个;5 个 Python 工具 → 1 个 `tools/build.py`;10 个运行时脚本 → 2 个;4 个 CI → 1 个;16 个测试文件 → 3 个(只测真实行为);删除诊断探针、WebUI 按钮矩阵、i18n 层、docs/ 目录;单文件 WebUI 只剩只读诊断。`uninstall.sh` 删除——卸载即删目录重启。
- **现代化**:Kotlin 2 文件(Entry/Policy),AGP 9.3 内置 Kotlin、JDK 21、SDK 36;Python 3.11 单文件打包器;CI 一个工作流同时出模块 zip 与诊断 APK。
- 保留的真机验证修复:安装副本竖直行度量归一到 Roboto 空壳载体(角标数字偏低/切下沿),构建期字形/轮廓/cmap/家族/轴逐字节守卫。
- 主字体安装名改为 `Selffont-primary.ttf`;Gecko 家族名集中在 `xposed/.../Policy.kt` 一处。
- 上游 MFGA 的变更历史不属于本仓库功能清单,见上游 release 页。

---

## v1.4.0(2026-09-12)

三化重构(现代化/自由化/原生化)的首版:文渊圆体系统字体模块 + 只读诊断 APK;度量归一修复角标;Gecko `font.name-list` 前置保留;平台闸门 + override 标记;SHA-256 死锁式校验。该策略路线已在 v2.0.0 被推翻。
