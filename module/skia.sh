#!/system/bin/sh
# Skia 那条路的开关：`/system/etc/fonts.xml`（Flutter / WebView / 部分厂商小组件读它）。
#
# 为什么默认 off，以及 2026-11-10 改了什么（有源码依据，见下）：
#   机制不在「有码位就命中」，在**位置**。AOSP minikin `FontCollection::calcCoverageScore`：
#       if ((vs == 0 || hasVSGlyph) && (mFamilies[0] == fontFamily || fontFamily->isCustomFallback()))
#           return kFirstFontScore;     // ← 无条件最高分，直接 return，不看别的族
#   旧版这里把我们的族插在 `<familyset>` 之后第一个位置 ⇒ 正好是 mFamilies[0]
#   ⇒ 本包字件的 cmap 一旦含该码位就必被选中，设备自带的 Noto/OPPO 完全没有机会。
#   实测（.evidence/h3_before.xml）：本包族序号 = 0 / 共 5 个族。
#   本包字件 cmap 有 33,944 个码位（汉字 20,977 + 扩展 A 6,582 + 假名 189 + …，谚文 0），
#   所以「大片没字」的量级完全对得上——不是空字形（空字形只有 13 个，其中 8 个是填空符）。
# 2026-11-10 的改动：**不再插匿名首族**，只插 sans-serif 与中日韩 lang 族。
#   这样本包族不再占 0 号位，命中要靠 hasGlyph + 语言分，缺字能正常落到设备的族。
# 仍未验证：真机上的可视差异。本轮没有设备，只有离线数字（见 .evidence/）。
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
            pending = 0
        }
        {
            # 2026-11-10 三次修正的最终形态（每条都有实测反例，见 .evidence/）：
            #   ① 不再在 <familyset> 后插匿名族 —— 那是 mFamilies[0]，minikin 一票通过。
            #   ② 不再插 sans-serif —— 设备上它往往就是 0 号族，等于没改。
            #   ③ 插在**族尾**（</family> 之前），不是族首：族内 getClosestMatch 同权重先到者
            #      优先，插族首会把设备自带的 Noto 挤到后面，仍然是我们被选中。
            # 只对带 lang 的中/日/韩族生效；插的是 <font> 行，必须落在 </family> 之前。
            if ($0 ~ /<\/family>/ && pending) {
                printf "%s", rows
                pending = 0
            }
            print
            if ($0 ~ /<family[ \t>]/ && $0 !~ /\/>[ \t]*$/) {
                pending = cjk($0) ? 1 : 0
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
        ui_print "Skia /system/etc/fonts.xml：已插 $touched 处（中日韩语言族族尾；不占 mFamilies[0]，设备字件在前、OEM 原样保留）"
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
