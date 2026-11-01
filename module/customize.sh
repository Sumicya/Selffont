#!/system/bin/sh
# KernelSU 安装脚本。自由化：没有平台闸门——任何 Android、任何厂商、任何管理器都放行。
# 在未测试设备上安装是你自己的选择；唯一的硬要求是包里得有打包好的字体（见 build.py）。
command -v ui_print >/dev/null 2>&1 || ui_print() { echo "$1"; }
command -v abort >/dev/null 2>&1 || abort() { echo "!!! $1" >&2; exit 1; }

# 仓库里不存字体二进制：直接压缩仓库（而不是 build.py 的产物）时在这里拦住。
[ -n "$(ls -A "$MODPATH/system/fonts" 2>/dev/null)" ] ||
    abort "Selffont: 模块里没有字体文件。请用 build.py 打包，不要直接压缩仓库。"

# 覆盖 font_fallback.xml 之前的体检。分两档，因为「缺字件」有两种后果：
#   硬档（abort）：默认族 sans-serif 的字件必须解析得到。这一族 system_server 开机就用，
#                  它缺了才是真砖（2026-11-01 进安全模式那条路）。
#   软档（只警告）：其余被引用的名字，设备没有也不会崩——Android 的字体解析器找不到文件就跳过，
#                  只是那些字符落到回退链。上一版把它写成硬档，结果每个真机都装不上，
#                  等于把「可能崩」换成了「必然装不上」，矫枉过正。
ROOT_DIR=${SELFFONT_SYSTEM_ROOT:-}
exists() {
    [ -f "$MODPATH/system/fonts/$1" ] && return 0
    [ -f "$ROOT_DIR/system/fonts/$1" ] && return 0
    return 1
}
boot_missing=""
for name in $(awk '/<family name="sans-serif"[ >]/{f=1} f&&/<\/family>/{f=0} f' "$MODPATH/font_fallback.xml" |
              tr '>' '\n' |
              sed -n 's/^[[:space:]]*\([A-Za-z0-9_.+-]*\.\(ttf\|otf\|ttc\)\).*/\1/p' | sort -u); do
    [ -n "$name" ] || continue
    exists "$name" || boot_missing="$boot_missing $name"
done
if [ -n "$boot_missing" ]; then
    abort "Selffont: 默认族 sans-serif 缺字件：$boot_missing
这一族是 system_server 开机就要用的，缺了会卡开机（2026-11-01 事故）。拒绝安装。"
fi

missing=""; checked=0
# 取「所有 <font> 的文本」不能按行 grep：带 <axis> 子节点的条目在同一行里后面跟的是 '<'，
# 旧写法 `grep -o '<font[^>]*>[^<[:space:]]*'` 会漏掉它们（实测 140 vs 243，漏掉 103 个）。
# 按 '>' 切行再取文件名，与构建期 ElementTree 的口径一致（两边都是 243）。
for name in $(tr '>' '\n' < "$MODPATH/font_fallback.xml" |
              sed -n 's/^[[:space:]]*\([A-Za-z0-9_.+-]*\.\(ttf\|otf\|ttc\)\).*/\1/p' | sort -u); do
    [ -n "$name" ] || continue
    checked=$((checked + 1))
    exists "$name" || missing="$missing $name"
done
if [ -n "$missing" ]; then
    ui_print "Selffont: 本机缺 $(echo $missing | wc -w) 个被引用的字件（不影响开机，那些字符走回退链）"
    ui_print "  缺：$(echo $missing | tr ' ' '\n' | head -8 | tr '\n' ' ')..."
fi
ui_print "Selffont: 字件体检通过（引用 $checked 个，默认族齐全）"

# 同名配置的旧模块必须让路。上一版的 id 是 MFGA，与基础包同源；这一版改成 selffont-mother。
# 两个模块同时挂 /system/etc/font_fallback.xml 会互相覆盖，字体可能整个起不来。
# 发现旧 id 就给它打 disable 标记（KernelSU / Magisk 的官方机制，可逆），不是删它。
OLD_MOD=/data/adb/modules/MFGA
if [ -d "$OLD_MOD" ] && [ "$OLD_MOD" != "${MODPATH%/system}" ]; then
    if [ ! -f "$OLD_MOD/disable" ] && [ ! -f "$OLD_MOD/remove" ]; then
        touch "$OLD_MOD/disable" 2>/dev/null &&
            ui_print "Selffont: 已停用旧模块 MFGA（同名配置，两份同时挂会冲突）；重启后生效"
    fi
fi

# 读配置的程序有两类，各读各的，两份都得换：
#   font_fallback.xml / fonts_base.xml / fonts_ule.xml   新语法，Android 框架（SystemFonts）读
#   fonts.xml                                            库存旧语法，Skia 读，路径写死在
#                                                        Skia 的 SkFontMgr_android_parser.cpp
#                                                        （LMP_SYSTEM_FONTS_FILE）
# Flutter（FlClash 这类）、WebView、部分厂商小组件走 Skia：只换前者，它们一个字都不变。
# 2026-10-28 真机：/system/etc/fonts.xml 里 Selffont 出现 0 次，另外三份各 16 次。
# fonts_customization.xml 不碰（它只管别名，不装字件）。
# 模块内统一放 $MODPATH/system/<分区>/…：KernelSU 的 vendor / product / system_ext 就是
# 指向 system/ 下同名的符号链接，直接建顶层分区目录会顶掉符号链接（已知会卡开机）。
ROOT=${SELFFONT_SYSTEM_ROOT:-}
replaced=""
count=0
for partition in system system_ext product; do
    base="$ROOT/$partition/etc"
    [ -d "$base" ] || continue
    for source in "$base"/font_fallback*.xml "$base"/fonts_base.xml "$base"/fonts_ule.xml; do
        [ -f "$source" ] || continue
        name=${source##*/}
        target="$MODPATH/system/$partition/etc"
        [ "$partition" = "system" ] && target="$MODPATH/system/etc"
        mkdir -p "$target" && cp -f "$MODPATH/font_fallback.xml" "$target/$name" ||
            abort "Selffont: 替换 $source 失败"
        replaced="$replaced $partition/etc/$name"
        count=$((count + 1))
    done
done

# Skia 那份（/system/etc/fonts.xml）**只插不换**：设备自己那份里有 OPPO Sans 等 OEM 字件，
# 整份盖掉等于把它们删掉（真机反馈：天气小组件落到 OPPO Sans）。这里在设备那份的副本上
# 做最小插入——默认链、sans-serif、中日韩语言族的最前面加我们的字件，其余行一个字节不动。
insert="$MODPATH/fonts-insert.xml"
skia="设备没有 /system/etc/fonts.xml：Flutter / WebView 不跟系统换字"
if [ -f "$ROOT/system/etc/fonts.xml" ]; then
    if [ -s "$insert" ]; then
        mkdir -p "$MODPATH/system/etc"
        awk -v rowsfile="$insert" '
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
            ' "$ROOT/system/etc/fonts.xml" > "$MODPATH/system/etc/fonts.xml" 2>/dev/null
        # 校验插进去了几条：拿插入行里的字件文件名去数（不写死 Selffont，
        # 自检夹具用的就是别的名字）。grep -c 没命中会先打印 0 再返回 1，
        # 写成 `|| echo 0` 会拿到两行的 "0\n0"，[ -gt 0 ] 直接报 Illegal number。
        marker=$(sed -n 's|.*>\([^<]*\)</font>.*|\1|p' "$insert" | head -n 1)
        touched=$(grep -c -F "$marker" "$MODPATH/system/etc/fonts.xml" 2>/dev/null || true)
        [ -n "$touched" ] || touched=0
        if [ "${touched:-0}" -gt 0 ]; then
            skia="已插 $touched 处（默认链 / sans-serif / 中日韩语言族，OEM 字件原样保留）"
        else
            rm -f "$MODPATH/system/etc/fonts.xml"
            skia="失败：设备 fonts.xml 插不进去，Flutter / WebView 不跟系统换字"
            ui_print "!!! Selffont: Skia 配置没插进去。系统字体照换，但 Flutter / WebView / 部分"
            ui_print "!!!   小组件走的是 /system/etc/fonts.xml，它们会继续用原字体。"
        fi
    fi
fi

# 安装结果落盘：安装日志在管理器里一闪而过，真机上没人抢得到这几行。
# 落到 /data/adb（不在模块里，卸载模块也还在），重启后 `cat` 就能回答「到底换了没、换了几处」。
SELFTEST=/data/adb/selffont-selftest.log
{
    echo "时刻 $(date +%Y-%m-%dT%H:%M:%S%z 2>/dev/null || echo 未知)"
    echo "框架配置 $count 份：$replaced"
    echo "Skia /system/etc/fonts.xml：$skia"
    echo "插入行 $(grep -c '<font ' "$MODPATH/fonts-insert.xml" 2>/dev/null || echo 0) 条（字重逐档，来自 fonts-insert.xml）"
    echo "模块内字件 $(ls -1 "$MODPATH/system/fonts" 2>/dev/null | wc -l) 个"
    echo "覆盖清单：见模块目录 coverage.txt（打包了哪些、哪些靠设备自带）"
} > "$SELFTEST" 2>/dev/null &&
    ui_print "Selffont: 自查已写 $SELFTEST（重启后 cat 可查换了哪些配置）"

if [ "$count" -gt 0 ]; then
    ui_print "Selffont: 已替换 $count 份字体配置：$replaced"
    ui_print "Selffont: Skia 配置 /system/etc/fonts.xml：$skia"
    ui_print "Selffont: 重启后生效（字体文件挂在 /system/fonts）。"
else
    abort "Selffont: 设备上没有可替换的字体配置（font_fallback.xml / fonts_base.xml / fonts_ule.xml 都没有）。本模块只支持带其中至少一份的设备。"
fi

# 火狐配置是 firefox.sh 装到 /data/local/tmp 的拷贝：模块更新后那份会变旧，字体名单就不再前进。
# 已接入（那份文件还在）就顺手换新；没接入过（文件不存在）不碰，不做任何推销。
bridge="${FIREFOX_DATA_DIR:-/data/local/tmp}/${FIREFOX_PACKAGE:-org.mozilla.firefox}-geckoview-config.yaml"
if [ -f "$bridge" ]; then
    # 走 web-fonts.sh refresh：按运行时开关状态生成，不覆盖你在管理器里切过的选择。
    if sh "$MODPATH/web-fonts.sh" refresh; then
        ui_print "Selffont: 已刷新火狐配置（保留网页字体开关状态，重启火狐后生效）。"
    else
        cp -f "$MODPATH/geckoview-config.yaml" "$bridge" &&
            ui_print "Selffont: 已刷新火狐配置（开关脚本不可用，退回模板默认）。"
    fi
fi
ui_print "Selffont: 重启即生效。无开机自动干预。"
