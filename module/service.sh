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

i=0
while [ "$i" -lt "$WAIT" ]; do
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

echo "$(now) 等了 ${WAIT} 秒仍没有 sys.boot_completed=1，计数保留" >> "$GUARD_LOG" 2>/dev/null
exit 0
