#!/system/bin/sh
# 全机垃圾排查：默认**只读**，只打印；确认无误后加 --delete 才动手。
#
# 为什么要有这个脚本
# -----------------
# 2026-11-08 主人问「前会话在 Download 里搞的 ksubak / disablebak 那些东西」。
# 手工一条 find 查不全：垃圾分三类，散在三个地方——
#   ① 本模块自己的临时件与状态（`/data/adb/selffont*`、`/data/local/tmp/selffont*`）；
#   ② 备份后缀（`*.bak` `*.orig` `*~`），多在 Download 与模块目录里；
#   ③ **误用的状态标记**（`disablebak` `disable.bak`）：KernelSU/APatch 只认名字正好是
#      `disable`/`remove`/`update` 的空文件，带后缀的不生效，纯垃圾；但它们和真标记
#      长得像，误删真标记会被当成「停用模块」，所以这里把两者分开列、只删后一种。
# 另外上一版脚本的坑写在下面「必须 root」那条里：非 root 跑出来的「（无）」是假的。
#
# 用法
#   su -c 'sh /storage/emulated/0/Download/check_garbage.sh'            # 只查
#   su -c 'sh /storage/emulated/0/Download/check_garbage.sh --delete'   # 查完就删可删的
#   SELFFONT_SCAN_BASE=/tmp/g sh tools/check_garbage.sh                 # 本机夹具自测用
#
# 退出码：0 = 查完（不论有无命中）；3 = 不是 root（拒绝给出「干净」的假结论）。

set -u
BASE="${SELFFONT_SCAN_BASE:-}"
DELETE=0
[ "${1:-}" = "--delete" ] && DELETE=1

# 非 root 时 /data/adb 读不到，find 静默返回空 —— 于是整份报告都是「（无）」。
# 上一版就栽在这：`su -c ... || sh ...` 兜底跑成普通用户，看着像全机干净。
if [ -z "$BASE" ] && [ "$(id -u)" != "0" ]; then
    echo "这脚本必须 root 跑：非 root 读不到 /data/adb，结论会是假的「（无）」。"
    echo "重来：su -c 'sh /storage/emulated/0/Download/check_garbage.sh --delete(可选)'"
    exit 3
fi

TOTALS=$(mktemp 2>/dev/null || echo /data/local/tmp/.selffont-scan.$$)
: > "$TOTALS"

time_of() {  # 11-08 05:38（toybox stat 有 -c）
    stat -c '%y' "$1" 2>/dev/null | cut -c6-16
}
size_kb() {
    stat -c '%s' "$1" 2>/dev/null | awk '{printf "%d", ($1 + 1023) / 1024}' 2>/dev/null || echo 0
}

# list <类别名> <可删:yes|no> <说明> <find 参数…>
# 命中就逐行列「大小 时间 路径」；标可删且 --delete 时删掉。
list() {
    label=$1; deletable=$2; note=$3; shift 3
    out=$(find "$@" 2>/dev/null)
    [ -n "$out" ] || return 0
    printf '\n-- %s（%s）\n   %s\n' "$label" "$deletable" "$note"
    echo "$out" | while IFS= read -r p; do
        [ -n "$p" ] || continue
        kb=$(size_kb "$p")
        printf '   %6s KB  %s  %s\n' "$kb" "$(time_of "$p")" "$p"
        echo "$kb" >> "$TOTALS"
        if [ "$DELETE" = 1 ] && [ "$deletable" = "yes" ]; then
            if rm -rf "$p" 2>/dev/null; then echo '           ↳ 已删'; fi
        fi
    done
}

echo "Selffont 全机垃圾排查　模式=$([ "$DELETE" = 1 ] && echo '查完即删' || echo '只读')　时间=$(date '+%Y-%m-%d %H:%M:%S %z')"
echo "根目录前缀=${BASE:-/}　uid=$(id -u)"

# ============================================================ ① 本模块自己的临时件
echo
echo '==================== ① 本模块自己的临时件与状态（可删）'
list '模块外的 selffont 状态/日志' yes \
     'skia.sh 的开关状态与自检日志；删了等于回默认（off）' \
     "$BASE/data/adb" -maxdepth 2 -name 'selffont*'
list '临时目录里的安装包副本' yes \
     '装完就没用了，装包本体留 Download 就行' \
     "$BASE/data/local/tmp" -maxdepth 2 \( -name 'selffont*' -o -name 'MFGA*.zip' \)

# ============================================================ ② 备份后缀
echo
echo '==================== ② 备份后缀（*.bak / *.orig / *~）（可删）'
list 'Download 下的备份件' yes \
     '复制/改名前留下的副本。注意 BakaSU*.apk 这类是正常应用，不带 .bak 后缀，不会被这条挑走' \
     "$BASE/storage/emulated/0/Download" -maxdepth 3 \
     \( -name '*.bak' -o -name '*.BAK' -o -name '*.orig' -o -name '*.rej' -o -name '*~' \)
list '模块目录里的备份件' yes \
     '模块自更新时会留旧文件' \
     "$BASE/data/adb/modules" -maxdepth 3 \
     \( -name '*.bak' -o -name '*.orig' -o -name '*~' \)
list 'ksubak / disablebak 命名的副本' yes \
     '前会话留下的副本，名字本身就是垃圾标记；.zip 里是旧安装包，删了不影响已装的模块' \
     "$BASE/data/adb" "$BASE/data/local/tmp" "$BASE/storage/emulated/0/Download" -maxdepth 5 \
     \( -iname 'ksubak*' -o -iname '*disablebak*' \)
list '其余名字带 bak 的东西（仅供辨认，不删）' no \
     '名字带 bak 不等于垃圾：BakaSU 是正常的 root 管理器。这条只列，删不删你定' \
     "$BASE/data/adb" "$BASE/data/local/tmp" "$BASE/storage/emulated/0/Download" -maxdepth 5 \
     \( -iname '*bak*' -o -iname '*ksubak*' \) -not -name '*.bak' \
     -not -iname 'ksubak*' -not -iname '*disablebak*'

# ============================================================ ③ 状态标记
echo
echo '==================== ③ 状态标记（真标记只列不删；带后缀的可删）'
list '误写的标记（disablebak / disable.bak …）' yes \
     '这类不生效：系统只认名字正好是 disable / remove / update 的空文件' \
     "$BASE/data/adb/modules" -maxdepth 3 \
     \( -name 'disable*' -o -name 'remove*' -o -name 'update*' \) \
     -not -name 'disable' -not -name 'remove' -not -name 'update'
list '真标记（模块被停用 / 待删 / 待更新）' no \
     '**看这条**：有 disable 就是模块被停用，字体不生效多半就是这个原因，它不是垃圾' \
     "$BASE/data/adb/modules" -maxdepth 3 \
     \( -name 'disable' -o -name 'remove' -o -name 'update' \) -type f

# ============================================================ ④ 挂载残留
echo
echo '==================== ④ 字体挂载残留（只读）'
mounts=/proc/1/mounts
[ -r "$mounts" ] || mounts=/proc/mounts
n_mount=$(grep -ci 'selffont\|MFGA' "$mounts" 2>/dev/null || true)
printf '   字体相关挂载层 %s 条（正常 1~2 条；同名重复叠加就是残留，重启即清）\n' "${n_mount:-0}"
grep -i 'selffont\|MFGA' "$mounts" 2>/dev/null | sed 's/^/   /'

# ============================================================ ⑤ 开机脚本
echo
echo '==================== ⑤ 开机脚本里谁在碰字体（只读）'
found=0
for dir in "$BASE/data/adb/service.d" "$BASE/data/adb/post-fs-data.d"; do
    for f in "$dir"/*; do
        [ -f "$f" ] || continue
        if echo "$f" | grep -qi 'font\|selffont\|mfg' || grep -qsi 'font\|selffont\|MFGA' "$f"; then
            found=1
            echo "   $f"
            grep -nsi 'font\|selffont\|MFGA' "$f" 2>/dev/null | head -3 | sed 's/^/      /'
        fi
    done
done
[ "$found" = 1 ] || echo '   （无）'

# ============================================================ 汇总
hit=$(wc -l < "$TOTALS" | tr -d ' ')
kb=$(awk '{s+=$1} END {printf "%d", s+0}' "$TOTALS")
rm -f "$TOTALS"
echo
printf '==================== 汇总：命中 %s 项，共 %s KB（%s MB）\n' "$hit" "$kb" "$((kb / 1024))"
if [ "$DELETE" = 1 ]; then
    echo '本次已删掉标「可删」的项；标「不删」的原样保留。'
else
    echo '本次只读。逐条看完、确认都不需要了，再跑一次加 --delete。'
fi
