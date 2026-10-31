#!/system/bin/sh
# KernelSU 管理器的「操作」按钮。点一下 = **热切换**：不重启把二创字件挂上/摘下，
# 与系统设置里换字体「立刻生效」同一套行为（实现见 hotswap.sh 顶部注释）。
#
# 用法（终端里也能直接跑）：
#   sh action.sh            切换字体（on ⇄ off），切完打印状态
#   sh action.sh status     只打印状态（on / off / partial）
#   sh action.sh verify     逐文件比对 sha256，证明系统里看到的就是模块里这份
#   sh action.sh panic      出事时的清场：摘掉本脚本挂过的一切，删 merged/upper/work
#   sh action.sh web        老行为：切换「网页自带字体」压 / 放行
#
# 为什么会失败、失败了怎么办：见 README「热切换」一节。
command -v ui_print >/dev/null 2>&1 || ui_print() { echo "$1"; }
MODDIR=${0%/*}; [ "$MODDIR" = "$0" ] && MODDIR=.

case ${1:-toggle} in
    status)
        ui_print "Selffont: 字体热切换状态 $(sh "$MODDIR/hotswap.sh" status)"
        ;;
    verify)
        out=$(sh "$MODDIR/hotswap.sh" verify 2>&1) || { ui_print "Selffont: $out"; exit 1; }
        ui_print "Selffont: $out"
        ;;
    panic)
        out=$(sh "$MODDIR/hotswap.sh" panic 2>&1)
        rc=$?
        ui_print "Selffont: $out"
        exit $rc
        ;;
    web)
        out=$(sh "$MODDIR/web-fonts.sh" toggle) || { ui_print "Selffont: 切换失败——$out"; exit 1; }
        ui_print "$out"
        ui_print "Selffont: 重启火狐后生效；系统字体与别名字件不受影响。"
        ;;
    *)
        out=$(sh "$MODDIR/hotswap.sh" toggle 2>&1) || {
            ui_print "Selffont: 切换失败——$out"
            ui_print "Selffont: 现在状态 $(sh "$MODDIR/hotswap.sh" status)；细节看 README「热切换」。"
            exit 1
        }
        ui_print "Selffont: $out"
        ui_print "Selffont: 现在状态 $(sh "$MODDIR/hotswap.sh" status)。"
        ui_print "Selffont: 网页字体开关用 sh action.sh web。"
        ;;
esac
