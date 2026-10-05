# 更新日志

## 2026-10-05 · 规范同步到第十六版（段位编号修正）

第十六版只改段位编号：`yy.m.d.当日序号.总序号` 里**第四段 = 当日序号、第五段 = 总序号**（此前规范误写第三段 / 第四段）。实现本来就是这个顺序（`version_core` 拼 `日期.当日序号.总序号`，`versionCode` = 第五段），所以本轮只同步版本戳与文案：

- `AGENTS.md`：升到「本仓库上次同步 = 第 16 版」，版本来源条目写明第四段 / 第五段。
- `spec-check.yml`：校验的规范版本与版本戳同步改成第十六版。
- `build.py --day` 帮助文案改「第四段」；README 补第四段 / 第五段的说明。
- 顺带核对：文档与代码里没有写死 run 号现值（版本查法只写 `gh api` 查询命令与 `--query-github`）。

## 2026-10-05 · 五段版本号 + CI 只读合规 + 火狐别名字件（未真机验证）

**1. 版本号换五段（规范第十五版）**:`yy.m.d.当日序号.总序号`，展示不含 `v`,`versionCode` = 总序号。

- 取数在仓库唯一构建工作流 `Build Selffont` 的运行历史里现场查（`build.py --query-github`）：总序号 = 该工作流最近一次运行的 `run_number`；当日序号 = 当天（Asia/Shanghai）该工作流 `push` / `workflow_dispatch` 且已开始的运行数，PR 检查不计入；日期按 UTC+8 一次取定，构建只读这三个值。
- 手工路径保留：`--build` / `--day` / `--date`（或 `SELFFONT_BUILD` / `SELFFONT_DAY` / `SELFFONT_DATE`），离线可用。
- 取不到当日序号 → 退化四段 `yy.m.d.总序号` 并警告（README 写明原因）；两个都取不到 → 不盖戳，`module.prop` 用非发行默认 `version=dev` / `versionCode=0`（旧默认 `v26.9.30.0` 退休，不再假装有正式序号）。
- 产物名跟版本走：`Selffont-<版本>.zip`；非发行版本仍是 `Selffont.zip`。
- 自检：`version_stamp` 覆盖五段 / 退化 / 非法值，新增 `version_numbers` 用假运行数据钉死「总序号取最近、PR 不计入当日、UTC+8 跨日」的取数口径，新增 `alias_fonts` 钉死别名字件的家族名、空字形与体积。

**2. CI 合规与清理（只读约束 + 手动清理）**:

- `build.yml`：加 `actions: read`（只为读本工作流的运行历史算版本号），构建步骤改用 `--query-github`；仍是校验性构建，**不发版、不上传 artifact**。
- 新增 `cleanup.yml`：仓库唯一有写权限的工作流（`actions: write`），**只手动触发**、默认干跑（`apply=false` 只打印清单）；按 `selffont-` 前缀筛选、完整分页、结构化字段、按 `created_at` 倒序保留最近 5 个，只删 artifact，不碰 Release / tag。
- `spec-check.yml` 扩检：规范版本与 `AGENTS.md` 版本戳、写权限白名单行、`pull_request_target` / `write-all` / 自动发版禁令，自身保持 `contents: read`。
- `AGENTS.md` 落「本仓库上次同步 = 第 15 版」、项目核对清单、CI 权限与清理说明、写权限白名单行。
- 旧体系积压（80 个历史 artifact，约 4.3 GB，来自已删除的旧工作流）：按「保留最近 5 个」核对出应删 75 个、应留 5 个（2026-09-29 与 09-30 的 `selffont-module`）。**本会话沙箱凭据没有 `actions: write`（删除请求回 403），未执行**；合并后手动触发 `cleanup.yml` 即按同一清单完成（`gh workflow run cleanup.yml -f apply=true`）。两个历史 tag（`v3.0.0`、`v26.9.30.39`）按规范默认保留。

**3. 火狐激进修复（未真机验证）**:

- 新增**别名字件**:`cursive` / `fantasy` / `casual` / `serif-monospace` / `sans-serif-smallcaps` / `sans-serif-condensed` 各一枚只有家族名、没有字形的极小字体（合计约 15 KB），放进 `system/fonts` 但不写进 `fonts.xml`——Gecko 按名解析命中它，逐字回退再按模块名单落到文渊；系统侧（Minikin 只读 fonts.xml）行为不变。`--no-alias-fonts` 可关。
- `browser.display.use_document_fonts: 0` 改为**默认开**：网页自带 webfont 不读系统清单，这是唯一能压它的开关；代价是图标字体（如 FontAwesome）会显示异常，README 写明关法。

**4. 文档**:README 重写（五段版本与查法、CI 行为与清理、火狐别名字件与网页字体默认、验证与回退、边界）；全仓库中文文案标点按规范统一为全角（代码内的路径、版本号、URL 不动）。

## 2026-09-30 · 火狐花体/小型大写确认根因：Unicode 逐字回退，修链对齐 fonts.xml

拿到测试数据（花体/小型大写是 **Unicode 字符本身**，表现是"渲染成了别的字体"，且上次测的可能是旧配置拷贝），根因闭环：

- 这类字符（𝓐𝓑𝓒 数学字母数字区、ᴀʙᴄ 小型大写区）不选字体，走 Gecko 的**逐字回退**：先按字符语言组查 `font.name-list.*`，再全清单乱序扫描——**不读 fonts.xml 顺序**，选中的兜底字体和系统（Minikin 按 fonts.xml 链）不同，同一字符两副面孔。
- 数学区的语言组是 `x-math`,Gecko 在 Android 的默认名单全是桌面数学字体（设备上没有）→ 直接乱序扫描。
- 修复：① 配置补 `x-math` 三条（默认名单逐条抄自 all.js Android 段，前置文渊）；② **构建期尾链**——`build.py` 把模块补充字库的内部家族名（优先 typographic，现场从基础包读）按 fonts.xml 出现顺序追加到每条 `font.name-list.*` 末尾，火狐逐字兜底从此与系统同序、选中同一个字体；③ 配置拷贝在模块更新时自动刷新（见下），配合 `firefox.sh` 重放。
- 自检：e2e 用真字体验尾链（内部家族名拼进每条名单、前置仍是文渊），firefox_bridge 断言 x-math 三条在位。

## 2026-09-30 · CI 收回纯校验（无产物）；模块更新自动刷新火狐配置

**1. CI 无产物**：直出的本意是 CI 不该产出任何东西——收掉上一版误加的 Release 发布，以及更早的 upload-artifact / sha256 边车。CI 只跑自检 + 一次验证性构建（产物随 runner 丢弃）；模块 zip 一律本地 `build.py` 产出。

**2. 火狐配置陈旧坑（真 bug）**:`firefox.sh` 装进 `/data/local/tmp` 的是配置**拷贝**，模块更新不会自动换新——更新模块后没重跑 `firefox.sh`，火狐用的还是旧名单，怎么改配置都"未修复"。`customize.sh` 现在在安装/更新时检测：那份拷贝存在（= 用户已接入）就顺手刷新；不存在不碰。自检覆盖两种情形（未接入不碰 / 已接入换新）。

**3. 火狐花体/小型大写排查记录**（全部源码为证）：确认 Gecko 的 `AndroidFont` 包装只有 `GetFontFilePath()`(`AndroidSystemFontIterator.h`)——字体清单 = 字件内部家族名，fonts.xml 别名永远进不去。带引号家族名（`"cursive"`/`"sans-serif-smallcaps"`）与泛型关键字走不同路径，pref 只覆盖泛型；把别名做成真实字体文件可修，但主字体 48.7MB ×4 份不可行，待确认具体测试写法再定（带引号名 / 泛型 / Unicode 花体字符 / webfont，修法各不相同）。

## 2026-09-30 · CI 直出裸 zip；火狐花体/小型大写按源码根因修复

**1. 直出**:CI 不再产 `upload-artifact`（下载得到的是 zip 套 zip）也不写 sha256 边车——每次推送（非 PR）把裸 `Selffont.zip` 挂到 Release,tag/标题 = 盖戳版本号；重跑同一 run_number 时 `gh release upload --clobber` 覆盖附件。PR 事件只构建校验不发版（没有写权限）。

**2. 火狐花体（fantasy/cursive）与小型大写未修复——三个源码根因，逐个关掉**:

- **Gecko 只认字体文件内部家族名**（`gfxFT2FontList` 经 harfbuzz 读 name 表建清单），fonts.xml 别名（`cursive`/`sans-serif-smallcaps`）不进清单：网页按名调用走泛型 pref 或默认字体回退，不查我们的 fonts.xml。
- **泛型缺口**:`all.js` Android 段只有 `cursive.x-unicode/x-western` 默认，`fantasy` 一个都没有；zh/ja/ko 下 `font-family: cursive` 的 pref 列表为空，`mFallbackGeneric` 已设导致不再补默认泛型 → 空字体组 → `GetDefaultFont()`（清单第一个家族，Roboto 空壳）→ 花体行不渲染文渊。`geckoview-config.yaml` 补齐 cursive/fantasy ×（x-unicode/x-western/zh-CN/zh-TW/zh-HK/ja/ko），与既有行同规则：前置文渊、原样保留原回退。
- **小型大写**:`build.py` 的 `PRIMARY_FAMILIES` 漏了 `sans-serif-smallcaps`,CarroisGothicSC 一直留在系统清单里可被按文件名解析。接管后它挤出清单，系统侧与火狐侧（名称回退到默认泛型 → 我们的 sans-serif pref）都是文渊；CSS `font-variant: small-caps` 由基础字体合成，天然文渊。
- 自检加两条硬断言：真实模板的 `sans-serif-smallcaps` 家族必须被接管；配置里 cursive/fantasy × 7 语言组必须齐全（缺一条就空字体组）。
- 配置头注释顺带修正：还指着已删除的 `tools/build.py`/`tests/selfcheck.py`。

边界（写进 README）：网页自带 webfont 的装饰花体/小型大写不读系统清单，只有 `browser.display.use_document_fonts: 0` 能压。

## 2026-09-30 · 四化重写 IV（ponytail 激进版）：一个 Python 文件，行为逐字节不变

按 ponytail 梯子（YAGNI → 复用 → stdlib → 原生 → 已有依赖 → 一行 → 最小实现）对现存每一件东西重新提问，能删就删。**等价性有证明**：同一输入下，新旧打包器产出的 `fonts.xml` 与包内主字体**逐字节相同**（sha256 比对）；模块 zip 的成员差异恰好等于下列删除项。

**提出的问题与答案**（每条都落到了代码里）：

- `action.sh` 谁按过？它自己的注释都承认"不证明渲染结果，只证明模块装上了"——一个自我声明无用的文件。**删**（KSU 模块本就不需要 action 按钮）。
- `report.json` 谁在读？CI 摘要步骤和 README 里的两处引用；数据要么不可行动（`unbundledFontReferences` 225 个"设备自带"名单），要么无消费者。**随包 report.json 整个删**,CI 的 Report 步骤一并删（38 行工作流，日志即报告），`--revision` 参数随之消失。
- `emojiCoverage` 防的是哪个 bug？还没人报告过火狐豆腐。真要看覆盖，拿 fontTools 查 cmap 是一行的事。**删**（连同 `EMOJI_RANGES`/`emoji_ceiling`/`emoji_coverage` 与给它们服务的逐字体 cmap 加载管线）。
- `--font` 为什么要可重复、还带一套静态多文件就近字重映射？产线自 v2.7.0 起恒为单个 VF。**收敛为单字体**:`weight_ladder(axes)` 一个参数；静态字体仍可打包（全档同文件，粗体交给系统合成）。
- `tests/selfcheck.py` 凭什么是第二个文件？同一份逻辑放两个文件必然漂移。**并进 `build.py --check`**，无框架无夹具的作风不变，8 项检查全保留。
- `tools/` 目录还剩什么？build.py 和 requirements.txt 两个文件。**挪到仓库根，目录删**。
- `report` 里的 `metricNormalization`/`weightMap`/`digitInkY`？装饰性数据。**删**;`normalize_metrics` 回归"进 bytes 出 bytes"。
- `write_module` 里的 MODULE_KEYS 每构建校验、tempfile 原子落盘、包内字体 sha256 回读？静态文件由 `--check` 把关；产物可再生，坏了大不了重跑；`testzip` 已经够。**删**（校验逻辑留在自检里）。
- `MAX_DOWNLOAD` 512MiB 上限？默认源是钉死的，自选 URL 是用户自己的事（自由化）。**删**。
- `firefox.sh` 的 `command -v am/settings` 探测与 `debug_app` 回读？Android 必有这两个二进制，`set-debug-app` 失败本身有回显；探测只为在 Linux 上跑测试服务。**删**,55 → 27 行，install/remove 骨架不动。
- `layout_metrics` 的 `typo`/`win` 键？report 死了之后无消费者。**删**。

**保留的**（问完不删）：度量归一（真机校准）、空壳映射剪除、OFL 整体改名、构建期字形守卫、基础包信任边界校验（路径穿越/绝对路径/符号链接/重复成员）、`customize.sh` 整份替换、火狐 GeckoView 原生接入、版本盖戳。

**净变化**:Python 991 行（2 文件）→ 823 行（1 文件）；仓库 15 → 13 个文件（`tools/`、`tests/` 目录消失）；模块 zip 少 `report.json`、`action.sh` 两个成员；CI 54 → 38 行。CI 路径全部指向根目录 `build.py`。

## 2026-09-29 · 版本 = 日期 + 总构建数；上游同步；CI 提示清零

**1. 版本号换成 `vYY.M.D.<总构建数>`,versionCode = 总构建数**。构建时盖戳（`SELFFONT_BUILD=<n>` 或 `--build <n>`,CI 传 `github.run_number`），日期按 UTC+8 取；仓库里的 `module.prop` 是未盖戳的本地默认（`versionCode=0`），不再是"上次发布"的残留。自检核对版本号末尾的构建数与 versionCode 一致——只改一处就失败。

**2. 拿到 `workflows` 权限后的 CI 改动**:

- `runs-on: ubuntu-24.04`：不再用 `ubuntu-latest`，顺带消掉 GitHub 那条"ubuntu-latest 将于 10 月迁移"的提示；
- 构建步骤带 `SELFFONT_BUILD: ${{ github.run_number }}`;
- 新增 Report 步骤：把版本、主字体家族、补充字体数、emoji 覆盖上限前三名写进 GitHub Step Summary（emoji 数据第一次出现在 UI 里，不用下 100 MiB 的包才能看），构建警告同时转成 `::warning::` 注释。

结果：CI 运行页的注释从 1 条 warning + 1 条 notice → **0 条**。

**3. 上游同步**。fork 之前显示"落后上游 1 个提交"（`32c0ed6`，只改它自己的 `mfga-xposed/**` 与文档）。用 `git merge -s ours upstream/main` 记录祖先关系：fork 的"落后"提示消失，而它的 Xposed 代码一行没进来（我们只取字体资源）。要上游的补充字库，换 `--base` 即可。

## v4.2.0(2026-09-29)· 版本带日期与构建数，CI 回到零警告

三件事，每一件都先查清再动手：

**1. 版本日期 / 构建数**:`module.prop` 以前只有 `v4.1.0` 加一串看不出规则的 `2026092801`。现在 `version=v4.2.0 (2026-09-29)`、`versionCode=2026092901`（`YYYYMMDD` + 当日两位构建序号），自检核对两者日期一致——版本号一改而 versionCode 忘改，CI 直接失败。

**2. 上游领先的那一个提交**：本仓库是 `Numbersf/MakeFontsGreatAgain` 的 fork,GitHub 上显示 fork 的 main 落后上游 1 个提交——就是 `32c0ed6 "fix: some basics"`（2026-09-15,168 行），**只改它自己的 Xposed 模块**（`mfga-xposed/**` 的 Java/Kotlin/Gradle + `scope.list`）。`fonts/` 与 `fonts.xml` 自 release `1717180003` 起没有任何改动，我们的 `fonts.xml` 与上游 main 逐字节相同（sha256 `dd15902a…`）。所以不追平：合并它会把我们早已删掉的 Xposed 目录再拖回来，而我们的模块只取字体资源。README 边界里记下了这条判断。

**3. 警告**:CI 上唯一一条警告是 `fonts.xml 引用但基础包没有的字体(不打包):…` 两百多个名字。它不是问题：基础包只带设备没有的补充字库，Noto 全套与 OEM 字体（如 MiSansL3、NotoColorEmojiLegacy/Flags）本来就在设备上；引用两边都没有的字体只会让该条目失效，不中断渲染，而设备字体集在构建期不可知——所以它没法变成"可行动"的警告，只会训练人忽略警告。改法：警告降级——日志里一行摘要（`fonts.xml 引用 N 个字体名:模块带 M 个,其余 K 个由设备自带`），完整名单留在 `report.json` 的 `unbundledFontReferences` 里备查。CI 注释随之归零（只剩 GitHub 自己的 ubuntu-latest 迁移提示）。

## v4.1.0(2026-09-28)· 火狐做回来：换成原生机制，断言换成数据

火狐那条路 v3.0.0 被删掉时留了句话——"Firefox 修复疑似失效"。重新查 Gecko 源码后，那句和 README 的"不可修"都站不住：问题不在能不能修，在于**Gecko 根本不按 `fonts.xml` 选家族**。

**机制**（源码为证，不是猜）：

- Gecko 的字体清单在 Android API 29+ 走 `AndroidSystemFontIterator`（即系统字体配置），但**选谁**取决于 `font.name-list.*` 里硬编码的家族名（`all.js` 的 Android 段）。所以只要家族名对得上，文渊就会被用；对不上，Gecko 就回到自己的默认名单——字体装了也没用。
- 老实现（LSPosed hook `RuntimeSettings.getPrefsMap`）做的正是这件事，但代价是整条 Kotlin/Gradle/APK/LSPosed 产线；而且 `font.name.*`/`font.name-list.*` 名单它动了，`font.name-list.emoji` 它没碰。
- GeckoView **官方**支持从 `/data/local/tmp/<包名>-geckoview-config.yaml` 读启动首选项，前提是该应用是 Android「调试应用」（`Settings.Global.DEBUG_APP`）。root 一句 `am set-debug-app --persistent org.mozilla.firefox` 就能给它这个身份，重启后仍在。

**改动**:

- `module/firefox.sh`（约 40 行 shell）：`install` 写配置 + 设调试应用 + 回读 `debug_app` 验证；`remove` 全撤。零 Kotlin、零 Gradle、零 APK、零 LSPosed——同一条 LSPosed 路线在 v3.0.0 被判定"过度建造"，现在用原生机制把能力做回来，而不是把代码搬回来。
- `module/geckoview-config.yaml`：默认名单逐条抄自 Gecko 的 `all.js`（Android 段），每条**前置**文渊、后面原样保留。emoji 也进了名单（Gecko 对 emoji 表现字符优先选带彩色的字体，前置不会挡彩色 emoji）——旧实现当年特意回避的那一项，现在有源码依据地补上。
- 断言换成数据：`report.json` 新增 `emojiCoverage`，逐个读包内字体 cmap 的 emoji 段上限并排序。以后再出现"只有火狐豆腐"，先看包里到底有没有那个码位，再谈 Gecko。README 删掉"属 Gecko 限制，不可修"。
- 自检 6 → 7 项：`firefox_bridge` 盯着"只前置不截断"和 install/remove 行为（`am`/`settings` 用 PATH 替身），家族名与 `tools/build.py` 的 `RENAME` 不一致时报错。

## v4.0.0(2026-09-28)· 四化重写 III（ponytail）：先提问，再删

按 ponytail 梯子（YAGNI → 复用 → stdlib → 原生 → 已有依赖 → 一行 → 最小实现）逐件质问现有设计，砍到只剩"设备真的需要的文件 + 让它们正确所需的代码"。留下的没变：原生 `fonts.xml` 挂载、无平台闸门、任意来源、真机验证的度量归一。

**提出的问题与答案**（每条都落到了代码里）：

- `config/sources.json` 比命令行多给了什么？——只有两个默认值。默认值就是 `tools/build.py` 顶部的常量，**删文件**，少一层 JSON 解析和键错误面。
- `--font` 为什么要一个目录加固定文件名？——没理由。改成"文件或 URL，可重复"，安装名取文件名本身。
- `extras` 机制谁在用？——自 v2.7.0 起恒为空。**删**；要加兜底字体就换 `--base`。
- `module.prop` 为什么要生成？——生成器只是把数据从 JSON 搬到字符串。KSU 惯例是静态文件，**删生成器**：版本号在 `module/module.prop` 里直接改。
- `--refresh` 谁用？——没人。`rm -rf build/cache` 就是 refresh,**删**。
- `action.sh` 需要一个子命令分发器吗？——它只有一个动作，**删分发器**；诊断改成文件名无关的计数（主字体安装名现在是自由的）。
- `report.json` 的消费方是谁？——CI 的四个键。压成 `revision`/`primary`/`metricCarrier`/`bundledSupplementalFonts`/`unreferencedFontsDropped`/`warnings`，删掉装饰性字段。
- 度量空壳（Roboto carrier）还需要吗？——**需要，而且是这次唯一"问完不删"的东西**:Minikin 用集合首字体（默认家族）的名义度量排版，虽然主字体已被归一到同一组数值，但删空壳等于拿渲染赌一次重构。真机校准不属于 ponytail 的删减范围。
- `--revision` 还要吗？——要，CI 靠它把 zip 钉到 commit。
- 静态多字重支持还要吗？——要（自由化），但去掉"目录 + 文件名约定"这层框架，静态单文件也直接可用。
- ChillRound 的 OFL 为什么在包里？——那字体自 v2.7.0 起不在产线，**删文件**。
- 测试测够了但测在了已删的机制上？——删掉对 extras/配置漂移的测试，保留 6 项会真失败的行为检查。

**净变化**:`tools/build.py` 564 → 473 行、`tests/selfcheck.py` 409 → 379 行；仓库文件 14 → 13（删 `config/sources.json`、`module/licenses/ChillRound-OFL.txt`，增静态 `module/module.prop`）。原生化：模块布局回到 KSU 惯例（静态 module.prop + install 脚本 + action 按钮）。现代化：丢掉 `from __future__ import annotations`,CI 仍是 Python 3.14 + fontTools 4.66.0。

**CI 无需改动即可跑通**:`report.json` 里 CI 读的四个键形状不变。更精简的工作流（去掉重复的 report 解析，45 → 15 行）需要 GitHub `workflows` 权限，agent 推不了，命令见 PR 描述。

## v3.0.0(2026-09-26)· 四化重写 II（ponytail）：纯原生，纯 Python

先回退：v2.8.0/v2.8.1 圆头化产线（前分支 PR #2）整条作废，树回到 v2.7.0 基线。再按 ponytail 梯子（YAGNI → 复用 → stdlib → 原生 → 已有依赖 → 一行 → 最小实现）重写：

- **删优先**:`tools/round.py` 实验引擎（不在产线，2.8.x 过度建造的源头）；`xposed/` LSPosed 模块整条（Firefox 修复疑似失效，该路径失去存在理由）；`generate_noto_font`（v2.2.0 遗留死代码，依赖引擎）；7z/py7zr 分支（未声明依赖，从未使用）；Noto/ZenMaru 陈旧许可文件；`webroot/` 单按钮 WebUI（唯一功能 `action.sh diagnose` 已有，UI 冗余）；report.json 的 v2.1 前兼容键 `font`/`weightLadder`（唯一消费者 CI 已迁移到 `primary`）。
- **工具链收敛**：仓库不再有 Kotlin/Gradle/Android SDK——构建链单语言 Python + fontTools;CI 两 job → 一 job（自检 → zip），30 分钟 Android job 消失。
- **简单化**：打包器清死分支；自检 7 项 → 6 项（去引擎冒烟）；`action.sh` 去 LSPosed 日志子命令；README 同步 2.7.0 事实（修正"单字重"/"寒蝉"陈旧段）。
- **自由化/原生化不变**：无平台闸门，`--font/--base` 任意来源，`fonts.xml` 原生挂载，零 JNI 零开机脚本，零伴侣应用。
- **版本拉满**:CI Python 3.11 → 3.14,fontTools 4.65.0 → 4.66.0。
- MFGA 全量 81MB 支撑面保留（v2.6.0 有意取舍，不推翻）。

## v2.7.0(2026-09-26)· 回归文渊 VF

候选盘点（活跃度/真字重/简体覆盖/空壳扫描全维度）后回归**文渊圆体 v1.010 可变字体**——全场唯一持续维护的（2026-07 v1.000 → 2026-08 v1.010），一个 VF 文件内含 100–900 真字重（+ital），细粗正常，真机验证过。安装副本内部名按 OFL 保留名规则改为 Selffont Rounded SC VF。寒蝉全圆体保留为备选（一个 URL 的距离）；圆头化（在文渊上做端头处理）留作后续实验。

## v2.6.0(2026-09-26)· 寒蝉全圆体

同系半圆体 ChillRoundM 实测 **34% 映射为空壳字形**（缺「这们你说发还样种」等常用字，cmap 声称有但字形空白，吞回退）——真机通知栏大面积缺字，弃用。主字体切换到**寒蝉全圆体 Chill Round F**（小杉丸骨架，12,162 码位，空壳仅 13 且多为空格变体）：照搬字形仅归一行度量；构建新增**空壳映射剪除**防线（非空白码位映射到空白字形时剪除，让其落到回退链；只剪映射不删字形）。

支撑字体维持 **MFGA 全量支撑面**（平面二/三绝版字兜底全随包，产物约 81MB）——不为体积砍兜底，这是有意取舍。

## v2.5.0(2026-09-26)· 寒蝉半圆体

主字体切换到**寒蝉半圆体 Chill Round M**(Warren2060):Zen Maru Gothic 骨架的 GB2312 简体优化圆体，半圆弧端头，禅丸缺的简体字全有。照搬字形仅归一行度量；OFL 保留字体名，安装副本内部名改为 Chill Round M（合规），OFL 文本随包附带。

## v2.4.0(2026-09-26)· 寒蝉圆黑体

主字体切换到**寒蝉圆黑体 ChillRoundGothic**（Warren2060,OFL 无保留名，main 最后更新 2023-10）：7 真字重（ExtraLight 200 / Light 300 / Regular 400 / Medium 500 / Bold 700 / Heavy 900），27,183 码位，龘字在列；全部真实字重无合成。照搬原版字节，仅归一行度量。

## v2.3.1(2026-09-26)· 回归文渊

自研圆体与禅丸方案都止步于实验：端头能仿，设计感仿不了。主字体回归**文渊圆体 v1.010 原版**（真机验证过、专业设计、可变字体），照搬字节仅归一行度量。`tools/round.py` 作为实验工具保留在仓库。

## v2.3.0(2026-09-26)· Zen Maru Gothic

主字体短暂切换到禅丸原版（照搬）。

## v2.2.0(2026-09-26)· 自研圆体字库

主字体由外部字体换为**自研 Selffont Round SC**:

- 圆角引擎 `tools/round.py`：结构化自由端头检测（短封口 + 平行长边 + 近垂直交角）→ 半圆替换；接口、拐角、口框零改动——根除资源圆体一类「逢角必圆」流派的接口凸起。
- Noto Sans SC（OFL）五字重全量圆角化：24–32 万端头/字重，30,889 码位；CFF→TrueType；衍生字库按保留名条款改名发布。
- 资源圆体扩展字库方案作废（自研字库覆盖同级，无外来 extras）；禅丸 Gothic 方案作废。
- build.py：多文件静态字重阶梯（每档取最近声明字重，并列取较重）、主字体本地生成 + `--font` 目录输入、extras 机制保留。
- CI 现场从 Noto 生成五字重再打包，仓库零二进制；自检加圆角引擎冒烟。

## v2.0.0(2026-09-26)· 四化重写

全仓库推倒重来。方向：自由化、简单化、现代化、原生化。

- **原生化**：系统字体只走 `fonts.xml` 原生挂载 + KSU 只读安装；删除开机脚本、GMS 组件干预、应用字体权限把戏（app-fonts）、emoji 重叠处理及其全部原生工具。LSPosed 只剩两条系统管不到的路径：应用自带字体（Typeface 工厂）与 Gecko 启动首选项。只用公开 API，零 JNI。
- **自由化**：删除全部平台闸门（Android 16/Oplus/KSU 检查、override 标记、平台支持测试）。SHA-256/版本/家族名断言全部降级为提示性警告；`--font`/`--base` 接受任意本地文件或 URL，家族名、可变轴、度量现场从字体读取，静态字体可打包，轴越界夹取不拒绝。
- **简单化**:10 个 Kotlin 类 → 2 个；5 个 Python 工具 → 1 个 `tools/build.py`;10 个运行时脚本 → 2 个；4 个 CI → 1 个；16 个测试文件 → 3 个（只测真实行为）；删除诊断探针、WebUI 按钮矩阵、i18n 层、docs/ 目录；单文件 WebUI 只剩只读诊断。`uninstall.sh` 删除——卸载即删目录重启。
- **现代化**:Kotlin 2 文件（Entry/Policy），AGP 9.3 内置 Kotlin、JDK 21、SDK 36;Python 3.11 单文件打包器；CI 一个工作流同时出模块 zip 与诊断 APK。
- 保留的真机验证修复：安装副本竖直行度量归一到 Roboto 空壳载体（角标数字偏低/切下沿），构建期字形/轮廓/cmap/家族/轴逐字节守卫。
- 主字体安装名改为 `Selffont-primary.ttf`;Gecko 家族名集中在 `xposed/.../Policy.kt` 一处。
- 上游 MFGA 的变更历史不属于本仓库功能清单，见上游 release 页。

---

## v1.4.0(2026-09-12)

三化重构（现代化/自由化/原生化）的首版：文渊圆体系统字体模块 + 只读诊断 APK；度量归一修复角标；Gecko `font.name-list` 前置保留；平台闸门 + override 标记；SHA-256 死锁式校验。该策略路线已在 v2.0.0 被推翻。
