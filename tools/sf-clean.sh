#!/system/bin/sh
# Selffont 全机清理：把「历次 AI 会话在你手机上留下的东西」一次列全，看清再删。
#
# 为什么重写（原来那份 tools/check_garbage.sh 的缺口）：
#   它只扫 selffont 前缀、备份后缀、状态标记、挂载残留、开机脚本五类。
#   真机上漏掉的三类恰恰是大头：
#     ① /data/adb/sf-crash/        历次开机转储，几十 MB
#     ② /data/adb/selffont-sans-serif-backup-*/  五槽同内容的错误备份
#     ③ /data/adb/MFGA/            上游基础包遗留目录
#   还漏了：/data/adb/ksu/log/、/data/local/tmp 里的包副本、Download 里的 zip。
#
# 用法（都在手机上跑，必须 root）：
#   su -c 'sh /data/local/tmp/sf-clean.sh'            # 只列，不删
#   su -c 'sh /data/local/tmp/sf-clean.sh --delete'   # 列完删掉「可删」项
#   su -c 'sh /data/local/tmp/sf-clean.sh --keep-module --delete'
#        ↑ 连模块一起删（默认**保留**模块与开机守卫脚本）
#
# 三类永不删，不管带不带 --delete：
#   · 名字正好是 disable / remove / update 的真标记（删了会让模块复活去卡开机）
#   · 正在用的模块目录（除非显式 --keep-module）
#   · post-fs-data.d / service.d 里非本模块的脚本（hmaoss.sh、auditpatch.sh 是别人的）

set -u
DELETE=0
DROP_MODULE=0
for a in "$@"; do
    case "$a" in
        --delete) DELETE=1 ;;
        --keep-module) DROP_MODULE=1 ;;
        *) echo "未知参数：$a"; exit 2 ;;
    esac
done

[ "$(id -u)" = "0" ] || { echo "必须 root：非 root 读不到 /data/adb，结论会是假的「（无）」。"; exit 3; }

FOUND=$(mktemp 2>/dev/null || echo /data/local/tmp/.sfclean.$$)
: > "$FOUND"
NDEL=0
NKEEP=0

when() { stat -c '%y' "$1" 2>/dev/null | cut -c1-16; }
kb()   { s=$(stat -c '%s' "$1" 2>/dev/null || echo 0); echo $(( (s + 1023) / 1024 )); }

# row <可删 yes|no> <原因> <路径…>  —— 每个路径一行；可删且 --delete 时删
row() {
    del=$1; why=$2; shift 2
    for p in "$@"; do
        [ -e "$p" ] || continue
        printf '  [%s] %6s KB  %s  %s\n         %s\n' \
            "$([ "$del" = yes ] && echo 删 || echo 留)" "$(kb "$p")" "$(when "$p")" "$p" "$why"
        echo "x" >> "$FOUND"
        if [ "$del" = yes ]; then
            if [ "$DELETE" = 1 ]; then
                rm -rf "$p" 2>/dev/null && { echo '         ↳ 已删'; NDEL=$((NDEL+1)); }
            fi
        else
            NKEEP=$((NKEEP+1))
        fi
    done
}

head1() { printf '\n==================== %s\n' "$1"; }

echo "Selffont 全机清理　模式=$([ "$DELETE" = 1 ] && echo '查完即删' || echo '只读')　时间=$(date '+%Y-%m-%d %H:%M:%S %z')"

# ---------------------------------------------------------------- ① 崩溃转储
head1 '① 开机转储 /data/adb/sf-crash（历次 sf-pstore.sh 抓的，可删）'
if [ -d /data/adb/sf-crash ]; then
    du -sh /data/adb/sf-crash 2>/dev/null | sed 's/^/   合计 /'
    row yes '开机转储：抓错了时机，没一条是崩溃证据，纯占空间' /data/adb/sf-crash
    row yes '抓取脚本自己写的索引' /data/adb/sf-crash.log
else
    echo '   （无）'
fi

# ---------------------------------------------------------------- ② 错误备份
head1 '② 五槽同内容的配置备份 /data/adb/selffont-sans-serif-backup-*（可删）'
shopt -s nullglob 2>/dev/null || true
matched=0
for p in /data/adb/selffont-sans-serif-backup-*; do
    [ -e "$p" ] || continue
    matched=1
    n=$(find "$p" -type f 2>/dev/null | wc -l | tr -d ' ')
    u=$(find "$p" -type f -exec md5sum {} + 2>/dev/null | awk '{print $1}' | sort -u | wc -l | tr -d ' ')
    printf '  %s\n     %s 个文件，不同内容 %s 份%s\n' "$p" "$n" "$u" \
        "$([ "$u" -le 1 ] 2>/dev/null && echo '（写五份同一份，就是那个 bug）')"
done
[ "$matched" = 1 ] || echo '   （无）'
if [ "$matched" = 1 ]; then
    row yes '安装脚本写错的备份：五个槽内容相同，回滚不了，留着没用' /data/adb/selffont-sans-serif-backup-*
fi

# ---------------------------------------------------------------- ③ 上游遗留
head1 '③ 上游基础包遗留 /data/adb/MFGA（可删，与本模块无关）'
if [ -d /data/adb/MFGA ]; then
    find /data/adb/MFGA -type f 2>/dev/null | while read -r f; do
        printf '     %6s KB  %s  %s\n' "$(kb "$f")" "$(when "$f")" "$f"
    done
    row yes '上游 MakeFontsGreatAgain 的目录，只剩一个 config，删了不影响本模块' /data/adb/MFGA
else
    echo '   （无）'
fi

# ---------------------------------------------------------------- ④ KernelSU 日志
head1 '④ KernelSU 自己的日志 /data/adb/ksu/log（可删）'
if [ -d /data/adb/ksu/log ]; then
    du -sh /data/adb/ksu/log 2>/dev/null | sed 's/^/   合计 /'
    row yes 'ksu 的 dmesg/init 日志，sf-pstore.sh 抓的就是这里；排完障就可以清' /data/adb/ksu/log
else
    echo '   （无）'
fi

# ---------------------------------------------------------------- ⑤ 其他状态与残留
head1 '⑤ 本模块的其它状态/残留（可删）'
row yes 'Skia 开关状态文件（删了回默认 off）' /data/adb/selffont-skia.state
row yes '网页字体开关状态文件（删了回默认「压成文渊」）' /data/adb/selffont-web-fonts.state
row yes '安装期自检日志（排完障可删）' /data/adb/selffont-selftest.log
row yes '旧守卫留下的标志文件' /data/adb/sf-boot-ok /data/adb/sf-fail-count
row yes '本模块的临时副本' /data/local/tmp/selffont* /data/local/tmp/MFGA*.zip

# ---------------------------------------------------------------- ⑥ 备份后缀
head1 '⑥ 备份后缀 *.bak / *.orig / *~ / ksubak / *disablebak*（可删）'
for d in /data/adb /data/local/tmp /storage/emulated/0/Download; do
    find "$d" -maxdepth 4 \( -name '*.bak' -o -name '*.BAK' -o -name '*.orig' -o -name '*~' \
        -o -iname 'ksubak*' -o -iname '*disablebak*' \) 2>/dev/null
done > /data/local/tmp/.sfclean.bak.$$ 2>/dev/null || true
if [ -s /data/local/tmp/.sfclean.bak.$$ ]; then
    while IFS= read -r p; do
        row yes '备份/副本后缀，不生效' "$p"
    done < /data/local/tmp/.sfclean.bak.$$
else
    echo '   （无）'
fi
rm -f /data/local/tmp/.sfclean.bak.$$
echo '   ※ 名字带 bak 但**不是**备份的（BakaSU 这类正常应用）下面单列，不删。'
found=0
for d in /data/adb /data/local/tmp /storage/emulated/0/Download; do
    find "$d" -maxdepth 4 -iname '*bak*' ! -name '*.bak' ! -name '*.BAK' \
        ! -iname 'ksubak*' ! -iname '*disablebak*' 2>/dev/null
done | while IFS= read -r p; do
    printf '   [留] %s  （名字带 bak，但不是我们的备份，删不删你定）\n' "$p"
done

# ---------------------------------------------------------------- ⑦ 大字件
head1 '⑦ Download 里的安装包与大文件（可删，先看清）'
find /storage/emulated/0/Download -maxdepth 2 \( -iname '*selffont*.zip' -o -iname '*Selfrounds*.zip' \
    -o -iname 'build-*.zip' -o -iname '*母版*.zip' \) 2>/dev/null | while IFS= read -r p; do
    printf '  %6s KB  %s  %s\n' "$(kb "$p")" "$(when "$p")" "$p"
done
echo '   ※ 这些不自动删：可能正是你现在要刷的那个包。'

# ---------------------------------------------------------------- ⑧ 状态标记
head1 '⑧ 状态标记：带后缀的可删，真的**一个都不许删**'
for m in /data/adb/modules/*/; do
    [ -d "$m" ] || continue
    id=$(grep -s '^id=' "$m/module.prop" | head -1 | cut -d= -f2)
    for f in "$m"disable* "$m"remove* "$m"update*; do
        [ -e "$f" ] || continue
        case "${f##*/}" in
            disable|remove|update)
                printf '  [留] %s  ← 真标记（模块 %s 当前状态）\n' "$f" "${id:-?}"
                NKEEP=$((NKEEP+1)) ;;
            *)
                row yes '带后缀的标记不生效，是垃圾' "$f" ;;
        esac
    done
done

# ---------------------------------------------------------------- ⑨ 模块本体
head1 '⑨ 模块目录本体'
for m in /data/adb/modules/*/; do
    [ -d "$m" ] || continue
    id=$(grep -s '^id=' "$m/module.prop" | head -1 | cut -d= -f2)
    case "${id:-}" in
        selffont*|MFGA)
            if [ "$DROP_MODULE" = 1 ]; then
                row yes '全部 Selffont 模块（--keep-module 指定要删）' "$m"
            else
                printf '  [留] %s  id=%s  ← 正在用的模块，默认保留（要删加 --keep-module）\n' "$m" "${id:-?}"
                NKEEP=$((NKEEP+1))
            fi ;;
        *) printf '  [留] %s  id=%s  ← 不是本项目的，一个字节都不动\n' "$m" "${id:-?}"; NKEEP=$((NKEEP+1)) ;;
    esac
done

# ---------------------------------------------------------------- ⑩ 开机脚本
head1 '⑩ 开机脚本（本模块的列为可删；别人的只列不动）'
for f in /data/adb/post-fs-data.d/* /data/adb/service.d/* /data/adb/boot-completed.d/*; do
    [ -f "$f" ] || continue
    case "${f##*/}" in
        sf-guard.sh|sf-night.sh|sf-pstore.sh|sf-ok.sh)
            row yes '本模块/前会话留下的开机脚本' "$f" ;;
        *) printf '  [留] %s  ← 别人的脚本，不动\n' "$f" ; NKEEP=$((NKEEP+1)) ;;
    esac
done

# ---------------------------------------------------------------- ⑪ 挂载
head1 '⑪ 字体挂载残留（只读，重启即清）'
mt=/proc/1/mounts
[ -r "$mt" ] || mt=/proc/mounts
n=$(grep -ci 'selffont\|MFGA' "$mt" 2>/dev/null || true)
printf '   相关挂载 %s 条（正常 1~2 条；多了就是残留）\n' "${n:-0}"
grep -i 'selffont\|MFGA' "$mt" 2>/dev/null | sed 's/^/   /'

# ---------------------------------------------------------------- 汇总
hit=$(wc -l < "$FOUND" | tr -d ' ')
rm -f "$FOUND"
printf '\n==================== 汇总：命中 %s 项；本次删除 %s 项；保留 %s 项\n' "$hit" "$NDEL" "$NKEEP"
if [ "$DELETE" = 1 ]; then
    echo '已删掉标「删」的；标「留」的原样保留（真标记、在用的模块、别人的脚本）。'
else
    echo '本次只读。逐条看完确认，再跑一次加 --delete。'
fi
