#!/system/bin/sh
# 火狐(Firefox/Gecko)接入,原生路径:Gecko 不按系统的 fonts.xml 挑字体,而是照自己
# font.name-list.* 名单里的家族名找字体(清单来自 Android 系统字体 API)。GeckoView 官方
# 支持从 /data/local/tmp/<包名>-geckoview-config.yaml 读启动首选项,前提是该应用是
# Android「调试应用」——不需要 LSPosed、不改 APK,一个文件加一个系统开关。
#
# 用法:su -c 'sh /data/adb/modules/MFGA/firefox.sh'          # 接入(默认)
#       su -c 'sh /data/adb/modules/MFGA/firefox.sh remove'   # 退出
set -u
PKG=${FIREFOX_PACKAGE:-org.mozilla.firefox}
CONFIG=${FIREFOX_DATA_DIR:-/data/local/tmp}/$PKG-geckoview-config.yaml
MODPATH=${0%/*}; [ "$MODPATH" = "$0" ] && MODPATH=.

case "${1:-install}" in
    install)
        [ -r "$MODPATH/geckoview-config.yaml" ] || { echo "读不到 $MODPATH/geckoview-config.yaml" >&2; exit 1; }
        mkdir -p "${CONFIG%/*}" && cp -f "$MODPATH/geckoview-config.yaml" "$CONFIG" ||
            { echo "写入 $CONFIG 失败" >&2; exit 1; }
        am set-debug-app --persistent "$PKG" || echo "am set-debug-app 失败(重启后可能失效)"
        echo "已接入。重启火狐后验证:logcat -s GeckoRuntime GeckoDebugConfig | grep -i config"
        echo "应看到 'Adding debug configuration from: $CONFIG'。退出:firefox.sh remove"
        ;;
    remove)
        rm -f "$CONFIG" && am clear-debug-app
        echo "已退出,重启火狐后恢复 Gecko 自带名单。"
        ;;
    *) echo '用法:firefox.sh [install|remove]' >&2; exit 2 ;;
esac
