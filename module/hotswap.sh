#!/system/bin/sh
# Selffont 热切换：**不重启**把二创字件挂上去 / 摘下来。
#
# 五条硬规矩（2026-10-31 两次真机事故之后定的，改这个文件先看这里）：
#   ① **不许任何形式的整目录 bind 到 /system 路径**。目录只走 overlay；`mount --bind`
#      只用于**常规文件**，而且目标必须是系统里**已经存在**的文件。上一版给过一个
#      `mount --bind /data/adb/selffont/merged /system/fonts`，`/proc/mounts` 里成了
#      `/dev/block/dm-76 on /system/fonts type f2fs`——`bind` 继承源文件系统的设备与类型，
#      等于把系统字体目录指到数据分区。守卫在 `guard_mount()`，谁调 mount 都得先过它。
#   ② **空文件占位只在 `SELFFONT_SYSTEM_ROOT` 假根下建**。真机上 `/system` 只读，
#      建占位文件必然失败，而且会在 `/data` 里留下成排 0 字节文件。真机路径没有这段代码。
#   ③ **挂之前记录 mnt_id，摘的时候认 mnt_id**。每个单元挂之前把目标当前顶层 mnt_id
#      记下来（`<计划>.pre`），挂完再记我们这一层的 mnt_id；`off`/`panic` 只摘
#      「顶层 mnt_id 等于我们记的那个」的挂载点。路径被别的东西盖住就报出来、不猜、不摘。
#   ④ **失败一定回滚**：计划先落 journal，每挂成一个追加 done；任何单元失败就按 done
#      反序摘回去，回到挂之前的状态，账清空。
#   ⑤ `panic`：摘掉本脚本挂过的全部挂载点（认 mnt_id，也按 `/data/adb/selffont/` 前缀
#      扫孤儿），删 merged/upper/work 与全部账，最后打印 /proc/mounts 里与 fonts 相关的剩余行。
#
# 为什么非 overlay 不可：`SelfroundsCJK-VF-<版本>.ttf`、`Selffont-WenYuanRoundedSCVF.ttf`
# 是新名字，bind 只能覆盖**已存在**的路径，往只读的 /system 里建新文件必然失败。
# 只有 upperdir 能让新名字从目录里长出来。所以：
#
#   mount -t overlay overlay \
#     -o lowerdir=/system/fonts,upperdir=/data/adb/selffont/upper,workdir=/data/adb/selffont/work \
#     /system/fonts
#
# upper 里放模块字件的**副本**（不硬链接：upper 里的文件带指向外面的第二个链接时，
# 挂载阶段可能 EINVAL）。26 个文件约 147 MB，复制几秒，workdir 每次挂之前清空。
# 设备上本来就有的配置（`/system/etc/fonts_base.xml` 这类）逐个 bind **文件**；
# 不整目录 overlay `/system/etc`，那底下可能还压着别的挂载。
#
# 用法：
#   sh hotswap.sh on|off|toggle|status|verify|panic [--dry-run] [--reload=system|app|none]
#
#   on      挂上（已经是 on 就是空操作）
#   off     摘下（回到开机时那份系统配置）
#   toggle  在两者之间切换
#   status  打印 on / off / partial（看 init 的挂载表与 mnt_id，不看账）
#   verify  逐文件比对 sha256（经 /proc/1/root 从 init 视角读）；核对数为 0 返回 1
#   panic   摘掉本脚本挂过的一切、删 merged/upper/work，打印 /proc/mounts 里 fonts 相关剩余行
#
# 环境变量（测试用，正常使用别设）：
#   SELFFONT_SYSTEM_ROOT   假根：把 /system 映射到某个目录，跑完整流程但不碰真系统
#   SELFFONT_STATE         状态文件前缀（默认 /data/adb/selffont-hotswap）
#   SELFFONT_UPPER         overlay 的 upperdir（默认 /data/adb/selffont/upper）
#   SELFFONT_WORK          overlay 的 workdir（默认 /data/adb/selffont/work）
#   SELFFONT_MOUNTINFO     读哪份挂载表（默认 init 的 /proc/1/mountinfo；测试用）
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
UNITS="$BASE.units"          # 第一行 #boot <boot_id>，其余 kind|相对路径|我们的 mnt_id
JOURNAL="$BASE.journal"      # 挂之前就写：一行一个「我要挂的」
DONE="$BASE.done"            # 挂成功的一个单元一行：kind|相对路径|mnt_id
PRE="$BASE.pre"              # 每个单元挂之前的目标顶层 mnt_id
PLAN="$BASE.plan"
DRY=${SELFFONT_DRY_RUN:-0}
RELOAD=${SELFFONT_RELOAD:-system}
UPPER=${SELFFONT_UPPER:-/data/adb/selffont/upper}
WORK=${SELFFONT_WORK:-/data/adb/selffont/work}
MERGED=${SELFFONT_MERGED:-/data/adb/selffont/merged}   # 旧版留下的垃圾目录，panic 删
BOOT=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || printf 'unknown')
export MODDIR ROOT UPPER WORK

say() { printf '%s\n' "$*"; }
die() { printf 'Selffont: %s\n' "$*" >&2; exit 2; }

# ---------------------------------------------------------------- 路径与挂载表
system_path() { printf '%s/%s\n' "${ROOT}" "$1"; }     # 挂载点绝对路径（假根带前缀）
init_view() {                                           # verify 读内容的路径
    if [ -n "$ROOT" ]; then printf '%s/%s\n' "$ROOT" "$1"
    elif [ -d /proc/1/root ]; then printf '/proc/1/root/%s\n' "$1"
    else printf '/%s\n' "$1"; fi
}
is_system_path() { case "$1" in /system|/system/*) return 0 ;; *) return 1 ;; esac; }

mountinfo_file() {
    if [ -n "${SELFFONT_MOUNTINFO:-}" ]; then printf '%s\n' "$SELFFONT_MOUNTINFO"
    elif [ -n "$ROOT" ]; then printf '/proc/self/mountinfo\n'
    else printf '/proc/1/mountinfo\n'; fi
}

# mnt_id 是每个挂载实例在内核里的编号，同一路径叠多层时各自不同。
# 顶层 = 该路径上 mnt_id 最大的那个（新挂的 id 一定更大）。
top_mnt_id() {   # $1=绝对路径 → 顶层 mnt_id；没有挂载则输出空
    f=$(mountinfo_file); [ -r "$f" ] || return 0
    awk -v mp="$1" '$5 == mp { if ($1 + 0 > best) best = $1 + 0 } END { if (best > 0) print best }' "$f"
}

mnt_id_exists() {   # $1=id $2=绝对路径；这一层还在不在（被盖住也算在）
    f=$(mountinfo_file); [ -r "$f" ] || return 1
    awk -v id="$1" -v mp="$2" '($1 == id) && ($5 == mp) { f = 1 } END { exit !f }' "$f"
}

any_mount_at() {
    f=$(mountinfo_file); [ -r "$f" ] || return 1
    awk -v mp="$1" '$5 == mp { f = 1 } END { exit !f }' "$f"
}

unit_ok() {   # $1=kind $2=相对路径 $3=mnt_id；0 = 我们这一层还在最上面
    abs=$(system_path "$2")
    if [ -n "${3:-}" ] && [ "$3" != "-" ]; then
        [ "$(top_mnt_id "$abs")" = "$3" ]
    else
        any_mount_at "$abs"
    fi
}

# ---------------------------------------------------------------- 目标清单
targets() {
    [ -d "$MODDIR/system" ] || return 1
    find "$MODDIR/system" -type f 2>/dev/null | sed "s|^$MODDIR/||" | sort
}

# ---------------------------------------------------------------- 计划
# 只允许两种单元：`overlay|system/fonts`（有且只有一条）与 `file|<已存在的系统文件>`。
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
            elif [ -n "$ROOT" ]; then
                # ② 只有假根才允许「目标不存在 → 稍后建空文件占位」。
                printf 'file|%s\n' "$rel" >> "$1"
            else
                say "跳过：$rel（系统里没有这个文件；bind 不能新增文件，真机上也不许建占位）" >&2
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

# ---------------------------------------------------------------- ① 守卫
# 唯一允许发起 mount 的地方都要过这里。规矩：
#   overlay  → 允许（目录只走这条）
#   file     → 源必须是**常规文件**；源在 /data/adb/selffont 之下（我们的工作目录）时
#              只允许是 upper 之外的配置？不——一律不许，工作目录只放数据，不往系统里挂。
#   其它     → 拒绝
guard_mount() {   # $1=类型 $2=源 $3=目的
    case "$1" in
        overlay)
            [ -d "$2" ] || die "拒绝：overlay 的源不是目录：$2"
            return 0 ;;
        file)
            [ -f "$2" ] || die "拒绝：bind 的源不是常规文件：$2（目录一律 overlay，第①条）"
            case "$2" in
                "$UPPER"/*|"$UPPER"|"$WORK"/*|"$WORK"|"$MERGED"/*|"$MERGED")
                    die "拒绝：不许把工作目录里的东西挂进系统：$2 → $3" ;;
            esac
            if is_system_path "$3" && [ -d "$2" ]; then
                die "拒绝：不许把目录 bind 到 /system 路径：$2 → $3（第①条）"
            fi
            return 0 ;;
        *)
            die "拒绝：未知挂载类型 $1" ;;
    esac
}

# ---------------------------------------------------------------- upper
prepare_upper() {   # $1 = overlay 目标的相对路径（system/fonts）
    mkdir -p "$UPPER" "$WORK" 2>/dev/null || return 1
    # workdir 必须是空的（上次失败的残留会让 overlay 直接 EINVAL）
    rm -rf "$WORK" 2>/dev/null; mkdir -p "$WORK" || return 1
    src="$MODDIR/$1"
    for f in "$UPPER"/*; do
        [ -e "$f" ] || continue
        [ -f "$src/${f##*/}" ] || rm -f "$f"
    done
    for f in "$src"/*; do
        [ -f "$f" ] || continue
        if [ -e "$UPPER/${f##*/}" ] && cmp -s "$f" "$UPPER/${f##*/}" 2>/dev/null; then
            continue
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
            guard_mount overlay "$MODDIR/$2" "$abs"
            mkdir -p "$UPPER" "$WORK" 2>/dev/null
            mount -t overlay overlay \
                -o "lowerdir=$abs,upperdir=$UPPER,workdir=$WORK" "$abs" ;;
        file)
            guard_mount file "$MODDIR/$2" "$abs"
            # ② 占位文件只许在假根下建；真机 /system 只读，建了也是失败。
            if [ -n "$ROOT" ] && [ ! -e "$abs" ]; then
                mkdir -p "${abs%/*}" 2>/dev/null
                : > "$abs" 2>/dev/null || { printf '建不出假根占位：%s\n' "$abs" >&2; return 1; }
            fi
            mount --bind "$MODDIR/$2" "$abs" ;;
        *)
            printf '未知单元类型：%s\n' "$1" >&2; return 1 ;;
    esac
}

ns_apply() {   # $1 = 计划文件；第②条（overlay 恰好一条）在这里也守一遍
    n=$(grep -c '^overlay|' "$1" 2>/dev/null); [ -n "$n" ] || n=0
    if [ "$n" -ne 1 ]; then
        printf 'fail|plan|%s|计划里 overlay 有 %s 条，只允许 1 条（第②条）\n' "$1" "$n"
        return 1
    fi
    pre="$1.pre"
    : > "$pre" || { printf 'fail|plan|%s|写不了 %s\n' "$1" "$pre"; return 1; }
    bad=0
    while IFS='|' read -r kind rel; do
        [ -n "${kind:-}" ] || continue
        abs=$(system_path "$rel")
        # ③ 挂之前记下目标当前顶层 mnt_id
        prev=$(top_mnt_id "$abs"); [ -n "$prev" ] || prev=-
        printf 'pre|%s|%s|%s\n' "$kind" "$rel" "$prev" >> "$pre"
        if err=$(mount_unit "$kind" "$rel" 2>&1); then
            id=$(top_mnt_id "$abs"); [ -n "$id" ] || id=-
            if [ "$id" != "-" ] && [ "$id" = "$prev" ]; then
                bad=$((bad + 1))
                printf 'fail|%s|%s|挂完 mnt_id 还是 %s：没挂上（或被别的东西盖着）\n' \
                    "$kind" "$rel" "$id"
                continue
            fi
            printf 'ok|%s|%s|%s|%s\n' "$kind" "$rel" "$id" "$prev"
        else
            bad=$((bad + 1))
            printf 'fail|%s|%s|%s\n' "$kind" "$rel" "$(printf '%s' "$err" | sed -n '1p')"
        fi
    done < "$1"
    [ "$bad" -eq 0 ]
}

ns_undo() {   # $1 = 单元文件（kind|相对路径|mnt_id）；反序摘，认 mnt_id
    rev="$1.rev"
    bad=0
    sed '1!G;h;$!d' "$1" > "$rev" 2>/dev/null || tac "$1" > "$rev"
    while IFS='|' read -r kind rel id; do
        [ -n "${kind:-}" ] || continue
        case "$kind" in '#'*) continue ;; esac
        abs=$(system_path "$rel")
        if [ -n "${id:-}" ] && [ "$id" != "-" ]; then
            top=$(top_mnt_id "$abs")
            if [ "$top" != "$id" ]; then
                if mnt_id_exists "$id" "$abs"; then
                    bad=$((bad + 1))
                    printf 'fail|%s|%s|被别的挂载盖住（我们 %s，上面 %s）\n' "$kind" "$rel" "$id" "$top"
                else
                    printf 'ok|%s|%s|已经不在了（mnt_id %s）\n' "$kind" "$rel" "$id"
                fi
                continue
            fi
        fi
        if umount "$abs" >/dev/null 2>&1; then
            printf 'ok|%s|%s|\n' "$kind" "$rel"
        elif err=$(umount -l "$abs" 2>&1); then
            printf 'ok|%s|%s|懒卸载\n' "$kind" "$rel"
        else
            bad=$((bad + 1))
            printf 'fail|%s|%s|%s\n' "$kind" "$rel" "$(printf '%s' "$err" | sed -n '1p')"
        fi
    done < "$rev"
    rm -f "$rev"
    [ "$bad" -eq 0 ]
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
    # 探测命令是 `true`：toybox 的 nsenter 会把命令行里任何 `-x` 当成自己的选项。
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

count_our_overlays() {
    f=$(mountinfo_file); [ -r "$f" ] || { printf 0; return 0; }
    awk -v up="upperdir=$UPPER" 'index($0, up) { n++ } END { print n + 0 }' "$f"
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

# ---------------------------------------------------------------- ④ 回滚
rollback() {
    if [ ! -s "$DONE" ]; then rm -f "$JOURNAL" "$DONE" "$PRE" "$PLAN.new" "$PLAN.new.pre"; return 0; fi
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
    rm -f "$DONE" "$JOURNAL" "$UNITS" "$STATE" "$PRE" "$PLAN.new" "$PLAN.new.pre"
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

    n_overlay=$(grep -c '^overlay|' "$try" 2>/dev/null); [ -n "$n_overlay" ] || n_overlay=0
    n_files=$(grep -c '^file|' "$try" 2>/dev/null); [ -n "$n_files" ] || n_files=0
    # ② 我们的 overlay 必须恰好一条，且必须是字体目录；字体目录不许出现逐名 bind。
    [ "$n_overlay" -eq 1 ] || { rm -f "$try"; die "计划里 overlay 有 $n_overlay 条，只允许 1 条（第②条）"; }
    grep -q '^overlay|.*/fonts$' "$try" || { rm -f "$try"; die "overlay 的目标不是字体目录：$(grep '^overlay|' "$try")"; }
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

    # ④ 挂之前先把「我要挂什么」落盘，每挂成功一个追加到 done
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
    while IFS='|' read -r tag kind rel id extra; do
        case "${tag:-}" in
            pre)  ;;
            ok)   ok=$((ok + 1)); printf '%s|%s|%s\n' "$kind" "$rel" "$id" >> "$DONE" ;;
            fail) bad=$((bad + 1)); say "挂载失败：$rel（$id）" ;;
        esac
    done <<EOF
$results
EOF

    # ③/② 执行期断言：我们的 overlay 恰好一条（假根里没有真挂载表可数，跳过）
    n_live=1
    if [ -z "$ROOT" ]; then n_live=$(count_our_overlays); fi
    if [ "$bad" -gt 0 ] || [ "$n_live" -ne 1 ]; then
        [ "$bad" -eq 0 ] && say "挂上去了，但我们的 overlay 有 $n_live 条（应当 1 条），按失败处理"
        rm -f "$try"
        rollback || say "回滚没干净：跑 \`sh $SELF panic\`"
        return 1
    fi

    printf '#boot %s\n' "$BOOT" > "$UNITS.new" || die "写不了状态文件：$UNITS.new"
    : > "$STATE.new" || die "写不了状态文件：$STATE.new"
    while IFS='|' read -r kind rel id; do
        [ -n "$kind" ] || continue
        printf '%s|%s|%s\n' "$kind" "$rel" "$id" >> "$UNITS.new"
        unit_files "$kind" "$rel" >> "$STATE.new"
    done < "$DONE"
    mv -f "$UNITS.new" "$UNITS" || die "写不了状态文件：$UNITS"
    mv -f "$STATE.new" "$STATE" || die "写不了状态文件：$STATE"
    [ -f "$try.pre" ] && mv -f "$try.pre" "$PRE"
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
        say "账是上一次开机留下的，这次没有热切换挂载：清账，顺手删 upper/work/merged"
        rm -rf "$UPPER" "$WORK" "$MERGED"
        rm -f "$STATE" "$UNITS" "$JOURNAL" "$DONE" "$PRE"
        return 0
    fi
    undo="$PLAN.undo"; : > "$undo" || die "写不了计划文件：$undo"
    n=0; skip=0; stuck=0
    while IFS='|' read -r kind rel id; do
        [ -n "${kind:-}" ] || continue
        case "$kind" in '#'*) continue ;; esac
        abs=$(system_path "$rel")
        if [ -n "${id:-}" ] && [ "$id" != "-" ]; then
            top=$(top_mnt_id "$abs")
            if [ "$top" = "$id" ]; then
                printf '%s|%s|%s\n' "$kind" "$rel" "$id" >> "$undo"; n=$((n + 1))
            elif mnt_id_exists "$id" "$abs"; then
                # ③ 我们的层被别的东西盖住了：不猜、不摘，报出来
                stuck=$((stuck + 1))
                say "不摘：$rel 我们这层（mnt_id $id）上面还压着 mnt_id $top"
            else
                skip=$((skip + 1)); say "跳过（mnt_id $id 已经不在了）：$rel"
            fi
        else
            # 旧账（没有 mnt_id）或假根：只能按路径
            if any_mount_at "$abs"; then
                printf '%s|%s|\n' "$kind" "$rel" >> "$undo"; n=$((n + 1))
            else
                skip=$((skip + 1)); say "跳过（挂载表里没有）：$rel"
            fi
        fi
    done < "$UNITS" 2>/dev/null || true
    if [ ! -f "$UNITS" ]; then
        while IFS= read -r rel; do
            [ -n "$rel" ] || continue
            printf 'file|%s|\n' "$rel" >> "$undo"; n=$((n + 1))
        done < "$STATE"
    fi
    if [ "$DRY" = 1 ]; then
        while IFS='|' read -r kind rel id; do say "[dry-run] umount $(system_path "$rel")  # mnt_id ${id:--}"; done < "$undo"
        rm -f "$undo"; return 0
    fi
    results=$(ns_run sh "$SELF" __ns undo "$undo") || {
        rm -f "$undo"
        say "在 init 命名空间里执行失败（见上面的原样输出）：账留着，挂载没动"
        return 1
    }
    bad=0
    while IFS='|' read -r tag kind rel note; do
        case "${tag:-}" in
            ok)   [ -n "${note:-}" ] && say "摘下：$rel（$note）" ;;
            fail) bad=$((bad + 1)); say "摘不动：$rel（$note）" ;;
        esac
    done <<EOF
$results
EOF
    rm -f "$undo"
    if [ "$bad" -gt 0 ] || [ "$stuck" -gt 0 ]; then
        say "没摘干净：$n 个可摘、$bad 个失败、$stuck 个被盖住；账留着。跑 panic，或重启后账自然作废"
        return 1
    fi
    rm -f "$STATE" "$UNITS" "$JOURNAL" "$DONE" "$PRE"
    say "摘下 $n 个单元"$([ "$skip" -gt 0 ] && printf '（%s 个跳过）' "$skip")
    reload "$RELOAD"
    return 0
}

# ---------------------------------------------------------------- panic（⑤）
cmd_panic() {
    say "panic：按 mnt_id 摘掉本脚本挂过的挂载点，删 merged/upper/work，然后报告剩余"
    list="$PLAN.panic"; : > "$list" || die "写不了 $list"
    n=0; stuck=0

    # (1) 账上有的：认 mnt_id
    if [ -f "$UNITS" ]; then
        while IFS='|' read -r kind rel id; do
            [ -n "${kind:-}" ] || continue
            case "$kind" in '#'*) continue ;; esac
            abs=$(system_path "$rel")
            [ -n "${id:-}" ] || id=-
            printf '%s|%s\n' "${id}" "$abs" >> "$list"
        done < "$UNITS"
    fi
    # (2) 账上没有的孤儿：只认「我们的 overlay（super options 里 upperdir=UPPER）」与
    # 「挂载点就在我们自己的 upper/work/merged 目录里」。**不按 /data 前缀扫**——
    # 上一版就是拿 /data/adb/selffont 当前缀，连别人的挂载都会被算成自己的。
    f=$(mountinfo_file)
    if [ -r "$f" ]; then
        awk -v up="upperdir=$UPPER" -v u="$UPPER" -v w="$WORK" -v m="$MERGED" '
            index($0, up) { print $1 "|" $5; next }
            ($5 == u || index($5, u "/") == 1) { print $1 "|" $5; next }
            ($5 == w || index($5, w "/") == 1) { print $1 "|" $5; next }
            ($5 == m || index($5, m "/") == 1) { print $1 "|" $5 }' "$f" >> "$list"
    fi

    if [ "$DRY" = 1 ]; then
        while IFS='|' read -r id abs; do say "[dry-run] umount $abs  # mnt_id $id"; done < "$list"
        say "[dry-run] rm -rf $MERGED $UPPER $WORK $STATE $UNITS $JOURNAL $DONE $PRE"
        rm -f "$list"; return 0
    fi

    # 去重后按挂载顺序反序摘（id 大的后挂，先摘）
    sort -u "$list" 2>/dev/null | sort -t'|' -k1,1n > "$list.sorted" 2>/dev/null || sort -u "$list" > "$list.sorted"
    sed '1!G;h;$!d' "$list.sorted" > "$list.rev" 2>/dev/null || tac "$list.sorted" > "$list.rev"
    while IFS='|' read -r id abs; do
        [ -n "${abs:-}" ] || continue
        if [ -n "$id" ] && [ "$id" != "-" ]; then
            if ! mnt_id_exists "$id" "$abs"; then
                say "跳过：$abs（mnt_id $id 已经不在）"; continue
            fi
            if [ "$(top_mnt_id "$abs")" != "$id" ]; then
                stuck=$((stuck + 1))
                say "不摘：$abs（mnt_id $id）上面还压着 mnt_id $(top_mnt_id "$abs")——重启最干净"
                continue
            fi
        fi
        if ns_run umount "$abs" >/dev/null 2>&1 || ns_run umount -l "$abs" >/dev/null 2>&1; then
            n=$((n + 1)); say "摘下：$abs（mnt_id $id）"
        else
            stuck=$((stuck + 1)); say "摘不动：$abs（重启后会消失）"
        fi
    done < "$list.rev"
    rm -f "$list" "$list.sorted" "$list.rev"

    rm -rf "$MERGED"
    if [ "$stuck" -gt 0 ]; then
        # 还有我们的 overlay 挂着：upper 正被它用着，删了会让 /system/fonts 读失败
        say "还有 $stuck 个没摘掉，upper/work 先留着（挂着的 overlay 正在用）；重启后再跑一次 panic"
    else
        rm -rf "$UPPER" "$WORK"
        say "删掉了 $MERGED、$UPPER、$WORK"
    fi
    rm -f "$STATE" "$UNITS" "$JOURNAL" "$DONE" "$PRE" "$PLAN" "$PLAN.new" "$PLAN.new.pre" "$PLAN.undo"
    say "账已清"
    say "摘掉 $n 个；没摘掉的 $stuck 个"
    say "---- /proc/mounts 里与 fonts 相关的剩余行 ----"
    grep -i font /proc/mounts 2>/dev/null || say "（没有）"
    say "---- /system/fonts 的挂载层数：$(awk '$2 == "/system/fonts" { n++ } END { print n + 0 }' /proc/mounts 2>/dev/null) ----"
    f=$(mountinfo_file); mp=$(system_path system/fonts)
    [ -r "$f" ] && say "---- $(printf '%s' "$mp") 在挂载表里的层数：$(awk -v mp="$mp" '$5 == mp { n++ } END { print n + 0 }' "$f") ----"
    [ "$stuck" -eq 0 ]
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
    while IFS='|' read -r kind rel id; do
        [ -n "${kind:-}" ] || continue
        case "$kind" in '#'*) continue ;; esac
        total=$((total + 1))
        unit_ok "$kind" "$rel" "${id:--}" && live=$((live + 1))
    done < "$UNITS"
    if [ "$total" -eq 0 ]; then
        # 只有旧版 state（无 units）：按文件路径判
        while IFS= read -r rel; do
            [ -n "$rel" ] || continue
            total=$((total + 1)); any_mount_at "$(system_path "$rel")" && live=$((live + 1))
        done < "$STATE"
    fi
    if [ "$total" -eq 0 ]; then say off
    elif [ "$live" -ge "$total" ]; then say on
    elif [ "$live" -eq 0 ]; then say off
    else say partial; fi
    return 0
}

cmd_verify() {
    [ -f "$STATE" ] || { say "verify：没有热切换状态（现在是 off），没有可核对的文件"; return 1; }
    if stale_state; then
        say "verify：账是上一次开机留下的，这次没有热切换挂载（开机 magic mount 不算）"
        return 1
    fi
    lost=0
    if [ -f "$UNITS" ]; then
        while IFS='|' read -r kind rel id; do
            [ -n "${kind:-}" ] || continue
            case "$kind" in '#'*) continue ;; esac
            unit_ok "$kind" "$rel" "${id:--}" || { say "没挂：$rel"; lost=$((lost + 1)); }
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
    STATE="$BASE.state"; UNITS="$BASE.units"; JOURNAL="$BASE.journal"
    DONE="$BASE.done"; PRE="$BASE.pre"; PLAN="$BASE.plan"
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
