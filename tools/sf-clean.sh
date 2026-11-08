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
# 文件用 stat 的字节数；目录用 du（stat 对目录只报元数据大小，会把 22 MB 的目录显示成 4 KB，
# 2026-11-08 真机第一版就是这样把 /data/adb/sf-crash 报成 4 KB 的）。
kb() {
    if [ -d "$1" ]; then
        du -sk "$1" 2>/dev/null | awk '{print $1}' || echo 0
    else
        s=$(stat -c '%s' "$1" 2>/dev/null || echo 0)
        echo $(( (s + 1023) / 1024 ))
    fi
}

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
head1 '⑥ 备份后缀 *.bak / *.orig / *~ / ksubak / *disablebak*'
# 2026-11-08 真机输出打回来的一个错：原来一条 find 扫全部模块，把
#   /data/adb/modules/hma_oss_zygisk/module.prop.bak（别人的模块备份）
#   /data/adb/tricky_store/keybox.xml.bak（证书箱备份，17 KB）
#   /data/adb/hybrid-mount/config.toml.bak（配置备份）
# 全列成「可删」。别人的模块备份删了，出问题没人能回滚。
# 现在按归属分两档：本模块目录 + tmp/Download 的可删；别人模块目录的只列不动。
PATTERNS='\( -name "*.bak" -o -name "*.BAK" -o -name "*.orig" -o -name "*~" -o -iname "ksubak*" -o -iname "*disablebak*" \)'

echo '  ── 可删（本模块目录 / tmp / Download）'
for d in /data/local/tmp /storage/emulated/0/Download; do
    eval "find \"$d\" -maxdepth 4 $PATTERNS 2>/dev/null"
done | while IFS= read -r f; do
    row yes '备份/副本后缀，不生效' "$f"
done
for m in /data/adb/modules/*/; do
    [ -d "$m" ] || continue
    id=$(grep -s '^id=' "$m/module.prop" | head -1 | cut -d= -f2)
    case "${id:-}" in
        selffont*|MFGA)
            eval "find \"$m\" -maxdepth 3 $PATTERNS 2>/dev/null" | while IFS= read -r f; do
                row yes '本模块自己的备份副本' "$f"
            done ;;
    esac
done
find /data/adb -maxdepth 1 \( -name '*.bak' -o -name '*.orig' -o -name '*~' \) 2>/dev/null \
    | while IFS= read -r f; do row yes '备份/副本后缀，不生效' "$f"; done

echo '  ── 别人的模块里的备份（只列，一个字节都不动）'
any=0
for m in /data/adb/modules/*/; do
    [ -d "$m" ] || continue
    id=$(grep -s '^id=' "$m/module.prop" | head -1 | cut -d= -f2)
    case "${id:-}" in
        selffont*|MFGA) continue ;;
    esac
    eval "find \"$m\" -maxdepth 3 $PATTERNS 2>/dev/null" | while IFS= read -r f; do
        printf '  [留] %s  ← 模块 %s 的备份，不是本项目的\n' "$f" "${id:-?}"
    done
    n=$(eval "find \"$m\" -maxdepth 3 $PATTERNS 2>/dev/null" | wc -l | tr -d ' ')
    [ "$n" -gt 0 ] && any=1
done
[ "$any" = 1 ] || true

echo '  ※ 名字带 bak 但**不是**备份的（BakaSU 这类正常应用）下面单列，不删。'
for d in /data/adb /data/local/tmp /storage/emulated/0/Download; do
    find "$d" -maxdepth 4 -iname '*bak*' ! -name '*.bak' ! -name '*.BAK' \
        ! -iname 'ksubak*' ! -iname '*disablebak*' 2>/dev/null
done | while IFS= read -r f; do
    printf '  [留] %s  （名字带 bak，但不是我们的备份）\n' "$f"
done

# ---------------------------------------------------------------- ⑦ 大字件
head1 '⑦ Download 里的安装包与大文件（可删，先看清）'
find /storage/emulated/0/Download -maxdepth 2 \( -iname '*selffont*.zip' -o -iname '*Selfrounds*.zip' \
    -o -iname 'build-*.zip' -o -iname '*母版*.zip' \) 2>/dev/null | while IFS= read -r p; do
    printf '  %6s KB  %s  %s\n' "$(kb "$p")" "$(when "$p")" "$p"
done
echo '   ※ 这些不自动删：可能正是你现在要刷的那个包。'

# ---------------------------------------------------------------- ⑧ 状态标记
head1 '⑧ 状态标记：只有 disable.bak 这类**纯后缀副本**可删，其余一概不动'
# 2026-11-08 真机输出打回来两个错，改在这里：
#   · `"$m"update*` 把 `/data/adb/modules/GGAT_10007/update.json`（KernelSU 的模块更新信息）
#     和 `hma_oss_zygisk/update_desc.sh`（别人模块自己的脚本）当成「假标记」列成可删。
#     glob 一条 `update*` 覆盖的范围比「名字正好是 update 后面多几个字符的副本」大得多。
#   · 于是改成白名单：只有「真标记名 + 备份后缀」，且**必须是普通文件、小于 64 字节**。
#     KernelSU 的真标记本来就是空文件；update.json 是几十字节的 JSON，天然被挡在门外。
#     拿不准的一律列「留」，宁可留着也不碰别人的模块。
MARK_MAX=64
for m in /data/adb/modules/*/; do
    [ -d "$m" ] || continue
    id=$(grep -s '^id=' "$m/module.prop" | head -1 | cut -d= -f2)
    for base in disable remove update; do
        # 真标记：只认名字完全一致的普通文件；存在就只报不动。
        if [ -f "$m$base" ]; then
            printf '  [留] %s  ← 真标记（模块 %s）\n' "$m$base" "${id:-?}"
            NKEEP=$((NKEEP+1))
        fi
        # 副本：只认 base 后面紧跟备份后缀的那几种写法。
        for suf in .bak .bak2 .bak.1 .orig .old .save .tmp '~' .disabled .bak.bak; do
            f="$m$base$suf"
            [ -f "$f" ] || continue
            sz=$(stat -c '%s' "$f" 2>/dev/null || echo 999)
            if [ "$sz" -le "$MARK_MAX" ]; then
                row yes '真标记的备份副本（不生效，删了不影响模块状态）' "$f"
            else
                printf '  [留] %s  ← 名字像标记副本但有 %s 字节，内容不明，不删\n' "$f" "$sz"
                NKEEP=$((NKEEP+1))
            fi
        done
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

# ---------------------------------------------------------------- ⑫ 全盘按名字找
head1 '⑫ 全盘按名字找（selffont / Selfrounds / MFGA / Maruko）'
# 2026-11-08 真机第二版的错：这一节的根写的是 `/data`，而 `/data` 底下就是
# `/data/data`（应用私有目录，几十万个文件）。真机上跑到「── /data」就卡住不动了，
# 而 ⑭ 里我明明写着「不查 /data/data」——说到做不到。
# 现在用 `-prune` 显式剪掉那几个目录，不进它们；每一根 timeout 45 秒封顶。
SCANNED=''
for root in /data /storage/emulated/0 /cache; do
    [ -d "$root" ] || continue
    SCANNED="$SCANNED $root"
    echo "  ── $root"
    # 剪枝清单按 $root 现算，不写死绝对路径：写死的话沙箱夹具测不到，
    # 改一层目录结构就悄悄失效（真机第二版在「── /data」卡住就是这个原因）。
    prune=""
    for sub in data misc system vendor app dalvik-cache tombstones local ota; do
        p="$root/$sub"
        [ -d "$p" ] || continue
        # /data/local/tmp 与 /data/adb 要能进去（前者在 ⑤ 段已单独处理），
        # 所以只剪 /data/local 本身，不剪它的子目录，靠 -prune 的层级控制。
        prune="$prune -path $p -o"
    done
    prune="${prune% -o}"
    # 超时只在真的超时（exit 124）时提示；否则「一个都没命中」会被误报成超时。
    if command -v timeout >/dev/null 2>&1; then
        out=$(timeout 45 find "$root" -maxdepth 5 \
            \( \( $prune \) -prune \) -o \
            \( -iname '*selffont*' -o -iname '*Selfrounds*' -o -iname '*MFGA*' -o -iname '*Maruko*' \) -print \
            2>/dev/null)
        rc=$?
        if [ "$rc" = "124" ]; then
            echo '     （超过 45 秒，已跳过这一根——这里的结论不完整）'
        fi
        printf '%s\n' "$out"
    else
        find "$root" -maxdepth 5 \
            \( \( $prune \) -prune \) -o \
            \( -iname '*selffont*' -o -iname '*Selfrounds*' -o -iname '*MFGA*' -o -iname '*Maruko*' \) -print \
            2>/dev/null
    fi | grep -v '^[[:space:]]*$' | while IFS= read -r f; do
        case "$f" in
            */modules/selffont-bench) printf '  [用] %s  ← 正在装的模块本体（不删）\n' "$f" ;;
            *) printf '  [看] %6s KB  %s  %s\n' "$(kb "$f")" "$(when "$f")" "$f" ;;
        esac
    done
done
echo '  ※ 这一节只列不删：名字带这些字的东西，可能正是你要刷的包、要留的证据。'

# ---------------------------------------------------------------- ⑬ 大文件排行
head1 '⑬ 占地最多的文件（Download 与临时目录，前 15）'
for d in /storage/emulated/0/Download /data/local/tmp; do
    [ -d "$d" ] || continue
    echo "  ── $d"
    # du -sk 输出「KB<TAB>路径」；用 tab 切，路径里的空格不会把字段切歪
    du -sk "$d"/* 2>/dev/null | sort -rn | head -15 | while IFS="$(printf '\t')" read -r k path; do
        [ -n "$path" ] || continue
        [ -d "$path" ] && what='目录' || what='文件'
        printf '  %9s MB  %s  %s\n' "$(awk -v k="$k" 'BEGIN{printf "%.1f", k/1024}')" "$what" "$path"
    done
done

# ---------------------------------------------------------------- ⑭ 没查的地方（如实报）
head1 '⑭ 这趟**没有**查的地方（宁可说清，不许假装扫了全机）'
cat <<'COVER'
  · /proc /sys /dev          —— 虚拟文件系统，没有真实占用
  · /data/data/*             —— 应用私有目录，逐个查要 root 遍历几十万个文件，
                                而且删了会破坏应用数据。要单独查哪一个，告诉我名字
  · /data/misc /data/system  —— 系统数据库与 dropbox/tombstone，属于系统证据，不是垃圾
  · /system /vendor /product —— 只读分区，写不进去也就没有垃圾
  · 回收站 / 云盘            —— 不在本机文件系统里
COVER
echo "  本次实际扫过的根：${SCANNED:-（无）}"

# ---------------------------------------------------------------- 汇总
hit=$(wc -l < "$FOUND" | tr -d ' ')
rm -f "$FOUND"
printf '\n==================== 汇总：命中 %s 项；本次删除 %s 项；保留 %s 项\n' "$hit" "$NDEL" "$NKEEP"
if [ "$DELETE" = 1 ]; then
    echo '已删掉标「删」的；标「留」的原样保留（真标记、在用的模块、别人的脚本）。'
else
    echo '本次只读。逐条看完确认，再跑一次加 --delete。'
fi
