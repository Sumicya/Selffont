#!/usr/bin/env python3
"""Selffont 清理：Actions 产物与运行记录、Release 与孤立 tag 共用这一份脚本。

CLEANUP_SCOPE=actions 处理 artifact 与 run；CLEANUP_SCOPE=releases 处理 Release 与项目孤立 tag。
读取 GH_TOKEN、REPO、RUN_ID、SEGMENTS、CLEANUP_APPLY；项目名前缀由 REPO 推导（Selffont-）。
动作先收齐并打印完整清单，再按 CLEANUP_APPLY 预演或执行；只动本项目对象。

artifact 五判据依次执行：命名口径（版本段数 != SEGMENTS 或任一段带前导零）→ 来源（workflow_run.event 是
pull_request）→ 重复当日序号（同日同序号按来源运行的 run_started_at 删旧留新）→ 号源口径
（末段总序号必须等于来源运行的 run_number；切换号源过渡期、全仓还没有任何新口径产物时暂留
最新 1 个旧产物）→ 数量（全仓按 created_at 保留最新 5 个，且来源运行必须仍在所属工作流保留的
最新 5 条运行记录内）。run 只有数量判据：每个工作流保留最新 5 条，未完成且超限的先取消。

失败分级：403 权限缺口打印对象、端点与返回码的 warning 后继续；403 以外的失败打印 error 并让
本轮失败，不把权限不足描述成清理成功。
"""
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

KEEP_RUNS = 5
KEEP_ARTIFACTS = 5
KEEP_RELEASES = 1
CLOCK = timezone(timedelta(hours=8))


def env_value(name: str, default: str | None = None) -> str:
    raw = (os.environ.get(name) or default or "").strip()
    if not raw:
        sys.exit(f"缺少环境变量 {name}")
    return raw


def env_int(name: str, minimum: int = 1) -> int:
    raw = env_value(name)
    if not raw.isdigit() or int(raw) < minimum:
        sys.exit(f"{name} 必须是 ≥{minimum} 的十进制整数，收到 {raw!r}")
    return int(raw)


APPLY = env_value("CLEANUP_APPLY", "false").lower() == "true"
if (os.environ.get("CLEANUP_APPLY") or "").strip().lower() not in ("true", "false"):
    sys.exit("CLEANUP_APPLY 必须是 true/false")
SCOPE = env_value("CLEANUP_SCOPE", "actions").lower()
if SCOPE not in ("actions", "releases"):
    sys.exit(f"CLEANUP_SCOPE 必须是 actions 或 releases，收到 {SCOPE!r}")
REPO = env_value("REPO")
PROJECT = REPO.rsplit("/", 1)[-1]
PREFIX = f"{PROJECT}-"
RUN_ID = env_int("RUN_ID")
SEGMENTS = env_int("SEGMENTS")

MODEL = "真删" if APPLY else "预演（只打印清单）"
PENDING: list[dict] = []                             # 每项：类型/端点/对象/方法/动作词/关联 tag
PERMISSION_GAPS: list[tuple[str, str, str]] = []     # (类型, 端点, 对象)
FAILURES: list[tuple[str, str, str]] = []            # (类型, 对象, 原因)


def api_list(endpoint: str, expression: str) -> list[dict]:
    """`gh api --paginate` 读列表端点，逐行 JSON 解析。

    读不到直接退出：清单不完整时宁可不动手，也不删半个仓库。
    """
    result = subprocess.run(["gh", "api", "--paginate", endpoint, "--jq", expression],
                            capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"读取 {endpoint} 失败（gh 退出码 {result.returncode}）：{result.stderr.strip()}")
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def repo_id() -> int:
    result = subprocess.run(["gh", "api", f"repos/{REPO}", "--jq", ".id"], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip().isdigit():
        sys.exit(f"读取 repos/{REPO} 失败：{result.stderr.strip() or result.stdout.strip()}")
    return int(result.stdout.strip())


def run_time(row: dict) -> str:
    """排序统一用 run_started_at；一直排队没真正开始过时该字段缺失，退回 created_at。"""
    return row.get("run_started_at") or row.get("created_at") or ""


def stamp(row: dict) -> str:
    """把运行时刻转成 UTC+8 的可读时间，日志里不出现零时区后缀。"""
    raw = run_time(row)
    if not raw:
        return "未知时间"
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(CLOCK).strftime(
        "%Y-%m-%d %H:%M:%S")


def version_parts(name: str):
    """`Selffont-yy.m.d.当日序号.总序号` → (日期, 当日序号, 总序号)；不合口径返回 None。"""
    if not name.startswith(PREFIX):
        return None
    parts = name[len(PREFIX):].split(".")
    if len(parts) != SEGMENTS:
        return None
    try:
        return ".".join(parts[:3]), int(parts[3]), int(parts[4])
    except ValueError:
        return None


def segments_of(name: str) -> int:
    version = name[len(PREFIX):] if name.startswith(PREFIX) else name
    return len([part for part in version.split(".") if part])


def zero_padded(name: str) -> str | None:
    """补零段（`26.11.01`、`26.11.1.01.7`）返回该段，合规返回 None。

    规范 2026-10-31：月、日、当日序号、总序号都不带前导零；`00` 这类段也不合法。
    """
    version = name[len(PREFIX):] if name.startswith(PREFIX) else name
    for part in version.split("."):
        if len(part) > 1 and part.startswith("0"):
            return part
    return None


def plan(kind: str, endpoint: str, label: str, method: str = "DELETE", verb: str = "删除",
         tag: str | None = None) -> None:
    PENDING.append({"kind": kind, "endpoint": endpoint, "label": label,
                    "method": method, "verb": verb, "tag": tag})


def permission_gap(stderr: str) -> bool:
    return "HTTP 403" in stderr or "Resource not accessible by integration" in stderr


def execute() -> None:
    print("=== 待处理清单（以下对象均已判定，清单打印完才动手） ===")
    if not PENDING:
        print("无")
    for item in PENDING:
        print(f"{item['verb']}[{item['kind']}] {item['method']} {item['endpoint']} 对象={item['label']}")
    if not APPLY:
        print("=== 预演结束：未执行任何删除（CLEANUP_APPLY=false） ===")
        return
    live_tags: set[str] | None = None
    for item in PENDING:
        kind, endpoint, label = item["kind"], item["endpoint"], item["label"]
        method, verb = item["method"], item["verb"]
        if kind == "tag":
            # 删 tag 前重取一次 Release：上一项 Release 若因 403 没删成，它的 tag 不能被当成孤立 tag 删掉。
            if live_tags is None:
                live_tags = {row.get("tag_name") for row in
                             api_list(f"repos/{REPO}/releases?per_page=100", ".[] | {tag_name}")}
            if item["tag"] in live_tags:
                print(f"跳过[tag] {item['tag']}（对应 Release 仍在，不当孤立 tag 删）")
                continue
        result = subprocess.run(["gh", "api", "-X", method, endpoint], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"已{verb}[{kind}] {label}")
            continue
        stderr = result.stderr.strip()
        if permission_gap(stderr):
            PERMISSION_GAPS.append((kind, endpoint, label))
            print(f"::warning::{verb}失败（403 权限缺口，跳过）：对象={label}；端点={method} {endpoint}；"
                  f"gh 返回码={result.returncode}；{stderr[:180]}")
            continue
        print(f"::error::{verb}失败：对象={label}；端点={method} {endpoint}；gh 返回码={result.returncode}；"
              f"{stderr[:220]}")
        FAILURES.append((kind, label, f"端点={method} {endpoint}；gh 返回码={result.returncode}"))
    if PERMISSION_GAPS:
        print(f"=== {len(PERMISSION_GAPS)} 项因 403 权限缺口未执行，不计为清理成功 ===")
    if FAILURES:
        sys.exit(f"{len(FAILURES)} 项删除失败（非 403），详见上方 ::error:: 行")


# ------------------------------------------------------------------ artifact / run

def clean_actions() -> None:
    runs = api_list(f"repos/{REPO}/actions/runs?per_page=100",
                    ".workflow_runs[] | {id,path,event,status,run_number,run_started_at,created_at}")
    run_by_id = {row["id"]: row for row in runs}

    # run 保留集合先算：每个工作流最新 5 条，硬上限不设当日、失败、承载产物等任何豁免。
    by_workflow: dict[str, list[dict]] = defaultdict(list)
    for row in runs:
        by_workflow[row.get("path") or ""].append(row)
    kept_run_ids: dict[str, set[int]] = {}
    for path, rows in by_workflow.items():
        ordered = sorted(rows, key=lambda row: (run_time(row), row["id"]), reverse=True)
        kept_run_ids[path] = {row["id"] for row in ordered[:KEEP_RUNS]}

    print(f"=== {PROJECT} 清理：{MODEL}；SEGMENTS={SEGMENTS}；run 每工作流最多 {KEEP_RUNS} 条、"
          f"artifact 全仓最多 {KEEP_ARTIFACTS} 个；今日(UTC+8)="
          f"{datetime.now(CLOCK).strftime('%Y-%m-%d')}；前缀={PREFIX}；本次运行 {RUN_ID} ===")

    for path, rows in sorted(by_workflow.items()):
        ordered = sorted(rows, key=lambda row: (run_time(row), row["id"]), reverse=True)
        for index, row in enumerate(ordered):
            label = (f"{path} {stamp(row)} run_number={row['run_number']} id={row['id']} "
                     f"status={row['status']}")
            if row["id"] in kept_run_ids[path]:
                print(f"保留[run] {label}（最新 {index + 1}/{KEEP_RUNS}）")
                continue
            if row["id"] == RUN_ID:
                print(f"保留[run] {label}（本次运行自己，永不取消不删）")
                continue
            if row["status"] != "completed":
                plan("run", f"repos/{REPO}/actions/runs/{row['id']}/cancel", label,
                     method="POST", verb="取消")
                continue
            plan("run", f"repos/{REPO}/actions/runs/{row['id']}", label)

    artifacts = api_list(f"repos/{REPO}/actions/artifacts?per_page=100",
                         ".artifacts[] | {id,name,created_at,workflow_run}")
    owner = repo_id()

    def owned(row: dict) -> bool:
        run = row.get("workflow_run") or {}
        return run.get("repository_id") == owner and run.get("head_repository_id") == owner

    candidates, unknown = [], []
    for row in artifacts:
        if not row["name"].startswith(PREFIX):
            continue
        if not owned(row):
            unknown.append(row)
            continue
        candidates.append(row)
    for row in unknown:
        print(f"保留[artifact] {row['created_at']} {row['name']} id={row['id']}"
              "（归属不明，不判定）")

    def source_run(row: dict) -> dict:
        return run_by_id.get((row.get("workflow_run") or {}).get("id")) or {}

    def source_label(row: dict) -> str:
        run = source_run(row)
        if not run:
            return f"{row['created_at']} {row['name']} id={row['id']} 来源运行未知"
        return (f"{row['created_at']} {row['name']} id={row['id']} "
                f"来源 run_number={run['run_number']} run_id={run['id']}")

    survivors: list[dict] = []
    victims: list[tuple[dict, str]] = []
    for row in candidates:
        if (row.get("workflow_run") or {}).get("id") == RUN_ID:
            print(f"保留[artifact] {source_label(row)}（本次运行刚产出，不判定）")
            survivors.append(row)
            continue
        # 判据一：命名口径（段数 + 不带前导零）。
        if segments_of(row["name"]) != SEGMENTS:
            victims.append((row, f"命名口径（{segments_of(row['name'])} 段 != SEGMENTS {SEGMENTS}）"))
            continue
        padded = zero_padded(row["name"])
        if padded:
            victims.append((row, f"命名口径（补零段 {padded!r}，规范只收 26.11.1 这种写法）"))
            continue
        run = source_run(row)
        # 判据二：来源。
        if run.get("event") == "pull_request":
            victims.append((row, "来源（workflow_run.event 是 pull_request）"))
            continue
        survivors.append(row)

    # 判据三：重复当日序号，按来源运行的 run_started_at 删旧留新。
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in survivors:
        parsed = version_parts(row["name"])
        if parsed is None:
            continue
        groups[(parsed[0], parsed[1])].append(row)
    duplicate_ids = set()
    for (date, day), rows in groups.items():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda row: (run_time(source_run(row)), row["id"]), reverse=True)
        for row in rows[1:]:
            victims.append((row, f"重复当日序号 {date}.{day}（保留 run_started_at 最新的 "
                                 f"{source_run(rows[0]).get('run_number', '?')}）"))
            duplicate_ids.add(row["id"])
    survivors = [row for row in survivors if row["id"] not in duplicate_ids]

    # 判据四：号源口径，末段总序号必须等于来源运行的 run_number。
    fresh, stale = [], []
    for row in survivors:
        parsed = version_parts(row["name"])
        run = source_run(row)
        if parsed is None or not run:
            fresh.append(row)
            print(f"保留[artifact] {source_label(row)}（号源无法核验，不当删除依据）")
            continue
        (fresh if parsed[2] == run.get("run_number") else stale).append(row)
    if fresh or not stale:
        for row in stale:
            victims.append((row, f"号源口径（总序号 {version_parts(row['name'])[2]} != 来源 "
                                 f"run_number {source_run(row).get('run_number')}）"))
    else:
        # 过渡期：全仓还没有任何新口径产物，暂留最新 1 个旧产物，别让手上一个可装的包都没有。
        keep = max(stale, key=lambda row: (row["created_at"], row["id"]))
        fresh.append(keep)
        print(f"保留[artifact] {source_label(keep)}"
              "（换号源过渡：全仓暂无新口径产物，暂留最新 1 个旧产物）")
        for row in stale:
            if row["id"] != keep["id"]:
                victims.append((row, f"号源口径（总序号 {version_parts(row['name'])[2]} != 来源 "
                                     f"run_number {source_run(row).get('run_number')}）"))

    # 判据五：数量，全仓最新 5 个，且来源运行必须仍在所属工作流保留的最新 5 条里。
    fresh.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
    kept_artifacts: list[dict] = []
    for index, row in enumerate(fresh):
        run = source_run(row)
        workflow = run.get("path") or ""
        if len(kept_artifacts) >= KEEP_ARTIFACTS:
            victims.append((row, f"数量（全仓第 {index + 1} 新，超过 {KEEP_ARTIFACTS}）"))
        elif workflow and run.get("id") not in kept_run_ids.get(workflow, set()):
            victims.append((row, f"运行记录上限优先（来源 run {run.get('id')} 不在 {workflow} "
                                 f"最新 {KEEP_RUNS} 条内）"))
        else:
            kept_artifacts.append(row)

    for row in kept_artifacts:
        print(f"保留[artifact] {source_label(row)}")
    for row, why in victims:
        plan("artifact", f"repos/{REPO}/actions/artifacts/{row['id']}",
             f"{source_label(row)} 判据={why}")
    print(f"artifact：候选 {len(candidates)} 个，保留 {len(kept_artifacts)} 个，"
          f"{'删除' if APPLY else '将删'} {len(victims)} 个，归属不明 {len(unknown)} 个")
    print(f"run：{'删除' if APPLY else '将删'} "
          f"{sum(1 for item in PENDING if item['kind'] == 'run' and item['verb'] == '删除')} 条，"
          f"{'取消' if APPLY else '将取消'} "
          f"{sum(1 for item in PENDING if item['kind'] == 'run' and item['verb'] == '取消')} 条")


# ------------------------------------------------------------------ Release / tag

def clean_releases() -> None:
    releases = api_list(f"repos/{REPO}/releases?per_page=100",
                        ".[] | {id,tag_name,name,created_at,published_at}")
    tags = api_list(f"repos/{REPO}/tags?per_page=100", ".[] | {name}")
    ordered = sorted(releases,
                     key=lambda row: (row.get("published_at") or row.get("created_at") or "", row["id"]),
                     reverse=True)
    kept, extra = ordered[:KEEP_RELEASES], ordered[KEEP_RELEASES:]
    kept_tags = {row.get("tag_name") for row in kept if row.get("tag_name")}
    print(f"=== {PROJECT} Release/tag 清理：{MODEL}；Release 保留 {KEEP_RELEASES} 个；"
          f"tag 前缀 {PREFIX} ===")
    for row in kept:
        print(f"保留[release] id={row['id']} tag={row.get('tag_name')} name={row.get('name')}")
    for row in extra:
        plan("release", f"repos/{REPO}/releases/{row['id']}",
             f"id={row['id']} tag={row.get('tag_name')} name={row.get('name')}")
    for row in tags:
        name = row["name"]
        if not name.startswith(PREFIX):
            print(f"保留[tag] {name}（不属于本项目名前缀，不判定）")
        elif name in kept_tags:
            print(f"保留[tag] {name}（对应保留的 Release）")
        else:
            plan("tag", f"repos/{REPO}/git/refs/tags/{quote(name, safe='')}",
                 f"name={name}（无对应保留 Release）", tag=name)


def verify() -> None:
    """清理后复核：数量仍超限且本轮没有 403 缺口，就当轮失败，不把没删成说成清理成功。"""
    if not APPLY:
        return
    if SCOPE == "actions":
        artifacts = api_list(f"repos/{REPO}/actions/artifacts?per_page=100",
                             ".artifacts[] | {id,name,workflow_run}")
        left = [row for row in artifacts if row["name"].startswith(PREFIX)]
        gap = any(kind == "artifact" for kind, _, _ in PERMISSION_GAPS)
        print(f"复核：artifact 当前剩 {len(left)} 个（上限 {KEEP_ARTIFACTS}）")
        if gap:
            print("复核未完成：artifact 清理遇到 403 权限缺口，未把未删对象描述成清理成功。")
        elif len(left) > KEEP_ARTIFACTS:
            FAILURES.append(("artifact", "清理后数量", f"实际剩 {len(left)} 个，超过 {KEEP_ARTIFACTS}"))
        runs = api_list(f"repos/{REPO}/actions/runs?per_page=100",
                        ".workflow_runs[] | {id,path,status}")
        per_workflow: dict[str, list[dict]] = defaultdict(list)
        for row in runs:
            per_workflow[row.get("path") or ""].append(row)
        cancel_gap = any(kind == "run" for kind, _, _ in PERMISSION_GAPS)
        for path, rows in sorted(per_workflow.items()):
            active = [row for row in rows if row["status"] != "completed" or row["id"] == RUN_ID]
            print(f"复核：{path} 当前剩 {len(rows)} 条（上限 {KEEP_RUNS}；其中未完成/本次运行 "
                  f"{len(active)} 条）")
            if cancel_gap:
                print(f"复核未完成：{path} 的运行清理遇到 403 权限缺口。")
            elif len(rows) > KEEP_RUNS + len(active):
                FAILURES.append(("run", path, f"清理后仍有 {len(rows)} 条，超过 {KEEP_RUNS}"))
    else:
        releases = api_list(f"repos/{REPO}/releases?per_page=100", ".[] | {id,tag_name}")
        tags = api_list(f"repos/{REPO}/tags?per_page=100", ".[] | {name}")
        kept_tags = {row.get("tag_name") for row in releases[:KEEP_RELEASES] if row.get("tag_name")}
        orphans = [row for row in tags if row["name"].startswith(PREFIX) and row["name"] not in kept_tags]
        gap = any(kind in ("release", "tag") for kind, _, _ in PERMISSION_GAPS)
        print(f"复核：Release 剩 {len(releases)} 个（上限 {KEEP_RELEASES}）；项目孤立 tag {len(orphans)} 个")
        if gap:
            print("复核未完成：Release/tag 清理遇到 403 权限缺口，未把未删对象描述成清理成功。")
        else:
            if len(releases) > KEEP_RELEASES:
                FAILURES.append(("release", "清理后数量", f"实际剩 {len(releases)} 个"))
            for row in orphans:
                FAILURES.append(("tag", row["name"], "清理后仍然存在"))
    if FAILURES:
        for kind, label, reason in FAILURES:
            print(f"::error::清理后仍超限[{kind}] {label}：{reason}")
        sys.exit(f"{len(FAILURES)} 项清理复核未通过")


def main() -> None:
    if SCOPE == "actions":
        clean_actions()
    else:
        clean_releases()
    execute()
    verify()


if __name__ == "__main__":
    main()
