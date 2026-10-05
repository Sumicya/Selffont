# Selffont 项目规则

本文件承载本仓库常驻规则。全局工程规范以 Sumicya/selfs 的 `GLOBAL.md` 为唯一权威（第二十一版，2026-10-05）。
**本仓库上次同步 = 第二十一版**；发现落后就把落后点报给主人，并在本轮更新本文件。

## 全局规范同步（2026-10-05，第二十一版）

以下条目继承自 Sumicya/selfs 的 `GLOBAL.md`，在本仓库逐条落位：

- 任何本轮本地改动必须最终提交并推送到当前远端分支；任务结束时不得留下未提交或已提交但未推送的改动。
- CI 不得自动创建 Release、正式发行 tag 或正式 Release asset；发版必须先获得主人对项目、版本和触发条件的明确允许。
- 默认保留数：Actions artifact 保留最近 5 个（`retention-days: 5` 作时间兜底，上传步骤已带）；滚动清理按数量保留，不以过期代替。
- 滚动清理自第二十一版起默认启用（不需逐仓批准）：清理只删本项目明确标识的 artifact，不产生 Release、不改动最新对象，不等价于发版授权；清理 job 必须在默认分支的构建工作流里。
- 写权限最小化：写权限只在 `build.yml` 的 `cleanup` job（`actions: write`，只删 Actions artifact）；构建与 PR 检查 job 保持只读，写权限 job 不执行未信任 PR 的代码。
- 只做新包与不做降级：涉及平台新机制只实现新机制；改平台行为前先查上游并留证据；能明确失败则直接失败，删降级路径前确认最坏失败模式不是不可恢复。

- CI 出包与 CI 发版分开：有产物的项目必须用 `actions/upload-artifact` 出包（`name` = `<项目名>-<版本>`、`retention-days: 5`、`if-no-files-found: error`，push 与 PR 都照传）；CI 发版（Release / 正式 tag / 正式 asset）未授权、禁止自动执行。
- 规范自检不设工作流，由 agent 在会话中完成（读 `AGENTS.md` / `GLOBAL.md`、核指针与版本戳、核权限与禁发版）；「少流程」只允许砍重复的只读检查，不得砍构建、校验或 artifact 上传。
- CI 禁旧：runner 钉具体镜像（`ubuntu-24.04`，不用 `ubuntu-latest`）；Action 用现行主版本（`actions/checkout@v7`、`actions/setup-python@v7`、`actions/upload-artifact@v7`），出现弃用警告当轮升级。
- Arena 会话（强制）：主人当轮出现辱骂或同等强度的愤怒表达时，先输出不少于 1000 字的书面检讨（写清错在哪、违反哪条、为何做错、如何纠正、如何防再犯），再立刻继续办事，不另开一轮。

## 项目核对清单

- 默认分支：`main`；会话固定在工作分支上提交并推送，不直接推 `main`。
- 构建方式：本地 `python3 build.py`（唯一构建链，自检内建）。产物只带一份字体配置 `font_fallback.xml`（新语法 `supportedAxes`，Android 15+ 运行时实例化）；安装脚本替换设备实际会读的字体配置（AOSP 的 `font_fallback*.xml`；ColorOS 的 `/system_ext/etc/fonts_base.xml` / `fonts_ule.xml`——分区 `system` / `system_ext` / `product`，模块路径 `system/<分区>/etc`），库存 `fonts.xml` 不碰，一份可替换配置都没有的设备中止安装。输入侧不降级：静态主字体、缺空壳的基础包都直接拒绝。CI（`.github/workflows/build.yml`）跑自检 + 一次构建：push 与 PR 都把 zip 传成 Actions artifact（`name=Selffont-<版本>`、`retention-days: 5`、`if-no-files-found: error`），出包成功后自动滚动清理旧 artifact（保留最近 5 个）；**不发版、不写 Release**。
- 产物：模块 zip `Selffont-<版本>.zip`（约 100 MB = 主字体约 46 MiB + 补充字库约 54 MiB + 配置脚本；只带一份 VF，不按字重复制）；非发行版本叫 `Selffont.zip`。产物由本地 `build.py` 产出，CI 也产一份并传成 Actions artifact（push 与 PR 都传，取包命令见 README）；仓库不发 Release，文档里不写 Release 下载入口。
- Actions artifact：`build.yml` 出包（名如 `Selffont-<版本>`）并自动滚动清理，保留最近 5 个；筛选按 `selffont-` 前缀（不分大小写，含旧积压 `selffont-module`）、完整分页、删除前打印完整清单；要提前删可手动跑 README 的 `gh api -X DELETE`。
- 工作流写权限：`build.yml` 的 `cleanup` job（`actions: write`，只删 artifact）；其余一律只读；上传 artifact 不需要写权限。
- 版本来源：五段 `yy.m.d.当日序号.总序号`，展示版本不含 `v`，`versionCode` = 总序号。取数在仓库唯一构建工作流的运行历史里现场查（`build.py --query-github` 或 README 给的 `gh api` 查法），不在文档/代码里写死现值；仓库里的 `module/module.prop` 默认是**非发行版本** `version=dev` / `versionCode=0`。
- 计数口径：总序号 = 该工作流最近一次运行的 `run_number`（含 PR 运行，单调递增）；当日序号 = 当天（Asia/Shanghai）该工作流 `push` / `workflow_dispatch` 且已开始的运行数，PR 检查不计入。**取不到当日序号时退化写四段 `yy.m.d.总序号`**，原因见 README。
- 历史 tag：`v3.0.0`（0d9ba81，2026-09-26）、`v26.9.30.39`（215cf25，2026-09-29）属已下线的旧发版链，按规范默认保留，不追溯改名、不改写历史。
- 下载与安装：不发 Release。安装 = KernelSU 装本地构建的 zip + 重启；卸载 = KSU 删模块 + 重启；火狐接入 = `su -c 'sh /data/adb/modules/MFGA/firefox.sh'`。
- 术语表：模块 zip = KernelSU 模块包；基础包 = MFGA 补充字库 ZIP（`build.py` 现场读取）；主字体 = 文渊圆体 VF；别名字件 = 已删除的实验（家族名当字体的极小字件，真机实测 Gecko 清单不认，见 changelog）；网页字体开关 = 火狐的 `browser.display.use_document_fonts`（压 = 0，放行 = 加 `Selffont:keep` 标记注释）；pref 尾链 = 构建期把补充字库内部家族名按 fonts.xml 顺序追加到火狐 `font.name-list.*` 末尾。

## CI 权限与清理

- `build.yml`：`contents: read` + `actions: read`（只为读本工作流运行历史算版本号）；版本号在该 job 一处算定后写进产物元数据，构建配置只读它。出包用 `actions/upload-artifact`（push 与 PR 都传），上传不需要写权限。
- `build.yml` 的 `cleanup` job：唯一写权限（`actions: write`），`needs: build` 出包成功后串行执行；只删本项目 artifact（`selffont-` 前缀不分大小写），保留最近 5 个，完整分页、结构化字段、删除前打印完整清单；不跑未信任 PR 的代码，不碰 Release / tag / 历史 tag。
- 规范自检：不设工作流，由 agent 在会话中完成（读 `AGENTS.md` / `GLOBAL.md`、核指针与版本戳、核权限与禁发版）。
- 发版：本仓库没有 CI 发版流程（CI 发版未授权）；发版仍需主人对项目、版本、触发条件的明确允许。清理授权不等于发版授权。

- 下个会话待办：见 `TODO.md`（自制圆体主字体，类筑紫 A 丸ゴシック；本会话已明确不做，开工前先提问核对）。

## 项目取舍（与规范的关系）

- 本项目 CI 只出包（Actions artifact）、不发版，因此「在发布工作流一处算定」落在唯一构建工作流 `Build` 上：日期与两个序号由 `build.py --query-github` 现场查运行历史一次取齐；本地打包可手工传 `--build` / `--day` / `--date`，或直接 `--query-github`。
- 网页字体默认压属激进修复：**已真机验证**（OnePlus / ColorOS 16，运行时开关切换生效）；别名字件实验**已删除**（真机实测 Gecko 字体清单不含未写进系统配置的字件，别名解析不到，且命中与否最终都渲染文渊）。别名字件只有构建期开关 `--no-alias-fonts`；网页自带字体是构建期默认值（`--keep-web-fonts` 放行）+ 运行时覆盖（KernelSU 管理器「操作」按钮 = `module/action.sh`，等价 `web-fonts.sh keep|block|toggle`，状态文件在 `/data/local/tmp/selffont-web-fonts.state`），`customize.sh` / `firefox.sh` 重生成配置副本时按状态走，不覆盖运行时的选择。
- 第二十一版承继的「只做新包与不做降级」在本仓库落成：只投放 `font_fallback*.xml`（新语法 `supportedAxes`），静态主字体、缺空壳的基础包、模板缺关键行都直接失败，设备没有 `font_fallback*.xml` 时中止安装；改平台行为前先查上游并留证据（近例：`font_fallback.xml` 有 AOSP 15 分支与官方文档佐证，未真机验证的改动在 changelog 标「未验证」并留回退开关）。
- 边界与限制以 README 为准；本文件的清单与 README 冲突时，先按 README 的事实改本文件。
