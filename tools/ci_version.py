#!/usr/bin/env python3
"""版本取号（纯标准库，不 import fontTools）。

`build.py` 与 `selfrounds.yml` / `hotswap.yml` 共用这一份：号源只有一处，规则只有一份实现。
放在 tools/ 而不是 build.py 里，是因为 selfrounds／hotswap 两条工作流没有装 fontTools，
它们只需要「算出版本串」这一件事。

直接跑（CI 里）：
  VERSION=$(python3 tools/ci_version.py --workflow selfrounds.yml)
读 `CI_WORKFLOW` 或 `--workflow`，默认 `build.yml`；打印 `yy.m.d.当日序号.总序号` 到 stdout，
取号的明细（head / run_number / R_first）打到 stderr。取不到就退出，不降级、不编数。
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

CLOCK = timezone(timedelta(hours=8))   # 版本号里的日期按 UTC+8（否则 CI 在 UTC 下会差一天）
PROJECT = "selffont"                   # 产物名的项目段：<项目名>-<版本>

# 每条工作流只认**自己**那一类产物当前导锚点。全仓四类产物同名同段，混着读会把两条号源搅在一起：
# build.yml 出的是 `build-*`，2026-11-06 之前这里写死 `selffont-`，于是母版那条永远找不到锚点——
# 当日运行攒到 5 条（保留上限）就撞 AnchorUnavailable，母版不再出包。这是实测踩出来的，不是推演。
ARTIFACT_PREFIX = {
    "build.yml": "build-",
    "selffont.yml": "selffont-",
    "selfrounds.yml": "selfrounds-",
    "hotswap.yml": "hotswap-",
}


def check_number(value: str, label: str, minimum: int = 0) -> str:
    if not value.isdigit() or int(value) < minimum:
        raise ValueError(f"{label}必须是 ≥{minimum} 的十进制整数，收到 {value!r}")
    return value


def gh_json(endpoint: str, key: str) -> list[dict]:
    """`gh api --paginate` 读一个分页端点，按 id 去重后返回列表。

    翻页期间若有新对象插队，同一对象会在两页里各出现一次；按 id 去重避免它被当成两条。
    取不到（无令牌、端点错、网络失败）直接抛，不用空列表冒充「没有历史」。
    """
    result = subprocess.run(["gh", "api", "--paginate", endpoint], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh api {endpoint} 退出码 {result.returncode}：{result.stderr.strip()}")
    rows, seen, index, raw = [], set(), 0, result.stdout
    decoder = json.JSONDecoder()
    while True:
        while index < len(raw) and raw[index] in " \r\n\t":
            index += 1
        if index >= len(raw):
            return rows
        page, index = decoder.raw_decode(raw, index)
        for row in page.get(key, []):
            if row.get("id") not in seen:
                seen.add(row.get("id"))
                rows.append(row)


def run_day(row: dict) -> date:
    """运行开始时刻转 UTC+8 的日期；`run_started_at` 缺失（一直排队没真正开始）退回 `created_at`。"""
    stamp = row.get("run_started_at") or row.get("created_at") or ""
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(CLOCK).date()


# 与 .github/scripts/cleanup.py 的 KEEP_RUNS 一致：每个工作流只留最新 5 条运行记录。
# 达到这个数就说明历史已被删过，当日更早的运行可能不在了——见 AnchorUnavailable。
KEEP_RUNS = 5


class AnchorUnavailable(RuntimeError):
    """当日首条运行号取不到：运行记录已达保留上限，更早的当日运行可能已被清理删掉。

    规范 §222「取不到即退出，不降级、不编数」。过去这里静默回落成当日序号 1，
    于是同一天会产出重复的当日序号，清理按「重复当日序号」再删掉更早那个包——
    编出来的数会把证据一起吃掉。
    """


def artifact_anchor(name: str, date: str, prefix: str = f"{PROJECT}-") -> int | None:
    """产物名 `selffont-yy.m.d.d0.r0` 反推当日首条运行号 `r0 - d0 + 1`；口径不合返回 None。

    前缀由调用方按工作流给（`ARTIFACT_PREFIX`），默认 `selffont-`。全仓四类产物各是各的序列：
    `build-26.11.6.1.320` 也是五段，不卡前缀就会被当成当日首个产物，把两条号源搅在一起。
    """
    if not name.startswith(prefix):
        return None
    version = name[len(prefix):]
    parts = version.split(".")
    if len(parts) != 5 or ".".join(parts[:3]) != date:
        return None
    try:
        day, total = int(parts[3]), int(parts[4])
    except ValueError:
        return None
    return total - day + 1 if day >= 1 and total >= day else None


def ci_version_numbers(runs: list[dict], artifacts: list[dict], run_number: int,
                       now: datetime, prefix: str = f"{PROJECT}-") -> tuple[str, int, int, int]:
    """差值锚定法取号：返回 (日期, 当日序号, 总序号, 当日首条运行号 R_first)。

    总序号取 `run_number` 原值（同一 run 重试时 GitHub 不换 run_number，版本号自然不变）。
    当日序号按差值锚定：当日现存 `build.yml` 运行的最小 `run_number`，与当日现存产物
    `selffont-yy.m.d.d0.r0` 反推的 `r0 - d0 + 1`，两者取小作 `R_first`（都没有就取当前
    `run_number`），当日序号 = 当前 `run_number - R_first + 1`。失败运行同样占号，
    `pull_request` 运行永不计入。锚点比当前号还大（旧运行已删）时钳到当前号，序号不小于 1。

    两个锚点都可能被清理吃掉（运行记录每工作流只留 5 条、artifact 每仓只留 5 个）。
    所以再加一条：**没有产物锚点、运行记录又已顶到保留上限**时抛 `AnchorUnavailable`，
    宁可不出包也不编数——静默回落成当日序号 1 会产出重复号，清理再按「重复当日序号」
    删掉更早那个包，编出来的数连证据一起吃。

    纯函数：只吃 API 读到的数据，不碰网络也不碰 git，自检用合成数据覆盖各分支。
    """
    total = int(check_number(str(run_number), "总序号", 1))
    moment = now.astimezone(CLOCK)
    date = f"{moment.year % 100}.{moment.month}.{moment.day}"
    today = moment.date()
    today_runs: list[int] = []
    older_days = 0
    for row in runs:
        if row.get("event") == "pull_request" or not row.get("run_number"):
            continue
        try:
            started = run_day(row)
        except (TypeError, ValueError):
            continue
        if started == today:
            today_runs.append(int(row["run_number"]))
        else:
            older_days += 1
    anchors = list(today_runs)
    artifact_anchors = []
    for row in artifacts:
        anchor = artifact_anchor(row.get("name", ""), date, prefix)
        if anchor is not None:
            artifact_anchors.append(anchor)
    anchors.extend(artifact_anchors)
    # 清理按 run_started_at 从旧到新删。只要还留着一条**往日**的运行，就能证明今天没有任何
    # 运行被删过（今天的一定比昨日的新），现存最小号就是真首条；反之若 5 条全是今天的，
    # 今天的首条可能已经被挤掉了，这时没有产物锚点就证不出来。
    capped_to_today = len(runs) >= KEEP_RUNS and today_runs and older_days == 0
    if not artifact_anchors and capped_to_today:
        # 没有产物锚点可证，而运行记录已经顶到保留上限：今天更早的那几条可能被删了，
        # 拿现存最小号当首条会算小当日序号。宁可不出包，不编数。
        raise AnchorUnavailable(
            f"当日锚点取不到：build.yml 现存 {len(runs)} 条运行已达保留上限 {KEEP_RUNS}，" 
            f"且现存 {KEEP_RUNS} 条全是今天的，今日首条可能已被挤掉；现存最小 run_number={min(today_runs)}，"
            f"当前 {total}。按规范「取不到即退出，不降级、不编数」停止出包。"
            "下一轮先攒推送（一次会话一次推送），让运行数落回上限内再出包。")
    first = min(min(anchors), total) if anchors else total
    day = total - first + 1
    check_number(str(day), "当日序号", 1)
    return date, day, total, first


def query_ci_version() -> tuple[str, str, str]:
    """CI 现场取号：读 `build.yml` 运行列表与全仓产物列表，按差值锚定法算出三段版本。

    取不到即抛：不降级、不编数。启动行打印 head SHA、run_id、run_number、R_first、当日序号
    与最终版本，和产物名逐字可对。

    读哪条工作流的运行列表由 `CI_WORKFLOW` 决定（默认 `build.yml`，即母版那条）。
    自版走自己那条 `selffont.yml`，号源才不会跟母版的运行数混在一起。
    """
    repo = (os.environ.get("REPO") or os.environ.get("GITHUB_REPOSITORY") or "").strip()
    run_number = (os.environ.get("RUN_NUMBER") or os.environ.get("GITHUB_RUN_NUMBER") or "").strip()
    if not repo or not run_number.isdigit() or int(run_number) < 1:
        sys.exit("--query-ci 只在 CI 里成立：REPO/GITHUB_REPOSITORY 与 "
                           f"RUN_NUMBER/GITHUB_RUN_NUMBER 都要取到，实际 REPO={repo!r} "
                           f"RUN_NUMBER={run_number!r}")
    now = datetime.now(timezone.utc).astimezone(CLOCK)
    workflow = (os.environ.get("CI_WORKFLOW") or "build.yml").strip()
    try:
        runs = gh_json(f"repos/{repo}/actions/workflows/{workflow}/runs?per_page=100", "workflow_runs")
    except RuntimeError as error:
        # 工作流一次都没跑过时，`/workflows/<文件名>` 还没注册（404）。退回全仓运行列表按 path 过滤：
        # 只要它跑起来过，这里就一定取得到；表里没有，仍然照样抛错——不拿空列表冒充「没有历史」。
        if "HTTP 404" not in str(error):
            raise
        path_suffix = f"/{workflow}"
        runs = [row for row in gh_json(f"repos/{repo}/actions/runs?per_page=100", "workflow_runs")
                if str(row.get("path", "")).endswith(path_suffix)]
    artifacts = gh_json(f"repos/{repo}/actions/artifacts?per_page=100", "artifacts")
    prefix = ARTIFACT_PREFIX.get(workflow, f"{PROJECT}-")
    try:
        date, day, total, first = ci_version_numbers(runs, artifacts, int(run_number), now, prefix)
    except AnchorUnavailable as error:
        sys.exit(f"[取号失败] {error}")
    print(f"[取号] head={os.environ.get('GITHUB_SHA', '未提供')} "
          f"run_id={os.environ.get('GITHUB_RUN_ID', '未提供')} run_number={total} R_first={first} "
          f"当日序号={day} 版本={date}.{day}.{total}（UTC+8 {now:%Y-%m-%d %H:%M:%S}）", file=sys.stderr)
    return date, str(day), str(total)


def main(argv: list[str] | None = None) -> int:
    """打印一个版本串到 stdout；`--workflow` 决定读哪条工作流的运行列表。"""
    args = list(sys.argv[1:] if argv is None else argv)
    workflow = ""
    while args:
        item = args.pop(0)
        if item == "--workflow":
            workflow = args.pop(0) if args else ""
        elif item.startswith("--workflow="):
            workflow = item.split("=", 1)[1]
        else:
            sys.exit(f"不认识的参数 {item!r}；只用 --workflow <文件名>")
    if workflow:
        os.environ["CI_WORKFLOW"] = workflow
    date, day, total = query_ci_version()
    print(f"{date}.{day}.{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
