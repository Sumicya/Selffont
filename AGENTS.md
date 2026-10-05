# Selffont 项目规则

本文件承载本仓库常驻规则。全局工程规范以 Sumicya/selfs 的 `GLOBAL.md` 为唯一权威（第十七版，2026-10-05）。
**本仓库上次同步 = 第十七版**；发现落后就把落后点报给主人，并在本轮更新本文件。

## 全局规范同步（2026-10-05，第十七版）

以下条目继承自 Sumicya/selfs 的 `GLOBAL.md`，在本仓库逐条落位：

- 任何本轮本地改动必须最终提交并推送到当前远端分支；任务结束时不得留下未提交或已提交但未推送的改动。
- CI 不得自动创建 Release、正式发行 tag 或正式 Release asset；发版必须先获得主人对项目、版本和触发条件的明确允许。
- 默认保留数：Release 1 个、关联 tag 1 个、Actions artifact 5 个（artifact 由 `retention-days: 5` 作时间兜底，上传步骤已带上；2026-10-05 主人精简流程，不设独立清理工作流）。
- 自动清理与发版授权分离：清理只按授权范围删本项目明确标识的对象，不产生新 Release，不改动新 Release 的资产，不等价于发版授权。
- 写权限最小化：本项目所有工作流只读（没有写权限 job）；PR 检查与构建 job 都不持有写权限。
- 只做新包与不做降级：涉及平台新机制只实现新机制；改平台行为前先查上游并留证据；能明确失败则直接失败，删降级路径前确认最坏失败模式不是不可恢复。

## 项目核对清单

- 默认分支：`main`；会话固定在工作分支上提交并推送，不直接推 `main`。
- 构建方式：本地 `python3 build.py`（唯一构建链，自检内建）。产物只带一份字体配置 `font_fallback.xml`（新语法 `supportedAxes`，Android 15+ 运行时实例化）；安装脚本只替换系统的 `font_fallback*.xml`，库存 `fonts.xml` 不碰，没有该文件的设备中止安装。输入侧不降级：静态主字体、缺空壳的基础包都直接拒绝。CI（`.github/workflows/build.yml`）跑自检 + 一次构建：非 PR 运行把 zip 传成 Actions artifact（名 = 产物名去 `.zip`，`retention-days: 5`），PR 运行只校验；**不发版、不写 Release**（上传 artifact 不在禁用范围内）。
- 产物：模块 zip `Selffont-<版本>.zip`（约 100 MB）；非发行版本叫 `Selffont.zip`。产物由本地 `build.py` 产出，CI 非 PR 运行也产一份并传成 Actions artifact（取包命令见 README）；仓库不发 Release，文档里不写 Release 下载入口。
- Actions artifact：`build.yml` 非 PR 运行上传模块 zip（名如 `Selffont-<版本>`，`retention-days: 5`）；不设数量清理工作流（2026-10-05 主人精简流程），要提前删就手动跑 README 的 `gh api -X DELETE` 命令。
- 工作流写权限：无（全部只读）；上传 artifact 不需要写权限。
- 版本来源：五段 `yy.m.d.当日序号.总序号`，展示版本不含 `v`，`versionCode` = 总序号。取数在仓库唯一构建工作流的运行历史里现场查（`build.py --query-github` 或 README 给的 `gh api` 查法），不在文档/代码里写死现值；仓库里的 `module/module.prop` 默认是**非发行版本** `version=dev` / `versionCode=0`。
- 计数口径：总序号 = 该工作流最近一次运行的 `run_number`（含 PR 运行，单调递增）；当日序号 = 当天（Asia/Shanghai）该工作流 `push` / `workflow_dispatch` 且已开始的运行数，PR 检查不计入。**取不到当日序号时退化写四段 `yy.m.d.总序号`**，原因见 README。
- 历史 tag：`v3.0.0`（0d9ba81，2026-09-26）、`v26.9.30.39`（215cf25，2026-09-29）属已下线的旧发版链，按规范默认保留，不追溯改名、不改写历史。
- 下载与安装：不发 Release。安装 = KernelSU 装本地构建的 zip + 重启；卸载 = KSU 删模块 + 重启；火狐接入 = `su -c 'sh /data/adb/modules/MFGA/firefox.sh'`。
- 术语表：模块 zip = KernelSU 模块包；基础包 = MFGA 补充字库 ZIP（`build.py` 现场读取）；主字体 = 文渊圆体 VF；别名字件 = 只有家族名、没有字形的极小字体；网页字体开关 = 火狐的 `browser.display.use_document_fonts`（压 = 0，放行 = 加 `Selffont:keep` 标记注释）；pref 尾链 = 构建期把补充字库内部家族名按 fonts.xml 顺序追加到火狐 `font.name-list.*` 末尾。

## CI 权限与清理

- `build.yml`：`contents: read` + `actions: read`（只为读本工作流运行历史算版本号），无写权限；版本号在该 job 一处算定后写进产物元数据，构建配置只读它。非 PR 运行上传 Actions artifact（上传不需要写权限）；PR 运行只校验。
- 清理：不设清理工作流（2026-10-05 主人精简流程）；artifact 靠 `retention-days: 5` 过期兜底，要提前删就手动执行 README 给的 `gh api -X DELETE`（需要带 `actions: write` 的凭据）。Release / tag 一概不动。
- 发版：本仓库没有 CI 发版流程；发版仍需主人对项目、版本、触发条件的明确允许。清理授权不等于发版授权。

## 项目取舍（与规范的关系）

- 本项目没有发布型 CI（CI 只校验、无产物），因此「在发布工作流一处算定」落在唯一构建工作流 `Build Selffont` 上：日期与两个序号由 `build.py --query-github` 现场查运行历史一次取齐；本地打包可手工传 `--build` / `--day` / `--date`，或直接 `--query-github`。
- 火狐别名字件与网页字体默认压属激进修复：**未在真机验证**，装机核对清单在 README「未验证项的真机清单」。别名字件只有构建期开关 `--no-alias-fonts`；网页自带字体是构建期默认值（`--keep-web-fonts` 放行）+ 运行时覆盖（KernelSU 管理器「操作」按钮 = `module/action.sh`，等价 `web-fonts.sh keep|block|toggle`，状态文件在 `/data/local/tmp/selffont-web-fonts.state`），`customize.sh` / `firefox.sh` 重生成配置副本时按状态走，不覆盖运行时的选择。
- 第十七版的「只做新包与不做降级」在本仓库落成：只投放 `font_fallback*.xml`（新语法 `supportedAxes`），静态主字体、缺空壳的基础包、模板缺关键行都直接失败，设备没有 `font_fallback*.xml` 时中止安装；改平台行为前先查上游并留证据（近例：`font_fallback.xml` 有 AOSP 15 分支与官方文档佐证，未真机验证的改动在 changelog 标「未验证」并留回退开关）。
- 边界与限制以 README 为准；本文件的清单与 README 冲突时，先按 README 的事实改本文件。
