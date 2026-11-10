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
# 混着读会让母版那条永远找不到锚点、当日运行攒满 5 条就不出包。实测踩出来的。
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
KEEP_RUNS = 5



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

    纯函数：只吃 API 读到的数据，不碰网络也不碰 git，自检用合成数据覆盖各分支。
    """
    total = int(check_number(str(run_number), "总序号", 1))
    moment = now.astimezone(CLOCK)
    date = f"{moment.year % 100}.{moment.month}.{moment.day}"
    today = moment.date()
    today_runs: list[int] = []
    for row in runs:
        if row.get("event") == "pull_request" or not row.get("run_number"):
            continue
        try:
            started = run_day(row)
        except (TypeError, ValueError):
            continue
        if started == today:
            today_runs.append(int(row["run_number"]))
    anchors = list(today_runs)
    artifact_anchors = []
    for row in artifacts:
        anchor = artifact_anchor(row.get("name", ""), date, prefix)
        if anchor is not None:
            artifact_anchors.append(anchor)
    anchors.extend(artifact_anchors)
    # ★ 2026-11-09 拆掉一条会把自己锁死的判据（selfrounds #44/#45 连卡两条的根因）。
    #
    #   旧判据：没有产物锚点、且现存运行全是今天的、且已顶到保留上限 → 抛 AnchorUnavailable
    #   拒绝出包。它防的是「当日首条已被清理删掉，拿现存最小号当首条会把当日序号算小」。
    #   但它在一个「从来没成功出过包」的工作流上是万劫不复的：
    #     永远没有产物锚点 → 永远拒绝出包 → 每拒绝一次多一条失败运行 → 又进清理候选池
    #     → 当日运行恒满 → 再拒绝。闭环，且不需要任何人做错事就会天天复发。
    #
    #   修法不是给取号器再加一条例外，而是把前提从源头去掉：清理侧
    #   `.github/scripts/cleanup.py` 的 `pinned_anchor()` 现在**钉住当日首条不许删**，
    #   于是「当日首条已被删」这件事不再会发生，这条判据连同它的前提一起作废。
    #   取号规则收窄成唯一一条：当日序号 = 当前号 − 当日现存最小号 + 1，与产物锚点取小。
    #   右侧若真出现「首条被删」，产物锚点仍能兜住；两个锚都没有时可证最坏情况只是
    #   当日序号偏小，而当日序号偏小不会删包（删包看 created_at，不看序号）。
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
    date, day, total, first = ci_version_numbers(runs, artifacts, int(run_number), now, prefix)
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
