# Selffont

Android 个人字体模块：**文渊圆体 v1.010 可变字体**（OFL，活跃维护；一个 VF 文件内含 `wght` 100–900 + `ital` 真字重）接管系统字体家族。原生 `fonts.xml` 挂载，模块即全部交付，无伴侣应用。模块 zip 由本地构建产出，CI 只做校验。

## 字体

照搬[文渊圆体](https://github.com/takushun-wu/WenYuanFonts/releases/tag/v1.010)：字形、cmap、可变轴逐字节不动（构建期逐字形守卫），安装副本只动三处——

1. 竖直行度量归一到基础包的 Roboto 空壳（真机验证：修角标数字偏低/切下沿）；
2. 剪除映射到空白字形的码位（上游声称覆盖但字形空白，会吞掉回退链）；
3. 按 OFL 保留名规则把内部家族名改成 **Selffont Rounded SC VF**。

字重阶梯现场从字体的 `wght`/`ital` 轴读取（越界夹取）；静态字体也能打包（全档同文件，粗体交给系统合成）。

模块带**两份同源的字体配置**，安装时按目标文件名投放：

- `fonts.xml`（legacy 解析目标）：主字体逐档展开成 18 条静态条目（每档一条 `axis` 子节点）；
- `font_fallback.xml`（Android 15+ 的新配置）：主字体一条 `supportedAxes="wght,ital"`，由系统按请求的字重 / 斜体**运行时实例化**——任意字重精确插值，不再落到最近的离散档；
- `font_fallback*.xml`（含厂商的 `font_fallback_cjkvf.xml` 等）一律放新语法，其余 `font*.xml` 放 legacy 展开；官方要求两个文件保持同步，所以它们由 `build.py` 从同一棵家族树生成（自检断言两边的接管家族集合一致）。
- 静态主字体没有 `wght`/`ital` 轴：新语法这一侧也退回逐档展开（`supportedAxes` 只认 `wght` / `wght,ital`）。另外附带几枚**别名字件**（只有家族名、没有字形的极小字体，合计约 15 KB）：Gecko 只认字件内部家族名，系统 `fonts.xml` 里的别名它看不见，带引号调用（如 `font-family: "sans-serif-smallcaps"`）会落到平台默认字体；同名字件让 Gecko 命中后逐字回退到文渊。不想要就 `--no-alias-fonts`。

## 构建

整个构建链是一个 Python 文件，自检内建其中：

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python build.py --check                  # 自检:无框架、无夹具,不下载不打包
.venv/bin/python build.py --query-github           # 正式打包:现场查运行历史取数并盖戳
.venv/bin/python build.py --build 47 --day 3       # 或手工传序号(离线;--date 可另给)
.venv/bin/python build.py --font 文件或URL --base 本地ZIP或URL
.venv/bin/python build.py --no-alias-fonts         # 不打火狐别名字件（回退旧行为）
.venv/bin/python build.py --keep-web-fonts         # 放行网页自带字体（默认压成文渊）
```

产物名跟版本走：`build/Selffont-<版本>.zip`；没盖戳的非发行版本叫 `build/Selffont.zip`。默认来源与提示性哈希钉在 `build.py` 顶部（哈希漂移只警告，不拦构建）；下载缓存在 `build/cache/`，删掉即重新下载。构建 stdout 就是构建报告；没有随包的 report.json。

**版本号（五段，展示不含 `v`）**:`yy.m.d.当日序号.总序号`（第四段 = 当日序号，第五段 = 总序号），`versionCode` = 第五段（总序号，KSU 靠它比新旧，单调递增）。日期按 UTC+8 取，免得 CI 在 UTC 下差一天。

- 计数对象 = 仓库唯一构建工作流 `Build Selffont`（`.github/workflows/build.yml`）的运行历史，现场查、不写死现值；取数在这一次运行里算定，构建只用算出的三个值。
- 总序号 = 该工作流最近一次运行的 `run_number`；当日序号 = 当天（Asia/Shanghai）该工作流 `push` / 手动触发且已开始的运行数，**PR 检查不计入**。
- 本地照抄能跑的查法（与 `--query-github` 同一口径）：

```sh
gh api 'repos/Sumicya/Selffont/actions/workflows/build.yml/runs?per_page=1' --jq '.workflow_runs[0].run_number'
gh api --paginate 'repos/Sumicya/Selffont/actions/workflows/build.yml/runs?per_page=100' --jq '.workflow_runs[]' \
  | python3 -c 'import json,sys;from datetime import datetime,timezone,timedelta;c=timezone(timedelta(hours=8));d=datetime.now(c).replace(hour=0,minute=0,second=0,microsecond=0);print(sum(1 for l in sys.stdin if (r:=json.loads(l))["event"] in ("push","workflow_dispatch") and datetime.fromisoformat(r["created_at"].replace("Z","+00:00"))>=d))'
```

- 取不到当日序号时**退化写四段** `yy.m.d.总序号`（规范允许；本项目没有发布型 CI，当日序号只能在运行历史里查，查不到就不编数）。两个数都取不到就不盖戳：`module/module.prop` 是**非发行默认** `version=dev` / `versionCode=0`，自检核对盖戳格式与 versionCode 一致。

CI（`.github/workflows/build.yml`）只做校验（自检 + 一次带版本号的验证性构建）：**不发版、不上传 artifact、不写 Release**；版本号由 `actions: read` 现场查运行历史算定。旧体系留下的 artifact 积压用 `cleanup.yml` 清（手动触发，保留最近 5 个）：

```sh
gh workflow run cleanup.yml -f apply=false          # 干跑:只打印将保留与将删除的清单
gh workflow run cleanup.yml -f apply=true           # 真删(需 actions: write)
gh api repos/Sumicya/Selffont/actions/artifacts --jq '.total_count'   # 核对剩余数量
```

## 安装 / 卸载

KSU 装 zip，重启（模块 ID `MFGA`；安装脚本整份替换系统全部 `font*.xml`，不碰 `fonts_customization.xml`）。卸载 = KSU 删模块 + 重启。仓库不发 Release，也不提供 Release 下载入口——zip 就是本地 `build.py` 的产物。

## 火狐

Gecko 不读系统的 `fonts.xml` 选家族：字体清单来自 Android 系统字体 API，选谁看它自己 `font.name-list.*` 里硬编码的**家族名**。所以字体装好了，Firefox 也不一定用——要单独接一次，走 GeckoView 官方的原生机制，不需要 LSPosed、不改 APK:

```sh
su -c 'sh /data/adb/modules/MFGA/firefox.sh'          # 接入
su -c 'sh /data/adb/modules/MFGA/firefox.sh remove'   # 退出
```

`firefox.sh` 只做两件事：把 `geckoview-config.yaml` 放到 `/data/local/tmp/org.mozilla.firefox-geckoview-config.yaml`，再把 Firefox 设成 Android「调试应用」（`am set-debug-app --persistent`，重启后仍在）——GeckoView 只在这两种情况下读那份配置。配置里每条首选项都是**前置**文渊、后面原样保留 Gecko 自己的回退链；整条覆盖会掐断回退，那才是缺字的来源。

**花体 / 小型大写（Unicode 字符本身，如 𝓐𝓑𝓒、ᴀʙᴄ）**——这类字符不选字体，走逐字回退，而 Gecko 的逐字回退**不读 fonts.xml 顺序**（先按字符语言组查 `font.name-list.*`，再全清单乱序扫描），选中的兜底字体和系统不同 → 同一字符两副面孔。修法 = 让火狐的回退链与 fonts.xml 同序：

- 数学字母数字区（𝓐𝓑𝓒）的语言组是 `x-math`,Gecko 在 Android 的默认名单全是桌面数学字体（设备上没有）——配置补上 x-math 三条（前置文渊）；
- 其余语言组的名单，构建时把模块补充字库的**内部家族名按 fonts.xml 顺序**追加到每条 `font.name-list.*` 末尾（火狐只认字件内部名，构建期现场从基础包读取）；
- 配置是 `firefox.sh` 装的拷贝：**模块更新时 `customize.sh` 检测到已接入就按当前开关状态重生成**，不用记得重放 `firefox.sh`，也不会把你切过的网页字体开关覆盖掉。

**泛型与家族名的坑**（CSS 写法不同，路径完全不同）：

- 泛型关键字（`font-family: cursive/fantasy`，不带引号）：all.js 的 Android 段只有 `cursive.x-unicode/x-western` 默认、`fantasy` 一个都没有，zh/ja/ko 下解析成空字体组落平台默认——配置把 cursive/fantasy × 7 语言组补齐。
- 带引号的家族名（`"cursive"`、`"sans-serif-smallcaps"`）：走名字解析，而 Gecko 清单只收**字体文件内部家族名**,fonts.xml 别名进不去。本轮改成给这些别名各发一枚**别名字件**（家族名 = 别名、无字形，合计约 15 KB）：Gecko 命中后逐字回退，按上面的名单落到文渊。**未在真机验证**；要退回旧行为，打包时加 `--no-alias-fonts`。
- 网页**自带的 webfont**（站内装饰字体、Google Fonts、图标字体）：不读系统清单，字体 pref 管不到，只有 `browser.display.use_document_fonts` 一个开关——**默认压成文渊**（全系统同一副面孔）。放行的两条路：打包时 `--keep-web-fonts`（当默认值烧进 zip），或运行时在 KernelSU 管理器里点模块的**「操作」按钮**切换（命令行等价 `su -c 'sh /data/adb/modules/MFGA/web-fonts.sh keep'`，状态存 `/data/local/tmp/selffont-web-fonts.state`）。放行后网页按自己的字体渲染、图标字体正常，代价是网页上的装饰字体不再是文渊；`web-fonts.sh status` 看当前状态。
- CSS `font-variant: small-caps` 由基础字体合成：基础字体是文渊，小型大写就是文渊。

验证：`logcat -s GeckoRuntime GeckoDebugConfig | grep -i 'config\|prefs'`，应出现 `Adding debug configuration from:` 与 `Adding prefs from debug config`。别名字件的真机验证：开一个用 `font-family: "sans-serif-smallcaps"` 的测试页，字形应是文渊而非 Roboto；若出现豆腐块，加 `--no-alias-fonts` 重新打包即可回到旧行为。

emoji:Gecko 在 Android 上认的彩色字体是 `SamsungColorEmoji` / `Noto Color Emoji` / `Noto Color Emoji Flags`（对 emoji 表现字符它优先选带彩色的那张，所以前置不挡彩色）；包内字体到底覆盖到哪个码位，拿 fontTools 查 cmap 即可——先拿数据，再谈 Gecko。

## 装完自查（约一分钟）

1. 系统：设置里随便看几行字——字形变圆即生效；通知栏角标数字不再偏低/切下沿（度量归一修复的目标）。
2. 火狐：`logcat -s GeckoRuntime GeckoDebugConfig | grep -i 'config\|prefs'` 应有两行；没有就先跑 `firefox.sh`。
3. emoji：拿一个较新的 emoji 看是否彩色；想看包内覆盖上限，用 fontTools 查 cmap（没有随包报告——查 cmap 是一行的事）。
4. 复原：卸载 = KSU 删模块 + 重启，一切回到系统自带字体。

## 未验证项的真机清单

别名字件与网页字体默认压是本轮新改，**没有真机数据**。装上一分钟后按顺序看这四条，任一条不对就按对应的回退走：

1. 基础项：系统字体变圆、角标数字正常 → 模块本身生效（旧结论，先确认这条）。
2. 火狐接入：`logcat -s GeckoRuntime GeckoDebugConfig | grep -i 'config\|prefs'` 出现 `Adding debug configuration from:` 与 `Adding prefs from debug config` 两行。
3. 别名字件：开一个测试页写 `font-family: "sans-serif-smallcaps"`（或 `"cursive"`），字形应是文渊的圆体；若出现豆腐块或方框，改用 `--no-alias-fonts` 重新打包。
4. 网页字体：开一个图标站点（如 FontAwesome 示例页）——**默认压掉**时图标会显示成方块/异常，这是预期代价；点管理器里模块的「操作」按钮切成「放行」（`web-fonts.sh status` 可核对），再重启火狐，图标应恢复。两种表现都算「按设计工作」，选哪种看你要全系统同一副面孔还是保图标。

回退都不用卸载：开关随时可切；要回到旧行为就重新打包（`--no-alias-fonts` / `--keep-web-fonts`）→ KSU 装新 zip → 重启。

## 边界

- 真机验证过：Android 16 / OnePlus / KernelSU 一台，其他平台自担风险。本轮的别名字件与网页字体默认压是**未验证**改动：装机核对清单见「未验证项的真机清单」。
- 本仓库是 [MFGA](https://github.com/Numbersf/MakeFontsGreatAgain) 的 fork。上游领先的提交只动它自己的 Xposed 侧与文档（`fonts/`、`fonts.xml` 从 1717180003 起未变，已逐字节比对）：用 `-s ours` 记录了祖先关系（不再显示"落后"），但**不取它的代码**，只取字体资源（见 `LICENSES.md`）。
- `fonts.xml` 里的字体名是「设备自带 + 基础包补充」的并集：基础包只带设备没有的补充字库（Plangothic、天珩、Unicode 新平面、SourceSansPro、ZDigit 等），Noto 全套与 OEM 字体（如 MiSans）由设备提供，不打包。引用两边都没有的字体只会让该条目失效，不中断渲染、也没法在构建期判断——构建只打一行摘要，不出名单。
- 火狐的家族名单来自 Gecko 自己的 `all.js`（Android 段），随 Firefox 版本可能变；名单变了 `firefox.sh install` 重放一次即可，不匹配时 Gecko 只是回到自己的默认字体。
- MFGA 基础包只取字体资源，绝不执行其代码（归属见 `LICENSES.md`）。
- 主字体必须能被 fontTools 解析；`.ttf`/`.otf`/`.ttc` 之外的后缀直接拒绝。
