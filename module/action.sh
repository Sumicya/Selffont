#!/system/bin/sh
# 只读诊断。模块没有其他动作:字体由系统原生加载,无需也无处干预。
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
    if [ -r /system/fonts/Selffont-WenYuanRoundedSCVF.ttf ]; then
        echo '[font-visible] 主字体在本 shell 可读。'
    else
        echo '[font-missing] 主字体不可读:检查安装、重启、KSU 挂载。'
    fi
}

case "${1:-diagnose}" in
    diagnose) diagnose ;;
    *) echo 'Usage: action.sh [diagnose]' >&2; exit 2 ;;
esac
