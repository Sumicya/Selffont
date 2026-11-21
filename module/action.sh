#!/system/bin/sh
# KernelSU 管理器的「操作」按钮：清场、打印状态、切 Skia 那条路（Flutter / WebView 用的）。
#
# 本机**不支持运行期换字体**（四条路的真机证据见 README「运行期换字体」一节）：
# 换字体 = 改模块 → 重启。这里只改标记，重启后由安装脚本按标记落地。
#
# 用法（终端里也能直接跑）：
#   sh action.sh          清场（panic）后打印状态
#   sh action.sh status   只打印状态（运行期换字体 + Skia 开关）
#   sh action.sh skia     切 Skia 开关（on/off），打印新的状态；改完要重启
#   sh action.sh panic    只清场：摘掉能认定是本模块留下的挂载层，删工作目录与状态文件
#
# 网页字体压/放行仍不在按钮里：sh web-fonts.sh keep|block|toggle
command -v ui_print >/dev/null 2>&1 || ui_print() { echo "$1"; }
MODDIR=${0%/*}; [ "$MODDIR" = "$0" ] && MODDIR=.

status() {
    ui_print "$(sh "$MODDIR/hotswap.sh" status)"
    ui_print "Selffont: 运行期换字体本机不支持；换字体请改模块后重启。"
    ui_print "$(sh "$MODDIR/skia.sh" status)"
}

case ${1:-panic} in
    status)
        status
        ;;
    skia)
        cur=$(sh "$MODDIR/skia.sh" status | sed -n 's/^Selffont:skia=//p' | head -n 1)
        if [ "$cur" = "on" ]; then
            sh "$MODDIR/skia.sh" off
        else
            sh "$MODDIR/skia.sh" on
        fi
        ui_print "----"
        status
        ;;
    panic)
        out=$(sh "$MODDIR/hotswap.sh" panic 2>&1)
        rc=$?
        ui_print "$out"
        ui_print "----"
        status
        exit $rc
        ;;
    *)
        ui_print "用法：sh action.sh [status|skia|panic]（本机不支持运行期换字体）"
        exit 2
        ;;
esac
