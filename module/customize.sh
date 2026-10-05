#!/system/bin/sh
# KernelSU 安装脚本。自由化：没有平台闸门——任何 Android、任何厂商、任何管理器都放行。
# 在未测试设备上安装是你自己的选择；唯一的硬要求是包里得有打包好的字体（见 build.py）。
command -v ui_print >/dev/null 2>&1 || ui_print() { echo "$1"; }
command -v abort >/dev/null 2>&1 || abort() { echo "!!! $1" >&2; exit 1; }

# 仓库里不存字体二进制：直接压缩仓库（而不是 build.py 的产物）时在这里拦住。
[ -n "$(ls -A "$MODPATH/system/fonts" 2>/dev/null)" ] ||
    abort "Selffont: 模块里没有字体文件。请用 build.py 打包，不要直接压缩仓库。"

# 设备读哪份字体配置按厂商而定，都用包里同一份新语法配置（supportedAxes）填充：
#   font_fallback.xml   AOSP 15+：SystemFonts 源码 FONTS_XML = font_fallback.xml
#   fonts_base.xml      ColorOS 基础层（日志：Loading font config from /system_ext/etc/fonts_base.xml）
#   fonts_ule.xml       ColorOS 界面实际使用的那层
# 不碰库存 fonts.xml（AOSP 16 头注已标 DEPRECATED）与 fonts_customization.xml。
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

if [ "$count" -gt 0 ]; then
    ui_print "Selffont: 已替换 $count 份字体配置：$replaced"
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
