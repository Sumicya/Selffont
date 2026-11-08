#!/system/bin/sh
# Selffont 开机守夜（late_start service，开机后由 init 拉起）。
#
# 只干一件事：等到 sys.boot_completed=1 就把 post-fs-data.sh 写的失败计数清零，
# 并记一行「这次开机走到底了」。这样下一次开机才能分辨「上次卡住」和「上次正常」。
#
# 为什么不在 post-fs-data 里判断：那一步本来就在关机链的最前面，
# 「这次开机成功没有」只有一个判据——sys.boot_completed。它只能在这里等。
#
# 超时（SELFFONT_BOOT_WAIT，默认 120 秒）内没等到就退出，**不清零**：
# 卡住的情形下本脚本自己也活不到 sys.boot_completed，计数自然保持，
# 下一次开机 post-fs-data.sh 会发现它又涨了一次。

DATA=${SELFFONT_DATA:-/data/adb/selffont}
COUNT="$DATA/boot-count"
GUARD_LOG="$DATA/guard.log"
WAIT=${SELFFONT_BOOT_WAIT:-120}

now() { date +%Y-%m-%dT%H:%M:%S%z 2>/dev/null || echo 未知时刻; }

# 同 post-fs-data.sh：先留一行「我到了」。没这一行就分不清
# 「守夜没跑」和「跑了但路径写不进去」。
mkdir -p "$DATA" 2>/dev/null
printf '%s 守夜进来了 pid=%s\n' "$(date +%H:%M:%S 2>/dev/null)" "$$" >> "$GUARD_LOG" 2>/dev/null

# ★ 2026-11-08 真机：22:06:22 第 1 次开机开始 → 22:06:24 守夜进来了 → 之后什么都没写。
#   系统其实起来了（主人 22:09 在敲命令），说明守夜是在等 sys.boot_completed 时
#   被 init 清掉的（service.d 的进程开完机会被收），不是没跑。
#   改法：①每 10 秒记一行心跳，被清掉时能看出停在哪一秒；
#        ②最后一行不管等到没等到都写，并且写明「被中途杀掉」与「等到超时」的区别。
i=0
while [ "$i" -lt "$WAIT" ]; do
    case $((i % 10)) in
        0) echo "$(now) 守夜等待中：${i} 秒，sys.boot_completed=$(getprop sys.boot_completed 2>/dev/null)" >> "$GUARD_LOG" 2>/dev/null ;;
    esac
    if [ "$(getprop sys.boot_completed 2>/dev/null)" = "1" ]; then
        n=$(cat "$COUNT" 2>/dev/null)
        case "$n" in ''|*[!0-9]*) n=? ;; esac
        echo "$(now) 开机走到底（第 $n 次），计数清零" >> "$GUARD_LOG" 2>/dev/null
        rm -f "$COUNT" 2>/dev/null
        exit 0
    fi
    i=$((i + 1))
    sleep 1
done

echo "$(now) 等了 ${WAIT} 秒仍没有 sys.boot_completed=1，计数保留（这次开机没能确认走到底）" >> "$GUARD_LOG" 2>/dev/null
exit 0
