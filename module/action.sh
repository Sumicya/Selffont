#!/system/bin/sh
# KernelSU 管理器的「操作」按钮：点一下切换「网页自带字体」的压 / 放行。
# 只改火狐的配置副本与一个状态文件（/data/local/tmp/selffont-web-fonts.state），
# 不动系统字体；重启火狐后生效。想固定某种状态，就用构建期开关重新打包
# （默认压；--keep-web-fonts 放行）——按钮是运行时覆盖，模块更新不会把它冲掉。
command -v ui_print >/dev/null 2>&1 || ui_print() { echo "$1"; }
MODDIR=${0%/*}; [ "$MODDIR" = "$0" ] && MODDIR=.
out=$(sh "$MODDIR/web-fonts.sh" toggle) || { ui_print "Selffont: 切换失败——$out"; exit 1; }
ui_print "$out"
ui_print "Selffont: 重启火狐后生效；系统字体与别名字件不受影响。"
