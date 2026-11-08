#!/system/bin/sh
# Selffont 开机守卫（post-fs-data 阶段，每次开机最早能跑起来的模块脚本）。
#
# 为什么要有这个文件（2026-11-08 真机事故）：
#   装了模块之后手机卡在第一屏不动，主人只能长按电源键强制重启，反复几次之后
#   系统进安全模式。查了两天查不出一条证据，原因不是「没崩干净」，是**根本没崩**：
#     · /sys/fs/pstore 三个文件全空       → 内核没 panic
#     · /data/system/dropbox 无 system_server_crash → 用户态没抛异常
#     · /data/tombstones 里 31 个全指向 com.android.launcher 的 libuleflutter.so
#       → 那是 OPPO 桌面插件自己的递归 bug，keyProcess: 0，不触发安全模式
#     · getprop ro.boot.bootreason = 2sec_reboot
#       → AOSP bootstat.cpp: *2sec_reboot*) var="cold,rtc,2sec"；这是**电源键强制重启**
#   结论：进程是**阻塞**，不是崩溃。阻塞不写 pstore、不写 tombstone，证据只在
#   logcat 的环形缓冲区里，而强制重启会把内存缓冲一起抹掉。
#
# 所以本脚本干两件事：
#   ① 开机计数：连续 MAX 次开机没走到 boot-completed 就自动打 disable 标记，
#      下次开机系统直接跳过本模块——主人不必再手动进安全模式。
#      计数由 service.sh 里的守夜子进程在 sys.boot_completed=1 之后清零。
#   ② 日志落盘：开机就在后台把 logcat 写进 /data/adb/selffont/boot.log。
#      卡住的那一次，缓冲区进不了磁盘，但**已经开始写到磁盘的那部分留下来了**。
#
# 两个开关（都做成默认值，不改默认行为）：
#   SELFFONT_MAX_BOOT_FAIL  连续失败几次自动停用，默认 2
#   SELFFONT_NO_LOGCAT=1    不抓开机日志

MODDIR=${MODDIR:-${0%/*}}
DATA=${SELFFONT_DATA:-/data/adb/selffont}
COUNT="$DATA/boot-count"
GUARD_LOG="$DATA/guard.log"
BOOT_LOG="$DATA/boot.log"
MAX=${SELFFONT_MAX_BOOT_FAIL:-2}

mkdir -p "$DATA" 2>/dev/null

# 时间戳用 +0800（本机主人所在时区）；date 不可用时给个占位，不许因此中断。
now() { date +%Y-%m-%dT%H:%M:%S%z 2>/dev/null || echo 未知时刻; }

# ---- ① 开机计数 ----
# 先写计数再干别的：万一本脚本自己后面卡住，这次开机也已经算进去了。
n=$(cat "$COUNT" 2>/dev/null)
case "$n" in ''|*[!0-9]*) n=0 ;; esac
n=$((n + 1))
echo "$n" > "$COUNT" 2>/dev/null

if [ "$n" -gt "$MAX" ]; then
    # 连续 MAX+1 次没走到 boot-completed：判定本模块是卡住的原因，自己停用自己。
    # 停用是 KernelSU 的官方机制（模块目录下一个叫 disable 的空文件），可逆：
    # 主人把那个文件删掉、重启，模块就回来。
    : > "$MODDIR/disable" 2>/dev/null
    echo "$(now) 连续第 $n 次开机没走到 boot-completed（阈值 $MAX），已自动停用：$MODDIR/disable" >> "$GUARD_LOG" 2>/dev/null
    # 停用之后不再抓日志：模块既然不生效，日志也没有意义。
    exit 0
fi
echo "$(now) 第 $n 次开机开始（阈值 $MAX）" >> "$GUARD_LOG" 2>/dev/null

# ---- ② 卡住那次的日志落盘 ----
[ "${SELFFONT_NO_LOGCAT:-0}" = "1" ] && exit 0

# 上一轮留下的 boot.log 若超过保留上限就滚一份，只留最近两份。
# 目的是让磁盘占用有上界：卡死循环里每次开机都写，不封顶会把 /data 写满。
MAX_BYTES=${SELFFONT_BOOT_LOG_BYTES:-2097152}
if [ -f "$BOOT_LOG" ] && [ "$(wc -c < "$BOOT_LOG" 2>/dev/null || echo 0)" -gt "$MAX_BYTES" ]; then
    mv -f "$BOOT_LOG" "$BOOT_LOG.1" 2>/dev/null
fi

# 后台抓：按标签过滤到与本模块和字体有关的通道，避免把整机日志都抄一遍。
# `logcat -b all` 在部分机型上要权限，失败就退回默认缓冲区；再失败就退出，不许空转。
(
    # 等 logd 起来（最多 15 秒）。post-fs-data 阶段 logd 通常已经在跑，但不保证。
    i=0
    while [ ! -e /dev/socket/logdw ] && [ "$i" -lt 15 ]; do
        i=$((i + 1))
        sleep 1
    done
    [ -e /dev/socket/logdw ] || exit 0
    if command -v timeout >/dev/null 2>&1; then
        # 用 timeout 封顶：开机 180 秒之后不再写，卡住的情形下这段正好覆盖 system_server 起来到卡死。
        timeout 180 logcat -b main,system,crash -v threadtime \
            -s minikin androidfw FontManager Typeface RescueParty Zygote64 ActivityManager Watchdog \
            >> "$BOOT_LOG" 2>/dev/null
    else
        logcat -b main,system,crash -v threadtime \
            -s minikin androidfw FontManager Typeface RescueParty Zygote64 ActivityManager Watchdog \
            >> "$BOOT_LOG" 2>/dev/null
    fi
) &

exit 0
