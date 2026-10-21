#!/usr/bin/env python3
"""Selffont 清理：所有自动清理入口共用这一份脚本。

CLEANUP_SCOPE=artifacts 处理 Actions artifact/run；CLEANUP_SCOPE=releases 处理 Release 与项目孤立 tag。
动作先收齐并打印完整清单，再按 CLEANUP_APPLY 预演或执行。Release/tag 清理单独使用
contents: write；artifact/run 清理单独使用 actions: write + contents: read。

失败分级：403 权限缺口打印含对象、端点和 HTTP 状态的 warning，跳过该对象并继续，不能报成成功；
403 以外的失败打印 error 并使 job 失败。清理后的数量复核遇到 403 时明确标为未完成，不把权限不足
降级描述为清理成功。

判据顺序固定，不许调换（2026-10-15 由四条加到五条，依据 `selfs` `GLOBAL.md` `129a292`：实测
Selffont 换号源后 4 个旧口径产物 `.5.120`/`.4.119`/`.6.115`/`.5.114` 原四条判据全过——段数 5
正确、非 PR 来源、当日序号不重复、当日之外数量 4 在 5 个内——一个都删不掉，承载它们的 run 也
因「承载保留产物不删」受保护，超量运行记录一并删不动；同日再依据 `GLOBAL.md` `790bf826`，数量
判据的「当日不设上限也不删」豁免被去掉；再依据 `GLOBAL.md` `4f748b56a`/`3144a2068`（撤销「承载
保留 artifact 的 run 不计入上限」这条例外——此前每个工作流实际能到 2×KEEP 条：KEEP 条承载保留
artifact 的 run 完全不算、另 KEEP 条非承载的才受上限约束，Selffont/gself/qself 三仓实测分别是
15/11/10 条而不是字面的 5 条，与主人核对后确认是规范字面「最多 5 条」与豁免条款互相矛盾，已由
主人在 selfs 侧改规范澄清），五条判据现在全部不豁免，run 的数量上限不再因承载 artifact 或任何
其它理由放宽，当日产物与运行记录同样计入 KEEP 的上限）：
  artifact：命名口径（版本段数 != SEGMENTS）→ 来源（workflow_run 事件是 pull_request）→
            重复当日序号（同一天同一当日序号出现两次，保留总序号最大的）→ 号源口径
            （artifact 名里的总序号必须等于该产物对应 run 的 head sha 的
            `git rev-list --count <sha>`，不等即旧口径产物；sha 不在本地历史里就跳过这条，
            不当删除依据——前提 checkout 要 `fetch-depth: 0`）→ 数量（全仓按 `created_at`
            统一保留最新 KEEP 个，但运行记录上限优先：若某 artifact 排名本在前 KEEP，但它挂的
            run 已经不在该 run 所属工作流的「最新 KEEP 条运行记录」里，删 artifact、不为它突破
            run 的硬上限，名额让给下一个 run 仍被保留的候选）。
  run：数量（每个工作流按 `run_started_at` 统一保留最新 KEEP 条，硬上限，不设任何例外——不区分
       当日、不因承载 artifact 放宽；run_started_at 缺失（一直排队没真正开始过）时退回
       `created_at`，`id` 只在同一时刻时作 tiebreak，不单独使用）。run 的保留集合先于 artifact
       的数量判据算出来，因为它要被 artifact 侧拿去做「运行记录上限优先」的否决依据。status 不是
       completed（queued/waiting/requested/in_progress 等）的超限 run 不能直接 DELETE（依据
       `selfs` `GLOBAL.md` 重设版「未完成运行造成超限时,先取消较旧的超限运行」），改成 POST
       `.../cancel` 先取消，真删留给它转成 completed 之后的下一轮；取消动作同样进入统一动作清单，
       由 `execute_actions()` 按 403/非 403 两条路径处理，不单独开后门。当前运行自己
       (`CURRENT_RUN_ID`) 永不取消不删，这条
       判断必须排在「未完成」判断之前，否则会在脚本运行中途自己取消自己。

run_number 序列按工作流分开计（build.yml 与 pr-check.yml 各一条），数量判据各自独立计算。
"""
import json
import os
import subprocess
import sys
from collections import defaultdict
from urllib.parse import quote, unquote

PROJECT_PREFIX = "selffont-"
PROJECT_TAG_PREFIX = "Selffont-"
BUILD_WORKFLOW = "build.yml"
PRCHECK_WORKFLOW = "pr-check.yml"


def env_int(name: str) -> int:
    raw = os.environ[name].strip()
    if not raw.isdigit() or int(raw) < 1:
        sys.exit(f"{name} 必须是正整数，收到 {raw!r}")
    return int(raw)


def env_bool(name: str) -> bool:
    raw = os.environ[name].strip().lower()
    if raw not in ("true", "false"):
        sys.exit(f"{name} 必须是 true/false，收到 {raw!r}")
    return raw == "true"


CLEANUP_SCOPE = os.environ.get("CLEANUP_SCOPE", "artifacts").strip().lower()
if CLEANUP_SCOPE not in ("artifacts", "releases"):
    sys.exit(f"CLEANUP_SCOPE 必须是 artifacts/releases，收到 {CLEANUP_SCOPE!r}")
KEEP = env_int("KEEP")
SEGMENTS = env_int("SEGMENTS")
APPLY = env_bool("CLEANUP_APPLY")
REPO = os.environ["REPO"]
CURRENT_RUN_ID = int(os.environ.get("CURRENT_RUN_ID", "0"))
if CLEANUP_SCOPE == "artifacts" and CURRENT_RUN_ID < 1:
    sys.exit("artifact 清理需要正整数 CURRENT_RUN_ID")
MODE = f"{CLEANUP_SCOPE} 清理 / " + ("真删(CLEANUP_APPLY=true)" if APPLY else "预演,不删(CLEANUP_APPLY=false)")

PENDING_ACTIONS: list[tuple[str, str, str, str, str]] = []
PERMISSION_SKIPS: list[tuple[str, str, str]] = []
SUCCESSFUL_ACTIONS: set[tuple[str, str]] = set()


def api(path: str, jq: str | None = None, method: str | None = None) -> str:
    command = ["gh", "api"] + (["--jq", jq] if jq else []) + (["-X", method] if method else []) + [path]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"gh api {path} 失败：{result.stderr.strip()}")
    return result.stdout


def paginate(path: str, jq: str) -> list[dict]:
    rows, page = [], 1
    sep = "&" if "?" in path else "?"
    while True:
        batch = [json.loads(line) for line in
                 api(f"{path}{sep}per_page=100&page={page}", jq=jq).splitlines() if line.strip()]
        if not batch:
            return rows
        rows += batch
        page += 1


def run_time(row: dict) -> str:
    """排序统一用 run_started_at；run 未真正开始过(如一直排队)该字段缺失时退回 created_at。"""
    return row.get("run_started_at") or row["created_at"]


FAILURES: list[tuple[str, str, str]] = []  # (kind, label, reason) 非 403 失败；非空就在 main() 末尾让 job 变红


def permission_gap(stderr: str) -> bool:
    """403 类权限缺口的识别：gh api 对只读 token（典型是 fork 发起的 pull_request）的 DELETE

    会在 stderr 里带 HTTP 403 或 GitHub 的标准权限错误文案；命中算权限缺口，降级为预演继续。
    其余返回码（404/422/5xx、网络错误、脚本自身异常等）一律算非权限类失败，当轮让 job 变红。
    """
    return "HTTP 403" in stderr or "Resource not accessible by integration" in stderr


def act(kind: str, path: str, label: str, method: str = "DELETE", verb: str = "删除") -> None:
    """先登记动作；所有待处理对象打印完后才执行，避免边删边发现后续对象。"""
    PENDING_ACTIONS.append((kind, path, label, method, verb))


def execute_actions() -> None:
    """先打印完整待处理清单，再执行；403 只降级为 warning，其他失败使本轮失败。"""
    print("=== 待处理清单（以下清理对象均已判定；此行之后才会执行） ===")
    if not PENDING_ACTIONS:
        print("无")
    for kind, path, label, method, verb in PENDING_ACTIONS:
        print(f"{verb}[{kind}] endpoint={path} method={method} object={label}")

    if not APPLY:
        print("=== 预演：未执行任何清理动作 ===")
        return

    remaining_release_tags = None
    for kind, path, label, method, verb in PENDING_ACTIONS:
        if kind == "tag":
            if remaining_release_tags is None:
                remaining = paginate(f"repos/{REPO}/releases", ".[]|{tag_name}")
                remaining_release_tags = {row.get("tag_name") for row in remaining}
            tag_name = unquote(path.rsplit("/", 1)[-1])
            if tag_name in remaining_release_tags:
                print(f"保留[tag](对应 Release 仍存在,不删除其 tag) {tag_name}")
                continue
        result = subprocess.run(["gh", "api", "-X", method, path], capture_output=True, text=True)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if permission_gap(stderr):
                PERMISSION_SKIPS.append((kind, path, label))
                print(f"::warning::权限缺口：object={label}; endpoint={path}; HTTP 403; "
                      f"gh_exit={result.returncode}; {stderr[:180]}。本项未执行，继续下一项。")
            else:
                print(f"::error::清理失败：object={label}; endpoint={path}; "
                      f"gh_exit={result.returncode}; {stderr[:180]}")
                FAILURES.append((kind, label, f"endpoint={path}; gh_exit={result.returncode}; {stderr[:180]}"))
            continue
        SUCCESSFUL_ACTIONS.add((kind, path))
        print(f"{method}[{kind}] {label}")
    if PERMISSION_SKIPS:
        print(f"=== 未执行的清理动作：{len(PERMISSION_SKIPS)} 项因 403 权限缺口跳过，不计为清理成功 ===")
        for kind, path, label in PERMISSION_SKIPS:
            print(f"未执行[{kind}] endpoint={path} object={label}")


def workflow_runs(workflow: str) -> list[dict]:
    path = f"repos/{REPO}/actions/workflows/{workflow}/runs"
    try:
        return paginate(path, ".workflow_runs[]|{id,run_number,status,event,created_at,run_started_at}")
    except SystemExit as exc:
        message = str(exc)
        if "HTTP 404" in message or "Not Found" in message:
            print(f"{workflow}:暂无运行记录(API 404),按空列表处理")
            return []
        raise


def name_segments(name: str) -> int:
    version = name.split("-", 1)[1] if "-" in name else ""
    return len([part for part in version.split(".") if part])


def version_parts(name: str):
    """<项目名>-yy.m.d.当日序号.总序号 -> (日期, 当日序号, 总序号)；段数不够就是 None。"""
    version = name.split("-", 1)[1] if "-" in name else ""
    parts = [part for part in version.split(".") if part]
    if len(parts) < 5:
        return None
    return ".".join(parts[:3]), parts[3], parts[4]


def all_artifacts() -> list[dict]:
    return paginate(f"repos/{REPO}/actions/artifacts",
                    ".artifacts[]|{id,name,created_at,size_in_bytes,workflow_run}")


def commit_total(sha: str) -> int | None:
    """该 sha 在本地仓库历史里的总提交数：`git rev-list --count <sha>`（号源口径判据用）。

    sha 不在本地历史里（来自已删分支、fork，或 checkout 没有 fetch-depth: 0）就返回 None，
    调用方把这条判据当「不可核验」处理，不当删除依据——宁可漏删也不错删。
    """
    result = subprocess.run(["git", "rev-list", "--count", sha], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return int(value) if value.isdigit() else None


def release_tag_plan(releases: list[dict], tags: list[dict], prefix: str = PROJECT_TAG_PREFIX):
    """保留最新一个 Release；只清理带项目名前缀且不再对应保留 Release 的孤立 tag。"""
    ordered = sorted(
        releases,
        key=lambda row: (row.get("published_at") or row.get("created_at") or "", int(row["id"])),
        reverse=True,
    )
    keep_releases = ordered[:1]
    delete_releases = ordered[1:]
    keep_tags = {row.get("tag_name") for row in keep_releases if row.get("tag_name")}
    project_tags = [row for row in tags if row["name"].lower().startswith(prefix.lower())]
    delete_tags = [row for row in project_tags if row["name"] not in keep_tags]
    return keep_releases, delete_releases, project_tags, delete_tags


def self_check_release_tag_plan() -> None:
    """小型断言：最新 Release 的 tag 保留，旧 Release 与无对应 Release 的项目 tag 删除。"""
    releases = [
        {"id": 1, "tag_name": "Selffont-old", "created_at": "2026-01-01", "published_at": "2026-01-01"},
        {"id": 2, "tag_name": "Selffont-new", "created_at": "2026-01-02", "published_at": "2026-01-02"},
    ]
    tags = [{"name": "Selffont-old"}, {"name": "Selffont-new"},
            {"name": "Selffont-orphan"}, {"name": "legacy-v1"}]
    kept, deleted_releases, project_tags, deleted_tags = release_tag_plan(releases, tags)
    assert [row["id"] for row in kept] == [2]
    assert [row["id"] for row in deleted_releases] == [1]
    assert {row["name"] for row in project_tags} == {"Selffont-old", "Selffont-new", "Selffont-orphan"}
    assert {row["name"] for row in deleted_tags} == {"Selffont-old", "Selffont-orphan"}


def clean_releases_and_tags() -> None:
    self_check_release_tag_plan()
    releases = paginate(
        f"repos/{REPO}/releases",
        ".[]|{id,tag_name,name,created_at,published_at}",
    )
    tags = paginate(f"repos/{REPO}/tags", ".[]|{name}")
    keep_releases, delete_releases, project_tags, delete_tags = release_tag_plan(releases, tags)
    retained_tags = {row.get("tag_name") for row in keep_releases if row.get("tag_name")}

    print(f"=== Selffont Release/tag 清理：{MODE}；Release 上限 1；tag 前缀 {PROJECT_TAG_PREFIX} ===")
    print(f"Release: {len(releases)} 个；保留最新 {len(keep_releases)} 个；待删 {len(delete_releases)} 个")
    for row in delete_releases:
        act("release", f"repos/{REPO}/releases/{row['id']}",
            f"id={row['id']} tag={row.get('tag_name')} name={row.get('name')}")
    for row in tags:
        name = row["name"]
        if not name.lower().startswith(PROJECT_TAG_PREFIX.lower()):
            print(f"保留[tag](不属于 {PROJECT_TAG_PREFIX} 项目名前缀范围,不判定) {name}")
        elif name in retained_tags:
            print(f"保留[tag](对应保留的 Release) {name}")
    for row in delete_tags:
        name = row["name"]
        ref = quote(name, safe="")
        act("tag", f"repos/{REPO}/git/refs/tags/{ref}",
            f"name={name}（无对应保留 Release）")


def main() -> None:
    if CLEANUP_SCOPE == "releases":
        clean_releases_and_tags()
        execute_actions()
        if APPLY:
            left_releases = paginate(
                f"repos/{REPO}/releases",
                ".[]|{id,tag_name,name,created_at,published_at}",
            )
            left_tags = paginate(f"repos/{REPO}/tags", ".[]|{name}")
            release_permission_gap = any(kind in ("release", "tag") for kind, _, _ in PERMISSION_SKIPS)
            _, extra_releases, _, orphan_tags = release_tag_plan(left_releases, left_tags)
            print(f"复核:Release 剩 {len(left_releases)} 个(上限 1);项目孤立 tag {len(orphan_tags)} 个")
            if release_permission_gap:
                print("复核未完成:Release/tag 清理遇到 403 权限缺口；未把未删对象描述为清理成功。")
            else:
                if len(left_releases) > 1:
                    FAILURES.append(("release", "清理后数量", f"实际剩 {len(left_releases)} 个,超过上限 1"))
                if extra_releases or orphan_tags:
                    FAILURES.append(("tag", "清理后孤立对象",
                                     f"仍有 {len(extra_releases)} 个多余 Release 与 {len(orphan_tags)} 个孤立 tag"))
        if FAILURES:
            print(f"=== {len(FAILURES)} 个 Release/tag 清理检查失败（非权限类），job 本轮标红 ===")
            for kind, label, reason in FAILURES:
                print(f"::error::阻塞[{kind}] {label} 原因:{reason}")
            sys.exit(f"{len(FAILURES)} 个 Release/tag 清理动作失败（非权限类）")
        return

    repo_id = int(json.loads(api(f"repos/{REPO}", jq="{id: .id}"))["id"])
    build_runs = workflow_runs(BUILD_WORKFLOW)
    prcheck_runs = workflow_runs(PRCHECK_WORKFLOW)
    event_by_run_id = {row["id"]: row["event"] for row in build_runs + prcheck_runs}

    print(f"=== Selffont 清理脚本：{MODE}，KEEP={KEEP}，SEGMENTS={SEGMENTS}，当前运行 id={CURRENT_RUN_ID}，PREFIX=Selffont- ===")

    # ---------------- run 数量：每个工作流独立算最新 KEEP 条,硬上限不设任何例外 ----------------
    # 2026-10-15 依据 selfs GLOBAL.md `4f748b56a`/`3144a2068`（撤销「承载保留 artifact 的 run 不计入
    # 上限」豁免）：run 的保留集合只看 run 自己的时间排序,与它是否挂着被保留的 artifact 无关；这个
    # 集合要先于 artifact 的数量判据算出来，因为「运行记录上限优先」要用它来否决 artifact。
    def top_run_ids(rows: list[dict]) -> set[int]:
        by_recency = sorted(rows, key=lambda row: (run_time(row), row["id"]), reverse=True)
        return {row["id"] for row in by_recency[:KEEP]}

    kept_run_ids = {BUILD_WORKFLOW: top_run_ids(build_runs), PRCHECK_WORKFLOW: top_run_ids(prcheck_runs)}
    workflow_of_run = {row["id"]: BUILD_WORKFLOW for row in build_runs}
    workflow_of_run.update({row["id"]: PRCHECK_WORKFLOW for row in prcheck_runs})

    # ---------------- artifact：命名口径 → 来源 → 重复当日序号 → 号源口径 ----------------
    candidates = [row for row in all_artifacts() if row["name"].lower().startswith(PROJECT_PREFIX)]

    def owned(row: dict) -> bool:
        run = row.get("workflow_run") or {}
        return run.get("repository_id") == repo_id and run.get("head_repository_id") == repo_id

    unknown = [row for row in candidates if not owned(row)]
    candidates = [row for row in candidates if owned(row)]
    for row in unknown:
        print(f"保留[artifact](归属不明,不判定) {row['created_at']} {row['name']} id={row['id']} "
              f"workflow_run={row.get('workflow_run')}")

    def is_current(row: dict) -> bool:
        run = row.get("workflow_run") or {}
        return run.get("id") == CURRENT_RUN_ID

    survivors, criteria_victims = [], []
    for row in candidates:
        if is_current(row):
            print(f"保留[artifact](本次运行刚产出,不判定) {row['created_at']} {row['name']} id={row['id']}")
            survivors.append(row)
            continue
        segs = name_segments(row["name"])
        if segs != SEGMENTS:
            criteria_victims.append((row, f"命名口径(段数={segs}≠SEGMENTS={SEGMENTS})"))
            continue
        run_event = event_by_run_id.get((row.get("workflow_run") or {}).get("id"))
        if run_event == "pull_request":
            criteria_victims.append((row, "来源(workflow_run 事件是 pull_request)"))
            continue
        survivors.append(row)

    groups: dict[tuple, list] = defaultdict(list)
    no_group = []
    for row in survivors:
        parsed = version_parts(row["name"])
        if parsed is None:
            no_group.append(row)
            continue
        date, day_index, total = parsed
        groups[(date, day_index)].append((int(total), row))

    after_dup = list(no_group)
    for (date, day_index), group in groups.items():
        group.sort(key=lambda pair: pair[0], reverse=True)
        after_dup.append(group[0][1])
        for total, row in group[1:]:
            criteria_victims.append(
                (row, f"重复当日序号 {date}.{day_index}(保留总序号最大的 {group[0][0]},此对象总序号 {total})"))

    # ---------------- 号源口径：总序号必须等于该产物对应 run 的 head sha 的 git rev-list --count ----------------
    after_source_check = []
    for row in after_dup:
        parsed = version_parts(row["name"])
        if parsed is None:
            after_source_check.append(row)
            continue
        _, _, total = parsed
        sha = (row.get("workflow_run") or {}).get("head_sha")
        if not sha:
            print(f"保留[artifact](号源口径:取不到 head_sha,不核验) {row['created_at']} {row['name']} id={row['id']}")
            after_source_check.append(row)
            continue
        expect = commit_total(sha)
        if expect is None:
            print(f"保留[artifact](号源口径:sha {sha[:9]} 不在本地历史,不核验) {row['created_at']} {row['name']} id={row['id']}")
            after_source_check.append(row)
            continue
        if int(total) != expect:
            criteria_victims.append(
                (row, f"号源口径(总序号={total}≠head {sha[:9]} 的 git rev-list --count={expect})"))
            continue
        after_source_check.append(row)
    after_dup = after_source_check

    for row, reason in criteria_victims:
        act("artifact", f"repos/{REPO}/actions/artifacts/{row['id']}",
            f"{row['created_at']} {row['name']} id={row['id']} 判据:{reason}")

    # ---------------- artifact 数量：全仓最新 KEEP 个,但运行记录上限优先 ----------------
    # 若某 artifact 按 created_at 排名本在前 KEEP 个内,但它挂的 run 不在该 run 所属工作流的
    # kept_run_ids 里（run 自己的硬上限已经把它判出局），不得为了保留这个 artifact 去突破 run
    # 上限——删 artifact,把名额让给下一个排名靠后但 run 仍被保留的候选（自然实现「同步校正
    # artifact 留存清单」，不强行凑够 KEEP 个）。
    by_recency = sorted(after_dup, key=lambda row: row["created_at"], reverse=True)
    kept_artifacts: list[dict] = []
    quantity_victims: list[tuple[dict, str]] = []
    for index, row in enumerate(by_recency):
        run_id = (row.get("workflow_run") or {}).get("id")
        workflow = workflow_of_run.get(run_id)
        run_capped = run_id is not None and workflow is not None and run_id not in kept_run_ids[workflow]
        if len(kept_artifacts) < KEEP and not run_capped:
            kept_artifacts.append(row)
            continue
        if run_capped:
            reason = (f"运行记录上限优先(第 {index + 1} 新,但所属 run id={run_id} 不在 {workflow} "
                      f"最新 {KEEP} 条运行记录内,删 artifact 而非为它突破 run 上限)")
        else:
            reason = f"数量(第 {index + 1} 新,超过 {KEEP})"
        quantity_victims.append((row, reason))

    print(f"artifact:候选 {len(candidates)} 个,命名口径/来源/重复/号源口径四条共删 {len(criteria_victims)} 个;"
          f"剩 {len(by_recency)} 个,数量判据全仓最多 {KEEP} 个且运行记录上限优先,不设任何例外")
    for row, reason in quantity_victims:
        act("artifact", f"repos/{REPO}/actions/artifacts/{row['id']}",
            f"{row['created_at']} {row['name']} id={row['id']} 判据:{reason}")

    if not APPLY:
        print(f"预演推算:artifact 若真删,应剩 {len(kept_artifacts)} 个")

    # ---------------- run：数量,硬上限 KEEP 条,不设任何例外（2026-10-15 承载豁免已撤销） ----------------
    planned_cancel_ids = {BUILD_WORKFLOW: set(), PRCHECK_WORKFLOW: set()}

    def clean_runs(workflow: str, rows: list[dict]) -> None:
        if not rows:
            print(f"{workflow}:目前没有任何运行记录,无需清理")
            return
        keep_ids = kept_run_ids[workflow]
        by_recency = sorted(rows, key=lambda row: (run_time(row), row["id"]), reverse=True)
        print(f"{workflow}:{len(rows)} 条运行记录,硬上限 {KEEP} 条,不设当日、承载 artifact 或其它例外")
        for row in by_recency:
            if row["id"] in keep_ids:
                print(f"保留[run,{workflow}](最新 {KEEP} 条内,不删) {run_time(row)} "
                      f"run_number={row['run_number']} id={row['id']}")
                continue
            if row["id"] == CURRENT_RUN_ID:
                print(f"保留[run,{workflow}](本次运行自己,不取消不删——安全兜底,理论上本就在最新 {KEEP} 条内) "
                      f"{run_time(row)} run_number={row['run_number']} id={row['id']}")
                continue
            if row["status"] != "completed":
                act("run", f"repos/{REPO}/actions/runs/{row['id']}/cancel",
                    f"{workflow} {run_time(row)} run_number={row['run_number']} id={row['id']} "
                    f"status={row['status']} 判据:数量超限(硬上限 {KEEP},不设任何例外,未完成先取消,"
                    f"真删留给它转为 completed 后的下一轮)",
                    method="POST", verb="取消")
                planned_cancel_ids[workflow].add(row["id"])
                continue
            act("run", f"repos/{REPO}/actions/runs/{row['id']}",
                f"{workflow} {run_time(row)} run_number={row['run_number']} id={row['id']} "
                f"判据:数量(硬上限 {KEEP},不设任何例外)")

    clean_runs(BUILD_WORKFLOW, build_runs)
    clean_runs(PRCHECK_WORKFLOW, prcheck_runs)

    execute_actions()
    if APPLY:
        left_artifacts = [row for row in all_artifacts()
                          if row["name"].lower().startswith(PROJECT_PREFIX) and owned(row)]
        artifact_permission_gap = any(kind == "artifact" for kind, _, _ in PERMISSION_SKIPS)
        print(f"复核:artifact 当前剩 {len(left_artifacts)} 个(上限 {KEEP})")
        if artifact_permission_gap:
            print("复核未完成:artifact 清理遇到 403 权限缺口；未把未删对象描述为清理成功。")
        elif len(left_artifacts) > KEEP:
            FAILURES.append(("artifact", "清理后数量", f"实际剩 {len(left_artifacts)} 个,超过上限 {KEEP}"))

        successful_cancel_ids = {
            int(path.rsplit("/", 2)[-2])
            for kind, path in SUCCESSFUL_ACTIONS
            if kind == "run" and path.endswith("/cancel")
        }
        run_permission_workflows = set()
        for kind, path, _ in PERMISSION_SKIPS:
            if kind != "run" or "/actions/runs/" not in path:
                continue
            run_id = int(path.split("/actions/runs/", 1)[1].split("/", 1)[0])
            workflow = workflow_of_run.get(run_id)
            if workflow:
                run_permission_workflows.add(workflow)

        for workflow in (BUILD_WORKFLOW, PRCHECK_WORKFLOW):
            left_rows = workflow_runs(workflow)
            left_ids = {row["id"] for row in left_rows}
            left_pending_cancel = left_ids & planned_cancel_ids[workflow] & successful_cancel_ids
            over = len(left_rows) - len(left_pending_cancel)
            print(f"{workflow}:复核当前 {len(left_rows)} 条(上限 {KEEP},其中本轮已成功取消但记录尚未消失的 "
                  f"{len(left_pending_cancel)} 条不计入本轮核验)")
            if workflow in run_permission_workflows:
                print(f"复核未完成:{workflow} 清理遇到 403 权限缺口；未把未删对象描述为清理成功。")
            elif over > KEEP:
                FAILURES.append(("run", workflow, f"清理后仍有 {over} 条(不含本轮成功取消待删),超过上限 {KEEP}"))

    if FAILURES:
        print(f"=== {len(FAILURES)} 个对象删除失败（非权限类，非 403），job 本轮标红 ===")
        for kind, label, reason in FAILURES:
            print(f"::error::阻塞[{kind}] {label} 原因:{reason}")
        sys.exit(f"{len(FAILURES)} 个对象删除失败（非权限类），详见上方 ::error:: 日志，不许降成 warning 蒙过去")


if __name__ == "__main__":
    main()
