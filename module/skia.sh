#!/system/bin/sh
# Skia 那条路的开关：`/system/etc/fonts.xml`（Flutter / WebView / 部分厂商小组件读它）。
#
# 2026-11-07 重写。旧版把字件插在「中日韩 lang 族**族尾**」，并且只插中日韩族。按 Skia 源码
# 逐条复算（`tools/skia_paths.py` 就是那个复算器），这个插法在 Flutter 里命中率是 **0.00%**：
#   · Flutter 走 Skia（`flutter/engine` `txt/src/txt/platform_android.cc`：
#     `GetDefaultFontFamilies()` 返回 `{"sans-serif"}`、`SkFontMgr_New_Android(nullptr, …)`），
#     每次逐字回退拿的族名就是 `sans-serif`。
#   · `SkFontMgr_android.cpp` `onMatchFamilyStyleCharacter` 第一层只查 `sans-serif`
#     **这一个族**；该族里 400 档已有设备自己的 OPPO/Noto，`unicharToGlyph != 0` 成立就 return。
#   · 而 `find_family_style_character` 对每个族**只取一个** face（`matchAStyle`），
#     `SkFontMgr.cpp:242 matchStyleCSS3` 并列时取先出现的（`maxScore < currentScore` 严格小于）。
#     ⇒ 排在族尾＝永远轮不到。
# 现在：插 `sans-serif`、中日韩语言族、以及无 name 无 lang 的匿名默认族的**族首**，默认开。
# 实测（同一份假设备配置，只差插法）：族尾 0.00% → 族首 100%（w100–w900 全档、含无族名请求）。
# 不吃掉设备的字：emoji 族（`lang="und-Zsye"`）、serif 族、阿拉伯族不在插入范围，逐字复算未受影响。
#
# 只插不换：设备那份里有 OPPO Sans 等 OEM 字件，整份盖掉会把它们删掉。
#
# 用法（手机上直接跑，改完重启生效）：
#   sh skia.sh status     打印当前开关与模块里那份文件在不在
#   sh skia.sh on         插（默认档）
#   sh skia.sh off        撤（删模块里那份，回设备原文件）
#   sh skia.sh apply      按当前标记落地一次（customize.sh 安装时调这个）
command -v ui_print >/dev/null 2>&1 || ui_print() { echo "$1"; }
MODDIR=${0%/*}; [ "$MODDIR" = "$0" ] && MODDIR=.
STATE=${SELFFONT_SKIA_STATE:-/data/adb/selffont-skia.state}
ROOT=${SELFFONT_SYSTEM_ROOT:-}
INSERT=$MODDIR/fonts-insert.xml
TARGET=$MODDIR/system/etc/fonts.xml

state() {
    case $(sed -n 's/^mode=//p' "$STATE" 2>/dev/null | tail -n 1) in
        off) echo off ;;
        *) echo on ;;
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
    # 韩文保护。本包 cmap 里谚文 0 个，而 Skia 对每族只查一个 face：我们一旦占了族首，
    # 设备的 NotoSansCJKkr / NotoSansKR 就再也轮不到，韩文整片落豆腐。实测判据见
    # tools/skia_paths.py（设备有韩文字件时族首插法的 Korean 命中率 0%）。
    # 只在「设备那份配置里确有韩文字件」时把 lang 含 ko 的族跳过，其余照插。
    skip_ko=0
    if grep -q 'lang="[^"]*ko' "$ROOT/system/etc/fonts.xml" 2>/dev/null; then
        skip_ko=1
    fi
    awk -v rowsfile="$INSERT" -v skipko="$skip_ko" '
        # 这一族该不该插：命名族 `sans-serif`、带中日韩 lang 的族、无 name 无 lang 的匿名默认族。
        # emoji（und-Zsye）/ serif / 阿拉伯等一族都不碰——每族只查一个 face，插进去会顶掉它们。
        function wanted(tag,   s, n, a, i, v) {
            if (tag ~ /name="sans-serif"/) return 1
            if (!match(tag, /lang="[^"]*"/)) {
                # 无 lang：只有完全没有 name 的匿名默认族要插；其余命名族（serif 等）不动。
                return tag !~ /name="/
            }
            s = substr(tag, RSTART + 6, RLENGTH - 7)
            n = split(s, a, ",")
            for (i = 1; i <= n; i++) {
                v = a[i]; sub(/-.*$/, "", v); gsub(/[ \t]/, "", v)
                v = tolower(v)
                if (v == "zh" || v == "ja") return 1
                if (v == "ko") return skipko ? 0 : 1
            }
            return 0
        }
        BEGIN {
            while ((getline row < rowsfile) > 0) rows = rows row "\n"
            close(rowsfile)
        }
        # 插在 <family …> 之后的第一行（族首）。Skia 对每个族只取一个 face 且并列取先出现的，
        # 所以只有族首能让我们的字件被选中；插族尾等于没插（旧版实测 0.00%）。
        {
            print
            if ($0 ~ /<family[ \t>]/ && $0 !~ /\/>[ \t]*$/ && wanted($0)) printf "%s", rows
        }
        ' "$ROOT/system/etc/fonts.xml" > "$TARGET" 2>/dev/null
    # 校验插进去了几条：拿插入行里的字件文件名去数（不写死 Selffont，自检夹具有别的名字）。
    # grep -c 没命中会先打印 0 再返回 1，写成 `|| echo 0` 会拿到两行的 "0\n0"，
    # [ -gt 0 ] 直接报 Illegal number，所以先 `|| true` 再补默认值。
    marker=$(sed -n 's|.*>\([^<]*\)</font>.*|\1|p' "$INSERT" | head -n 1)
    touched=$(grep -c -F "$marker" "$TARGET" 2>/dev/null || true)
    [ -n "$touched" ] || touched=0
    if [ "${touched:-0}" -gt 0 ]; then
        [ "$skip_ko" = 1 ] && note="，韩文族已跳过（本包无谚文，留给设备）" || note=""
        ui_print "Skia /system/etc/fonts.xml：已插 $touched 处（sans-serif / 中日韩族 / 匿名默认族的族首$note）"
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
