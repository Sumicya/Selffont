#!/system/bin/sh
# KernelSU 安装脚本。自由化：没有平台闸门——任何 Android、任何厂商、任何管理器都放行。
# 在未测试设备上安装是你自己的选择；唯一的硬要求是包里得有打包好的字体。
command -v ui_print >/dev/null 2>&1 || ui_print() { echo "$1"; }
command -v abort >/dev/null 2>&1 || abort() { echo "!!! $1" >&2; exit 1; }

# 仓库里不存字体二进制：直接压缩仓库（而不是 build.py 的产物）时在这里拦住。
[ -n "$(ls -A "$MODPATH/system/fonts" 2>/dev/null)" ] ||
    abort "Selffont: 模块里没有字体文件。请用 build.py 打包，不要直接压缩仓库。"

# 整份替换系统全部 font*.xml（familyset 只能有一份；fonts_customization.xml 是用户自选配置，不碰）。
# 按目标文件名选语法：font_fallback*.xml 是 Android 15+ 的新配置，放新语法（supportedAxes，
# 主字体由系统按 wght/ital 运行时实例化）；其余 font*.xml 是 legacy 解析目标，放展开好的静态阶梯。
# 官方要求两个文件保持同步，包里两份内容同源（都由 build.py 从同一棵家族树生成）。
SYSTEM_ROOT=${SELFFONT_SYSTEM_ROOT:-/system}
copied=0
for base in "$SYSTEM_ROOT/system_ext/etc" "$SYSTEM_ROOT/product/etc" "$SYSTEM_ROOT/etc"; do
    [ -d "$base" ] || continue
    for source in "$base"/font*.xml; do
        [ -f "$source" ] || continue
        case "${source##*/}" in
            fonts_customization.xml) continue ;;
            font_fallback*.xml) from=font_fallback.xml ;;
            *) from=fonts.xml ;;
        esac
        [ -f "$MODPATH/$from" ] || abort "Selffont: 包里缺少 $from，无法替换 $source"
        mkdir -p "$MODPATH$base" && cp -f "$MODPATH/$from" "$MODPATH$base/${source##*/}" ||
            abort "Selffont: 替换 $source 失败"
        copied=$((copied + 1))
    done
done

if [ "$copied" -gt 0 ]; then
    ui_print "Selffont: 已替换 $copied 份字体配置，重启后生效。"
else
    ui_print "Selffont: 警告——没找到系统 font*.xml，字体配置未替换（模块只挂载了字体文件）。"
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
