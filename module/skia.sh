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
    # `mode=` 是用户亲手选的值，`ver=` 是写下它时模块自己的版本。
    # 2026-11-25 真机：主人在旧版里点过 off，升级到「默认 on」的版本后 state 文件还在，
    # `mode=off` 被照读 ⇒ 新版本的默认值对老用户永远无效。所以升级时必须按版本重判一次：
    # 状态文件里的 ver 和当前 module.prop 的 version 不一致 ⇒ 用户没在**这个版本**上表过态，
    # 回到默认值（on）。用户在**本版本**里点过 on/off 的，ver 相同，照旧尊重。
    _st=$(sed -n 's/^mode=//p' "$STATE" 2>/dev/null | tail -n 1)
    _ver=$(sed -n 's/^ver=//p' "$STATE" 2>/dev/null | tail -n 1)
    _cur=$(sed -n 's/^version=//p' "${MODDIR}/module.prop" 2>/dev/null | head -n 1)
    if [ -n "$_st" ] && [ "$_ver" = "$_cur" ]; then
        case $_st in
            off) echo off ;;
            *) echo on ;;
        esac
        return
    fi
    echo on
}

write_state() {
    mkdir -p "${STATE%/*}" 2>/dev/null
    printf 'mode=%s\nver=%s\n' "$1" \
        "$(sed -n 's/^version=//p' "${MODDIR}/module.prop" 2>/dev/null | head -n 1)" \
        > "$STATE" 2>/dev/null || {
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
    if [ ! -s "$INSERT" ]; then
        ui_print "Skia /system/etc/fonts.xml：模块里没有插入行（fonts-insert.xml），跳过"
        return 0
    fi
    # ★ 2026-11-25 真机：MFGA 与我们同时存在时 FlClash 一个字都没变。
    #   MFGA 的 `script/search_dirs.sh: handle_file()` 干的是
    #       cp -f "$MODPATH/fonts.xml" "$MODPATH/system/etc/fonts.xml"
    #   —— 它把自己那份 1,824 行的 fonts.xml **整份盖**到同一个挂载点
    #   `/system/etc/fonts.xml`，和我们抢的是同一个路径。谁的模块后被加载谁赢，
    #   这个顺序我们控制不了。它那份里 `Selffont` 出现 0 次，`sans-serif` 只有
    #   Roboto 空壳，所以它赢的时候我们的插入等于没做（逐字复算 0.00%）。
    #   改法：把**它那份**当输入，往里插我们的行；再垫一个自己的副本跟在后加载的模块
    #   抢同一个路径时也不丢行。两份内容一致，谁赢都对。
    MODULES=${SELFFONT_MODULES:-/data/adb/modules}
    MFGA="$MODULES/MFGA/system/etc/fonts.xml"
    # 输入取「最可能赢那个挂载点」的那份：MFGA 整份覆盖、覆盖面更大（1,824 行），排第一。
    # $ROOT 只给夹具换根用。
    SOURCE=""
    for _cand in "$MFGA" "$ROOT/system/etc/fonts.xml"; do
        [ -f "$_cand" ] || continue
        SOURCE=$_cand
        break
    done
    if [ -z "$SOURCE" ]; then
        ui_print "Skia /system/etc/fonts.xml：设备没有这份文件，无处可插"
        return 0
    fi
    mkdir -p "$MODDIR/system/etc"
    # 韩文保护。本包 cmap 里谚文 0 个，而 Skia 对每族只查一个 face：我们一旦占了族首，
    # 设备的 NotoSansCJKkr / NotoSansKR 就再也轮不到，韩文整片落豆腐。实测判据见
    # tools/skia_paths.py（设备有韩文字件时族首插法的 Korean 命中率 0%）。
    # 只在「设备那份配置里确有韩文字件」时把 lang 含 ko 的族跳过，其余照插。
    skip_ko=0
    if grep -q 'lang="[^"]*ko' "$SOURCE" 2>/dev/null; then
        skip_ko=1
    fi
    awk -v rowsfile="$INSERT" -v skipko="$skip_ko" '
        # 这一族该不该插：命名族 `sans-serif`、带中日韩 lang 的族、无 name 无 lang 的匿名默认族。
        # emoji（und-Zsye）/ serif / 阿拉伯等一族都不碰——每族只查一个 face，插进去会顶掉它们。
        function wanted(tag,   s, n, a, i, v) {
            if (tag ~ /name="sans-serif"/) return 1
            if (!match(tag, /lang="[^"]*"/)) {
                # ★ 2026-11-25 真机：MFGA 界面出现豆腐块，豆腐是生僻符号。
                #   根因是**这一行**（上一版就在这里插）：匿名族（无 name 无 lang）插族首，
                #   Skia 第 3 层按文件顺序扫匿名族，扫到我们这条、`unicharToGlyph` 不认识
                #   那个符号 → continue 到下一族 —— 而 Unicode16/17/18-new.ttf 全在后面的匿
                #   名族里，于是那些符号整片落豆腐。实测：Unicode18 的 1,290 个码位母版
                #   一个都没有（只有 3 个非汉字码位重叠）。
                #   所以匿名族一律不插。无族名请求改由 sans-serif 那条覆盖。
                return 0
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
        ' "$SOURCE" > "$TARGET" 2>/dev/null
    # 输入是别家模块那份时，把同一份内容写回它自己的目录：挂载顺序决定谁的文件生效，
    # 我们控制不了顺序，那就让**两份内容一样**——谁赢都带着我们的行。
    if [ "$SOURCE" = "$MFGA" ] && [ -f "$MFGA" ]; then
        cp -f "$TARGET" "$MFGA" 2>/dev/null ||
            ui_print "无法把插入行写回 $MFGA（只在本模块那份里生效）"
    fi
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
