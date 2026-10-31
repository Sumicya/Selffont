#!/system/bin/sh
# Selffont 运行期换字体：**本机不支持**。这个脚本只剩两件事——报告状态、清残留。
#
# 四条路都有真机证据判死（2026-10-31，一加 / Android 16 / SDK 36 / KernelSU 3.3.1 /
# 内核 6.6.118-android15 GKI），证据行原样抄在下面，README 同文：
#
#   ① 内核 overlay 带 upperdir（本脚本上一版的做法）
#      mount: 'overlay'->'/system/fonts': Invalid argument        （加 userxattr 同样 EINVAL）
#      —— /system/fonts 上已有 KernelSU 的开机 overlay，lowerdir 是 erofs，内核直接拒。
#   ② 逐文件 bind（mount 的 --bind 形式）
#      can't create /system/fonts/Selffont-WenYuanRoundedSCVF.ttf: Read-only file system
#      —— bind 只能覆盖已存在的路径，新字体名要先在只读分区建文件。
#   ③ 改模块目录再触发重挂（KernelSU hot_install）
#      —— 探针文件在 /system/fonts 里不出现：那是开机快照，运行期改模块目录不重挂。
#   ④ cmd font update
#      —— 需要签名；install-debug-cert 只对 debuggable 包放行。
#
# 所以：**换字体 = 装/改模块 → 重启**。要以后运行期换，只剩进程内路线（LSPosed 探针，
# 见 README「进程内路线」），那条还没验。
#
# 用法：
#   sh hotswap.sh            打印状态（本机不支持 + 残留层数）
#   sh hotswap.sh status     同上
#   sh hotswap.sh panic      清残留：摘掉能认定是本模块留下的挂载层，删 /data/adb/selffont
#                            与全部状态文件，最后打印 /proc/mounts 里与 fonts 相关的剩余行
#
# 这个文件里没有任何发起挂载的语句：它只摘不挂。
set -u

SELF=$(readlink -f "$0" 2>/dev/null || printf '%s' "$0")
MODDIR=${SELF%/*}
[ "$MODDIR" = "$SELF" ] && MODDIR=.
# 路径可覆盖只为测试（真机上别设）：
DATA=${SELFFONT_DATA:-/data/adb/selffont}
BASE=${SELFFONT_BASE:-/data/adb/selffont-hotswap}
UPPER=$DATA/upper
WORK=$DATA/work
MERGED=$DATA/merged
SYSTEM_FONTS=${SELFFONT_SYSTEM_FONTS:-/system/fonts}

say() { printf '%s\n' "$*"; }

mountinfo() {
    if [ -n "${SELFFONT_MOUNTINFO:-}" ]; then printf '%s' "$SELFFONT_MOUNTINFO"
    elif [ -r /proc/1/mountinfo ]; then printf '/proc/1/mountinfo'
    else printf '/proc/self/mountinfo'; fi
}
mnts() {
    if [ -n "${SELFFONT_MOUNTS:-}" ]; then printf '%s' "$SELFFONT_MOUNTS"
    elif [ -r /proc/1/mounts ]; then printf '/proc/1/mounts'
    else printf '/proc/mounts'; fi
}

# 本模块留下的挂载层：只认三种可认定的形状，其余一律当别人的。
#   (a) 挂载点就是 /system/fonts 且 fstype 不是 overlay —— 上一版目录 bind 的形状
#       （bind 继承源文件系统，/data 是 f2fs，于是 mountinfo 里显示 f2fs）；
#   (b) 挂载点在 $DATA 之下（upper/work/merged 里挂出来的东西）；
#   (c) super options 里 upperdir= 指向 $UPPER —— 我们那份 overlay。
# 输出：mnt_id|挂载点|来源说明（按 mnt_id 升序，摘的时候反序）。
our_layers() {
    f=$(mountinfo)
    [ -r "$f" ] || return 0
    awk -v sf="$SYSTEM_FONTS" -v data="$DATA" -v up="upperdir=$UPPER" '
        {
            id = $1; mp = $5
            sep = 0
            for (i = 7; i <= NF; i++) { if ($i == "-") { sep = i; break } }
            fstype = (sep ? $(sep + 1) : "")
            why = ""
            if (mp == sf && fstype != "overlay") why = "整目录 bind 残留（fstype " fstype "）"
            else if (index(mp, data "/") == 1 || mp == data) why = "工作目录里的挂载"
            else if (index($0, up)) why = "我们那份 overlay（upperdir 对得上）"
            if (why != "") print id "|" mp "|" why
        }' "$f"
}

residue_count() {
    # grep -c 空输入会打印 0 并退出 1：写 `|| printf 0` 会拼出 "0\n0"，[ -gt ] 当场报错。
    n=$(our_layers | grep -c . 2>/dev/null || true)
    printf '%s' "${n:-0}"
}

cmd_status() {
    n=$(residue_count)
    say "运行期换字体：本机不支持（四条路的真机证据见 README「热切换」一节）"
    say "换字体请改模块后**重启**；这个脚本只报告与清场，不挂任何东西。"
    say "残留挂载层：$n"
    if [ "$n" -gt 0 ]; then
        our_layers | while IFS='|' read -r id mp why; do
            say "  mnt_id $id  $mp  —— $why"
        done
        say "清场：sh $SELF panic"
    fi
    if [ -d "$DATA" ]; then
        say "工作目录：$DATA（$(du -sh "$DATA" 2>/dev/null | cut -f1)）"
    fi
    ls "$BASE".* >/dev/null 2>&1 && say "状态文件：$(ls "$BASE".* 2>/dev/null | tr '\n' ' ')"
    return 0
}

cmd_panic() {
    say "panic：只摘能认定是本模块留下的层，然后删工作目录与状态文件"
    list=/tmp/selffont-panic.$$
    our_layers > "$list" || : > "$list"
    n=0; left=0
    # 反序摘：mnt_id 大的后挂，先摘
    sort -t'|' -k1,1n "$list" 2>/dev/null | sed '1!G;h;$!d' > "$list.rev" 2>/dev/null \
        || sort -t'|' -k1,1n "$list" > "$list.rev"
    while IFS='|' read -r id mp why; do
        [ -n "${mp:-}" ] || continue
        # 只摘顶层：同一路径上还有更新的挂载时不动，免得摘出个洞
        top=$(awk -v mp="$mp" '$5 == mp { if ($1 + 0 > m) m = $1 + 0 } END { print m + 0 }' "$(mountinfo)")
        if [ "$top" != "$id" ]; then
            left=$((left + 1))
            say "不摘：$mp（mnt_id $id 上面还压着 mnt_id $top）"
            continue
        fi
        if umount "$mp" >/dev/null 2>&1 || umount -l "$mp" >/dev/null 2>&1; then
            n=$((n + 1)); say "摘下：$mp（mnt_id $id，$why）"
        else
            left=$((left + 1)); say "摘不动：$mp（重启后会消失）"
        fi
    done < "$list.rev"
    rm -f "$list" "$list.rev"

    rm -rf "$DATA"
    rm -f "$BASE".state "$BASE".units "$BASE".journal "$BASE".done "$BASE".pre \
          "$BASE".plan "$BASE".plan.new "$BASE".plan.new.pre "$BASE".plan.undo
    say "删掉了 $DATA 与全部状态文件"
    say "摘掉 $n 层；没摘掉 $left 层"
    say "---- /proc/mounts 里与 fonts 相关的剩余行 ----"
    grep -i font "$(mnts)" 2>/dev/null || say "（没有）"
    say "---- $SYSTEM_FONTS 的挂载层数：$(awk -v sf="$SYSTEM_FONTS" '$2 == sf { n++ } END { print n + 0 }' "$(mnts)" 2>/dev/null) ----"
    [ "$left" -eq 0 ]
}

case "${1:-status}" in
    status|"") cmd_status ;;
    panic)     cmd_panic ;;
    -h|--help|help) awk 'NR > 1 && /^set -u$/ { exit } NR > 1' "$SELF"; exit 0 ;;
    *)
        say "本机不支持运行期换字体。用法：sh hotswap.sh [status|panic]" >&2
        exit 2 ;;
esac
