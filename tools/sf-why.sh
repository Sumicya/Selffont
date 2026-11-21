#!/system/bin/sh
# Selffont 崩溃定因：把「手机卡住 / 重启了」判成下面几种里的一种，并说清依据。
#
#   ① 电源键 / RTC 强制重启（bootreason=2sec_reboot 等）——不是崩溃，是长按电源键
#   ② 内核 panic（/sys/fs/pstore 有内容）
#   ③ 用户态崩溃（/data/system/dropbox 的 *_crash*）
#   ④ native 崩溃（/data/tombstones，看 keyProcess 是不是 1）
#   ⑤ 本模块被自动停用 / 开机守卫的计数
#   ⑥ 阻塞（前三样全空，但守卫记着「每次都卡在同一处」）——证据只在开机日志里
#
# 只读：不删、不改、不 touch 任何东西。跑一次几秒。
#
# 用法：
#   su -c 'sh /data/local/tmp/sf-why.sh'              看最近一次开机
#   su -c 'sh /data/local/tmp/sf-why.sh 2026-11-08'   只看某一天
#
# 本脚本刻意**不**用 2>/dev/null 去闷读不到的目录：读不到就明说读不到。
# 「静默空输出」正是上一轮把全机清理做废的那个坑，不许在这里重演。

R=${SELFFONT_ROOT:-}                       # 夹具用的根前缀；真机为空
D=${R}${SELFFONT_DATA:-/data/adb/selffont}
DAY=$1
HIT=0
MISS=''

hr() { printf '\n==================== %s\n' "$1"; }
say() { printf '  %s\n' "$*"; }
miss() { MISS="$MISS
$1"; printf '  [无] %s  （读不到或不存在）\n' "$1"; }

printf 'Selffont 崩溃定因  %s\n' "$(date +%Y-%m-%dT%H:%M:%S%z)"

if [ "${SELFFONT_FAKE_ROOT:-0}" != "1" ] && [ "$(id -u)" != "0" ]; then
    printf '\n[停] 当前不是 root。pstore / dropbox / tombstone 都读不到，\n'
    printf '     非 root 跑出来的「没证据」不算结论。请用 su。\n'
    exit 2
fi

# ---------------------------------------------------------------- ① 上次怎么重启的
hr '① 上次重启的原因（getprop ro.boot.bootreason）'
br=$(getprop ro.boot.bootreason)
say "bootreason = ${br:-空}"
if [ -z "$br" ]; then
    miss 'ro.boot.bootreason（getprop 取不到）'
else
    case "$br" in
        *2sec_reboot*|*powerkey*|*rtc*)
            say '→ 电源键 / RTC 强制重启。AOSP bootstat.cpp 把 2sec_reboot 归到'
            say '  cold,rtc,2sec；这不是崩溃，是有人长按了电源键（或电池瞬时掉电）。'
            HIT=$((HIT + 1)) ;;
        *panic*|*watchdog*|*hardware_reset*|*unknown*)
            say '→ 内核/硬件层面异常重启，看 ② 里有没有実体。'
            HIT=$((HIT + 1)) ;;
        *cold*|*warm*)
            say '→ 普通冷/热启动，没有异常原因码。'
            HIT=$((HIT + 1)) ;;
        *)
            say '→ 其它原因码，原文见上，本脚本不硬猜。' ;;
    esac
fi

# ---------------------------------------------------------------- ② 内核 panic
hr '② 内核 pstore（panic 会把这里写满）'
if [ -d "$R/sys/fs/pstore" ]; then
    n=0
    for f in "$R"/sys/fs/pstore/*; do
        [ -e "$f" ] || continue
        n=$((n + 1))
        say "$(wc -c < "$f") B  $f"
    done
    if [ "$n" -eq 0 ]; then
        say '目录在，里面一个文件都没有 → 内核没留下 panic 记录。'
        say '（pstore 由内核按次清理，这里空就是「最近这次没 panic」。）'
    else
        HIT=$((HIT + 1))
    fi
else
    miss '/sys/fs/pstore'
fi

# ---------------------------------------------------------------- ③ 用户态崩溃
hr '③ 用户态崩溃（/data/system/dropbox 的 *_crash*）'
if [ -d "$R/data/system/dropbox" ]; then
    if [ -n "$DAY" ]; then
        lst=$(ls -1 "$R/data/system/dropbox" | grep -F "$DAY" | grep -F '_crash')
    else
        lst=$(ls -1t "$R/data/system/dropbox" | grep -F '_crash' | head -20)
    fi
    if [ -z "$lst" ]; then
        say '没有 *_crash* 条目 → 用户态没抛未捕获异常。'
        say "（该目录共 $(ls -1 "$R/data/system/dropbox" | wc -l) 个文件，确实读到了。）"
    else
        # ★ 真机上 dropbox 里全是 xxxx_crash@<毫秒>.txt.gz。第一版拿 grep 去读 .gz，
        #   读出空串，于是每一条都印「进程：」后面什么都没有——看着像查了，其实没读。
        #   .gz 用 zcat/gzip -dc 解；解不开就明说打不开，不许印空白。
        printf '%s\n' "$lst" | while read -r x; do
            [ -n "$x" ] || continue
            f="$R/data/system/dropbox/$x"
            who=$(case "$x" in
                      *.gz)
                          if command -v zcat >/dev/null 2>&1; then zcat "$f" 2>&1
                          elif command -v gzip >/dev/null 2>&1; then gzip -dc "$f" 2>&1
                          else echo '(没有 zcat/gzip，读不了压缩包)' ; fi ;;
                      *) cat "$f" 2>&1 ;;
                  esac | grep -m1 -E '^Package:|^Process:|^Subject:' )
            printf '  %s\n      %s\n' "$x" "${who:-（文件里没有 Package/Process 行，或解不开）}"
        done
        HIT=$((HIT + 1))
    fi
else
    miss '/data/system/dropbox'
fi

# ---------------------------------------------------------------- ④ native 崩溃
hr '④ native 崩溃（/data/tombstones）'
if [ -d "$R/data/tombstones" ]; then
    # ★ 同目录还有 tombstone_NN.pb（protobuf 二进版）。第一版把它也列进来，
    #   于是每一条都多出一个「? keyProcess=?」的空行，把真清单冲稀。
    #   .pb 单独计数报一行即可。
    pb=$(ls -1 "$R/data/tombstones" | grep -cE '\.pb$')
    files=$(ls -1 "$R/data/tombstones" | grep -E '^tombstone_[0-9]+$')
    if [ -z "$files" ]; then
        say '没有 tombstone_ 文件。'
    else
        say "共 $(printf '%s\n' "$files" | wc -l) 个文本版（另有 $pb 个 .pb 二进版，内容同源，不重复列）。最近 10 个："
        printf '%s\n' "$files" | while read -r f; do
            [ -n "$f" ] || continue
            p="$R/data/tombstones/$f"
            proc=$(grep -m1 '^pid:' "$p" | sed -n 's/.*>>> *\([^ ]*\) *<<<.*/\1/p')
            key=$(grep -m1 '^keyProcess:' "$p" | sed 's/.*: *//')
            when=$(ls -l "$p" | awk '{print $6, $7, $8}')
            printf '  %-14s %-30s keyProcess=%s\n' "$when" "${proc:-?}" "${key:-?}"
        done | tail -10
        say '按 keyProcess 汇总（1 = 会让系统进安全模式；0 = 不会，属旁证）：'
        printf '%s\n' "$files" | while read -r f; do
            [ -n "$f" ] || continue
            grep -m1 '^keyProcess:' "$R/data/tombstones/$f" | sed 's/.*: */  /'
        done | sort | uniq -c
        HIT=$((HIT + 1))
    fi
else
    miss '/data/tombstones'
fi

# ---------------------------------------------------------------- ⑤ 守卫与停用标记
hr '⑤ 开机守卫（本模块自己记的账）'
for f in guard.log boot-count; do
    if [ -r "$D/$f" ]; then
        printf '  --- %s\n' "$D/$f"
        tail -12 "$D/$f" | sed 's/^/    /'
    else
        miss "$D/$f"
    fi
done
for mod in "$R"/data/adb/modules/selffont-*; do
    [ -d "$mod" ] || continue
    if [ -e "$mod/disable" ]; then
        printf '  ! %s 带 disable 标记\n' "$mod"
        say '    → 本次开机系统根本没加载它。「装了没反应」不是字形问题，是它被停用了。'
        HIT=$((HIT + 1))
    else
        printf '  - %s 已启用（无 disable 标记）\n' "$mod"
    fi
done

# ---------------------------------------------------------------- ⑥ 卡住那次的开机日志
hr "⑥ 开机日志（$D/boot.log）"
if [ -r "$D/boot.log" ]; then
    sz=$(wc -c < "$D/boot.log")
    say "大小 $sz 字节。"
    if [ "$sz" -eq 0 ]; then
        say '空文件 → 那次开机在 logd 起来之前就卡死了，或守卫没来得及抓。'
        say '这种情形只能靠 ⑤ 的计数确认「确实每次都卡在同一处」。'
    else
        total=0
        for k in FATAL Watchdog 'ANR in' blocked minikin FontManager RescueParty; do
            c=$(grep -c -F "$k" "$D/boot.log")
            case "$c" in ''|*[!0-9]*) c=0 ;; esac
            total=$((total + c))
            printf '  %-14s %s 次\n' "$k" "$c"
        done
        printf '  --- 最后 15 行\n'
        tail -15 "$D/boot.log" | sed 's/^/    /'
        # ★ 2026-11-09 自查：原来只要 boot.log 存在就 +1，哪怕它只有 9 字节、
        #   七个关键词**全是 0**，也算「读到的证据块」，最后给出「按 ①→⑥ 认」的结论。
        #   空日志被当成证据，就是「假装查了」。有关键词命中才算。
        if [ "$total" -gt 0 ]; then
            HIT=$((HIT + 1))
        else
            miss "$D/boot.log 里七个关键词一个都没有（文件在，但没内容可认）"
        fi
    fi
else
    miss "$D/boot.log"
fi

# ---------------------------------------------------------------- ⑦ 判定
hr '⑦ 判定'
printf '  读到的证据块：%s 处\n' "$HIT"
if [ -n "$MISS" ]; then
    printf '  没查成（不存在或读不到，不冒充查过）：\n'
    printf '%s\n' "$MISS" | while read -r m; do
        [ -n "$m" ] && printf '    - %s\n' "$m"
    done
fi
printf '\n'
if [ "$HIT" -eq 0 ]; then
    printf '  结论：**判不出来**——上面每一块都是空的或读不到。\n'
    printf '  这时唯一还能做的：把 %s/boot-count 删掉，重启一次，\n' "$D"
    printf '  卡住之后进 recovery 或安全模式再看本脚本 ⑤ 有没有记上「第 N 次开机」。\n'
else
    printf '  结论：按 ①→⑥ 的顺序认，排在前面的通常是因、后面的是果。\n'
fi
printf '\n'
