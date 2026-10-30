#!/system/bin/sh
# Selffont 热切换：**不重启**把二创字件挂上去 / 摘下来。
#
# 为什么要有这个脚本：模块平时靠 KernelSU 的 magic mount 在开机时把
# `$MODDIR/system/<分区>/…` 叠到只读分区上——那是「开机时生效」，改一次要重启一次。
# 系统设置里换字体是**立刻生效**的，差别就在「运行中能不能换挂载」。
#
# 做法与 magic mount 同构，但发生在运行时：
#   ① 把模块里每一个文件逐个 `mount --bind` 到系统里的同名路径（进 init 的挂载命名空间，
#      否则只有 shell 自己看得见，zygote 起来的应用看不到）；
#   ② 让读字体的人重新读一次：优先 `cmd font`（FontManagerService，Android 12+），
#      没有就只重启 system_server（软重启，约 15–20 秒，不是整机重启）；
#   ③ 每一步都记账（$STATE），`off` 按账反着摘，半路失败也不会留下摘不掉的东西。
#
# 用法：
#   sh hotswap.sh on|off|toggle|status|verify [--dry-run] [--reload=system|app|none]
#
#   on            挂上（已经是 on 就是空操作）
#   off           摘下（回到开机时那份系统配置）
#   toggle        在两者之间切换
#   status        打印 on / off / partial
#   verify        逐文件比对 sha256：系统里看到的是不是模块里这份，返回 0/1
#
# 环境变量（测试用，正常使用别设）：
#   SELFFONT_SYSTEM_ROOT   假根：把 /system 映射到某个目录，跑完整流程但不碰真系统
#   SELFFONT_STATE         状态文件路径（默认 /data/adb/selffont-hotswap.state）
#   SELFFONT_DRY_RUN=1     只打印要执行的命令，不真的挂
#   SELFFONT_NSENTER       进入 init 命名空间的前缀（默认 `nsenter -t 1 -m`；空串=不进）
#   SELFFONT_RELOAD        默认的重新读取方式：system（软重启）/app（只影响新进程）/none
#   SELFFONT_FAKE_FAIL     测试用：让名字匹配的某个挂载点失败一次（写它的路径子串）
set -u

MODDIR=${0%/*}
[ "$MODDIR" = "$0" ] && MODDIR=.
ROOT=${SELFFONT_SYSTEM_ROOT:-}
STATE=${SELFFONT_STATE:-/data/adb/selffont-hotswap.state}
DRY=${SELFFONT_DRY_RUN:-0}
NS=${SELFFONT_NSENTER-nsenter -t 1 -m}
RELOAD=${SELFFONT_RELOAD:-system}
FAIL_MATCH=${SELFFONT_FAKE_FAIL:-}

say() { printf '%s\n' "$*"; }
die() { printf 'Selffont: %s\n' "$*" >&2; exit 2; }

# ---------------------------------------------------------------- 目标清单
# 模块里 `system/` 下的每一个普通文件都是要叠上去的东西：字体在 system/fonts，
# 配置在 system/etc、system_ext/etc、product/etc。用 `find` 列，不写死文件名——
# 换字体名、加一份许可，都不用改这个脚本。
targets() {
    [ -d "$MODDIR/system" ] || return 1
    find "$MODDIR/system" -type f 2>/dev/null | sed "s|^$MODDIR/||" | sort
}

rel_path_of() {   # $1 = 模块内相对路径（system/fonts/x.ttf）→ 系统绝对路径
    printf '%s/%s\n' "${ROOT%/}" "$1"
}

# ---------------------------------------------------------------- 挂 / 摘
run() {   # 真正执行（dry-run 只打印）
    if [ "$DRY" = 1 ]; then
        say "[dry-run] $*"
        return 0
    fi
    # 拆词是故意的：$NS 是一串命令，需要按空格分成 nsenter -t 1 -m
    # shellcheck disable=SC2086
    $NS "$@"
}

bind_one() {   # $1=模块内相对路径；成功 0
    src="$MODDIR/$1"; [ -n "$ROOT" ] && src="$MODDIR/$1"
    dst=$(rel_path_of "$1")
    [ -e "$src" ] || die "模块里缺文件：$src"
    if [ "$DRY" != 1 ] && [ ! -e "$dst" ]; then
        # 设备上没有这个文件（不同分区布局）：建一个同内容的替身，别让 bind 失败
        mkdir -p "$(dirname "$dst")" 2>/dev/null || die "建不出目录：$(dirname "$dst")"
        : > "$dst" 2>/dev/null || die "建不出目标文件：$dst"
    fi
    if [ -n "$FAIL_MATCH" ] && [ "$DRY" != 1 ]; then
        case "$dst" in
            *"$FAIL_MATCH"*) return 1 ;;
        esac
    fi
    run mount --bind "$src" "$dst" || return 1
    printf '%s\n' "$1" >> "$STATE.tmp"
    return 0
}

cmd_on() {
    if [ "$(cmd_status)" = on ]; then
        say "已经是 on（$STATE）"; return 0
    fi
    if [ "$(cmd_status)" = partial ]; then
        say "上一次是 partial，先清理再挂"; cmd_off >/dev/null 2>&1 || true
    fi
    list=$(targets) || die "模块里没有 system/ 目录：$MODDIR"
    [ -n "$list" ] || die "模块里没有可挂的文件：$MODDIR/system"
    : > "$STATE.tmp" || die "写不了状态文件：$STATE.tmp"
    ok=0; bad=0
    for rel in $list; do
        if bind_one "$rel"; then ok=$((ok + 1)); else bad=$((bad + 1)); say "挂载失败：$rel"; fi
    done
    if [ "$DRY" = 1 ]; then rm -f "$STATE.tmp"; say "dry-run：共 $ok 个文件，未改动系统"; return 0; fi
    if [ "$bad" -gt 0 ]; then
        mv -f "$STATE.tmp" "$STATE" 2>/dev/null || true
        say "部分失败：$ok 个挂上、$bad 个没挂上（状态 partial，可 off 摘干净）"
        return 1
    fi
    mv -f "$STATE.tmp" "$STATE" && say "挂上 $ok 个文件" || die "写不了状态文件：$STATE"
    reload "$RELOAD"
    return 0
}

cmd_off() {
    [ -f "$STATE" ] || { say "已经是 off"; return 0; }
    ok=0; bad=0
    # 反序摘：后挂的先摘，依赖关系与挂的时候对称
    tac "$STATE" 2>/dev/null > "$STATE.undo" || sed '1!G;h;$!d' "$STATE" > "$STATE.undo"
    while IFS= read -r rel; do
        [ -n "$rel" ] || continue
        dst=$(rel_path_of "$rel")
        if run umount "$dst" 2>/dev/null; then
            ok=$((ok + 1))
        else
            # 不是我们挂的（比如开机 magic mount 也在）就跳过，别把系统的挂载摘了
            bad=$((bad + 1)); say "摘不动（可能不是本脚本挂的）：$rel"
        fi
    done < "$STATE.undo"
    rm -f "$STATE.undo"
    if [ "$DRY" = 1 ]; then say "dry-run：共要摘 $ok 个"; return 0; fi
    rm -f "$STATE"
    say "摘下 $ok 个文件"$([ "$bad" -gt 0 ] && printf '（%s 个跳过）' "$bad")
    reload "$RELOAD"
    return 0
}

# ---------------------------------------------------------------- 让别人重读
reload() {   # $1 = system | app | none
    case "${1:-system}" in
        none) say "不触发重读：新进程会看到新挂载，已开的程序要手动重启"; return 0 ;;
        app)  say "只影响新进程：已开的程序保持旧字体（重启那个程序即可）"; return 0 ;;
    esac
    # ① FontManagerService（Android 12+ 的可更新字体服务）：有 shell 服务就让它刷一遍。
    if command -v cmd >/dev/null 2>&1 && cmd font help >/dev/null 2>&1; then
        if [ "$DRY" = 1 ]; then say "[dry-run] cmd font update"; return 0; fi
        # 返回 0 只代表请求被受理：FontManagerService 会不会把新 Typeface 推给已注册的进程，
        # 各家 ROM 不一样。这里不许说「已经生效」——屏幕没变就加 --reload=system 软重启。
        cmd font update >/dev/null 2>&1 && {
            say "已请求 FontManagerService 重读（返回 0；屏幕没变就加 --reload=system 软重启）"
            return 0
        }
    fi
    # ② 没有就软重启 system_server：不重启整机，挂载与模块都还在，15–20 秒回来。
    pid=$(pidof system_server 2>/dev/null | head -1)
    if [ -n "${pid:-}" ]; then
        if [ "$DRY" = 1 ]; then say "[dry-run] kill -9 $pid  # 软重启 system_server"; return 0; fi
        say "软重启 system_server（pid $pid），约 15–20 秒"
        kill -9 "$pid" 2>/dev/null || die "杀不掉 system_server（没有 root？）"
        return 0
    fi
    say "找不到可用的重读入口：新进程用新字体，已开的程序要重启"
    return 1
}

# ---------------------------------------------------------------- 查询
cmd_status() {
    # 「状态」不是「状态文件存在与否」，而是**模块里该挂的都挂上了没有**：
    # 半路失败时状态文件只记了成功的那几个，只看文件会误报 on（自检里就抓到过这一次）。
    [ -f "$STATE" ] || { say off; return 0; }
    want=$(targets 2>/dev/null | grep -c . 2>/dev/null || echo 0)
    live=0
    while IFS= read -r rel; do
        [ -n "$rel" ] || continue
        dst=$(rel_path_of "$rel")
        if [ "$DRY" = 1 ]; then live=$((live + 1)); continue; fi
        # 挂了没有：拿 mount 表对（Linux 上 bind mount 在 mount 输出里带路径）
        if mount 2>/dev/null | grep -F " $dst " >/dev/null 2>&1; then live=$((live + 1)); fi
    done < "$STATE"
    if [ "$want" -gt 0 ] && [ "$live" -ge "$want" ]; then say on
    elif [ "$live" -eq 0 ]; then say off
    else say partial; fi
    return 0
}

cmd_verify() {
    [ -f "$STATE" ] || die "没有热切换状态（现在是 off）"
    ok=0; bad=0
    while IFS= read -r rel; do
        [ -n "$rel" ] || continue
        dst=$(rel_path_of "$rel")
        src="$MODDIR/$rel"
        if [ ! -f "$dst" ]; then say "缺：$dst"; bad=$((bad + 1)); continue; fi
        a=$(sha256sum "$src" 2>/dev/null | cut -d' ' -f1)
        b=$(sha256sum "$dst" 2>/dev/null | cut -d' ' -f1)
        if [ -n "$a" ] && [ "$a" = "$b" ]; then ok=$((ok + 1)); else say "不一致：$dst（模块 $a / 系统 $b）"; bad=$((bad + 1)); fi
    done < "$STATE"
    say "verify：一致 $ok，不一致 $bad"
    [ "$bad" -eq 0 ]
}

# ---------------------------------------------------------------- 入口
action=${1:-status}
shift 2>/dev/null || true
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY=1 ;;
        --reload=*) RELOAD=${1#--reload=} ;;
        *) die "不认识的参数：$1" ;;
    esac
    shift
done
[ "$DRY" = 1 ] && [ "${SELFFONT_STATE:-}" = "" ] && STATE=/tmp/selffont-hotswap.state

case "$action" in
    on)     cmd_on ;;
    off)    cmd_off ;;
    toggle) if [ "$(cmd_status)" = on ]; then cmd_off; else cmd_on; fi ;;
    status) cmd_status ;;
    verify) cmd_verify ;;
    -h|--help|help) sed -n '2,26p' "$0"; exit 0 ;;
    *) die "用法：sh hotswap.sh on|off|toggle|status|verify [--dry-run] [--reload=system|app|none]" ;;
esac
