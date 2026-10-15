#!/usr/bin/env python3
"""Selffont CI 清理：出包工作流（build.yml）与 PR 校验工作流（pr-check.yml）共用这一份脚本，
靠 CLEANUP_APPLY 区分调用，真删逻辑只有一处（不许各写一份）：

- 两个工作流的清理 job 现在都是 actions: write + CLEANUP_APPLY=true，判定即执行删除。
  2026-10-14 之前的版本把真删只挂在 build.yml 上（它只在 push[限默认分支] / workflow_dispatch
  触发，会话分支天然碰不到），导致「预演已证、待出包工作流首次运行」这句话在会话侧永远等不到——
  从 03:35Z 挂到 07:11Z 一次真删都没发生，根因是把「清理只留一份脚本」误写成了「真删只挂一处」，
  而那一处正好会话够不着。现在改成两处都真删：build.yml 的 cleanup job（push 到默认分支时跑）与
  pr-check.yml 的 cleanup job（pull_request 事件时跑，会话推送同仓 PR 即可触发，不是 fork 的
  pull_request 里 GITHUB_TOKEN 能拿到工作流声明的写权限）；两处挂同一个 concurrency group
  （selffont-artifacts）串行，不会同时跑互相打架。
- DELETE 失败按返回码原因分两条路（主人 2026-10-14 选定，不许把两种原因混在一起降级）：
  403 这类权限缺口（典型是 fork 发起的 pull_request，GITHUB_TOKEN 只读）打一条 ::warning::
  annotation、跳过这一条继续往下走，不让整个 job 变红、也不让脚本中途退出；403 以外的失败
  （脚本异常、判据算错、网络错误、其它返回码）打 ::error:: 并计入失败清单，main() 跑完后只要
  清单非空就让这次运行以非零退出码结束，job 当轮变红，汇报里把它列为阻塞项——不许吞掉、不许
  降成 warning 蒙过去。只有真正执行成功的删除才打 DELETE[...] 日志，没成功的仍然算「将删」。

判据顺序固定，不许调换（2026-10-15 由四条加到五条，依据 `selfs` `GLOBAL.md` `129a292`：实测
Selffont 换号源后 4 个旧口径产物 `.5.120`/`.4.119`/`.6.115`/`.5.114` 原四条判据全过——段数 5
正确、非 PR 来源、当日序号不重复、当日之外数量 4 在 5 个内——一个都删不掉，承载它们的 run 也
因「承载保留产物不删」受保护，超量运行记录一并删不动）：
  artifact：命名口径（版本段数 != SEGMENTS）→ 来源（workflow_run 事件是 pull_request）→
            重复当日序号（同一天同一当日序号出现两次，保留总序号最大的）→ 号源口径
            （artifact 名里的总序号必须等于该产物对应 run 的 head sha 的
            `git rev-list --count <sha>`，不等即旧口径产物；sha 不在本地历史里就跳过这条，
            不当删除依据——前提 checkout 要 `fetch-depth: 0`）→ 数量（当日之外每条序列
            保留最近 KEEP 个，当日不设上限）。
  run：承载（run 的 workflow_run 下还挂着被保留的 artifact——删 run 会连带删它的
       artifact，承载保留对象的 run 不删、不计入数量上限）→ 数量（不承载保留对象的 run 里，
       当日之外每条序列保留最近 KEEP 条，按 run_started_at 排序，id 只在同一时刻时作 tiebreak，
       不单独使用；当日不设上限）。run_started_at 缺失（一直排队没真正开始过）时退回 created_at，
       不当场报错；status 不是 completed（queued/waiting/requested/in_progress 等）一律不删，
       不只挡 in_progress 一种状态。

run_number 序列按工作流分开计（build.yml 与 pr-check.yml 各一条），数量判据各自独立计算。
"""
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

CLOCK = timezone(timedelta(hours=8))
PROJECT_PREFIX = "selffont-"
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


KEEP = env_int("KEEP")
SEGMENTS = env_int("SEGMENTS")
APPLY = env_bool("CLEANUP_APPLY")
REPO = os.environ["REPO"]
CURRENT_RUN_ID = int(os.environ["CURRENT_RUN_ID"])
MODE = "真删(CLEANUP_APPLY=true)" if APPLY else "预演,不删(CLEANUP_APPLY=false)"


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


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def run_time(row: dict) -> str:
    """排序/当日判定统一用 run_started_at；run 未真正开始过(如一直排队)该字段缺失时退回 created_at。"""
    return row.get("run_started_at") or row["created_at"]


def today_start() -> datetime:
    now = datetime.now(CLOCK)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def is_today(timestamp: str, start: datetime) -> bool:
    return parse_time(timestamp) >= start


FAILURES: list[tuple[str, str, str]] = []  # (kind, label, reason) 非 403 失败；非空就在 main() 末尾让 job 变红


def permission_gap(stderr: str) -> bool:
    """403 类权限缺口的识别：gh api 对只读 token（典型是 fork 发起的 pull_request）的 DELETE

    会在 stderr 里带 HTTP 403 或 GitHub 的标准权限错误文案；命中算权限缺口，降级为预演继续。
    其余返回码（404/422/5xx、网络错误、脚本自身异常等）一律算非权限类失败，当轮让 job 变红。
    """
    return "HTTP 403" in stderr or "Resource not accessible by integration" in stderr


def act(kind: str, path: str, label: str) -> None:
    """真删单条对象；DELETE 失败按返回码原因分两条路，不许混在一起降级（见模块 docstring）：

    403 这类权限缺口打 ::warning:: annotation 并继续,不用 sys.exit 把整个脚本/job 弄红,也不当
    真的删掉了——降级为"将删"但明确标出失败原因；403 以外的失败打 ::error:: 并计入 FAILURES,
    main() 结束时按 FAILURES 是否非空决定这次运行是否以非零退出码收尾（job 当轮变红）。
    """
    if not APPLY:
        print(f"将删[{kind}](预演，未执行 DELETE) {label}")
        return
    result = subprocess.run(["gh", "api", "-X", "DELETE", path], capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if permission_gap(stderr):
            print(f"::warning::{label} 删除失败（权限缺口）：{stderr[:180]}"
                  f"（fork PR 或 actions 写权限不足，本次降级为预演，不计入已删，继续下一条）")
        else:
            print(f"::error::{label} 删除失败（非权限类，端点 {path}）：{stderr[:180]}")
            FAILURES.append((kind, label, stderr[:180]))
        return
    print(f"DELETE[{kind}] {label}")


def workflow_runs(workflow: str) -> list[dict]:
    try:
        return paginate(f"repos/{REPO}/actions/workflows/{workflow}/runs",
                        ".workflow_runs[]|{id,run_number,status,event,created_at,run_started_at}")
    except SystemExit:
        return []  # 工作流文件还没有任何运行记录时,接口 404


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


def main() -> None:
    start = today_start()
    repo_id = int(json.loads(api(f"repos/{REPO}", jq="{id: .id}"))["id"])
    build_runs = workflow_runs(BUILD_WORKFLOW)
    prcheck_runs = workflow_runs(PRCHECK_WORKFLOW)
    event_by_run_id = {row["id"]: row["event"] for row in build_runs + prcheck_runs}

    print(f"=== Selffont 清理脚本：{MODE}，KEEP={KEEP}，SEGMENTS={SEGMENTS}，当前运行 id={CURRENT_RUN_ID}，PREFIX=Selffont- ===")

    # ---------------- artifact：命名口径 → 来源 → 重复当日序号 → 数量 ----------------
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

    non_today = sorted((row for row in after_dup if not is_today(row["created_at"], start)),
                       key=lambda row: row["created_at"], reverse=True)
    today_rows = [row for row in after_dup if is_today(row["created_at"], start)]
    qty_victims = non_today[KEEP:]
    print(f"artifact:候选 {len(candidates)} 个,命名口径/来源/重复/号源口径四条共删 {len(criteria_victims)} 个;"
          f"当日 {len(today_rows)} 个(数量不设上限,不判定);非当日 {len(non_today)} 个,保留最近 {KEEP} 个")
    for index, row in enumerate(non_today):
        if index < KEEP:
            continue
        act("artifact", f"repos/{REPO}/actions/artifacts/{row['id']}",
            f"{row['created_at']} {row['name']} id={row['id']} 判据:数量(非当日第 {index + 1} 新,超过 {KEEP})")

    kept_artifacts = today_rows + non_today[:KEEP]
    retained_run_ids = {(row.get("workflow_run") or {}).get("id") for row in kept_artifacts}
    retained_run_ids.discard(None)

    if APPLY:
        left = [row for row in all_artifacts() if row["name"].lower().startswith(PROJECT_PREFIX) and owned(row)]
        left_non_today = [row for row in left if not is_today(row["created_at"], start)]
        print(f"复核:artifact 剩 {len(left)} 个,非当日 {len(left_non_today)} 个(上限 {KEEP})")
        if len(left_non_today) > KEEP:
            sys.exit(f"清理后非当日 artifact 仍有 {len(left_non_today)} 个,超过上限 {KEEP}")
    else:
        print(f"预演推算:artifact 若真删,应剩 {len(kept_artifacts)} 个(当日 {len(today_rows)} + "
              f"非当日保留 {min(len(non_today), KEEP)})")

    releases = json.loads(api(f"repos/{REPO}/releases", jq="length"))
    print(f"Release 数:{releases}(规范上限 1。CI 不发版也不删 Release;获准人工发布时由发布者做发布后清理)")
    if releases > 1:
        print("WARNING: Release 超过 1 个,需要获准的人工操作清理(CI 无 contents 写权限)")

    # ---------------- run：承载 → 数量 ----------------
    def clean_runs(workflow: str, rows: list[dict]) -> None:
        if not rows:
            print(f"{workflow}:目前没有任何运行记录,无需清理")
            return
        carrying = [row for row in rows if row["id"] in retained_run_ids]
        not_carrying = [row for row in rows if row["id"] not in retained_run_ids]
        for row in carrying:
            print(f"保留[run,{workflow}](承载被保留的 artifact,不计入数量上限) "
                  f"{run_time(row)} run_number={row['run_number']} id={row['id']}")
        non_today = sorted((row for row in not_carrying if not is_today(run_time(row), start)),
                           key=lambda row: (run_time(row), row["id"]), reverse=True)
        today_rows = [row for row in not_carrying if is_today(run_time(row), start)]
        print(f"{workflow}:{len(rows)} 条运行记录,承载保留 artifact {len(carrying)} 条(不计入上限),"
              f"当日 {len(today_rows)} 条(不设上限,不判定),非当日(不承载) {len(non_today)} 条,"
              f"保留最近 {KEEP} 条")
        for index, row in enumerate(non_today):
            if index < KEEP:
                continue
            if row["status"] != "completed":
                print(f"保留[run,{workflow}](status={row['status']}≠completed,未跑完不删) {run_time(row)} "
                      f"run_number={row['run_number']} id={row['id']}")
                continue
            if row["id"] == CURRENT_RUN_ID:
                print(f"保留[run,{workflow}](本次运行自己,不删) {run_time(row)} "
                      f"run_number={row['run_number']} id={row['id']}")
                continue
            act("run", f"repos/{REPO}/actions/runs/{row['id']}",
                f"{workflow} {run_time(row)} run_number={row['run_number']} id={row['id']} "
                f"判据:数量(非当日且不承载保留对象,第 {index + 1} 新,超过 {KEEP})")
        if APPLY:
            left_rows = workflow_runs(workflow)
            left_non_today = [row for row in left_rows
                              if row["id"] not in retained_run_ids and not is_today(run_time(row), start)]
            print(f"{workflow}:复核剩 {len(left_rows)} 条,非当日不承载 {len(left_non_today)} 条(上限 {KEEP})")
            if len(left_non_today) > KEEP:
                sys.exit(f"{workflow} 清理后非当日不承载运行记录仍有 {len(left_non_today)} 条,超过上限 {KEEP}")

    clean_runs(BUILD_WORKFLOW, build_runs)
    clean_runs(PRCHECK_WORKFLOW, prcheck_runs)

    if FAILURES:
        print(f"=== {len(FAILURES)} 个对象删除失败（非权限类，非 403），job 本轮标红 ===")
        for kind, label, reason in FAILURES:
            print(f"::error::阻塞[{kind}] {label} 原因:{reason}")
        sys.exit(f"{len(FAILURES)} 个对象删除失败（非权限类），详见上方 ::error:: 日志，不许降成 warning 蒙过去")


if __name__ == "__main__":
    main()
