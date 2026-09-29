#!/system/bin/sh
# 火狐(Firefox/Gecko)接入,原生路径:Gecko 不按系统的 fonts.xml 挑字体,而是照自己
# font.name-list.* 名单里的家族名找字体(清单来自 Android 系统字体 API)。GeckoView 官方支持
# 从 /data/local/tmp/<包名>-geckoview-config.yaml 读启动首选项,前提是该应用是 Android
# 「调试应用」——所以这里不需要 LSPosed、不改 APK,只放一个文件加一个系统开关。
#
# 用法:su -c 'sh /data/adb/modules/MFGA/firefox.sh'            # 接入(默认)
#       su -c 'sh /data/adb/modules/MFGA/firefox.sh remove'     # 退出
set -u
PKG=${FIREFOX_PACKAGE:-org.mozilla.firefox}
DIR=${FIREFOX_DATA_DIR:-/data/local/tmp}
CONFIG=$DIR/$PKG-geckoview-config.yaml
MODPATH=${0%/*}
[ "$MODPATH" = "$0" ] && MODPATH=.
SOURCE=$MODPATH/geckoview-config.yaml

note_am() {
    echo "提示:没有可用的 am,请用电脑执行 adb shell am $1 $PKG"
}

install() {
    [ -r "$SOURCE" ] || { echo "读不到 $SOURCE" >&2; exit 1; }
    mkdir -p "$DIR" && cp -f "$SOURCE" "$CONFIG" || { echo "写入 $CONFIG 失败" >&2; exit 1; }
    echo "已写入 $CONFIG"
    if command -v am >/dev/null 2>&1; then
        am set-debug-app --persistent "$PKG" || echo "am set-debug-app 失败(重启后可能失效)"
    else
        note_am "set-debug-app --persistent"
    fi
    if command -v settings >/dev/null 2>&1; then
        current=$(settings get global debug_app)
        echo "debug_app = $current"
        [ "$current" = "$PKG" ] || echo "警告:debug_app 不是 $PKG,Gecko 不会读这份配置"
    fi
    echo "重启火狐后验证:logcat -s GeckoRuntime GeckoDebugConfig | grep -i 'config\\|prefs'"
    echo "应看到 'Adding debug configuration from: $CONFIG' 与 'Adding prefs from debug config'。"
    echo "退出:firefox.sh remove"
}

remove() {
    rm -f "$CONFIG" && echo "已删除 $CONFIG"
    if command -v am >/dev/null 2>&1; then
        am clear-debug-app && echo "已清除调试应用标记"
    else
        note_am "clear-debug-app"
    fi
    echo "重启火狐后恢复 Gecko 自带名单。"
}

case "${1:-install}" in
    install) install ;;
    remove) remove ;;
    *) echo '用法:firefox.sh [install|remove]' >&2; exit 2 ;;
esac
