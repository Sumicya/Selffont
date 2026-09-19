#!/system/bin/sh
MODPATH=${0%/*}
echo '[Selffont] Read-only shell diagnostics (not proof of Gecko rendering)'
printf 'Android API: '; getprop ro.build.version.sdk
printf 'Brand: '; getprop ro.product.brand
printf 'Manufacturer: '; getprop ro.product.manufacturer
printf 'Module: '; sed -n 's/^version=/ /p' "$MODPATH/module.prop"
# Installed primary font's filename comes from the generated font.conf (v1.4.1+
# modules); older modules carry no font.conf and are reported as such.
[ -r "$MODPATH/font.conf" ] && . "$MODPATH/font.conf"
FONT=/system/fonts/${SELFFONT_INSTALLED_FONT:-}
if [ -z "$FONT" ]; then
    echo '[shell-font-missing] No font.conf in module (pre-v1.4.1); check the primary font under /system/fonts manually.'
elif [ -r "$FONT" ]; then
    echo '[shell-font-visible] Primary font target is readable in this shell namespace.'
else
    echo '[shell-font-missing] Check installation, reboot and KSU mounting.'
fi
if command -v dumpsys >/dev/null 2>&1; then
    dumpsys package org.mozilla.firefox 2>/dev/null | grep -E 'versionName=|versionCode=' | head -n 2
fi
echo 'LSPosed logs: [attach] -> [hook-installed] -> [typeface-hit] / [gecko-prefs]'
echo 'Firefox has a separate process/mount namespace. [gecko-skip] means its font is not visible.'
echo 'CSS small-caps, weight and italic should remain. Rendering still needs the comparison page.'
