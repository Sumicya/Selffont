#!/system/bin/sh
# Selffont 热切换：**不重启**把二创字件挂上去 / 摘下来。
#
# 四条硬规矩（2026-10-31 真机事故之后定的，谁改这个文件都得守住）：
#   ① 挂之前先记账，失败一定回滚到自己挂之前的状态；回滚不成就报出来，绝不假装成功。
#   ② `/system/fonts` 上**只许一次目录级 overlay**，不许对单个字体名挂任何东西。
#   ③ **任何情况下不许把 /data 下的目录 bind 到 /system 路径**——上一版就是
#      `mount --bind /data/adb/selffont/merged /system/fonts`，在 `mount` 输出里成了
#      `/dev/block/dm-76 on /system/fonts type f2fs`：等于让系统字体目录指向数据分区。
#   ④ `panic`：把本脚本挂过的全部挂载点摘掉、删掉 merged/upper，再打印 /proc/mounts
#      里与 fonts 相关的剩余行。
#
# 为什么非 overlay 不可：`SelfroundsCJK-VF-<版本>.ttf`、`Selffont-WenYuanRoundedSCVF.ttf`
# 是新名字，`mount --bind` 只能覆盖**已存在**的路径；而往只读的 /system 里建占位文件
# 必然 `Read-only file system`。只有 upperdir 能让新名字从目录里长出来。
#
# 一次 overlay 的全部内容：
#   mount -t overlay overlay \
#     -o lowerdir=/system/fonts,upperdir=/data/adb/selffont/upper,workdir=/data/adb/selffont/work \
#     /system/fonts
# upper 里放模块字件的**副本**（不是硬链接：upper 里的文件不能有指向外面的第二个链接，
# 否则 overlay 挂载阶段就可能 EINVAL）。26 个文件、约 147 MB，一次几秒。
# 设备上本来就有的配置（`/system/etc/fonts_base.xml` 这类）仍逐个 `mount --bind`
# **文件**——文件 bind 不违反第③条，目录 bind 才违反；而且这类文件系统里本来就有，
# 不需要建占位文件。整目录 overlay `/system/etc` 是不做的：那底下可能还压着别的挂载。
#
# 用法：
#   sh hotswap.sh on|off|toggle|status|verify|panic [--dry-run] [--reload=system|app|none]
#
#   on      挂上（已经是 on 就是空操作）
#   off     摘下（回到开机时那份系统配置）
#   toggle  在两者之间切换
#   status  打印 on / off / partial（看 init 的挂载表，不看账）
#   verify  逐文件比对 sha256（经 /proc/1/root 从 init 的视角读）；核对数为 0 返回 1
#   panic   摘掉本脚本挂过的一切、删 merged/upper，打印 /proc/mounts 里与 fonts 相关的剩余行
#
# 环境变量（测试用，正常使用别设）：
#   SELFFONT_SYSTEM_ROOT   假根：把 /system 映射到某个目录，跑完整流程但不碰真系统
#   SELFFONT_STATE         状态文件前缀（默认 /data/adb/selffont-hotswap）
#   SELFFONT_UPPER         overlay 的 upperdir（默认 /data/adb/selffont/upper）
#   SELFFONT_WORK          overlay 的 workdir（默认 /data/adb/selffont/work）
#   SELFFONT_DRY_RUN=1     只打印要执行的命令，不真的挂
#   SELFFONT_NSENTER       进 init 命名空间的前缀（默认自动探测；空串=不进）
#   SELFFONT_RELOAD        默认的重新读取方式：system（软重启）/app /none
set -u

SELF=$(readlink -f "$0" 2>/dev/null || printf '%s' "$0")
MODDIR=${SELF%/*}
[ "$MODDIR" = "$SELF" ] && MODDIR=.
ROOT=${SELFFONT_SYSTEM_ROOT:-}
ROOT=${ROOT%/}
BASE=${SELFFONT_STATE:-/data/adb/selffont-hotswap}
STATE="$BASE.state"          # 一行一个文件（verify 按它数）
UNITS="$BASE.units"          # 第一行 #boot <boot_id>，其余一行一个挂载单元
JOURNAL="$BASE.journal"      # 挂之前就写：一行一个「我要挂的」
DONE="$BASE.done"            # 挂成功了的一个单元一行（回滚按它反序摘）
PLAN="$BASE.plan"
DRY=${SELFFONT_DRY_RUN:-0}
RELOAD=${SELFFONT_RELOAD:-system}
UPPER=${SELFFONT_UPPER:-/data/adb/selffont/upper}
WORK=${SELFFONT_WORK:-/data/adb/selffont/work}
MERGED=${SELFFONT_MERGED:-/data/adb/selffont/merged}   # 旧版垃圾的位置，panic 顺手删
BOOT=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || printf 'unknown')
export MODDIR ROOT UPPER WORK

say() { printf '%s\n' "$*"; }
die() { printf 'Selffont: %s\n' "$*" >&2; exit 2; }

# ---------------------------------------------------------------- 路径
system_path() { printf '%s/%s\n' "${ROOT}" "$1"; }          # 挂载点的绝对路径（假根带前缀）
init_view() {                                              # verify 读内容的路径
    if [ -n "$ROOT" ]; then printf '%s/%s\n' "$ROOT" "$1"
    elif [ -d /proc/1/root ]; then printf '/proc/1/root/%s\n' "$1"
    else printf '/%s\n' "$1"; fi
}
is_system_path() { case "$1" in /system|/system/*) return 0 ;; *) return 1 ;; esac; }

# ---------------------------------------------------------------- 目标清单
targets() {
    [ -d "$MODDIR/system" ] || return 1
    find "$MODDIR/system" -type f 2>/dev/null | sed "s|^$MODDIR/||" | sort
}

# ---------------------------------------------------------------- 计划：只许一种形状
# `overlay|system/fonts` 一条（有且只有一条），其余全是 `file|<已存在的系统文件>`。
# 这条规则在生成阶段就挡住第②③条，不靠执行阶段再检查。
build_plan() {   # $1 = 计划文件
    files="$1.files"
    targets > "$files" || return 1
    [ -s "$files" ] || return 1
    : > "$1" || return 1
    dirs=""
    while IFS= read -r rel; do
        d=${rel%/*}
        case " $dirs " in *" $d "*) ;; *) dirs="$dirs $d" ;; esac
    done < "$files"
    for d in $dirs; do
        case "$d" in
            */fonts)
                # 字体目录：整个目录一条 overlay。**一个名字都不单独挂**。
                printf 'overlay|%s\n' "$d" >> "$1"
                continue ;;
        esac
        while IFS= read -r rel; do
            case "$rel" in "$d"/*) ;; *) continue ;; esac
            if [ -e "$(init_view "$rel")" ]; then
                printf 'file|%s\n' "$rel" >> "$1"
            else
                say "跳过：$rel（系统里没有这个文件，bind 覆盖不了新文件）" >&2
            fi
        done < "$files"
    done
    rm -f "$files"
    [ -s "$1" ]
}

unit_files() {   # 这个单元让哪些文件变得可见（verify 按行数核对）
    case "$1" in
        overlay) targets | while IFS= read -r rel; do
                     case "$rel" in "$2"/*) printf '%s\n' "$rel" ;; esac
                 done ;;
        file)    printf '%s\n' "$2" ;;
    esac
}

# ---------------------------------------------------------------- 第③条守卫
# 任何 mount 调用之前都过这里：目录 → 只允许 overlay；bind 的源不许是目录，
# 目的地在 /system 下时更不许。写死在这一处，别的地方不许自己调 mount。
guard_mount() {   # $1=类型 $2=源 $3=目的
    case "$1" in
        overlay) return 0 ;;
        file)
            if [ -d "$2" ]; then
                die "拒绝：$2 是目录，不许 bind 到 $3（第③条：目录一律 overlay）"
            fi
            if is_system_path "$3" && is_system_path "$2" && [ -d "$2" ]; then
                die "拒绝：不许把 $2 目录 bind 到 $3"
            fi
            return 0 ;;
        *)
            die "拒绝：未知挂载类型 $1" ;;
    esac
}

# ---------------------------------------------------------------- upper
prepare_upper() {   # $1 = overlay 目标的相对路径（system/fonts）
    mkdir -p "$UPPER" "$WORK" 2>/dev/null || return 1
    # workdir 必须是空的（上一次失败的残留会让 overlay 直接 EINVAL），upper 只留模块里有的
    rm -rf "$WORK" 2>/dev/null; mkdir -p "$WORK" || return 1
    src="$MODDIR/$1"
    for f in "$UPPER"/*; do
        [ -e "$f" ] || continue
        [ -f "$src/${f##*/}" ] || rm -f "$f"
    done
    for f in "$src"/*; do
        [ -f "$f" ] || continue
        # 复制，不硬链接：upper 里的文件不能有指向外面的第二个链接。
        if [ -e "$UPPER/${f##*/}" ] && cmp -s "$f" "$UPPER/${f##*/}" 2>/dev/null; then
            [ "$(wc -c < "$f")" = "$(wc -c < "$UPPER/${f##*/}")" ] && continue
        fi
        cp -f "$f" "$UPPER/${f##*/}" || return 1
    done
    return 0
}

# ---------------------------------------------------------------- 命名空间里干活的
mount_unit() {   # $1=类型 $2=相对路径；只在本进程（= init 命名空间）里跑
    abs=$(system_path "$2")
    case "$1" in
        overlay)
            src="$MODDIR/$2"
            guard_mount overlay "$src" "$abs"
            mkdir -p "$UPPER" "$WORK" 2>/dev/null
            mount -t overlay overlay \
                -o "lowerdir=$abs,upperdir=$UPPER,workdir=$WORK" "$abs" ;;
        file)
            guard_mount file "$MODDIR/$2" "$abs"
            mount --bind "$MODDIR/$2" "$abs" ;;
        *)
            printf '未知单元类型：%s\n' "$1" >&2; return 1 ;;
    esac
}

ns_apply() {   # $1 = 计划文件；第②条在这里也守一遍，谁调用都绕不过去
    n=$(grep -c '^overlay|' "$1" 2>/dev/null); [ -n "$n" ] || n=0
    if [ "$n" -ne 1 ]; then
        printf 'fail|plan|%s|计划里 overlay 有 %s 条，只允许 1 条（第②条）\n' "$1" "$n"
        return 1
    fi
    bad=0
    while IFS='|' read -r kind rel; do
        [ -n "${kind:-}" ] || continue
        if err=$(mount_unit "$kind" "$rel" 2>&1); then
            printf 'ok|%s|%s\n' "$kind" "$rel"
        else
            bad=$((bad + 1))
            printf 'fail|%s|%s|%s\n' "$kind" "$rel" "$(printf '%s' "$err" | sed -n '1p')"
        fi
    done < "$1"
    [ "$bad" -eq 0 ]
}

ns_undo() {   # $1 = 单元文件；反序摘
    rev="$1.rev"
    sed '1!G;h;$!d' "$1" > "$rev" 2>/dev/null || tac "$1" > "$rev"
    while IFS='|' read -r kind rel; do
        [ -n "${kind:-}" ] || continue
        case "$kind" in '#'*) continue ;; esac
        abs=$(system_path "$rel")
        if umount "$abs" >/dev/null 2>&1; then
            printf 'ok|%s|%s|\n' "$kind" "$rel"
        elif err=$(umount -l "$abs" 2>&1); then
            printf 'ok|%s|%s|懒卸载\n' "$kind" "$rel"
        else
            printf 'fail|%s|%s|%s\n' "$kind" "$rel" "$(printf '%s' "$err" | sed -n '1p')"
        fi
    done < "$rev"
    rm -f "$rev"
}

# ---------------------------------------------------------------- 命名空间
NS_DONE=0
NS_CACHE=""
ns_prefix() {
    [ "$NS_DONE" = 1 ] && { printf '%s' "$NS_CACHE"; return 0; }
    NS_DONE=1
    if [ "${SELFFONT_NSENTER+given}" = given ]; then
        NS_CACHE=${SELFFONT_NSENTER}; printf '%s' "$NS_CACHE"; return 0
    fi
    if [ -n "$ROOT" ]; then printf ''; return 0 ; fi
    # 探测命令是 `true`：Android 的 toybox nsenter 会把命令行里任何 `-x` 当成自己的选项。
    for cand in "nsenter -t 1 -m" "nsenter -t 1 --mount" \
                "nsenter --target 1 --mount" "nsenter --target=1 --mount"; do
        # shellcheck disable=SC2086
        if err=$($cand true 2>&1); then
            NS_CACHE=$cand; printf '%s' "$NS_CACHE"; return 0
        fi
        printf 'Selffont: 探测 %s 不成 → %s\n' "$cand" "$(printf '%s' "$err" | sed -n '1p')" >&2
    done
    die "进不了 init 的挂载命名空间：三种 nsenter 写法都不成（原样输出在上面）。把 \`nsenter --help\` 的前 20 行贴出来再改。"
}

ns_run() {   # 永远只把 `sh 本脚本 …` 交给 nsenter，mount 的参数不许经过它的 getopt
    prefix=$(ns_prefix) || exit 2
    if [ -z "$prefix" ]; then "$@"; return $?; fi
    # shellcheck disable=SC2086
    $prefix "$@"
}

# ---------------------------------------------------------------- 挂载表
mount_table() { [ -n "$ROOT" ] && printf '/proc/self/mountinfo' || printf '/proc/1/mountinfo'; }

mounted_unit() {   # 0 = init（假根时=当前）的挂载表里有这个单元，而且是我们这份
    mnt=$(mount_table); [ -r "$mnt" ] || return 1
    abs=$(system_path "$2")
    case "$1" in
        overlay)
            [ -n "$ROOT" ] && { awk -v mp="$abs" '$5 == mp { f = 1 } END { exit !f }' "$mnt"; return $?; }
            awk -v mp="$abs" -v up="upperdir=$UPPER" \
                '$5 == mp && index($0, up) { f = 1 } END { exit !f }' "$mnt" ;;
        file)
            awk -v mp="$abs" '$5 == mp { f = 1 } END { exit !f }' "$mnt" ;;
        *) return 1 ;;
    esac
}

our_mountpoints() {   # 本脚本挂过的挂载点（init 视角），一行一个；从挂载表认，不从账认
    mnt=$(mount_table); [ -r "$mnt" ] || return 0
    awk -v up="upperdir=$UPPER" -v base="${UPPER%/*}" '
        {
            mp = $5
            if (index($0, up) || index(mp, base "/")) print mp
        }' "$mnt" | sort -u
}

count_our_overlays() {   # 第②条：我们的 overlay 必须恰好一条
    mnt=$(mount_table); [ -r "$mnt" ] || { printf 0; return 0; }
    awk -v up="upperdir=$UPPER" 'index($0, up) { n++ } END { print n + 0 }' "$mnt"
}

# ---------------------------------------------------------------- 账
stale_state() {
    [ -f "$UNITS" ] || return 1
    head=$(sed -n '1p' "$UNITS" 2>/dev/null)
    case "$head" in
        "#boot "*) [ "${head#\#boot }" = "$BOOT" ] && return 1 || return 0 ;;
    esac
    return 1
}

# ---------------------------------------------------------------- 回滚（第①条）
rollback() {   # 把 DONE 里记的按反序摘回去，然后清账；返回 0 = 回到挂之前
    [ -s "$DONE" ] || { rm -f "$JOURNAL" "$DONE"; return 0; }
    nd=$(grep -c . "$DONE" 2>/dev/null); [ -n "$nd" ] || nd=0
    say "回滚：摘掉本次已挂的 $nd 个单元"
    results=$(ns_run sh "$SELF" __ns undo "$DONE") || {
        say "回滚失败：进不去 init 命名空间，账留着（跑 panic 再试）"
        return 1
    }
    left=0
    while IFS='|' read -r tag kind rel note; do
        case "${tag:-}" in
            fail) left=$((left + 1)); say "回滚摘不动：$rel（$note）" ;;
        esac
    done <<EOF
$results
EOF
    rm -f "$JOURNAL" "$DONE" "$UNITS" "$STATE"
    if [ "$left" -gt 0 ]; then
        say "回滚没摘干净：$left 个还挂着。跑 \`sh $SELF panic\`"
        return 1
    fi
    say "已回滚到挂之前：没有本脚本的挂载残留"
    return 0
}

# ---------------------------------------------------------------- on
cmd_on() {
    st=$(cmd_status)
    if [ "$st" = on ]; then say "已经是 on（$UNITS）"; return 0; fi
    if [ "$st" = partial ]; then
        say "上一次是 partial，先摘干净再挂"
        cmd_off || die "partial 没摘干净（见上面的原样输出）：先跑 panic，或重启"
    fi

    if [ -f "$JOURNAL" ]; then
        say "检测到上一次没跑完的挂载（$JOURNAL），先清干净再挂"
        cmd_panic >/dev/null 2>&1 || true
    fi

    try="$PLAN.new"
    build_plan "$try" || die "没有可挂的文件：$MODDIR/system"

    # 第②条：计划里我们的 overlay 必须恰好一条，而且必须是字体目录。
    n_overlay=$(grep -c '^overlay|' "$try" 2>/dev/null); [ -n "$n_overlay" ] || n_overlay=0
    n_files=$(grep -c '^file|' "$try" 2>/dev/null); [ -n "$n_files" ] || n_files=0
    [ "$n_overlay" -eq 1 ] || { rm -f "$try"; die "计划里 overlay 有 $n_overlay 条，只允许 1 条（第②条）"; }
    grep -q '^overlay|.*/fonts$' "$try" || { rm -f "$try"; die "overlay 的目标不是字体目录：$(grep '^overlay|' "$try")"; }
    # 第③条：计划里不许出现目录 bind。
    if grep -q '^file|.*/fonts/' "$try"; then rm -f "$try"; die "计划里出现了逐字体 bind，禁止（第②条）"; fi

    if [ "$DRY" = 1 ]; then
        say "[dry-run] upper=$UPPER work=$WORK"
        say "[dry-run] 计划 $n_overlay 条 overlay + $n_files 条文件 bind"
        while IFS='|' read -r kind rel; do
            case "$kind" in
                overlay) say "[dry-run] mount -t overlay overlay -o lowerdir=$(system_path "$rel"),upperdir=$UPPER,workdir=$WORK $(system_path "$rel")" ;;
                file)    say "[dry-run] mount --bind $MODDIR/$rel $(system_path "$rel")" ;;
            esac
        done < "$try"
        rm -f "$try"
        return 0
    fi

    # ①：挂之前先把「我要挂什么」落盘（JOURNAL），每挂成功一个再追加到 DONE。
    cp -f "$try" "$JOURNAL" || { rm -f "$try"; die "写不了记账文件：$JOURNAL"; }
    : > "$DONE" || { rm -f "$try"; die "写不了记账文件：$DONE"; }

    for rel in $(grep '^overlay|' "$try" | cut -d'|' -f2); do
        prepare_upper "$rel" || { rm -f "$try"; rollback; die "upper 准备失败：$UPPER（/data 写不了或满了）"; }
    done

    results=$(ns_run sh "$SELF" __ns apply "$try")
    if [ -z "$results" ]; then
        rm -f "$try" "$JOURNAL" "$DONE"
        die "在 init 命名空间里执行失败（见上面的原样输出），系统没动"
    fi

    ok=0; bad=0
    while IFS='|' read -r tag kind rel note; do
        case "${tag:-}" in
            ok)   ok=$((ok + 1)); printf '%s|%s\n' "$kind" "$rel" >> "$DONE" ;;
            fail) bad=$((bad + 1)); say "挂载失败：$rel（$note）" ;;
        esac
    done <<EOF
$results
EOF

    # 第②条的执行期断言：我们的 overlay 必须恰好一条。
    # 假根里没有真挂载表可数（mount 是桩），这条只在真机生效。
    n_live=$(count_our_overlays)
    [ -n "$ROOT" ] && n_live=1
    if [ "$bad" -gt 0 ] || [ "$n_live" -ne 1 ]; then
        [ "$bad" -eq 0 ] && say "挂上去了，但我们的 overlay 有 $n_live 条（应当 1 条），按失败处理"
        rm -f "$try"
        rollback || say "回滚没干净：跑 \`sh $SELF panic\`"
        return 1
    fi

    printf '#boot %s\n' "$BOOT" > "$UNITS.new" || die "写不了状态文件：$UNITS.new"
    : > "$STATE.new" || die "写不了状态文件：$STATE.new"
    while IFS='|' read -r kind rel; do
        [ -n "$kind" ] || continue
        printf '%s|%s\n' "$kind" "$rel" >> "$UNITS.new"
        unit_files "$kind" "$rel" >> "$STATE.new"
    done < "$DONE"
    mv -f "$UNITS.new" "$UNITS" || die "写不了状态文件：$UNITS"
    mv -f "$STATE.new" "$STATE" || die "写不了状态文件：$STATE"
    rm -f "$JOURNAL" "$try"
    files=$(wc -l < "$STATE" | tr -d ' ')
    say "挂上 $ok 个单元、$files 个文件（字体目录一次 overlay，配置逐个 bind）"
    reload "$RELOAD"
    return 0
}

# ---------------------------------------------------------------- off
cmd_off() {
    if [ ! -f "$STATE" ] && [ ! -f "$UNITS" ]; then say "已经是 off"; return 0; fi
    if stale_state; then
        say "账是上一次开机留下的，这次没有热切换挂载：清账"
        rm -f "$STATE" "$UNITS" "$JOURNAL" "$DONE"
        return 0
    fi
    units="$UNITS"
    if [ ! -f "$UNITS" ]; then
        units="$UNITS.derived"; : > "$units"
        while IFS= read -r rel; do
            [ -n "$rel" ] || continue
            printf 'file|%s\n' "$rel" >> "$units"
        done < "$STATE"
    fi
    undo="$PLAN.undo"; : > "$undo" || die "写不了计划文件：$undo"
    n=0; skip=0
    while IFS='|' read -r kind rel; do
        [ -n "${kind:-}" ] || continue
        case "$kind" in '#'*) continue ;; esac
        if mounted_unit "$kind" "$rel"; then
            printf '%s|%s\n' "$kind" "$rel" >> "$undo"; n=$((n + 1))
        else
            skip=$((skip + 1)); say "跳过（挂载表里没有，不是本脚本挂的）：$rel"
        fi
    done < "$units"
    if [ "$DRY" = 1 ]; then
        while IFS='|' read -r kind rel; do say "[dry-run] umount $(system_path "$rel")"; done < "$undo"
        rm -f "$undo" "$UNITS.derived"; return 0
    fi
    results=$(ns_run sh "$SELF" __ns undo "$undo") || {
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
        say "部分摘掉：$n 个单元里 $bad 个失败，账先留着；跑 panic，或重启后账自然作废"
        return 1
    fi
    rm -f "$STATE" "$UNITS" "$JOURNAL" "$DONE"
    say "摘下 $n 个单元"$([ "$skip" -gt 0 ] && printf '（%s 个跳过）' "$skip")
    reload "$RELOAD"
    return 0
}

# ---------------------------------------------------------------- panic（第④条）
cmd_panic() {
    say "panic：摘掉本脚本挂过的一切挂载点，删 merged/upper，然后报告剩余"
    list="$PLAN.panic"
    our_mountpoints > "$list" || : > "$list"

    if [ "$DRY" = 1 ]; then
        while IFS= read -r mp; do [ -n "$mp" ] && say "[dry-run] umount $mp"; done < "$list"
        say "[dry-run] rm -rf $MERGED $UPPER $WORK $STATE $UNITS $JOURNAL $DONE"
        rm -f "$list"; return 0
    fi

    n=0; left=0
    # 反序摘：后挂的先摘（挂载表里靠后的在上面）
    sed '1!G;h;$!d' "$list" > "$list.rev" 2>/dev/null || tac "$list" > "$list.rev"
    while IFS= read -r mp; do
        [ -n "$mp" ] || continue
        if ns_run umount "$mp" >/dev/null 2>&1 || ns_run umount -l "$mp" >/dev/null 2>&1; then
            n=$((n + 1)); say "摘下：$mp"
        else
            left=$((left + 1)); say "摘不动：$mp（重启后会消失）"
        fi
    done < "$list.rev"
    rm -f "$list" "$list.rev"
    rm -rf "$MERGED" "$UPPER" "$WORK"
    rm -f "$STATE" "$UNITS" "$JOURNAL" "$DONE" "$PLAN" "$PLAN.new" "$PLAN.undo"
    say "删掉了 $MERGED、$UPPER、$WORK 与全部账"
    say "本脚本挂过并摘掉的：$n 个；摘不动的：$left 个"
    say "---- /proc/mounts 里与 fonts 相关的剩余行 ----"
    grep -i font /proc/mounts 2>/dev/null || say "（没有）"
    say "---- /system/fonts 的挂载层数：$(awk '$2 == "/system/fonts" { n++ } END { print n + 0 }' /proc/mounts 2>/dev/null) ----"
    [ "$left" -eq 0 ]
}

# ---------------------------------------------------------------- 重读
reload() {
    case "${1:-system}" in
        none) say "不触发重读：新进程会看到新挂载，已开的程序要手动重启"; return 0 ;;
        app)  say "只影响新进程：已开的程序保持旧字体（重启那个程序即可）"; return 0 ;;
    esac
    if command -v cmd >/dev/null 2>&1 && cmd font help >/dev/null 2>&1; then
        if [ "$DRY" = 1 ]; then say "[dry-run] cmd font update"; return 0; fi
        cmd font update >/dev/null 2>&1 && {
            say "已请求 FontManagerService 重读（返回 0；屏幕没变就加 --reload=system 软重启）"
            return 0
        }
    fi
    pid=$(pidof system_server 2>/dev/null | sed -n '1p')
    if [ -n "${pid:-}" ]; then
        if [ "$DRY" = 1 ]; then say "[dry-run] kill -9 $pid"; return 0; fi
        say "软重启 system_server（pid $pid），约 15–20 秒"
        kill -9 "$pid" 2>/dev/null || die "杀不掉 system_server（没有 root？）"
        return 0
    fi
    say "找不到可用的重读入口：新进程用新字体，已开的程序要重启"
    return 1
}

# ---------------------------------------------------------------- 查询
cmd_status() {
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
    fi
    if [ "$total" -eq 0 ]; then say off
    elif [ "$live" -ge "$total" ]; then say on
    elif [ "$live" -eq 0 ]; then say off
    else say partial; fi
    return 0
}

cmd_verify() {
    # 空账不算通过；开机 magic mount 不算本次成果；单元还得真在挂载表里。
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
        src="$MODDIR/$rel"; dst=$(init_view "$rel")
        if [ ! -f "$dst" ]; then say "缺：$dst"; bad=$((bad + 1)); continue; fi
        a=$(sha256sum "$src" 2>/dev/null | cut -d' ' -f1)
        b=$(sha256sum "$dst" 2>/dev/null | cut -d' ' -f1)
        if [ -n "$a" ] && [ "$a" = "$b" ]; then ok=$((ok + 1)); else say "不一致：$dst（模块 $a / 系统 $b）"; bad=$((bad + 1)); fi
    done < "$STATE"
    say "verify：一致 $ok，不一致 $bad$([ "$lost" -gt 0 ] && printf '，没挂 %s' "$lost")"
    if [ $((ok + bad)) -eq 0 ]; then
        say "verify：没有核对任何文件（$STATE 是空的）——空账不算通过"
        return 1
    fi
    [ "$bad" -eq 0 ] && [ "$lost" -eq 0 ]
}

# ---------------------------------------------------------------- 命名空间内的第二趟
case "${1:-}" in
    __ns)
        ns_action=${2:-}; plan=${3:-}
        [ -f "$plan" ] || die "计划文件不存在：$plan"
        case "$ns_action" in
            apply) ns_apply "$plan"; rc=$? ;;
            undo)  ns_undo "$plan"; rc=$? ;;
            *)     die "内部用法：hotswap.sh __ns apply|undo <计划文件>" ;;
        esac
        exit "$rc" ;;
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
    BASE=/tmp/selffont-hotswap
    STATE="$BASE.state"; UNITS="$BASE.units"; JOURNAL="$BASE.journal"; DONE="$BASE.done"; PLAN="$BASE.plan"
fi

case "$action" in
    on)     cmd_on ;;
    off)    cmd_off ;;
    toggle) if [ "$(cmd_status)" = on ]; then cmd_off; else cmd_on; fi ;;
    status) cmd_status ;;
    verify) cmd_verify ;;
    panic)  cmd_panic ;;
    -h|--help|help) awk 'NR > 1 && /^set -u$/ { exit } NR > 1' "$SELF" ; exit 0 ;;
    *) die "用法：sh hotswap.sh on|off|toggle|status|verify|panic [--dry-run] [--reload=system|app|none]" ;;
esac
