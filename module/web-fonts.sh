#!/system/bin/sh
# 网页字体开关（运行时）：keep = 放行网页自带字体，block = 压成文渊（默认）。
#
# 状态存在配置副本旁边（FIREFOX_DATA_DIR，默认 /data/local/tmp），所以模块更新时
# customize.sh / firefox.sh 重新生成副本会按状态来，不会把你的选择覆盖掉。
# 同一条规则两侧通用：模板里那一行生效 = 压，加标记注释掉 = 放行。
#
# 用法：sh web-fonts.sh [status|keep|block|toggle|refresh]
#   status   打印当前状态（状态文件 → 配置副本 → 模板，逐级回退）
#   keep     放行网页自带字体（图标字体可用）
#   block    压掉网页自带字体（全系统同一副面孔）
#   toggle   在两者间切换（action.sh / 管理器按钮用的就是它）
#   refresh  按状态从模块模板重生成配置副本（安装、更新、接入时用）
set -u
DIR=${FIREFOX_DATA_DIR:-/data/local/tmp}
PKG=${FIREFOX_PACKAGE:-org.mozilla.firefox}
STATE=$DIR/selffont-web-fonts.state
CONFIG=$DIR/$PKG-geckoview-config.yaml
MODPATH=${0%/*}; [ "$MODPATH" = "$0" ] && MODPATH=.
TEMPLATE=$MODPATH/geckoview-config.yaml
ACTIVE='browser.display.use_document_fonts: 0'
KEPT='# Selffont:keep browser.display.use_document_fonts: 0'

# 把配置文本变成目标状态（幂等）：keep 注释掉 pref 行，block 还原成生效行。
switched() {  # $1=keep|block
    case "$1" in
        keep) sed -e "s|^  ${ACTIVE}$|  ${KEPT}|" ;;
        block) sed -e "s|^  ${KEPT}$|  ${ACTIVE}|" ;;
        *) echo "未知状态：$1" >&2; exit 2 ;;
    esac
}

state_of() {  # 从标准输入判断当前状态
    if grep -q "^  ${KEPT}\$"; then echo keep; else echo block; fi
}

ensure_template() {
    [ -r "$TEMPLATE" ] || { echo "读不到 $TEMPLATE" >&2; exit 1; }
    grep -q "^  ${ACTIVE}$" "$TEMPLATE" || grep -q "^  ${KEPT}$" "$TEMPLATE" ||
        { echo "模板里找不到网页字体开关行（$ACTIVE）" >&2; exit 1; }
}

refresh() {  # 按状态（没有状态文件就用模板默认）重生成副本
    ensure_template
    mkdir -p "$DIR" || exit 1
    tmp="$CONFIG.tmp.$$"
    if [ -f "$STATE" ]; then
        switched "$(cat "$STATE")" < "$TEMPLATE" > "$tmp" || exit 1
    else
        cat "$TEMPLATE" > "$tmp" || exit 1
    fi
    mv -f "$tmp" "$CONFIG" || { rm -f "$tmp"; exit 1; }
}

label() { [ "$1" = keep ] && echo '放行' || echo '压成文渊'; }

set_state() {  # $1=keep|block：记状态，已接入就立刻刷新副本
    ensure_template
    printf '%s\n' "$1" > "$STATE" || { echo "写 $STATE 失败" >&2; exit 1; }
    if [ -f "$CONFIG" ]; then
        refresh && echo "Selffont：网页自带字体 = $(label "$1")；已刷新配置，重启火狐后生效。"
    else
        echo "Selffont：网页自带字体 = $(label "$1")；火狐还没接入，接入时生效。"
    fi
}

current() {
    if [ -f "$STATE" ]; then cat "$STATE"
    elif [ -f "$CONFIG" ]; then state_of < "$CONFIG"
    elif [ -r "$TEMPLATE" ]; then state_of < "$TEMPLATE"
    else echo block
    fi
}

case "${1:-status}" in
    status)
        echo "网页自带字体 = $(label "$(current)")"
        if [ -f "$STATE" ]; then echo "状态文件：$STATE"; else echo "状态文件：无（用模板默认）"; fi
        if [ -f "$CONFIG" ]; then echo "火狐配置：$CONFIG"; else echo "火狐配置：未接入"; fi
        ;;
    keep) set_state keep ;;
    block) set_state block ;;
    toggle)
        if [ "$(current)" = keep ]; then set_state block; else set_state keep; fi
        ;;
    refresh) refresh ;;
    *) echo '用法：web-fonts.sh [status|keep|block|toggle|refresh]' >&2; exit 2 ;;
esac
