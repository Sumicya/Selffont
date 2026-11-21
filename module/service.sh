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
# 同 post-fs-data.sh：非数字会让 [ -lt ] 报 Illegal number，循环一秒都不跑，
# 守夜直接落到「超时」分支，把好机器记成「没能确认走到底」。
case "$WAIT" in ''|*[!0-9]*) WAIT=120 ;; esac

now() { date +%Y-%m-%dT%H:%M:%S%z 2>/dev/null || echo 未知时刻; }

# KernelSU 的 resetprop（事件驱动等待，不轮询）；夹具可用 $SELFFONT_RESETPROP 换掉。
RESETPROP=${SELFFONT_RESETPROP:-/data/adb/ksu/bin/resetprop}

# 同 post-fs-data.sh：先留一行「我到了」。没这一行就分不清
# 「守夜没跑」和「跑了但路径写不进去」。
mkdir -p "$DATA" 2>/dev/null
printf '%s 守夜进来了 pid=%s\n' "$(date +%H:%M:%S 2>/dev/null)" "$$" >> "$GUARD_LOG" 2>/dev/null

# ★ 2026-11-09 主人打回的第二个致命 bug：等待循环原来写在**前台**。
#   init 的 service.d 进程在开机收尾时会被回收，前台循环跟着被杀 ——
#   于是 sys.boot_completed=1 明明到了，「计数清零」这一步却来不及跑。
#   两次 bug 叠加（post-fs-data 的窗口判据是死分支 + 这里清不掉），
#   正常用一天、重启一次，模块就把自己 disable 掉了。
#
# 现在：整段等待**放进后台子进程**，立刻 return，让 init 收尾时本脚本已经退出。
# 等待本身不用手写循环：KernelSU 自带 resetprop -w（底层 futex 阻塞，属性变 1 立刻醒），
# 没有 sleep、没有轮询、也不占前台。找不到 resetprop 就明说等不了（不静默）。
wait_boot_completed() {
    if [ "$(getprop sys.boot_completed 2>/dev/null)" = "1" ]; then
        return 0
    fi
    if [ -x "$RESETPROP" ]; then
        # 封顶：等不到就自己退出，别留一个永久挂着的子进程。
        if command -v timeout >/dev/null 2>&1; then
            timeout "$WAIT" "$RESETPROP" -w sys.boot_completed 1
        else
            "$RESETPROP" -w sys.boot_completed 1
        fi
        [ "$(getprop sys.boot_completed 2>/dev/null)" = "1" ] && return 0
    fi
    # 没有 resetprop 就明说「等不了」，不用 sleep 轮询糊过去（§8 禁 sleep 与手写循环）。
    # 本模块只在 KernelSU 下运行，resetprop 必定存在；真缺了要让人看见，不许静默。
    echo "$(now) 找不到 $RESETPROP，无法事件等待 sys.boot_completed；计数保留" >> "$GUARD_LOG" 2>/dev/null
    return 1
}

(
    if wait_boot_completed; then
        n=$(cat "$COUNT" 2>/dev/null)
        case "$n" in ''|*[!0-9]*) n=? ;; esac
        echo "$(now) 开机走到底（第 $n 次），计数清零" >> "$GUARD_LOG" 2>/dev/null
        rm -f "$COUNT" 2>/dev/null
    else
        echo "$(now) 没等到 sys.boot_completed=1，计数保留（这次开机没能确认走到底）" >> "$GUARD_LOG" 2>/dev/null
    fi
) &

echo "$(now) 守夜已转后台（pid=$!），前台立即退出，等 init 收尾"
exit 0
