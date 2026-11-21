#!/system/bin/sh
# Selffont 上一轮日志扫描（手动版）。
#
# 为什么要有它：定因的现场就在 boot.log 里，但清账命令一 `rm` 就没了。
# 守卫现在每次开机**自动**扫一遍（结论写进 guard.log，原文留成 boot.log.prev），
# 这个脚本是同一份逻辑的手动入口——不想重启、想立刻再扫一次时用。
#
# 用法：
#   su -c 'sh /data/local/tmp/sf-scan.sh'                扫上一轮（boot.log.prev）与这一轮（boot.log）
#   su -c 'sh /data/local/tmp/sf-scan.sh /某个/日志文件'   扫指定文件
#
# 只读：不删、不 mv、不 touch 任何东西。

D=${SELFFONT_DATA:-/data/adb/selffont}
GUARD="$D/../post-fs-data.d/sf-guard.sh"
[ -f "$GUARD" ] || GUARD=${SELFFONT_GUARD:-/data/adb/post-fs-data.d/sf-guard.sh}

if [ ! -f "$GUARD" ]; then
    echo "[停] 找不到守卫脚本：$GUARD"
    echo "     没有它就没有扫描判据（我不在这里另写一套，两套判据一定会分叉）。"
    exit 2
fi

# 只把 now 与 scan_boot_log 取出来，不执行守卫的主流程。
#   · now 是单行函数，按行取（原来用 sed 区间取，遇到同行 `}` 会一路吃掉后面的代码）
#   · scan_boot_log 用 awk 从函数头取到行首的 `}` 为止
_now_line=$(grep -m 1 '^now() {' "$GUARD")
if [ -z "$_now_line" ]; then
    echo "[停] 守卫里找不到 now() 单行定义，不猜。"
    exit 2
fi
eval "$_now_line"
eval "$(awk '/^scan_boot_log\(\) \{/{f=1} f{print} f && /^\}/{exit}' "$GUARD")"
# 默认 /proc/self/fd/1：真机上 /dev/stdout 和 /dev/tty 在 root 下都可能打不开，
# 那样整段扫描一行都出不来——又是「看着跑了，其实没输出」。
# 都不行就退回终端：(exec >"$F") 会撞权限，所以用「先试、失败就空」的方式探测。
# 输出走临时文件，最后整段 cat 到终端。
# 不再往 /dev/stdout、/dev/tty、/proc/self/fd/1 直接写：这些在 root/无控制终端下
# 会「探测能写、实际写不进去」，整段扫描一行都出不来（我自己撞了三次）。
OUT=${SELFFONT_SCAN_OUT:-/data/local/tmp/sf-scan.out}
case "$OUT" in /data/local/tmp/*) mkdir -p /data/local/tmp 2>/dev/null ;; esac
: > "$OUT" 2>/dev/null || OUT=/tmp/sf-scan.$$.out
: > "$OUT" 2>/dev/null || { echo "[停] 写不出临时文件：$OUT" >&2; exit 2; }
# scan_boot_log 是从守卫里 eval 出来的，它内部读的是**它自己那份** GUARD_LOG，
# 所以这个赋值被人读、不可删（我删过一次，sf-scan 立刻静默变成零输出）。
GUARD_LOG=$OUT

if ! command -v scan_boot_log >/dev/null 2>&1; then
    echo "[停] 守卫里找不到 scan_boot_log 函数：判据没函数化，我不猜。"
    exit 2
fi

if [ "$#" -ge 1 ]; then
    TARGET=$1
    if [ ! -f "$TARGET" ]; then
        echo "[停] 没有这个文件：$TARGET"
        exit 2
    fi
    scan_boot_log "$TARGET" "  $TARGET"
    exit 0
fi

FOUND=0
for f in "$D/boot.log.prev" "$D/boot.log"; do
    if [ -f "$f" ]; then
        scan_boot_log "$f" "  $f"
        FOUND=1
    else
        echo "  [无] $f 不存在"
    fi
done
[ "$FOUND" = "1" ] || echo "[停] 两份日志都不在：还没跑过一轮，或者被清账删了。"

echo "=== 扫描结果（同时写到 $OUT） ==="
cat "$OUT"
