# Selffont

Android 个人字体模块：**文渊圆体 v1.010 可变字体**（OFL，活跃维护；一个 VF 文件内含 `wght` 100–900 + `ital` 真字重）接管系统的主字体家族——**本来各有自己字体的命名族（等宽 / 手写 / 小型大写等）保持原样**，缺 CJK 时才落到文渊。原生 `fonts.xml` 挂载，模块即全部交付，无伴侣应用。模块 zip 由本地构建产出，CI 只做校验。

## 字体

照搬[文渊圆体](https://github.com/takushun-wu/WenYuanFonts/releases/tag/v1.010)：字形、cmap、可变轴逐字节不动（构建期逐字形守卫），安装副本只动三处——

1. 竖直行度量归一到基础包的 Roboto 空壳（真机验证：修角标数字偏低/切下沿）；
2. 剪除映射到空白字形的码位（上游声称覆盖但字形空白，会吞掉回退链）；
3. 按 OFL 保留名规则把内部家族名改成 **Selffont Rounded SC VF**。

字重阶梯现场从字体的 `wght`/`ital` 轴读取（越界夹取）；**主字体必须是含 `wght` 轴的可变字体**，静态字体直接拒绝（配置只出新语法，没有可声明的轴）。

模块只带**一份字体配置**：`font_fallback.xml`（Android 15+ 的新配置），主字体一条 `supportedAxes="wght,ital"`，由系统按请求的字重 / 斜体**运行时实例化**——任意字重精确插值，不再落到最近的离散档。

缺字回退分两个区，两边都要放主字体（AOSP `font_fallback.xml` 头注：家族分默认家族、命名家族、**locale fallback family** 三类，缺字时按「完整 BCP-47 标签（含 script）→ 仅语言 → 顺序」匹配）：

- **默认区**（不带 `lang` 的匿名家族，按文件顺序）：主字体作为一条匿名家族紧随默认家族，排在最前。
- **语言区**（带 `lang` / `variant` 的 locale fallback family，按语言标签优先匹配）：中日韩语言区（`zh` / `zh-Hans` / `zh-Hant,zh-Bopo` / `ja` / `ko`…）一律把主字体前置，区内原有字件（`NotoSansCJK` 等）原样留在后面——**覆盖只加不减**。只往默认区插一条是不够的：中文场景缺字会先在语言区里命中厂商字体，主字体根本轮不到。
- 非 CJK 语言区（`und-Arab` 之类）与 emoji 区（`und-Zsye`）逐字不动：那些字形主字体没有，插进去只会挡路。
- **不要的厂商字体连引用一起清掉**：`MiSans`（模板里 `lang="zh"` 那条 `MiSansL3.otf`，以及火狐名单里的 `MiSans VF` / `MiSans TC` 等）在生成的配置与火狐名单里都不留——中文缺字不落到它上面，继续往默认区的补充字库（天珩 / Unicode 新平面等）走。清掉后空掉的家族节点一并删除，标注它的注释也删。安装时把它投放到设备实际会读的每一份配置上（内容都是这同一份新语法）：AOSP 的 `font_fallback*.xml`，以及 ColorOS 的 `/system_ext/etc/fonts_base.xml` 与 `fonts_ule.xml`——**读哪份按厂商而定**，只换 AOSP 那份时 ColorOS 会继续用厂商配置，字体看起来「没生效」；**库存 `fonts.xml` 不再替换**（AOSP 16 头注已把这份文件标为 DEPRECATED，且 AOSP 的 JSON 作者层是构建期管线、设备上不落地）。设备一份可替换配置都没有（Android 15 以下）时安装直接中止，不留下半套配置。

## 构建

整个构建链是一个 Python 文件，自检内建其中：

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python build.py --check                  # 自检:无框架、无夹具,不下载不打包
.venv/bin/python build.py --query-git               # 正式打包:现场跑 git rev-list --count 取数并盖戳
.venv/bin/python build.py --build 47 --day 3 --date 26.10.6   # 或手工传三段(离线;缺一段就报错不出包)
.venv/bin/python build.py --font 文件或URL --base 本地ZIP或URL
.venv/bin/python build.py --keep-web-fonts         # 放行网页自带字体（默认压成文渊）
```

产物名跟版本走：`build/Selffont-<版本>.zip`；没有规范版本数据就不出包（取数失败停止出包和上传）。输入侧不降级：基础包缺 Roboto 空壳、或 `--font` 给的字体没有 `wght` 轴，都直接报错退出（不做「跳过归一」或「全档同文件」的降级）。默认来源与提示性哈希钉在 `build.py` 顶部（哈希漂移只警告，不拦构建）；下载缓存在 `build/cache/`，删掉即重新下载。构建 stdout 就是构建报告；没有随包的 report.json。

**版本号（展示不含 `v`）**：五段 `yy.m.d.当日序号.总序号`；`versionCode` = 最后一段（总序号，KSU 靠它比新旧，单调递增）。日期按 UTC+8 取，免得 CI 在 UTC 下差一天。

- **号源 2026-10-14 由 `run_number` 改成 git 提交数**（依据 `selfs` `GLOBAL.md` `240a214`/`c5ac12d`，Qself/Gself/Selffont 三仓统一）：总序号 = head 提交在本仓历史里的位次 `git rev-list --count HEAD`；当日序号 = head 提交在当日（UTC+8，取号发生的这一刻）提交序列里的位次 `git rev-list --count --since=<当日0点 UTC+8> HEAD`。号源不挂 CI 运行、不挂工作流文件名、不挂事件类型，只挂本仓提交历史——`build.yml` 只接 `push`（不限分支，会话分支推送同样出包）与 `workflow_dispatch`；PR 校验是独立的 `pr-check.yml`（只接 `pull_request`），从不触碰取号。
- **总序号**：本仓全部提交数，同一提交重跑（重试、再 dispatch、PR 再触发、改工作流文件名）得到同一个号，天然幂等——旧口径（`run_number`）挂在 CI 运行上时，PR 运行吃号、改工作流文件名号回头、并发运行竞态出重复当日序号，这些问题挂在提交上后全部消失。
- **当日序号**：head 提交不是今天推的（重出旧提交的包）这个数天然是 0，不写 1 冒充当日首包，也不退化四段——号源挂在提交上后当日序号永远算得出来，五段恒定；四段只在本地手工省略 `--day` 时才会出现。
- **硬前提**：CI 里 `actions/checkout` 必须 `fetch-depth: 0`，浅克隆下 `git rev-list --count HEAD` 恒为 1，所有产物都会叫 `.1.1`。
- **本地不算号**：`--query-git` 现场跑本地 `git rev-list --count`，不查 CI 运行历史、不用 `gh`、不需要任何令牌；本地出包必须显式传齐 `--date/--build`（不传 `--day` 就是四段，`--day` 可以传 `0`），数的可追溯性由打包的人负责。
- `module/module.prop` 在仓库里保持 `version=dev` / `versionCode=0` 只是入库默认值，盖戳时被覆盖，自检核对盖戳格式与 versionCode 一致。

CI 拆成两个工作流：`.github/workflows/build.yml`（出包，只接 `push`[不限分支，会话分支推送同样出包，这是会话侧唯一能拿到真实可装产物的验证路径] / `workflow_dispatch`）跑自检 + 一次构建并取号出包上传模块包本身为 Actions artifact；`.github/workflows/pr-check.yml`（PR 校验，只接 `pull_request`）的 `selfcheck` job 只跑自检，不取号、不出包、不上传，但它的 `cleanup` job 会真删超量/违规的 artifact 与 run（见下）——两者是不同工作流文件，号源不挂工作流文件，PR 运行再多也不影响版本号（同一提交若共用一个工作流文件会被 push 与 pull_request 各出一次包，产出两个同名 artifact 互相覆盖，这是拆文件的现行理由，不再是旧口径下的「吃号」）；artifact 名 = `Selffont-<版本>`，**artifact 包内根目录就是 `module.prop`，网页下载下来可直接刷，不再 zip 套 zip**——构建仍先产出 `build/Selffont-<版本>.zip`，CI 解开后上传目录内容；上传前先核对产物名符合版本格式，`retention-days: 5` 只是时间兜底）。

清理逻辑只有一份脚本 `.github/scripts/cleanup.py`，两个工作流的 `cleanup` job 共用，**两处现在都真删**（`actions: write`，`CLEANUP_APPLY=true`）：`build.yml` 的 `cleanup` job 每次出包成功都跑，**不按分支限定**（2026-10-14 之前这里有 `github.ref == 'refs/heads/main'` 守卫，连会话分支出包的清理也一并砍掉，已删）；`pr-check.yml` 的 `cleanup` job 由同仓分支发起的 `pull_request` 事件触发——这类事件里 `GITHUB_TOKEN` 能拿到工作流声明的权限（只有 fork 发起的 PR 才受限只读），会话推送到同仓开的 PR 就会触发，是另一个会话侧真正够得着的真删入口，不是预演。两个 `cleanup` job 挂同一个 `concurrency` group（`selffont-artifacts`）串行；DELETE 失败按返回码分两条路（2026-10-14 教训，`act()` 曾不分原因一律降级，docstring 却声称有分级，已改）：403 这类权限缺口打 `::warning::` 降级为预演继续，不让 job 变红；403 以外的失败打 `::error::` 并让 job 当轮变红，不许吞掉。五条判据按固定顺序执行，前四条不豁免当日：**命名口径**（产物版本段数须等于顶部声明的 `env.SEGMENTS`）→ **来源**（`workflow_run` 事件是 `pull_request` 的产物一律删，这条留给拆分前的历史遗留）→ **重复当日序号**（同一天同一当日序号出现两次，保留总序号最大的）→ **号源口径**（2026-10-15 新增，依据 `selfs` `GLOBAL.md` `129a292`：产物名里的总序号必须等于该产物对应 run 的 head sha 的 `git rev-list --count <sha>`，本地现跑，不等即旧口径产物当轮删；sha 不在本地历史里就跳过这条、不当删除依据——两个 `cleanup` job 的 `actions/checkout` 因此都要 `fetch-depth: 0`）→ **数量**（当日之外每条序列 artifact 5 个、run 5 条，序列按工作流分开计，当日的不设上限——当日序号现在挂在提交上，删当日运行不再抽走计数基准）。**run 与 artifact 的承载关系**：删 run 连带删它的 artifact，承载被保留 artifact 的 run 不删、不计入 run 的数量上限；排序按 `run_started_at`，`id` 只作同刻 tiebreak。`selffont-` 前缀（不分大小写）只用于筛候选 artifact，归属再按 `workflow_run` 的 `repository_id` / `head_repository_id` 核验，归属不明的对象保留不删。**CI 出包 ≠ CI 发版**：不发 Release、不建正式 tag、不写正式 asset（本仓库现有 Release 数 = 0，规范上限 1；真要人工发布，发布后的数量清理由发布者做，CI 不拿 `contents` 写权限）；版本号由本地 `git rev-list --count` 现场算定，`actions: read` 已不需要。会话分支推送出包的 artifact 跟默认分支同一套命名口径、同一号源（提交数），不另立号段、不开豁免、不回溯删既存产物，由两个 `cleanup` job 按上述判据正常收口。

```sh
# build.yml 不接 pull_request,其运行取回来的就是出包运行;最近一次的 artifact 就是模块包本身:
# 下载下来直接刷,不用再解一层
RUN=$(gh api 'repos/Sumicya/Selffont/actions/workflows/build.yml/runs?per_page=20' \
  --jq '.workflow_runs[0].id')
set -- $(gh api "repos/Sumicya/Selffont/actions/runs/$RUN/artifacts" --jq '.artifacts[0] | "\(.id) \(.name)"')
curl -fL -H "Authorization: token $(gh auth token)" -o "$2.zip" \
  "https://api.github.com/repos/Sumicya/Selffont/actions/artifacts/$1/zip"
ls -l "$2.zip" && unzip -p "$2.zip" module.prop    # 约 100 MB 量级才正常
# 用 gh run download 的话记得 -D 指一个空目录:artifact 是目录内容,会摊开

# 查看滚动清理的现状(只读查询,这条命令本身不删):清理逻辑是 .github/scripts/cleanup.py,
# build.yml 与 pr-check.yml 的 cleanup job 都用 runner 自带、工作流声明的 actions: write
# 令牌执行真删,不是会话令牌或人工的事——会话令牌对本仓库 actions 写同样是 403(实测,能力按
# 权限类分不按仓库分,见本文件上方「清理逻辑」一段);pr-check.yml 的 cleanup job 由同仓 PR 的 pull_request
# 事件触发,会话推送到开着的 PR 就能让它真的跑一次删除,不只是打印预演
gh api --paginate repos/Sumicya/Selffont/actions/artifacts \
  --jq '.artifacts[] | "\(.created_at) \(.id) \(.name) \(.size_in_bytes)"'
gh api --paginate repos/Sumicya/Selffont/actions/workflows/build.yml/runs \
  --jq '.workflow_runs[] | "\(.created_at) \(.id) \(.run_number) \(.status)"'
```

## 安装 / 卸载

KSU 装 zip，重启（模块 ID `MFGA`；安装脚本替换设备实际会读的字体配置——AOSP 的 `font_fallback*.xml`、ColorOS 的 `fonts_base.xml` / `fonts_ule.xml`，库存 `fonts.xml` 与 `fonts_customization.xml` 都不碰；一份都没有的设备中止安装）。卸载 = KSU 删模块 + 重启。仓库不发 Release：zip 来自本地 `build.py` 或 CI 的 Actions artifact。

管理器安装：KernelSU → 模块 → 从存储安装 → 选解压出的 zip → 重启。

命令行安装（Termux / adb，需 root）：先把 zip 搬到 `/data/local/tmp` 再装——`ksud` 直接读 Termux 家目录或 `/sdcard` 路径常因挂载命名空间 / SELinux 报 `No such file or directory`：

```sh
ZIP=$(ls -t "$PWD"/Selffont-*.zip | head -1)            # 定位刚解出的模块 zip
ls -l "$ZIP" && unzip -l "$ZIP" | head -5               # 约 100 MB；根部有 module.prop 才对
su -c "cp '$ZIP' /data/local/tmp/selffont-module.zip"   # 搬进 root 能读的 /data/local/tmp
su -c 'ls -l /data/local/tmp/selffont-module.zip'       # 字节数应与上一步一致
su -c 'ksud module install /data/local/tmp/selffont-module.zip'
su -c 'rm -f /data/local/tmp/selffont-module.zip'
su -c reboot                                            # 或手动重启
```

装完字体没变时，按序查三条：管理器里模块已启用且已重启；`su -c 'for f in /system/etc/font_fallback.xml /system_ext/etc/fonts_base.xml /system_ext/etc/fonts_ule.xml; do [ -f "$f" ] && echo "$f Selffont=$(grep -c Selffont "$f")"; done'`——设备读了哪份，就该有哪份被换（ColorOS 只查后两行；全是 0 或文件不存在说明选错了配置文件）；KernelSU 需要挂载类元模块（metamodule）才能把模块内容挂进系统——缺了它模块装得上但不生效（`mount | grep MFGA` 能看到才说明挂上了）。

若 `cp` 被 SELinux 拦：先在 Termux 里 `cp "$ZIP" ~/storage/downloads/`（`termux-setup-storage` 给的软链），再 `su -c 'cp /sdcard/Download/<文件名> /data/local/tmp/'` 后照上装。

## 火狐

Gecko 不读系统的 `fonts.xml` 选家族：字体清单来自 Android 系统字体 API，选谁看它自己 `font.name-list.*` 里硬编码的**家族名**。所以字体装好了，Firefox 也不一定用——要单独接一次，走 GeckoView 官方的原生机制，不需要 LSPosed、不改 APK：

```sh
su -c 'sh /data/adb/modules/MFGA/firefox.sh'          # 接入
su -c 'sh /data/adb/modules/MFGA/firefox.sh remove'   # 退出
```

`firefox.sh` 只做两件事：把 `geckoview-config.yaml` 放到 `/data/local/tmp/org.mozilla.firefox-geckoview-config.yaml`，再把 Firefox 设成 Android「调试应用」（`am set-debug-app --persistent`，重启后仍在）——GeckoView 只在这两种情况下读那份配置。配置里每条首选项都只**插入**不清空，后面原样保留 Gecko 自己的回退链（整条覆盖会掐断回退，那才是缺字的来源）。谁排在最前，看这个泛型在系统里本来是什么字体：`sans-serif` / `serif` / `emoji` 本来就是主字体（`serif` 是旧数字字件、`sans-serif` 是度量空壳），文渊在最前是把火狐改掉的恢复回来；`monospace` / `cursive` / `fantasy` 本来是 Droid Sans Mono / Dancing Script / Coming Soon（`fonts.xml` 的 `monospace` / `cursive` / `casual`），**本来是什么字体就保持什么字体**，文渊只紧随其后兜这些字体没有的 CJK。

**花体 / 小型大写（Unicode 字符本身，如 𝓐𝓑𝓒、ᴀʙᴄ）**——这类字符不选字体，走逐字回退，而 Gecko 的逐字回退**不读 fonts.xml 顺序**（先按字符语言组查 `font.name-list.*`，再全清单乱序扫描），选中的兜底字体和系统不同 → 同一字符两副面孔。修法 = 让火狐的回退链与 fonts.xml 同序：

- 数学字母数字区（𝓐𝓑𝓒）的语言组是 `x-math`，Gecko 在 Android 的默认名单全是桌面数学字体（设备上没有）——配置补上 x-math 三条（前置文渊）；
- 其余语言组的名单，构建时把模块补充字库的**内部家族名按 fonts.xml 顺序**追加到每条 `font.name-list.*` 末尾（火狐只认字件内部名，构建期现场从基础包读取）；
- 配置是 `firefox.sh` 装的拷贝：**模块更新时 `customize.sh` 检测到已接入就按当前开关状态重生成**，不用记得重放 `firefox.sh`，也不会把你切过的网页字体开关覆盖掉。

**泛型与家族名的坑**（CSS 写法不同，路径完全不同）：

- 泛型关键字（`font-family: cursive/fantasy`，不带引号）：all.js 的 Android 段只有 `cursive.x-unicode/x-western` 默认、`fantasy` 一个都没有，zh/ja/ko 下解析成空字体组落平台默认——配置把 cursive/fantasy × 7 语言组补齐。
- 带引号的家族名（`"cursive"`、`"sans-serif-smallcaps"`）：走名字解析，而 Gecko 的字体清单只收**写进系统配置的字件**。曾试过给这些别名各发一枚「别名字件」（家族名 = 别名、无字形），2026-10-05 真机实测（OnePlus / ColorOS 16）**解析不到**：20 个空格的宽度与默认链完全相同，别名字件的 0.5em 空格没有出现。又因为每条 `font.name-list.*` 都被我们前置了文渊，命中与不命中最终渲染一致——既不可见也无收益，**已删除**（`build.py` 不再产别名字件、也无 `--no-alias-fonts` 开关）。
- 网页**自带的 webfont**（站内装饰字体、Google Fonts、图标字体）：不读系统清单，字体 pref 管不到，只有 `browser.display.use_document_fonts` 一个开关——**默认压成文渊**（全系统同一副面孔）。放行的两条路：打包时 `--keep-web-fonts`（当默认值烧进 zip），或运行时在 KernelSU 管理器里点模块的**「操作」按钮**切换（命令行等价 `su -c 'sh /data/adb/modules/MFGA/web-fonts.sh keep'`，状态存 `/data/local/tmp/selffont-web-fonts.state`）。放行后网页按自己的字体渲染、图标字体正常，代价是网页上的装饰字体不再是文渊；`web-fonts.sh status` 看当前状态。
- CSS `font-variant: small-caps` 由基础字体合成：基础字体是文渊，小型大写就是文渊。

验证：`logcat -s GeckoRuntime GeckoDebugConfig | grep -i 'config\|prefs'`，应出现 `Adding debug configuration from:` 与 `Adding prefs from debug config`。

emoji：Gecko 在 Android 上认的彩色字体是 `SamsungColorEmoji` / `Noto Color Emoji` / `Noto Color Emoji Flags`（对 emoji 表现字符它优先选带彩色的那张，所以前置不挡彩色）；包内字体到底覆盖到哪个码位，拿 fontTools 查 cmap 即可——先拿数据，再谈 Gecko。

## 装完自查（约一分钟）

1. 系统：设置里随便看几行字——字形变圆即生效；通知栏角标数字不再偏低/切下沿（度量归一修复的目标）。
2. 火狐：`logcat -s GeckoRuntime GeckoDebugConfig | grep -i 'config\|prefs'` 应有两行；没有就先跑 `firefox.sh`。
3. emoji：拿一个较新的 emoji 看是否彩色；想看包内覆盖上限，用 fontTools 查 cmap（没有随包报告——查 cmap 是一行的事）。
4. 复原：卸载 = KSU 删模块 + 重启，一切回到系统自带字体。

## 未验证项的真机清单

**已真机验证**（2026-10-05，一加 / ColorOS 16 / Android 16 / KernelSU）：① 系统字体生效——三份配置（`/system/etc/font_fallback.xml`、`/system_ext/etc/fonts_base.xml`、`/system_ext/etc/fonts_ule.xml`）替换后字形变圆，模块版本 `26.10.5.23.86`；② 火狐网页字体开关（运行时「操作」按钮 / `web-fonts.sh keep|block|toggle`）切换生效；③ 别名字件已实测**无效**并删除（见上「泛型与家族名的坑」）。**2026-10-07 装机核对（配置层已核对，渲染层未验证）**（同一台设备）：装「清掉 MiSans 引用（10-06）+ 卡开机修复 + 语言区改法 + 五个命名族恢复本来字体（10-07）」之后的构建，**正常开机、不再重启循环**，三条自查 **8 / 0 / 3** —— `grep -c Selffont /system_ext/etc/fonts_base.xml` = **8**（与构建期「主字体被 8 族引用：匿名回退区 + `serif` + CJK 语言区」逐项吻合）、`grep -ci misans` = **0**、`grep -aic mfga /proc/mounts` = **3**（模块已挂载）。**这三条只覆盖配置层**：证明设备上那份配置的内容符合构建预期、模块挂上了；**渲染层没有任何证据**——字形是否变圆、角标数字是否被切、等宽是否回到 Droid Sans Mono，都不在这三条命令的射程里，需要设备截图，取证命令与存放位置见 `docs/evidence/`。**仍无真机数据**：① 纯 AOSP（非 ColorOS）机器上的 `font_fallback.xml` 路径；② 三项只影响观感、不影响开机的观察——生僻字是否仍渲染成圆体（清掉 MiSans 后这些字改由补充字库接管）、终端 / 代码类 App 的等宽字体是否回到 Droid Sans Mono（不该是圆体）、WebView 的 `font-variant: small-caps` 会不会去查 `sans-serif-smallcaps`；③ artifact「包直出」格式实测用的是哪个包未记录（`.102` 旧格式解一层、`.103` 起直接刷，两者字体配置相同）。装上一分钟后按顺序看三条，任一条不对就按对应的回退走：

1. 基础项：系统字体变圆、角标数字正常 → 模块本身生效（ColorOS 上已通过；纯 AOSP `font_fallback.xml` 路径尚未在非 ColorOS 机器上验证）。
2. 火狐接入：`logcat -s GeckoRuntime GeckoDebugConfig | grep -i 'config\|prefs'` 出现 `Adding debug configuration from:` 与 `Adding prefs from debug config` 两行。
3. 网页字体（**已真机验证**）：开一个图标站点（如 FontAwesome 示例页）——**默认压掉**时图标会显示成方块/异常，这是预期代价；点管理器里模块的「操作」按钮切成「放行」（`web-fonts.sh status` 可核对），再重启火狐，图标恢复。两种表现都算「按设计工作」，选哪种看你要全系统同一副面孔还是保图标。

回退都不用卸载：开关随时可切；要回到旧行为就重新打包（`--keep-web-fonts`）→ KSU 装新 zip → 重启。

## 产物构成（为什么约 100 MB）

| 内容 | 大小量级 |
| --- | --- |
| 主字体（文渊圆体 VF，归一度量后的安装副本） | 约 46 MiB |
| 补充字库（`fonts.xml` 引用、基础包里有的那几个：Plangothic、Unicode*-New、NotoSansPro、ZDigit 等） | 约 54 MiB |
| 配置与脚本（`font_fallback.xml`、`customize.sh`、火狐配置） | 不到 0.1 MiB |

「去掉静态」只删掉了配置里的逐档展开（`fonts.xml` 的 18 个 `<font>` 节点，几 KB）——字体数据从来只带一份 VF，没有按字重复制过文件，所以体积不变。装完想自己看构成：`unzip -l Selffont-<版本>.zip | sort -k1 -nr | head -15`。

## 边界

- 只支持带 `font_fallback*.xml` 的设备（Android 15+）：装在没有该文件的机器上会中止安装。装机核对过：Android 16 / OnePlus / KernelSU 一台。其中**配置层有命令输出为证**（三份配置的 `grep -c`、`/proc/mounts`）；**渲染层只有 2026-10-05 当次目视，未留图像**（系统字形变圆、火狐网页字体开关切换生效都属这一类）；别名字件实验留下了可复核的量化依据（20 个空格宽度与默认链相同、0.5em 未出现），判定无效后已删除。其他平台自担风险。**未验证**：纯 AOSP 机器的配置路径、CJK 语言区改动——装机核对清单见「未验证项的真机清单」。
- 本仓库是 [MFGA](https://github.com/Numbersf/MakeFontsGreatAgain) 的 fork。上游领先的提交只动它自己的 Xposed 侧与文档（`fonts/`、`fonts.xml` 从 1717180003 起未变，已逐字节比对）：用 `-s ours` 记录了祖先关系（不再显示「落后」），但**不取它的代码**，只取字体资源（见 `LICENSES.md`）。
- `fonts.xml` 里的字体名是「设备自带 + 基础包补充」的并集：基础包只带设备没有的补充字库（Plangothic、天珩、Unicode 新平面、SourceSansPro、ZDigit 等），Noto 全套与其余 OEM 字体由设备提供，不打包（`MiSans` 不要，引用已在构建期清掉，见「字体」）。引用两边都没有的字体只会让该条目失效，不中断渲染、也没法在构建期判断——构建只打一行摘要，不出名单。
- 火狐的家族名单来自 Gecko 自己的 `all.js`（Android 段），随 Firefox 版本可能变；名单变了 `firefox.sh install` 重放一次即可，不匹配时 Gecko 只是回到自己的默认字体。
- MFGA 基础包只取字体资源，绝不执行其代码（归属见 `LICENSES.md`）。
- 主字体必须能被 fontTools 解析且含 `wght` 轴；`.ttf`/`.otf`/`.ttc` 之外的后缀、静态字体、缺空壳的基础包都直接拒绝。
