#!/system/bin/sh
# 只读诊断 + 日志过滤。模块没有其他动作:字体由系统原生加载,无需也无处干预。
MODPATH=${0%/*}

diagnose() {
    echo '[Selffont] 只读诊断(不证明任何渲染结果,只证明安装与可见性)'
    if command -v getprop >/dev/null 2>&1; then
        printf 'Android API: '; getprop ro.build.version.sdk
        printf 'Brand: '; getprop ro.product.brand
    else
        echo 'Android API: unknown (no getprop in this environment)'
    fi
    sed -n 's/^version=/Module: /p' "$MODPATH/module.prop" 2>/dev/null
    if [ -r /system/fonts/Selffont-ChillRoundF.ttf ]; then
        echo '[font-visible] 主字体在本 shell 可读。'
    else
        echo '[font-missing] 主字体不可读:检查安装、重启、KSU 挂载。'
    fi
    echo 'LSPosed 日志标记:[attach] → [hook-installed] → [typeface-hit] / [gecko-prefs]'
}

logs() {
    # ponytail: grep 全文匹配 "Selffont" 的天花板是其他模块日志提到这个词会误收;
    # 升级:需要精确时再解析 LSPosed 的 [origin] 日志格式。
    logdir=${SELFFONT_LOG_DIR:-/data/adb/lspd/log}
    found=0
    for file in "$logdir"/modules*.log "$logdir"/verbose*.log; do
        [ -f "$file" ] && [ -r "$file" ] || continue
        grep -a 'Selffont' "$file" && found=1
    done
    [ "$found" = 1 ] || echo '[logs-missing] 没有可读的 Selffont 日志记录。'
}

case "${1:-diagnose}" in
    diagnose) diagnose ;;
    logs) logs ;;
    *) echo 'Usage: action.sh [diagnose | logs]' >&2; exit 2 ;;
esac
