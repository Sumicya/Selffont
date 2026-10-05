#!/system/bin/sh
# KernelSU 安装脚本。自由化：没有平台闸门——任何 Android、任何厂商、任何管理器都放行。
# 在未测试设备上安装是你自己的选择；唯一的硬要求是包里得有打包好的字体。
command -v ui_print >/dev/null 2>&1 || ui_print() { echo "$1"; }
command -v abort >/dev/null 2>&1 || abort() { echo "!!! $1" >&2; exit 1; }

# 仓库里不存字体二进制：直接压缩仓库（而不是 build.py 的产物）时在这里拦住。
[ -n "$(ls -A "$MODPATH/system/fonts" 2>/dev/null)" ] ||
    abort "Selffont: 模块里没有字体文件。请用 build.py 打包，不要直接压缩仓库。"

# 整份替换系统全部 font*.xml（familyset 只能有一份；fonts_customization.xml 是用户自选配置，不碰）。
# ponytail: 整份替换的天花板是非 familyset schema 的 ROM 会显示异常（实机已验证 Oplus 整替可行）；
# 升级：遇到异 schema 实机再按 schema 分支，不预先建框架。
SYSTEM_ROOT=${SELFFONT_SYSTEM_ROOT:-/system}
copied=0
for base in "$SYSTEM_ROOT/system_ext/etc" "$SYSTEM_ROOT/product/etc" "$SYSTEM_ROOT/etc"; do
    [ -d "$base" ] || continue
    for source in "$base"/font*.xml; do
        [ -f "$source" ] || continue
        case "${source##*/}" in fonts_customization.xml) continue ;; esac
        mkdir -p "$MODPATH$base" && cp -f "$MODPATH/fonts.xml" "$MODPATH$base/${source##*/}" ||
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
    cp -f "$MODPATH/geckoview-config.yaml" "$bridge" &&
        ui_print "Selffont: 已刷新火狐配置（重启火狐后生效）。"
fi
ui_print "Selffont: 重启即生效。无开机自动干预。"
