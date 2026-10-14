# Selffont 项目规则

本文件承载本仓库常驻规则。全局工程规范以 Sumicya/selfs 的 `GLOBAL.md` 为唯一权威（该仓本身不带版本号，规范以其默认分支现文为准）。发现本仓落后就把落后点报给主人，并在本轮更新本文件。

**2026-10-14 本轮同步**：总序号改用 `run_number` 直接计数（不再查历史成功出包数），当日序号改用「head 提交在当日默认分支提交序列的位次」（取不到就退化四段，不再是「三段缺一不可」）；`build.py` 与自检已按新口径改完，9 项自检全部通过。`build.yml` 的 `cleanup` job 已补上删除工作流运行记录（保留最近 5 条），此前记录的落位缺口已修复。本仓库目前没有记录过 `RUN_NUMBER_BASELINE`（没发生过 workflow 重建），总序号直接等于 `run_number` 原值。

## 全局规范（不抄条文，只记落位）

`GLOBAL.md` 的条文不抄进本文件——本仓库怎么落位见下面「项目核对清单」「CI 权限与清理」「项目取舍」三节；冲突时以 `GLOBAL.md` 为准并当轮更新本文件。四条不在那三节里、必须常驻的：

- **改动落地**：任何本轮本地改动必须最终提交并推送到当前远端分支，任务结束不留未提交或未推送的改动。
- **分支**：会话固定在工作分支提交并推送，不直接推 `main`；旧会话分支（PR 已合并）按要求删除，删前确认内容已进 `main`，未进的先带过来。
- **Arena 会话**：主人当轮出现辱骂或同等强度的愤怒表达时，先输出不少于 1000 个汉字的书面检讨（错在哪、违反哪条、为何做错、如何纠正、如何防再犯），每满 100 个汉字标 `【累计100字】`、`【累计200字】` 递增，末尾不足百字注明实际总数；随后立刻继续办事，不另开一轮。
- **CI 禁旧**：runner 钉具体镜像（`ubuntu-24.04`，不用 `ubuntu-latest`）；Action 用现行主版本（2026-10-10 核对 `checkout` / `setup-python` / `upload-artifact` 都是 v7），出现弃用警告当轮升级。


## 项目核对清单

- 默认分支：`main`。远端分支只留 `main` 与当前会话分支；PR 合并后删掉旧会话分支（主人 2026-10-06 明确要求，覆盖此前「保留分支」的做法）。
- 构建方式：本地 `.venv/bin/python build.py`（唯一构建链，自检内建，9 项）。产物只带一份字体配置 `font_fallback.xml`（新语法 `supportedAxes`，Android 15+ 运行时实例化）；安装脚本替换设备实际会读的字体配置（AOSP 的 `font_fallback*.xml`；ColorOS 的 `/system_ext/etc/fonts_base.xml` / `fonts_ule.xml`——分区 `system` / `system_ext` / `product`，模块路径 `system/<分区>/etc`），库存 `fonts.xml` 不碰，一份可替换配置都没有的设备中止安装。输入侧不降级：静态主字体、缺空壳的基础包都直接拒绝。
- **缺字回退分两个区**（AOSP `font_fallback.xml` 头注：默认家族 / 命名家族 / locale fallback family 三类，缺字按「完整 BCP-47 标签 → 仅语言 → 顺序」匹配）：默认区放一条匿名主字体家族紧随默认家族；**中日韩语言区（`zh` / `zh-Hans` / `zh-Hant,zh-Bopo` / `ja` / `ko`…）必须自带主字体**（前置，区内原有 `NotoSansCJK` 等字件留在后面，覆盖只加不减）——只往默认区插一条时，中文场景缺字会先在语言区命中厂商字体，主字体轮不到（旧实现整族删掉了 5 个 CJK 语言区，2026-10-06 修正）。非 CJK 语言区（`und-Arab` 等）与 emoji 区（`und-Zsye`）逐字不动，自检逐条比对。
- 不要的厂商字体：`MiSans`（主人 2026-10-06 明确不喜欢）。构建期把配置里的 `MiSansL3.otf` 引用、标注它的注释、以及火狐名单里的 `MiSans VF` / `MiSans TC` 等一并清掉；清空的家族节点删除，不留空节点。清掉后中文缺字由默认区的补充字库接管（覆盖靠基础包，不靠厂商字体）；自检有**字面**断言（`"MiSans" not in xml`），改匹配式也绕不过去。
- 产物：模块 zip `Selffont-<五段版本>.zip`（约 100 MB = 主字体约 46 MiB + 补充字库约 54 MiB + 配置脚本；只带一份 VF，不按字重复制）。产物由本地 `build.py` 产出，CI 也产一份并传成 Actions artifact（push 与 PR 都传，取包命令见 README）；仓库不发 Release，文档里不写 Release 下载入口。
- Actions artifact：`build.yml` 出包（名 = `Selffont-<五段版本>`，上传前核对产物名符合五段格式）并自动滚动清理，跨分支跨事件合计保留最近 5 个；筛选按 `selffont-` 前缀（不分大小写，含旧积压 `selffont-module`），归属按 `workflow_run` 的 `repository_id` / `head_repository_id` 核验，归属不明保留，完整分页、删除前打印完整清单、删完复核超限报错；要提前删可手动跑 README 的 `gh api -X DELETE`。
- Release：本仓库现有 **0 个**（2026-10-06 现场核）；CI 不发版也不删 Release，清理 job 只读打印数量并在超过 1 个时告警。获准人工发布时，发布后的「只留最近 1 个 + 清理其专属关联 tag」由发布者做（CI 不拿 `contents` 写权限）。
- 工作流写权限：`build.yml` 的 `cleanup` job（`actions: write`，删 artifact 与 build.yml 自己的运行记录）；其余一律只读；上传 artifact 不需要写权限。
- 版本来源：五段 `yy.m.d.当日序号.总序号`，当日序号取不到时退化四段 `yy.m.d.总序号`；展示版本不含 `v`，`versionCode` = 总序号。取数现场查运行历史（`build.py --query-github`），不在文档/代码里写死现值；`--query-github` 与手工 `--date/--day/--build` 不混用。仓库里的 `module/module.prop` 入库值是 `version=dev` / `versionCode=0`（只是入库默认，盖戳时被覆盖）。
- 计数口径（实现在 `build.py`，自检断言覆盖）：**总序号** = 本次 run 的 `run_number`（含失败与 PR，取自运行上下文，不查历史），按 `RUN_NUMBER_BASELINE`（见下）相减；`run_attempt` 不影响 `run_number`，重试天然复用同一个号，不需要额外处理。**当日序号** = 本次 run 的 head 提交（`GITHUB_SHA`）在当日（UTC+8）默认分支提交序列里的位次（查 `GET /commits?sha=main&since=...&until=...`，时间串用 `Z` 后缀，`+00:00` 在查询串里会被当空格转义移位）；head 不在默认分支历史里（PR 运行的常态）就是 `None`，版本号退化成四段，日志写明原因。日期 = `created_at` 换算 UTC+8 的 `yy.m.d`（月日不补零）。
- `RUN_NUMBER_BASELINE`：workflow 重建导致 `run_number` 号段跳变时，把重建前的最大号写成本文件里的一行 `RUN_NUMBER_BASELINE = N`，总序号相应减去 N；**本仓库目前没有这一行**（没发生过重建），总序号就是 `run_number` 原值（2026-10-14 核实：最新 run_number = 115，连续无跳变）。
- 本地序号规则：本地 `build.py` **不自己算号**，必须显式传 `--date/--day/--build`（不传 `--day` 就是四段），三个数由打包的人负责可追溯；`--query-github` 只在 CI 里能用，环境里没有 `GITHUB_RUN_ID` 直接报错——不退到「最近一次运行」口径，也不拿当前时间冒充 CI 计数。
- **验证表述分三层，各留各的证据**：配置层（设备上的配置内容、模块是否挂载，证据 = 命令输出）、构建层（打包器行为与产物命名，证据 = `--check` 与 CI run 号）、渲染层（屏幕上的字形、版面、字重，证据 = **截图 png**）。三层不许合并成一句「真机验证通过」；写「已验证」必须能指到 `docs/evidence/` 下的具体文件或某条命令输出，指不到就写「推断」或「未验证」。渲染层证据只能来自设备（沙箱取不到主字体发布资产，GitHub Release 资产会跳转到 `release-assets.githubusercontent.com`，不在沙箱允许访问的主机名单里，握手即断；仓库内 `vf/*.ttf` 这类直接提交的 git blob 可以用 `git/blobs` API 取），取证命令与当前缺口清单见 `docs/evidence/`。
- 历史 tag：`v3.0.0`（0d9ba81，2026-09-26）、`v26.9.30.39`（215cf25，2026-09-29）属已下线的旧发版链，按规范默认保留，不追溯改名、不改写历史。
- 下载与安装：不发 Release。安装 = KernelSU 装本地构建或 CI artifact 的 zip + 重启；卸载 = KSU 删模块 + 重启；火狐接入 = `su -c 'sh /data/adb/modules/MFGA/firefox.sh'`。
- 术语表：模块 zip = KernelSU 模块包；基础包 = MFGA 补充字库 ZIP（`build.py` 现场读取）；主字体 = 文渊圆体 VF；默认区 = 不带 `lang` 的匿名家族按文件顺序组成的缺字回退列表；语言区 = 带 `lang` / `variant` 的 locale fallback family（按语言标签优先匹配）；网页字体开关 = 火狐的 `browser.display.use_document_fonts`（压 = 0，放行 = 加 `Selffont:keep` 标记注释）；pref 尾链 = 构建期把补充字库内部家族名按 fonts.xml 顺序追加到火狐 `font.name-list.*` 末尾。

## CI 权限与清理

- `build.yml`：`contents: read` + `actions: read`（只为读本工作流运行历史算版本号）；版本号在该 job 一处算定后写进产物元数据，构建配置只读它。出包用 `actions/upload-artifact`（push 与 PR 都传），上传不需要写权限。
- `build.yml` 的 `cleanup` job：唯一写权限（`actions: write`，删 artifact 与运行记录，`contents` 保持只读——本仓库 Release 数为 0 且 CI 不发版，用不上 `contents: write`，按最小化不申请），`needs: build` 出包成功后串行执行，**只在默认分支 `main` 上跑**（写权限只给可信的默认分支构建 job；PR 的合并 ref 与其他分支的代码都不可信）。只删本项目 artifact（前缀筛候选 + `workflow_run` 核验归属）与 `build.yml` 自己的运行记录（按 `run_number` 排序，跳过仍在跑的），各自跨分支跨事件合计保留最近 5 个，完整分页、结构化字段、删除前打印完整清单、删完复核；不碰 Release / tag / 历史 tag。**代价**：只在分支上推送时清理不触发，artifact/运行记录会暂时超过 5 个，由下一次 `main` 构建收口，急用按 README 的 `gh api -X DELETE` 手动删。
- 规范自检：不设工作流，由 agent 在会话中完成（读 `AGENTS.md` / `GLOBAL.md`、核指针与版本戳、核权限与禁发版）。
- 发版：本仓库没有 CI 发版流程（CI 发版未授权）；发版仍需主人对项目、版本、触发条件的明确允许。清理授权不等于发版授权。

- 下个会话待办：见 `TODO.md`（自制圆体主字体，类筑紫 A 丸ゴシック；开工前先提问核对）。

## 项目取舍（与规范的关系）

- 本项目 CI 只出包（Actions artifact）、不发版，因此「在一个来源固定日期与两个序号」落在唯一构建工作流 `Build` 上：CI 锚定本次运行身份取数（`build.py --query-github` 读 `GITHUB_RUN_ID` / `GITHUB_RUN_ATTEMPT`），本地打包必须手工传 `--date/--day/--build`。
- 网页字体默认压属激进修复：**已真机验证**（OnePlus / ColorOS 16，运行时开关切换生效）；别名字件实验**已删除**（真机实测 Gecko 字体清单不含未写进系统配置的字件，别名解析不到，且命中与否最终都渲染文渊），构建期开关 `--no-alias-fonts` 也随之删除。网页自带字体是构建期默认值（`--keep-web-fonts` 放行）+ 运行时覆盖（KernelSU 管理器「操作」按钮 = `module/action.sh`，等价 `web-fonts.sh keep|block|toggle`，状态文件在 `/data/local/tmp/selffont-web-fonts.state`），`customize.sh` / `firefox.sh` 重生成配置副本时按状态走，不覆盖运行时的选择。
- 「只做新包与不做降级」（GLOBAL.md「先进性」要领）在本仓库落成：只投放 `font_fallback*.xml`（新语法 `supportedAxes`），静态主字体、缺空壳的基础包、模板缺关键行、版本数据不全都直接失败，设备没有 `font_fallback*.xml` 时中止安装；改平台行为前先查上游并留证据（近例：语言区优先于默认区顺序，依据 AOSP `font_fallback.xml` 头注与 `source.android.com/docs/core/fonts/custom-font-fallback`；未真机验证的改动在 changelog 标「未验证」并留回退开关）。
- 边界与限制以 README 为准；本文件的清单与 README 冲突时，先按 README 的事实改本文件。
