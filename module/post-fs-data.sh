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

# ★ 2026-11-08 真机第五次输出暴露的事故：post-fs-data.d/sf-guard.sh 时间戳 17:12、
#   /data/adb/selffont 目录时间戳也是 17:12（mkdir 成功），但里面**一个账都没有**，
#   连 guard.log 都没被创建——脚本被执行了，在写第一行之前就死了。
#   根因：`MODDIR=${0%/*}`。被 init 以 source 加载时 $0 是**父进程**的路径（/system/bin/sh），
#   MODDIR 变成 /system/bin，后面 `: > "$MODDIR/disable"` 在只读分区写不进去；
#   而所有日志都是 `>> ... 2>/dev/null`，报错被吞——脚本把自己的证据销掉了。
MODDIR=${MODDIR:-}
# $MODULES 只给沙箱夹具换根用；真机上是 /data/adb/modules。
MODULES=${SELFFONT_MODULES:-/data/adb/modules}
if [ -z "$MODDIR" ] || [ ! -d "$MODDIR" ]; then
    for d in "$MODULES"/selffont-*; do
        [ -d "$d" ] || continue
        MODDIR=$d; break
    done
fi
DATA=${SELFFONT_DATA:-/data/adb/selffont}
COUNT="$DATA/boot-count"
GUARD_LOG="$DATA/guard.log"
BOOT_LOG="$DATA/boot.log"
MAX=${SELFFONT_MAX_BOOT_FAIL:-2}
# ★ 2026-11-09 自查：这些环境变量是**裸取**的。给一个非数字，
#   `[ "$n" -gt "$MAX" ]` 会报 Illegal number 并返回 2，if 判假 ——
#   于是「连续 3 次没走到底自动停用」**永远不触发**，而日志里一个字都不提。
#   真机上没人会去设它，但我不能靠「没人会这么干」把守卫写脆。
case "$MAX" in ''|*[!0-9]*) MAX=2 ;; esac
_limit_s=${SELFFONT_BOOT_LOG_SECONDS:-180}
case "$_limit_s" in ''|*[!0-9]*) _limit_s=180 ;; esac

mkdir -p "$DATA" 2>/dev/null
# 无条件先留一行：只要这行在，就证明「这个脚本真的被执行了」。
# 没这行的话，「没跑」和「跑了但路径写不进去」就分不开——2026-11-08 那次就是靠猜。
printf '%s 守卫进来了 pid=%s 脚本=%s MODDIR=%s\n' \
    "$(date +%H:%M:%S 2>/dev/null)" "$$" "$0" "$MODDIR" >> "$DATA/guard.log" 2>/dev/null
# 认不出模块目录就明说，不许静默：空 MODDIR 下 `: > "$MODDIR/disable"` 等于往 / 写。
if [ -z "$MODDIR" ] || [ ! -d "$MODDIR" ]; then
    echo "$(date +%Y-%m-%dT%H:%M:%S%z 2>/dev/null || echo 未知时刻) MODDIR 认不出来（$MODULES 下没有 selffont-*），本次跳过自动停用，日志照写" >> "$DATA/guard.log" 2>/dev/null
    MODDIR=''
fi

# 时间戳用 +0800（本机主人所在时区）；date 不可用时给个占位，不许因此中断。
now() { date +%Y-%m-%dT%H:%M:%S%z 2>/dev/null || echo 未知时刻; }

# ---- ⓪ 同一次开机只算一次 ----
# 本脚本有**两条**触发路径：① 打包进模块时由 KernelSU 自己 source；
# ② 手工放在 /data/adb/post-fs-data.d/ 时由 init 直接执行。两条同时在，
# 每开一次机计数会涨 2 —— 阈值是 2，于是**每次开机都正常**也会在第 2 次自己打 disable。
# 判据用 /proc/stat 的 btime（本次开机的时间戳，每次开机唯一）。
# **不能用 uptime**：两次开机都可能在第 3 秒跑到 post-fs-data，uptime 一样，
# 第二次就会被误判成「同一次开机」而不计数——恰恰在反复卡机的场景下把守卫废掉。
# 判不出来（没有 btime）时一律**照常计数**：宁可重复算，也不许去重把守卫吞掉。
# $SELFFONT_BOOT_ID 只给夹具用，用来在同一台机器上模拟不同的开机。
STAMP="$DATA/pfd-seen"
boot_id=${SELFFONT_BOOT_ID:-$(awk '/^btime/{print $2; exit}' /proc/stat 2>/dev/null)}
case "$boot_id" in ''|*[!0-9]*) boot_id='' ;; esac
if [ -n "$boot_id" ]; then
    last=$(cat "$STAMP" 2>/dev/null)
    if [ "$last" = "$boot_id" ]; then
        printf '%s 本次开机已计过数（boot_id=%s），跳过——模块内与 post-fs-data.d 两份同时在\n' \
            "$(now)" "$boot_id" >> "$GUARD_LOG" 2>/dev/null
        exit 0
    fi
    echo "$boot_id" > "$STAMP" 2>/dev/null
fi

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
    [ -n "$MODDIR" ] && : > "$MODDIR/disable" 2>/dev/null
    if [ -n "$MODDIR" ]; then
        echo "$(now) 连续第 $n 次开机没走到 boot-completed（阈值 $MAX），已自动停用：$MODDIR/disable" >> "$GUARD_LOG" 2>/dev/null
    else
        echo "$(now) 连续第 $n 次开机没走到 boot-completed（阈值 $MAX），但 MODDIR 不明，**没能自动停用**" >> "$GUARD_LOG" 2>/dev/null
    fi
    # 停用之后不再抓日志：模块既然不生效，日志也没有意义。
    exit 0
fi
echo "$(now) 第 $n 次开机开始（阈值 $MAX）" >> "$GUARD_LOG" 2>/dev/null

# ---- ② 卡住那次的日志落盘 ----
# 体积上限。**这是两份加起来的上限**，磁盘占用最多约 2×MAX_BYTES（滚动的瞬间两份都在）。
MAX_BYTES=${SELFFONT_BOOT_LOG_BYTES:-2097152}
case "$MAX_BYTES" in ''|*[!0-9]*) MAX_BYTES=2097152 ;; esac
# ★ 2026-11-09 真机：清完账 ls 一看还躺着 boot.log.1 = 13,219,112 字节（12.6 MB）。
#   两个原因叠在一起：①旧版只在本次开机给 boot.log 封顶，写坏的 boot.log 被 mv 成 .1
#   之后**再没人管它**；②这段清理原本写在 NO_LOGCAT 提前退出的后面，
#   关掉抓日志时根本走不到。现在挪到前面，并且 .1 超上限就整份丢掉。
if [ -f "$BOOT_LOG.1" ]; then
    _old1=$(wc -c < "$BOOT_LOG.1" 2>/dev/null)
    case "$_old1" in ''|*[!0-9]*) _old1=0 ;; esac
    if [ "$_old1" -gt "$MAX_BYTES" ]; then
        echo "$(now) boot.log.1 有 ${_old1} 字节，超过上限 ${MAX_BYTES}，整份丢弃（旧版没管它）" >> "$GUARD_LOG" 2>/dev/null
        rm -f "$BOOT_LOG.1" 2>/dev/null
    fi
fi
if [ -f "$BOOT_LOG" ]; then
    _cur=$(wc -c < "$BOOT_LOG" 2>/dev/null)
    case "$_cur" in ''|*[!0-9]*) _cur=0 ;; esac
    [ "$_cur" -gt "$MAX_BYTES" ] && mv -f "$BOOT_LOG" "$BOOT_LOG.1" 2>/dev/null
fi

[ "${SELFFONT_NO_LOGCAT:-0}" = "1" ] && exit 0


# 后台抓日志。
#
# ★ 2026-11-08 真机打回来的两个漏洞，都在这段：
#   ① 原来用 `-s 白名单` 只抓 8 个 tag。真机上桌面每 5 秒重载一次字体，
#      「Typeface: Preloading Roboto-Regular.ttf」把 180 秒窗口**填满了**，
#      ActivityManager / Watchdog / minikin 的报错一条都挤不进来 ——
#      日志有 1707 行、看着挺充实，该有的全没有。
#   ② 更糟的是，卡住那几分钟一行都不剩，等于又回到「没有证据」。
#
# 现在的抓法：**抓全量，再排除刷屏的**（`-s` 是白名单，会丢主干；这里用 grep -v 黑名单）。
# 黑名单只放「确认与本模块无关且会刷屏」的：桌面字体预加载、冻结/解冻的例行广播。
# 其余一律落盘，宁可文件大一点也不许再把主干挤掉。
#
# 体积仍由 SELFFONT_BOOT_LOG_BYTES（默认 2 MiB）封顶；超了滚一份 .1。
# 一次抓取。参数：$1=秒数上限。
# ★ 2026-11-08 真机：日志写「180 秒到，停止」，实际从 22:33:15 跑到 23:04:44，
#   31 分 29 秒。原因是那句「180 秒到」是**写死的字符串**，从来没算过真实时长 ——
#   又一个「看着说了，其实没查」。现在前后各取一次时间戳，差多少就报多少。
grab() {
    _limit=${1:-180}
    if command -v timeout >/dev/null 2>&1; then
        timeout "$_limit" logcat -b main,system,crash -v threadtime
    else
        logcat -b main,system,crash -v threadtime
    fi | grep -v -E 'Typeface: Preloading|reportOneUidFrozenStateChanged|skip deliver sticky broadcast|Async freezing|Cancel freezing|ProcessObserver broadcast disabled'
}

(
    # 等 logd 起来（最多 15 秒）。post-fs-data 阶段 logd 通常已经在跑，但不保证。
    # 等不到**记一行**再退出：静默退出等于这次开机白抓，说不清是没 logd 还是没跑。
    i=0
    while [ ! -e /dev/socket/logdw ] && [ "$i" -lt 15 ]; do
        i=$((i + 1))
        sleep 1
    done
    if [ ! -e /dev/socket/logdw ]; then
        echo "$(now) 抓日志：等了 15 秒没有 /dev/socket/logdw，本次没抓到（不是没跑，是 logd 没起来）" >> "$GUARD_LOG" 2>/dev/null
        exit 0
    fi
    # 体积封顶用**边抓边看**：每 2000 行检查一次，超了就停。
    # 原来只在「下次开机」检查，跑的过程中不设防——真机一次就写了 100,453 行、22 MB。
    _cap=${SELFFONT_BOOT_LOG_BYTES:-2097152}
    _lines=$(( _cap / 200 ))
    [ "$_lines" -lt 2000 ] && _lines=2000
    # 秒级 date 分辨不出亚秒差：夹具里跑 0.2 秒会印成「实际跑了 0 秒」，也是假话。
    # 有 /proc/uptime 就用它（带两位小数）；没有就退回秒级并标明「精度 1 秒」。
    _t0=$(cut -d' ' -f1 /proc/uptime 2>/dev/null)
    [ -n "$_t0" ] || _t0=$(date +%s 2>/dev/null || echo 0)
    echo "$(now) 抓日志：开始（全量，排除刷屏标签），上限 $_limit_s 秒 / $_cap 字节" >> "$GUARD_LOG" 2>/dev/null
    grab "$_limit_s" | awk -v cap="$_lines" 'NR > cap { exit } { print }' >> "$BOOT_LOG"
    _t1=$(cut -d' ' -f1 /proc/uptime 2>/dev/null)
    [ -n "$_t1" ] || _t1=$(date +%s 2>/dev/null || echo 0)
    _el=$(awk -v a="$_t0" -v b="$_t1" 'BEGIN{ if (a+0 == 0 && b+0 == 0) { print "?"; exit }
        d = b - a; if (d < 0) d = 0; printf "%.1f", d }')
    echo "$(now) 抓日志：停止。实际跑了 ${_el} 秒（上限 $_limit_s 秒），boot.log 现在 $(wc -l < "$BOOT_LOG" 2>/dev/null || echo ?) 行 / $(wc -c < "$BOOT_LOG" 2>/dev/null || echo ?) 字节" >> "$GUARD_LOG" 2>/dev/null
) &

exit 0
