# Selffont 项目规则

本文件承载本仓库常驻规则。全局工程规范以 Sumicya/selfs 的 `GLOBAL.md` 为唯一权威（第十七版，2026-10-05）。
**本仓库上次同步 = 第十七版**；发现落后就把落后点报给主人，并在本轮更新本文件。

## 全局规范同步（2026-10-05，第十七版）

以下条目继承自 Sumicya/selfs 的 `GLOBAL.md`，在本仓库逐条落位：

- 任何本轮本地改动必须最终提交并推送到当前远端分支；任务结束时不得留下未提交或已提交但未推送的改动。
- CI 不得自动创建 Release、正式发行 tag 或正式 Release asset；发版必须先获得主人对项目、版本和触发条件的明确允许。
- 默认保留数：Release 1 个、关联 tag 1 个、Actions artifact 5 个（artifact 另以 `retention-days: 5` 作时间兜底；本项目 CI 不上传 artifact，该兜底在启用上传时一并加上）。
- 自动清理与发版授权分离：清理只按授权范围删本项目明确标识的对象，不产生新 Release，不改动新 Release 的资产，不等价于发版授权。
- 写权限最小化：发布 / 清理 job 只授予所需最小写权限；PR 检查与规范检查保持只读，不把写权限暴露给未信任 PR 代码。
- 只做新包与不做降级：涉及平台新机制只实现新机制；改平台行为前先查上游并留证据；能明确失败则直接失败，删降级路径前确认最坏失败模式不是不可恢复。

## 项目核对清单

- 默认分支：`main`；会话固定在工作分支上提交并推送，不直接推 `main`。
- 构建方式：本地 `python3 build.py`（唯一构建链，自检内建）。产物只带一份字体配置 `font_fallback.xml`（新语法 `supportedAxes`，Android 15+ 运行时实例化）；安装脚本只替换系统的 `font_fallback*.xml`，库存 `fonts.xml` 不碰，没有该文件的设备中止安装。输入侧不降级：静态主字体、缺空壳的基础包都直接拒绝。CI（`.github/workflows/build.yml`）只跑自检 + 一次验证性构建，**不发版、不上传 artifact、不写 Release**。
- 产物：模块 zip `Selffont-<版本>.zip`（约 100 MB）；非发行版本叫 `Selffont.zip`。产物只由本地构建产出；仓库未启用 Release，文档里不写 Release 下载入口。
- Actions artifact:CI 不再上传产物；`cleanup.yml` 手动触发清理，保留最近 **5** 个，按 `selffont-` 前缀筛选、完整分页、结构化字段，只删 artifact（详见"CI 权限与清理"）。
- 允许写权限的工作流：cleanup.yml(actions) —— 只手动触发、只删 Actions artifact，不碰 Release、tag 与历史 tag。（这行同时是 `spec-check.yml` 的写权限白名单来源。）
- 版本来源：五段 `yy.m.d.当日序号.总序号`，展示版本不含 `v`,`versionCode` = 总序号。取数在仓库唯一构建工作流的运行历史里现场查（`build.py --query-github` 或 README 给的 `gh api` 查法），不在文档/代码里写死现值；仓库里的 `module/module.prop` 默认是**非发行版本** `version=dev` / `versionCode=0`。
- 计数口径：总序号 = 该工作流最近一次运行的 `run_number`（含 PR 运行，单调递增）；当日序号 = 当天（Asia/Shanghai）该工作流 `push` / `workflow_dispatch` 且已开始的运行数，PR 检查不计入。**取不到当日序号时退化写四段 `yy.m.d.总序号`**，原因见 README。
- 历史 tag:`v3.0.0`（0d9ba81,2026-09-26）、`v26.9.30.39`（215cf25,2026-09-29）属已下线的旧发版链，按规范默认保留，不追溯改名、不改写历史。
- 下载与安装：不发 Release。安装 = KernelSU 装本地构建的 zip + 重启；卸载 = KSU 删模块 + 重启；火狐接入 = `su -c 'sh /data/adb/modules/MFGA/firefox.sh'`。
- 术语表：模块 zip = KernelSU 模块包；基础包 = MFGA 补充字库 ZIP（`build.py` 现场读取）；主字体 = 文渊圆体 VF；别名字件 = 只有家族名、没有字形的极小字体；网页字体开关 = 火狐的 `browser.display.use_document_fonts`（压 = 0，放行 = 加 `Selffont:keep` 标记注释）；pref 尾链 = 构建期把补充字库内部家族名按 fonts.xml 顺序追加到火狐 `font.name-list.*` 末尾。

## 三条硬规则（2026-10-05，主人定）

- **只做新包**：配置只出新语法（`supportedAxes`），只投放 `font_fallback*.xml`；不做 legacy 逐档展开、不替换库存 `fonts.xml`。没有目标文件的设备中止安装，不为兼容再开旧路径。
- **先查证再动手**：动到平台行为（Android 字体管线、Gecko、KernelSU）之前先查上游源码或官方文档（googlesource / gerrit、searchfox、官方文档），依据写进 changelog / PR；只有间接证据的必须标「未验证」并留回退开关。
- **不做冗余降级**：能明确失败的直接失败（静态主字体、缺空壳、模板缺关键行、系统没有目标文件都报错/中止），不静默产出半成品；删降级路径前先确认最坏失败模式不是不可恢复（优先「功能不生效」而不是「系统损坏」）。

## CI 权限与清理

- `build.yml`:`contents: read` + `actions: read`（只为读本工作流运行历史算版本号），无写权限；版本号在该 job 一处算定后写进产物元数据，构建配置只读它。
- `cleanup.yml`：唯一有写权限的工作流（`actions: write`），只手动触发（`workflow_dispatch`），默认干跑（`apply=false` 只打印清单），不与 PR 触发器共存；删除前校验 KEEP 为正整数、按 `selffont-` 前缀过滤、完整分页、按 `created_at` 倒序。
- `spec-check.yml`：只读（`contents: read`），静态检查规范版本与 AGENTS.md 指针、关键 CI 权限、自动发版禁令；不拥有任何发布写权限。
- 发版与清理分离：本仓库没有 CI 发版流程；清理授权不等于发版授权，发版仍需主人对项目、版本、触发条件的明确允许。

## 项目取舍（与规范的关系）

- 本项目没有发布型 CI（CI 只校验、无产物），因此「在发布工作流一处算定」落在唯一构建工作流 `Build Selffont` 上：日期与两个序号由 `build.py --query-github` 现场查运行历史一次取齐；本地打包可手工传 `--build` / `--day` / `--date`，或直接 `--query-github`。
- 火狐别名字件与网页字体默认压属激进修复：**未在真机验证**，装机核对清单在 README「未验证项的真机清单」。别名字件只有构建期开关 `--no-alias-fonts`；网页自带字体是构建期默认值（`--keep-web-fonts` 放行）+ 运行时覆盖（KernelSU 管理器「操作」按钮 = `module/action.sh`，等价 `web-fonts.sh keep|block|toggle`，状态文件在 `/data/local/tmp/selffont-web-fonts.state`），`customize.sh` / `firefox.sh` 重生成配置副本时按状态走，不覆盖运行时的选择。
- 边界与限制以 README 为准；本文件的清单与 README 冲突时，先按 README 的事实改本文件。
