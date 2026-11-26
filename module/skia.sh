#!/system/bin/sh
# 只往 `sans-serif` 一族插一行。不整份替换、不碰别的族。
#
# 为什么是这一族、为什么只一处（全部由源码推出，不是偏好）：
#   1. Flutter 在 Android 上不用 Java 的 Typeface，用 libflutter.so 里的 Skia。
#      `txt/src/txt/platform_android.cc`：GetDefaultFontFamilies() 返回 {"sans-serif"}、
#      SkFontMgr_New_Android(nullptr, …)；`SkFontMgr_android.cpp` findDefaultStyleSet()
#      也只认 sans-serif，取不到才退 fStyleSets[0]。
#   2. Skia 的解析器把路径写死成 /system/etc/fonts.xml（SkFontMgr_android_parser.cpp
#      LMP_SYSTEM_FONTS_FILE）。这份文件在 AOSP 头注释里标着 DEPRECATED，对系统框架已废；
#      但 Flutter 只读它，所以不改就没戏。这就是「可以碰」的全部理由，也决定了碰法：
#      只许插行，因为整份替换会删掉设备自己的 OEM 族（2026-11-25 卡开机）。
#   3. onMatchFamilyStyleCharacter 五层顺序的第一层就是「名字相等的族」，
#      find_family_style_character 每族只取一个面（matchAStyle），matchStyleCSS3
#      并列时先出现的赢（严格小于）。⇒ 插在族首＝我方负责该面覆盖的字符，没有的字符
#      自动流到族内设备那条、再流到别的族。机制本身就是分工，不是取代。
#      插在族尾则一个字都不会变（零与一，不是优先级）。
#   4. 只插一处：其余八处（中日韩语言族、无名族、多字件匿名族）都在第一层之外，
#      只有第一层落空才会执行；而第一层对我方覆盖的字符命中我方、对我方没有的字符
#      命中设备那条，所以那八处在功能上是死代码，删掉不损失命中率。
#
# 用法：sh skia.sh [status|on|off|apply]（改完重启生效）
command -v ui_print >/dev/null 2>&1 || ui_print() { echo "$1"; }
[ "$#" -gt 1 ] && ui_print "Skia 告警：我不读位置参数（$*）；模块目录＝脚本自身路径或 SELFFONT_MODDIR"
MODDIR=${SELFFONT_MODDIR:-${0%/*}}; [ "$MODDIR" = "$0" ] && MODDIR=.
# 2026-11-27：MODDIR 历来由脚本自身路径推导、位置参数从来不读；传位置参数曾被静默
# 忽略且报错「没有插入行」（报错不指真因，多查半轮）。现在位置参数直接告警。
STATE=${SELFFONT_SKIA_STATE:-/data/adb/selffont-skia.state}
ROOT=${SELFFONT_SYSTEM_ROOT:-}
INSERT=$MODDIR/fonts-insert.xml
TARGET=$MODDIR/system/etc/fonts.xml
SOURCE=$ROOT/system/etc/fonts.xml
FONTDIR=${ROOT}/system/fonts; [ -n "$ROOT" ] || FONTDIR=/system/fonts

state() {
    # `mode=` 是用户亲手选的值，`ver=` 是写下它时模块自己的版本。
    # 升级后状态文件里 ver 与当前版本不一致 ⇒ 用户没在**这个版本**上表过态，回默认 on。
    _st=$(sed -n 's/^mode=//p' "$STATE" 2>/dev/null | tail -n 1)
    _ver=$(sed -n 's/^ver=//p' "$STATE" 2>/dev/null | tail -n 1)
    _cur=$(sed -n 's/^version=//p' "${MODDIR}/module.prop" 2>/dev/null | head -n 1)
    if [ -n "$_st" ] && [ "$_ver" = "$_cur" ]; then
        case $_st in off) echo off ;; *) echo on ;; esac
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

# 目标族在不在（且不在注释块里）。打印 1=不在/不可见，0=可见。
target_hidden() {
    awk '
        function upd(s,   i, j) {
            while (1) {
                if (!incmt) { i = index(s, "<!--"); if (!i) break; incmt = 1; s = substr(s, i + 4); continue }
                j = index(s, "-->"); if (!j) break; incmt = 0; s = substr(s, j + 3)
            }
            return incmt
        }
        { c = upd($0) }
        !c && /<family[ \t>]/ && $0 ~ /name="sans-serif"/ { print 0; done = 1; exit }
        END { if (!done) print 1 }
    ' "$SOURCE"
}

# 目标族里 <font> 的总数与可读数，输出「可读 总数」。
# 抽名字不用 sed `\|`：Android toybox sed 把 `\|` 当字面量，438 真机抽到 0 个
# （selftest：「sans-serif 族里 0 个字件一个都打不开，不插」），CI 的 GNU sed 过不了真机。
font_readable() {
    _tot=0; _ok=0
    for _f in $(awk '
        function upd(s,   i, j) {
            while (1) {
                if (!incmt) { i = index(s, "<!--"); if (!i) break; incmt = 1; s = substr(s, i + 4); continue }
                j = index(s, "-->"); if (!j) break; incmt = 0; s = substr(s, j + 3)
            }
            return incmt
        }
        { c = upd($0) }
        c { next }
        /<family[ \t>]/ { in_f = ($0 ~ /name="sans-serif"/); next }
        in_f && /<\/family>/ { exit }
        in_f {
            gsub(/[<>]/, " ")
            for (i = 1; i <= NF; i++)
                if ($i ~ /\.ttf$/ || $i ~ /\.otf$/ || $i ~ /\.ttc$/) print $i
        }
    ' "$SOURCE"); do
        [ -n "$_f" ] || continue
        _tot=$((_tot + 1))
        [ -r "$FONTDIR/$_f" ] && _ok=$((_ok + 1))
    done
    echo "$_ok $_tot"
}

# 从别人模块里那份 fonts.xml 剔掉我们的插入行（off / 卸载后 overlay 还在抢挂载）。
strip_others() {
    _mk=$1
    [ -n "$_mk" ] || return 0
    MODULES=${SELFFONT_MODULES:-/data/adb/modules}
    for _d in "$MODULES"/*/; do
        _p="${_d}system/etc/fonts.xml"
        [ -f "$_p" ] || continue
        [ "$_p" -ef "$TARGET" ] 2>/dev/null && continue
        grep -q -F "$_mk" "$_p" || continue
        awk -v marker="$_mk" 'index($0, marker) { next } { print }' "$_p" > "$_p.sf.tmp" &&
            mv -f "$_p.sf.tmp" "$_p"
    done
}

apply() {
    rm -f "$TARGET"
    _marker=$(sed -n 's|.*>\([^<]*\)</font>.*|\1|p' "$INSERT" 2>/dev/null | head -n 1)
    if [ "$(state)" != on ]; then
        strip_others "$_marker"
        ui_print "Skia /system/etc/fonts.xml：未插（Selffont:skia=off，Flutter 用设备自己那份）"
        return 0
    fi
    [ -s "$INSERT" ] || { ui_print "Skia：模块里没有插入行（fonts-insert.xml），跳过"; return 0; }
    [ -s "$SOURCE" ] || { ui_print "Skia：设备没有 /system/etc/fonts.xml，无处可插"; return 0; }
    # 族不在或在注释块里：插了也不被解析。设备族里的字件读不读得开不再当闸门——
    # 我们插的是本包字件，空闸门在 438 真机把 Flutter 整条路掐死（ColorOS 17 的
    # Roboto 空壳当时还不在 /system/fonts，模块还没挂上）。
    if [ "$(target_hidden)" = 1 ]; then
        ui_print "Skia：sans-serif 族不存在或在注释块里，不插（插了也不被解析）"
        return 0
    fi
    if [ ! -r "$MODDIR/system/fonts/$_marker" ] && [ ! -r "$FONTDIR/$_marker" ]; then
        ui_print "!!! Skia：本包字件 $_marker 读不到，不插"
        return 0
    fi
    set -- $(font_readable)
    _ok=${1:-0}; _tot=${2:-0}
    mkdir -p "$MODDIR/system/etc"
    awk -v rowsfile="$INSERT" -v marker="$_marker" '
        function upd(s,   i, j) {
            while (1) {
                if (!incmt) { i = index(s, "<!--"); if (!i) break; incmt = 1; s = substr(s, i + 4); continue }
                j = index(s, "-->"); if (!j) break; incmt = 0; s = substr(s, j + 3)
            }
            return incmt
        }
        BEGIN { while ((getline row < rowsfile) > 0) rows = rows row "\n"; close(rowsfile) }
        { c = upd($0) }
        # 注释块里的行原样输出，一律不参与族匹配（2026-11-26 真机：ColorOS 有一整段被注释掉的族）
        c { print; next }
        # 2026-11-27 两处族首：sans-serif ＋ Roboto。Flutter 引擎在 Android 按名要
        # Roboto（FlClash 源码链读得：theme→fontFamilyFallback→prism_ui，具名族列表
        # 绕开 sans-serif），只插 sans-serif 时具名请求落回设备字件＝应用里字体不变。
        /<family[ \t>]/ { in_f = 1; tgt = ($0 ~ /name="sans-serif"/ || $0 ~ /name="Roboto"/); nf = 0; nxt = 0; print; next }
        in_f && /<\/family>/ { in_f = 0; print; next }
        # 剔掉上一轮的插入行，保证幂等
        in_f && index($0, marker) { next }
        in_f && /<font / {
            if (tgt && nf == 0 && !nxt) { printf "%s", rows; nxt = 1 }
            nf++
        }
        { print }
    ' "$SOURCE" > "$TARGET"
    _n=$(grep -c -F "$_marker" "$TARGET" 2>/dev/null || true); [ -n "$_n" ] || _n=0
    if [ "$_n" -gt 0 ]; then
        # 438 真机：KSU overlay lowerdir=GGAT_10007/system/etc:selffont-bench/system/etc
        # GGAT 在最左＝最上层，它有 fonts.xml 时我们模块那份永远看不见。谁有这份文件
        # 就写回谁，挂载顺序不再决定 Flutter 看不看得见我们。
        _wb=0
        MODULES=${SELFFONT_MODULES:-/data/adb/modules}
        for _d in "$MODULES"/*/; do
            _p="${_d}system/etc/fonts.xml"
            [ -f "$_p" ] || continue
            [ "$_p" -ef "$TARGET" ] 2>/dev/null && continue
            cp -f "$TARGET" "$_p" || continue
            _wb=$((_wb + 1))
        done
        ui_print "插入=$_n 族=sans-serif+Roboto 字件=$_marker 族内可读=$_ok/$_tot 写回=$_wb"
        return 0
    fi
    rm -f "$TARGET"
    ui_print "!!! Skia：插入失败（族里没有 <font> 行？），Flutter 继续用设备原文件"
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
