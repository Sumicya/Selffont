#!/system/bin/sh
# Selffont 热切换：**不重启**把二创字件挂上去 / 摘下来。
#
# 为什么要有这个脚本：模块平时靠 KernelSU 的 magic mount 在开机时把
# `$MODDIR/system/<分区>/…` 叠到只读分区上——那是「开机时生效」，改一次要重启一次。
#
# 2026-10-31 真机把上一版打回来了（30 个文件全挂、`nsenter: Unknown option 'bind'`、
# `: > /system/fonts/新名字` 撞只读分区、`verify` 空账判通过），所以现在分两种挂法：
#
#   ① **字体目录一次 overlayfs**。upper/work 放 /data/adb/selffont/ 下，lowerdir 就是
#      系统那个目录本身；模块里的字件**硬链接**进 upper（同一块 /data，不复制上百 MB），
#      于是「系统原有的」与「模块新增的」（`Selffont-*.ttf`、`SelfroundsCJK-VF-*.ttf`）
#      同时出现在同一个目录里。逐文件 `mount --bind` 做不到这件事：bind 只能覆盖
#      **已存在**的路径，新名字只能靠 upperdir 从目录里长出来。
#   ② 系统里已有同名文件的（`/system/etc/fonts_base.xml` 这类配置）：逐个 bind，最省。
#      配置文件不整目录 overlay——`/system/etc` 下面可能还压着别的挂载（hosts 之类），
#      overlayfs 会把它们从视图里盖掉。
#   ③ 所有 mount 都在 **init 的挂载命名空间**里做（`nsenter -t 1 -m`），否则只有当前
#      shell 看得见、zygote 起的应用看不见。nsenter 后面跟的是 `sh 本脚本 __ns …`，
#      不是 `mount`——否则 `mount --bind` 的 `--bind`、`-t`、`-o` 都会被 nsenter 的
#      getopt 当成它自己的选项（上一版就是死在 `nsenter: Unknown option 'bind'`）。
#   ④ 每一步记账（`$STATE` 一行一个文件，`$STATE.units` 一行一个挂载单元），`off` 反序摘；
#      账上写着上一次开机的 boot_id 就判 off——重启后挂载早没了，账不能当现状。
#
# 用法：
#   sh hotswap.sh on|off|toggle|status|verify [--dry-run] [--reload=system|app|none]
#
#   on            挂上（已经是 on 就是空操作）
#   off           摘下（回到开机时那份系统配置）
#   toggle        在两者之间切换
#   status        打印 on / off / partial（看的是 init 的挂载表，不是账）
#   verify        逐文件比对 sha256：系统里看到的是不是模块里这份；核对数为 0 返回 1
#
# 环境变量（测试用，正常使用别设）：
#   SELFFONT_SYSTEM_ROOT   假根：把 /system 映射到某个目录，跑完整流程但不碰真系统
#   SELFFONT_STATE         状态文件路径（默认 /data/adb/selffont-hotswap.state）
#   SELFFONT_UPPER         overlay 的 upperdir（默认 /data/adb/selffont/upper）
#   SELFFONT_COPY=1        upper 里用复制而不是硬链接（overlay 不认硬链接时的退路）
#   SELFFONT_DRY_RUN=1     只打印要执行的命令，不真的挂
#   SELFFONT_NSENTER       进 init 命名空间的前缀（默认自动探测；空串=不进）
#   SELFFONT_RELOAD        默认的重新读取方式：system（软重启）/app（只影响新进程）/none
set -u

SELF=$(readlink -f "$0" 2>/dev/null || printf '%s' "$0")
MODDIR=${SELF%/*}
[ "$MODDIR" = "$SELF" ] && MODDIR=.
ROOT=${SELFFONT_SYSTEM_ROOT:-}
ROOT=${ROOT%/}
STATE=${SELFFONT_STATE:-/data/adb/selffont-hotswap.state}
UNITS="$STATE.units"
PLAN="$STATE.plan"
DRY=${SELFFONT_DRY_RUN:-0}
RELOAD=${SELFFONT_RELOAD:-system}
UPPER=${SELFFONT_UPPER:-/data/adb/selffont/upper}
WORK=${SELFFONT_WORK:-/data/adb/selffont/work}
BOOT=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || printf 'unknown')
# 子命令 `__ns` 是同一个脚本在 init 命名空间里的第二趟，靠这几个变量认得路。
export MODDIR ROOT UPPER WORK

say() { printf '%s\n' "$*"; }
die() { printf 'Selffont: %s\n' "$*" >&2; exit 2; }

# ---------------------------------------------------------------- 路径
system_path() {   # 相对路径（system/fonts/x.ttf）→ 挂载时的绝对路径（假根时带前缀）
    printf '%s/%s\n' "${ROOT}" "$1"
}

target_view() {   # 判「设备上有没有这个名字」/ verify 读内容：一律看 init 命名空间那一份
    if [ -n "$ROOT" ]; then printf '%s/%s\n' "$ROOT" "$1"
    elif [ -d /proc/1/root ]; then printf '/proc/1/root/%s\n' "$1"
    else printf '%s/%s\n' "" "$1"; fi
}

# ---------------------------------------------------------------- 目标清单
# 模块里 `system/` 下的每一个普通文件都是要叠上去的东西：字体在 system/fonts，
# 配置在 system/etc、system_ext/etc、product/etc。用 `find` 列，不写死文件名。
targets() {
    [ -d "$MODDIR/system" ] || return 1
    find "$MODDIR/system" -type f 2>/dev/null | sed "s|^$MODDIR/||" | sort
}

# ---------------------------------------------------------------- 计划
# 计划文件一行一个挂载单元：`dir|路径`（overlay）或 `file|路径`（bind）。
build_plan() {   # $1 = 计划文件
    files="$1.files"
    dirs_out="$1.dirs"
    targets > "$files" || return 1
    [ -s "$files" ] || return 1
    : > "$dirs_out" || return 1
    : > "$1" || return 1
    dirs=""
    while IFS= read -r rel; do
        d=${rel%/*}
        case " $dirs " in *" $d "*) ;; *) dirs="$dirs $d" ;; esac
    done < "$files"
    for d in $dirs; do
        # 字体目录无条件 overlay：新字体名（系统里没有的那些）只有 upperdir 能长出来，
        # 而字体目录底下没有别人压的挂载，整目录盖掉是安全的。
        case "$d" in
            */fonts)
                printf 'dir|%s\n' "$d" >> "$dirs_out"
                continue ;;
        esac
        # 其它目录（etc 那几份配置）逐个 bind：不整目录 overlay——`/system/etc` 底下
        # 可能还压着别的挂载（hosts 之类），overlayfs 会把它们从视图里盖掉。
        while IFS= read -r rel; do
            case "$rel" in "$d"/*) ;; *) continue ;; esac
            if [ -e "$(target_view "$rel")" ]; then
                printf 'file|%s\n' "$rel" >> "$1"
            else
                say "跳过：$rel（系统里没有这个路径，bind 覆盖不了新文件）" >&2
            fi
        done < "$files"
    done
    # 目录先挂、文件后挂：先 bind 单个文件、再把整个目录盖上去，那个 bind 会被盖掉。
    cat "$1" >> "$dirs_out"
    mv -f "$dirs_out" "$1"
    rm -f "$files"
    [ -s "$1" ]
}

unit_files() {   # $1=单元类型 $2=相对路径 → 这个单元让哪些文件变得可见
    case "$1" in
        dir)  targets | while IFS= read -r rel; do
                  case "$rel" in "$2"/*) printf '%s\n' "$rel" ;; esac
              done ;;
        file) printf '%s\n' "$2" ;;
    esac
}

# ---------------------------------------------------------------- upper（真机才用）
prepare_upper() {   # $1 = 目录的相对路径（system/fonts）
    mkdir -p "$UPPER" || return 1
    # workdir 必须是空目录（上一次挂载失败留下的东西会让 overlay 直接 EINVAL）
    rm -rf "$WORK" 2>/dev/null
    mkdir -p "$WORK" || return 1
    src="$MODDIR/$1"
    # upper 是我们的地盘：上一版模块里有、这一版没有的字件要从这里清掉，
    # 否则 /system/fonts 里会多出已经不存在的字体名。
    for f in "$UPPER"/*; do
        [ -e "$f" ] || continue
        [ -f "$src/${f##*/}" ] || rm -f "$f"
    done
    for f in "$src"/*; do
        [ -f "$f" ] || continue
        # 模块在 /data/adb/modules 下，upper 在 /data/adb/selffont 下：同一块盘，
        # 硬链接零拷贝零等待（真复制一次 147 MB 要几秒，还要再占一份空间）。
        if [ "${SELFFONT_COPY:-0}" = 1 ] || ! ln -f "$f" "$UPPER/${f##*/}" 2>/dev/null; then
            cp -f "$f" "$UPPER/${f##*/}" || return 1
        fi
    done
    return 0
}

# ---------------------------------------------------------------- 命名空间里干活的
mount_unit() {   # $1=类型 $2=相对路径；只在本进程（= init 命名空间）里跑
    abs=$(system_path "$2")
    case "$1" in
        dir)
            if [ -n "$ROOT" ]; then
                # 假根跑不了 overlay（要真内核），用目录 bind 近似：整目录换成模块里的
                mkdir -p "$abs" 2>/dev/null
                mount --bind "$MODDIR/$2" "$abs"
            else
                mkdir -p "$UPPER" "$WORK" 2>/dev/null
                mount -t overlay overlay \
                    -o "lowerdir=$abs,upperdir=$UPPER,workdir=$WORK" "$abs"
            fi ;;
        file)
            if [ -n "$ROOT" ] && [ ! -e "$abs" ]; then
                # 只有假根才建占位文件：真设备上 /system 是只读的，`> /system/fonts/x`
                # 必然 Read-only file system——上一版就是在这里全挂的。
                mkdir -p "${abs%/*}" 2>/dev/null
                : > "$abs" 2>/dev/null
            fi
            mount --bind "$MODDIR/$2" "$abs" ;;
        *)    printf '未知单元类型：%s\n' "$1" >&2; return 1 ;;
    esac
}

ns_apply() {   # $1 = 计划文件
    while IFS='|' read -r kind rel; do
        [ -n "${kind:-}" ] || continue
        if err=$(mount_unit "$kind" "$rel" 2>&1); then
            printf 'ok|%s|%s\n' "$kind" "$rel"
        else
            printf 'fail|%s|%s|%s\n' "$kind" "$rel" "$(printf '%s' "$err" | sed -n '1p')"
        fi
    done < "$1"
}

ns_undo() {   # $1 = 计划文件（反序摘：后挂的先摘）
    rev="$1.rev"
    sed '1!G;h;$!d' "$1" > "$rev" 2>/dev/null || tac "$1" > "$rev"
    while IFS='|' read -r kind rel; do
        [ -n "${kind:-}" ] || continue
        abs=$(system_path "$rel")
        if umount "$abs" >/dev/null 2>&1; then
            printf 'ok|%s|%s|\n' "$kind" "$rel"
        elif err=$(umount -l "$abs" 2>&1); then
            # 文件还被进程开着时 umount 会 EBUSY：懒卸载先把它从目录树摘掉
            printf 'ok|%s|%s|懒卸载\n' "$kind" "$rel"
        else
            printf 'fail|%s|%s|%s\n' "$kind" "$rel" "$(printf '%s' "$err" | sed -n '1p')"
        fi
    done < "$rev"
    rm -f "$rev"
}

# ---------------------------------------------------------------- 进 init 的挂载命名空间
NS_DONE=0
NS_CACHE=""
ns_prefix() {   # 打印前缀；空串 = 就在当前命名空间里跑（假根 / 显式设空）
    [ "$NS_DONE" = 1 ] && { printf '%s' "$NS_CACHE"; return 0; }
    NS_DONE=1
    if [ "${SELFFONT_NSENTER+given}" = given ]; then
        NS_CACHE=${SELFFONT_NSENTER}
        printf '%s' "$NS_CACHE"
        return 0
    fi
    if [ -n "$ROOT" ]; then printf ''; return 0 ; fi
    # 四种写法按「最可能在这台机器上成立」排序；探测命令是 `true`——**不许带 `-` 开头的
    # 参数**：Android 自带的 toybox nsenter 会把命令行里任何 `-x` 都当成自己的选项
    # （真机原样输出就是 `nsenter: Unknown option 'bind'`，`-c`、`-t`、`-o` 同理）。
    for cand in "nsenter -t 1 -m" "nsenter -t 1 --mount" \
                "nsenter --target 1 --mount" "nsenter --target=1 --mount"; do
        # shellcheck disable=SC2086
        if err=$($cand true 2>&1); then
            NS_CACHE=$cand
            printf '%s' "$NS_CACHE"
            return 0
        fi
        printf 'Selffont: 探测 %s 不成 → %s\n' "$cand" "$(printf '%s' "$err" | sed -n '1p')" >&2
    done
    die "进不了 init 的挂载命名空间：三种 nsenter 写法都不成（原样输出在上面）。把 \`nsenter --help\` 的前 20 行贴出来再改。"
}

ns_run() {   # $@ = 要在 init 命名空间里跑的命令（永远是 `sh 本脚本 …`，不是 mount）
    prefix=$(ns_prefix) || exit 2
    if [ -z "$prefix" ]; then "$@"; return $?; fi
    # 拆词是故意的：$prefix 是一串命令词（nsenter -t 1 -m），必须按空格分开
    # shellcheck disable=SC2086
    $prefix "$@"
}

# ---------------------------------------------------------------- 账
stale_state() {   # 0 = 账是上一次开机留下的
    [ -f "$UNITS" ] || return 1
    head=$(sed -n '1p' "$UNITS" 2>/dev/null)
    case "$head" in
        "#boot "*) [ "${head#\#boot }" = "$BOOT" ] && return 1 || return 0 ;;
    esac
    return 1
}

mounted_unit() {   # $1=类型 $2=相对路径；0 = init（假根时是当前）的挂载表里有它
    mnt=/proc/1/mountinfo
    [ -n "$ROOT" ] && mnt=/proc/self/mountinfo
    [ -r "$mnt" ] || return 1
    abs=$(system_path "$2")
    if [ "$1" = dir ] && [ -z "$ROOT" ]; then
        # 目录单元必须认得是**我们这份** overlay：光有 overlay 挂在上面不算
        awk -v mp="$abs" -v up="upperdir=$UPPER" \
            '$5 == mp && index($0, up) { f = 1 } END { exit !f }' "$mnt"
    else
        awk -v mp="$abs" '$5 == mp { f = 1 } END { exit !f }' "$mnt"
    fi
}

# ---------------------------------------------------------------- 挂 / 摘
cmd_on() {
    st=$(cmd_status)
    if [ "$st" = on ]; then say "已经是 on（$UNITS）"; return 0; fi
    if [ "$st" = partial ]; then
        say "上一次是 partial，先摘干净再挂"
        # 摘不干净就别往上盖：upper 还挂在 live overlay 下面，动它只会把状态搞得更乱
        cmd_off || die "partial 的账没摘干净（见上面的原样输出）：先重启，或手动 umount 再试"
    fi

    try="$PLAN.new"
    build_plan "$try" || die "没有可挂的文件：$MODDIR/system"
    while IFS='|' read -r kind rel; do
        [ "$kind" = dir ] || continue
        [ -n "$ROOT" ] && continue
        prepare_upper "$rel" || die "upper 准备失败：$UPPER（/data 写不了或满了）"
    done < "$try"

    if [ "$DRY" = 1 ]; then
        say "[dry-run] upper=$UPPER work=$WORK"
        while IFS='|' read -r kind rel; do
            case "$kind" in
                dir)  say "[dry-run] mount -t overlay overlay -o lowerdir=$(system_path "$rel"),upperdir=$UPPER,workdir=$WORK $(system_path "$rel")" ;;
                file) say "[dry-run] mount --bind $MODDIR/$rel $(system_path "$rel")" ;;
            esac
        done < "$try"
        rm -f "$try"
        return 0
    fi

    results=$(ns_run sh "$SELF" __ns apply "$try") || {
        rm -f "$try"
        die "在 init 命名空间里执行失败（见上面的原样输出），系统没动"
    }
    printf '#boot %s\n' "$BOOT" > "$UNITS.new" || die "写不了状态文件：$UNITS.new"
    : > "$STATE.new" || die "写不了状态文件：$STATE.new"
    ok=0; bad=0
    while IFS='|' read -r tag kind rel note; do
        case "${tag:-}" in
            ok)
                ok=$((ok + 1))
                printf '%s|%s\n' "$kind" "$rel" >> "$UNITS.new"
                unit_files "$kind" "$rel" >> "$STATE.new" ;;
            fail)
                bad=$((bad + 1))
                say "挂载失败：$rel（$note）" ;;
        esac
    done <<EOF
$results
EOF
    mv -f "$UNITS.new" "$UNITS" 2>/dev/null || die "写不了状态文件：$UNITS"
    mv -f "$STATE.new" "$STATE" 2>/dev/null || die "写不了状态文件：$STATE"
    rm -f "$try"
    if [ "$ok" -eq 0 ]; then
        # 一个都没挂上就别留一本「partial」账：账是给人看的，它得对应真实挂载。
        rm -f "$UNITS" "$STATE"
        say "一个也没挂上（$bad 个单元失败，原因见上面的原样输出）：账已清，系统一处没动"
        return 1
    fi
    files=$(wc -l < "$STATE" 2>/dev/null | tr -d ' ')
    if [ "$bad" -gt 0 ]; then
        say "部分失败：$ok 个单元挂上、$bad 个没挂上（状态 partial，可 off 摘干净）"
        return 1
    fi
    say "挂上 $ok 个单元、$files 个文件（字体目录一次 overlay，已存在的配置逐个 bind）"
    reload "$RELOAD"
    return 0
}

cmd_off() {
    if [ ! -f "$STATE" ] && [ ! -f "$UNITS" ]; then say "已经是 off"; return 0; fi
    if stale_state; then
        say "账是上一次开机留下的，这次没有任何热切换挂载：清账"
        rm -f "$STATE" "$UNITS"
        return 0
    fi
    units="$UNITS"
    if [ ! -f "$UNITS" ]; then
        # 老版本的账只有文件路径：按单文件 bind 反着摘（老版本本来也没挂成过）
        units="$UNITS.derived"
        while IFS= read -r rel; do
            [ -n "$rel" ] || continue
            printf 'file|%s\n' "$rel"
        done < "$STATE" > "$units"
    fi
    undo="$PLAN.undo"
    : > "$undo" || die "写不了计划文件：$undo"
    n=0; skip=0
    while IFS='|' read -r kind rel; do
        [ -n "${kind:-}" ] || continue
        case "$kind" in '#'*) continue ;; esac
        if mounted_unit "$kind" "$rel"; then
            printf '%s|%s\n' "$kind" "$rel" >> "$undo"
            n=$((n + 1))
        else
            skip=$((skip + 1))
            say "跳过（init 的挂载表里没有，不是本脚本挂的）：$rel"
        fi
    done < "$units"
    if [ "$DRY" = 1 ]; then
        while IFS='|' read -r kind rel; do say "[dry-run] umount $(system_path "$rel")"; done < "$undo"
        rm -f "$undo" "$UNITS.derived"
        return 0
    fi
    results=$(ns_run sh "$SELF" __ns undo "$undo") || {
        # 进不去命名空间 / 里面直接炸了：账必须留着，否则下次连「摘了什么」都不知道
        rm -f "$undo" "$UNITS.derived"
        say "在 init 命名空间里执行失败（见上面的原样输出）：账留着，挂载没动"
        return 1
    }
    bad=0
    while IFS='|' read -r tag kind rel note; do
        case "${tag:-}" in
            ok) [ -n "${note:-}" ] && say "摘下：$rel（$note）" ;;
            fail) bad=$((bad + 1)); say "摘不动：$rel（$note）" ;;
        esac
    done <<EOF
$results
EOF
    rm -f "$undo" "$UNITS.derived"
    if [ "$bad" -gt 0 ]; then
        say "部分摘掉：$n 个单元里 $bad 个失败，账先留着；再跑一次 off，或重启后账自然作废"
        return 1
    fi
    rm -f "$STATE" "$UNITS"
    say "摘下 $n 个单元"$([ "$skip" -gt 0 ] && printf '（%s 个跳过）' "$skip")
    reload "$RELOAD"
    return 0
}

# ---------------------------------------------------------------- 让别人重读
reload() {   # $1 = system | app | none
    case "${1:-system}" in
        none) say "不触发重读：新进程会看到新挂载，已开的程序要手动重启"; return 0 ;;
        app)  say "只影响新进程：已开的程序保持旧字体（重启那个程序即可）"; return 0 ;;
    esac
    if command -v cmd >/dev/null 2>&1 && cmd font help >/dev/null 2>&1; then
        if [ "$DRY" = 1 ]; then say "[dry-run] cmd font update"; return 0; fi
        # 返回 0 只代表请求被受理：FontManagerService 会不会把新 Typeface 推给已注册的进程，
        # 各家 ROM 不一样。这里不许说「已经生效」——屏幕没变就加 --reload=system 软重启。
        cmd font update >/dev/null 2>&1 && {
            say "已请求 FontManagerService 重读（返回 0；屏幕没变就加 --reload=system 软重启）"
            return 0
        }
    fi
    pid=$(pidof system_server 2>/dev/null | sed -n '1p')
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
    # 「状态」不是「账上有文件」，而是**init 的挂载表里还在不在**：
    # 重启之后账还在、挂载早没了，所以先比 boot_id，再逐个单元对挂载表。
    [ -f "$UNITS" ] || [ -f "$STATE" ] || { say off; return 0; }
    stale_state && { say off; return 0; }
    total=0; live=0
    if [ -f "$UNITS" ]; then
        while IFS='|' read -r kind rel; do
            [ -n "${kind:-}" ] || continue
            case "$kind" in '#'*) continue ;; esac
            total=$((total + 1))
            mounted_unit "$kind" "$rel" && live=$((live + 1))
        done < "$UNITS"
    else
        while IFS= read -r rel; do
            [ -n "$rel" ] || continue
            total=$((total + 1))
            mounted_unit file "$rel" && live=$((live + 1))
        done < "$STATE"
    fi
    if [ "$total" -eq 0 ]; then say off
    elif [ "$live" -ge "$total" ]; then say on
    elif [ "$live" -eq 0 ]; then say off
    else say partial; fi
    return 0
}

cmd_verify() {
    # 三个不许：不许空账算通过（上一版 `一致 0，不一致 0` 退回 0）、不许把开机 magic mount
    # 当成本次热切换的成果（比 boot_id）、不许只看文件内容不看挂载（单元还得在挂载表里）。
    [ -f "$STATE" ] || { say "verify：没有热切换状态（现在是 off），没有可核对的文件"; return 1; }
    if stale_state; then
        say "verify：账是上一次开机留下的，这次没有热切换挂载（开机 magic mount 不算）"
        return 1
    fi
    lost=0
    if [ -f "$UNITS" ]; then
        while IFS='|' read -r kind rel; do
            [ -n "${kind:-}" ] || continue
            case "$kind" in '#'*) continue ;; esac
            mounted_unit "$kind" "$rel" || { say "没挂：$rel"; lost=$((lost + 1)); }
        done < "$UNITS"
    fi
    ok=0; bad=0
    while IFS= read -r rel; do
        [ -n "$rel" ] || continue
        src="$MODDIR/$rel"
        dst=$(target_view "$rel")
        if [ ! -f "$dst" ]; then say "缺：$dst"; bad=$((bad + 1)); continue; fi
        a=$(sha256sum "$src" 2>/dev/null | cut -d' ' -f1)
        b=$(sha256sum "$dst" 2>/dev/null | cut -d' ' -f1)
        if [ -n "$a" ] && [ "$a" = "$b" ]; then ok=$((ok + 1)); else say "不一致：$dst（模块 $a / 系统 $b）"; bad=$((bad + 1)); fi
    done < "$STATE"
    say "verify：一致 $ok，不一致 $bad$([ "$lost" -gt 0 ] && printf '，没挂 %s' "$lost")"
    if [ $((ok + bad)) -eq 0 ]; then
        # 核对数为 0 一律不算通过：账是空的、或者一个文件都没比对到，就别给退出码 0。
        say "verify：没有核对任何文件（$STATE 是空的）——空账不算通过"
        return 1
    fi
    [ "$bad" -eq 0 ] && [ "$lost" -eq 0 ]
}

# ---------------------------------------------------------------- 命名空间内的第二趟
# 只有 ns_run 会走到这里：nsenter 把控制权交给 sh，`mount --bind` 的 `--bind` 不再
# 经过 nsenter 的选项解析。（上一版 `nsenter: Unknown option 'bind'` 的根因。）
case "${1:-}" in
    __ns)
        ns_action=${2:-}; plan=${3:-}
        [ -f "$plan" ] || die "计划文件不存在：$plan"
        case "$ns_action" in
            apply) ns_apply "$plan" ;;
            undo)  ns_undo "$plan" ;;
            *)     die "内部用法：hotswap.sh __ns apply|undo <计划文件>" ;;
        esac
        exit 0 ;;
esac

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
if [ "$DRY" = 1 ] && [ "${SELFFONT_STATE:-}" = "" ]; then
    STATE=/tmp/selffont-hotswap.state
    UNITS="$STATE.units"
    PLAN="$STATE.plan"
fi

case "$action" in
    on)     cmd_on ;;
    off)    cmd_off ;;
    toggle) if [ "$(cmd_status)" = on ]; then cmd_off; else cmd_on; fi ;;
    status) cmd_status ;;
    verify) cmd_verify ;;
    -h|--help|help) awk 'NR > 1 && /^set -u$/ { exit } NR > 1' "$SELF" ; exit 0 ;;
    *) die "用法：sh hotswap.sh on|off|toggle|status|verify [--dry-run] [--reload=system|app|none]" ;;
esac
