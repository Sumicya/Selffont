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
    # ★ 2026-11-25 真机读数暴露的幂等 bug：我们把插好的内容**写回 MFGA 自己的目录**，
    #   下一轮又以那份为输入 ⇒ 每次 apply 都再插一遍。真机上攒到了 30 处，
    #   同一个族里出现两三条并列的同一字件（39/40、1382/1383/1384 就是这种形状）。
    #   修法：插入前先把「我们自己插入的那些行」全部剔掉，再插一次。这样无论
    #   apply 跑多少遍，结果都等于「干净输入 + 一套插入行」。
    #   判据用插入行里的字件名，不写死 Selffont（自检夹具有别的名字）。
    _marker=$(sed -n 's|.*>\([^<]*\)</font>.*|\1|p' "$INSERT" | head -n 1)
    _clean=""
    if [ -n "$_marker" ] && grep -qF "$_marker" "$SOURCE" 2>/dev/null; then
        _clean="$MODDIR/.fonts-input.clean"
        grep -vF "$_marker" "$SOURCE" > "$_clean" 2>/dev/null && SOURCE=$_clean
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
        # Skia 逐字回退的真实代码路径（SkFontMgr_android.cpp，2026-11-25 逐行核对）：
        #   onMatchFamilyStyleCharacter()                    :374
        #       for current in { familyName, SkString() }    :385  ← 先 sans-serif，再空族名
        #           find_family_style_character(current, …)  :342
        #               for i in fallbackNameToFamilyMap:    :348  ← 只遍历**无名族**，按文件顺序
        #                   if current != family->fFallbackFor: continue   :350
        #                   if langTag 不匹配: continue                   :355
        #                   if face->unicharToGlyph(c) != 0: return face  :367
        #
        # 三条硬结论（前三版全错在这）：
        #  ① 带 name= 的族**不进**这张表（parser.cpp:311 置 fIsFallbackFont=false），
        #     所以往 <family name="sans-serif"> 里插对逐字回退毫无作用。
        #  ② 请求族名 sans-serif 那轮，只有 fFallbackFor=="sans-serif" 的族会中，
        #     而 fFallbackFor 只由 <font fallbackFor="…"> 设置，AOSP 配置里出现 0 次 ⇒ 该轮必空。
        #  ③ 真正生效的是空族名那轮：扫**所有**无 lang 匿名族（lang 过滤只在 langTag 非空时拦），
        #     谁在前面谁先被问。MFGA 那份配置里 zh 族是 [10]，而 [2] 是 100.ttf..900.ttf
        #     同一套中文全字重 ⇒ 我们插在 [10] 族首也轮不到。
        #
        # 所以插入点是：中日韩无名族的族首（覆盖 zh/ja 请求）＋ 排在它们之前的、
        # **多字件**的无 lang 匿名族族首（抢在挡路者前面）。单字件的无 lang 匿名族不许插：
        # 每族只取一个 face，插进去会把该族唯一 face 换掉，ASCII 直接落空。
        function is_named(tag) { return tag ~ /name="/ }
        function is_anon_lang(tag) { return !is_named(tag) && tag ~ /lang="/ }
        function wanted(tag,   s, n, a, i, v) {
            if (!is_anon_lang(tag)) return 0
            s = substr(tag, index(tag, "lang=\"") + 6)
            s = substr(s, 1, index(s, "\"") - 1)
            n = split(s, a, ",")
            for (i = 1; i <= n; i++) {
                v = a[i]; sub(/-.*$/, "", v); gsub(/[ \t]/, "", v)
                v = tolower(v)
                if (v == "zh" || v == "ja") return 1
                if (v == "ko") return skipko ? 0 : 1
            }
            return 0
        }
        # 一个 <family> 缓冲起来，到 </family> 才知道字件数，那时再决定插不插。
        function flush(   head, body, nf, i) {
            if (!in_family) return
            head = buf[1]
            nf = 0
            for (i = 2; i <= nb; i++) if (buf[i] ~ /<font /) nf++
            emit = 0
            if (wanted(head)) emit = 1                       # 中日韩无名族：插
            else if (!is_named(head) && head !~ /lang="/ && nf >= 2) emit = 1  # 挡路的多字件匿名族：抢先
            print head
            if (emit) printf "%s", rows
            for (i = 2; i <= nb; i++) print buf[i]
            in_family = 0; nb = 0
        }
        BEGIN {
            while ((getline row < rowsfile) > 0) rows = rows row "\n"
            close(rowsfile)
        }
        /<family[ \t>]/ && $0 !~ /\/>[ \t]*$/ {
            flush()
            in_family = 1; nb = 1; buf[1] = $0
            next
        }
        in_family { buf[++nb] = $0; if ($0 ~ /<\/family>/) flush(); next }
        { print }
        END { flush() }
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
    # 判据不能只数「插了几条」——前三版都数出来了、真机还是没变。必须验**插在哪**：
    # Skia 的逐字回退只看无名族（`fFallbackFor` 相等），插在命名族里等于没插。
    # 所以再数一遍「紧跟在带 name= 的 <family> 后面的那条」，必须为 0。
    if [ "$touched" -gt 0 ]; then
        stray=$(awk '/<family[ \t>].*name="/{named=1; next} /<\/family>/{named=0; next}
                     named && index($0, marker){c++} END{print c+0}' marker="$marker" "$TARGET")
        if [ "${stray:-0}" -gt 0 ]; then
            ui_print "!!! Skia：有 $stray 条插进了命名族（Skia 逐字回退看不到命名族），Flutter 不会变"
        fi
        [ "$skip_ko" = 1 ] && note="，韩文族已跳过（本包无谚文，留给设备）" || note=""
        ui_print "Skia /system/etc/fonts.xml：已插 $touched 处（中日韩无名族的族首$note）"
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
