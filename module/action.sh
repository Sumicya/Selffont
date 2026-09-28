#!/system/bin/sh
# KernelSU 动作按钮:只读诊断——不证明渲染结果,只证明模块装上了、字体文件还在。
MODPATH=${0%/*}
echo '[Selffont] 只读诊断'
if command -v getprop >/dev/null 2>&1; then
    printf 'Android API: '; getprop ro.build.version.sdk
    printf 'Brand: '; getprop ro.product.brand
else
    echo 'Android API: unknown(此环境没有 getprop)'
fi
sed -n 's/^version=/Module: /p' "$MODPATH/module.prop" 2>/dev/null
count=0
for font in "$MODPATH"/system/fonts/*; do
    [ -f "$font" ] && count=$((count + 1))
done
echo "Bundled fonts: $count"
[ -f "$MODPATH/fonts.xml" ] && echo 'fonts.xml: present' || echo 'fonts.xml: MISSING'
if [ -f "$MODPATH/geckoview-config.yaml" ]; then
    echo 'Firefox: firefox.sh 可接入(Gecko 原生配置)'
fi
