#!/system/bin/sh
# KernelSU 管理器的「操作」按钮：只做两件事——清场、打印状态。
#
# 本机**不支持运行期换字体**（四条路的真机证据见 README「运行期换字体」一节）：
# 换字体 = 改模块 → 重启。按钮不再切换任何东西，也不会去挂载任何东西。
#
# 用法（终端里也能直接跑）：
#   sh action.sh          清场（panic）后打印状态
#   sh action.sh status   只打印状态（本机不支持 + 残留层数）
#   sh action.sh panic    只清场：摘掉能认定是本模块留下的挂载层，删工作目录与状态文件
#
# 网页字体压/放行仍可用，但不在按钮里：sh web-fonts.sh keep|block|toggle
command -v ui_print >/dev/null 2>&1 || ui_print() { echo "$1"; }
MODDIR=${0%/*}; [ "$MODDIR" = "$0" ] && MODDIR=.

case ${1:-panic} in
    status)
        ui_print "$(sh "$MODDIR/hotswap.sh" status)"
        ui_print "Selffont: 运行期换字体本机不支持；换字体请改模块后重启。"
        ;;
    panic)
        out=$(sh "$MODDIR/hotswap.sh" panic 2>&1)
        rc=$?
        ui_print "$out"
        ui_print "----"
        ui_print "$(sh "$MODDIR/hotswap.sh" status)"
        ui_print "Selffont: 运行期换字体本机不支持；换字体请改模块后重启。"
        exit $rc
        ;;
    *)
        ui_print "用法：sh action.sh [status|panic]（本机不支持运行期换字体）"
        exit 2
        ;;
esac
