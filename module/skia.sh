#!/system/bin/sh
# Skia 那条路的开关：`/system/etc/fonts.xml`（Flutter / WebView / 部分厂商小组件读它）。
#
# 为什么默认 off：Skia 的逐字回退是「有码位就命中」——
#   skia/src/ports/SkFontMgr_android.cpp · find_family_style_character
#   only `if (face->unicharToGlyph(character) != 0) return face;`
# 它不看字形有没有轮廓，也不会因为我们这张字件排在前面就继续往下找设备自带的 Noto/OPPO。
# Flutter（FlClash 这类）用的是 SkiaFontMgr + 这一份文件；插进去之后，凡是主字体 cmap 里
# 有的字都由它画，缺的才回退。真机症状：界面大片没字，或大字号被切成一个个方块
# （usWin 高于行框时 Skia 按行框裁字形框）。off 时 Flutter 用设备自己的链，一定有字。
#
# 用法（手机上直接跑，改完重启生效）：
#   sh skia.sh status     打印当前开关与模块里那份文件在不在
#   sh skia.sh on         插（默认链 / sans-serif / 中日韩语言族最前面加我们的字件）
#   sh skia.sh off        撤（删模块里那份，回设备原文件）
#   sh skia.sh apply      按当前标记落地一次（customize.sh 安装时调这个）
# 一律只插不换：设备自己那份里有 OPPO Sans 等 OEM 字件，整份盖掉会把它们删掉。
command -v ui_print >/dev/null 2>&1 || ui_print() { echo "$1"; }
MODDIR=${0%/*}; [ "$MODDIR" = "$0" ] && MODDIR=.
STATE=${SELFFONT_SKIA_STATE:-/data/adb/selffont-skia.state}
ROOT=${SELFFONT_SYSTEM_ROOT:-}
INSERT=$MODDIR/fonts-insert.xml
TARGET=$MODDIR/system/etc/fonts.xml

state() {
    case $(sed -n 's/^mode=//p' "$STATE" 2>/dev/null | tail -n 1) in
        on) echo on ;;
        *) echo off ;;
    esac
}

write_state() {
    mkdir -p "${STATE%/*}" 2>/dev/null
    printf 'mode=%s\n' "$1" > "$STATE" 2>/dev/null || {
        ui_print "!!! 写不了 $STATE（要 root）：开关没生效"
        exit 1
    }
}

apply() {
    rm -f "$TARGET"
    if [ "$(state)" != on ]; then
        ui_print "Skia /system/etc/fonts.xml：未插（Selffont:skia=off，Flutter 用设备自己那份）"
        return 0
    fi
    if [ ! -f "$ROOT/system/etc/fonts.xml" ]; then
        ui_print "Skia /system/etc/fonts.xml：设备没有这份文件，无处可插"
        return 0
    fi
    if [ ! -s "$INSERT" ]; then
        ui_print "Skia /system/etc/fonts.xml：模块里没有插入行（fonts-insert.xml），跳过"
        return 0
    fi
    mkdir -p "$MODDIR/system/etc"
    awk -v rowsfile="$INSERT" '
        function cjk(tag,   s, n, a, i, v) {
            if (!match(tag, /lang="[^"]*"/)) return 0
            s = substr(tag, RSTART + 6, RLENGTH - 7)
            n = split(s, a, ",")
            for (i = 1; i <= n; i++) {
                v = a[i]; sub(/-.*$/, "", v); gsub(/[ \t]/, "", v)
                if (tolower(v) == "zh" || tolower(v) == "ja" || tolower(v) == "ko") return 1
            }
            return 0
        }
        BEGIN {
            while ((getline row < rowsfile) > 0) rows = rows row "\n"
            close(rowsfile)
        }
        {
            print
            if (!opened && index($0, "<familyset") > 0) {
                print "    <family>"
                printf "%s", rows
                print "    </family>"
                opened = 1
                next
            }
            if ($0 ~ /<family[ \t>]/ && $0 !~ /\/>[ \t]*$/) {
                if (index($0, "name=\"sans-serif\"") > 0 || cjk($0)) printf "%s", rows
            }
        }
        ' "$ROOT/system/etc/fonts.xml" > "$TARGET" 2>/dev/null
    # 校验插进去了几条：拿插入行里的字件文件名去数（不写死 Selffont，自检夹具用的就是别的名字）。
    # grep -c 没命中会先打印 0 再返回 1，写成 `|| echo 0` 会拿到两行的 "0\n0"，
    # [ -gt 0 ] 直接报 Illegal number，所以先 `|| true` 再补默认值。
    marker=$(sed -n 's|.*>\([^<]*\)</font>.*|\1|p' "$INSERT" | head -n 1)
    touched=$(grep -c -F "$marker" "$TARGET" 2>/dev/null || true)
    [ -n "$touched" ] || touched=0
    if [ "${touched:-0}" -gt 0 ]; then
        ui_print "Skia /system/etc/fonts.xml：已插 $touched 处（默认链 / sans-serif / 中日韩语言族，OEM 字件原样保留）"
        return 0
    fi
    rm -f "$TARGET"
    ui_print "!!! Skia /system/etc/fonts.xml：插不进去，Flutter / WebView 继续用设备原文件"
    return 0
}

case ${1:-status} in
    status)
        ui_print "Selffont:skia=$(state)"
        [ -f "$TARGET" ] && ui_print "模块里那份：在（重启后 Flutter 走主字体链）" ||
            ui_print "模块里那份：不在（重启后 Flutter 走设备原文件）"
        ;;
    on) write_state on; apply; ui_print "重启生效。关掉用：sh $0 off" ;;
    off) write_state off; apply; ui_print "重启生效。" ;;
    apply) apply ;;
    *) ui_print "用法：sh skia.sh [status|on|off|apply]"; exit 2 ;;
esac
