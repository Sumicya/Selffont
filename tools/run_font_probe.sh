#!/system/bin/sh
# Execute only the standalone diagnostic entry point; never install the APK.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run this diagnostic in a root shell.' >&2; exit 2; }
[ "$#" = 1 ] && [ -r "$1" ] || { echo 'Usage: run_font_probe.sh /path/to/probe-container.apk' >&2; exit 2; }
apk=$(realpath "$1")
work=$(mktemp -d /data/local/tmp/selffont-font-probe.XXXXXX)
trap 'rm -f "$work/classes.dex"; rmdir "$work"' EXIT
trap 'exit 1' HUP INT TERM
umask 077
if command -v unzip >/dev/null 2>&1; then
    unzip -p "$apk" classes.dex > "$work/classes.dex"
else
    /data/adb/ksu/bin/busybox unzip -p "$apk" classes.dex > "$work/classes.dex"
fi
# Android's dynamic code loading requires a read-only DEX. Only this temporary copy changes mode.
chmod 0444 "$work/classes.dex"
if command -v timeout >/dev/null 2>&1; then
    CLASSPATH="$work/classes.dex" timeout 60 /system/bin/app_process /system/bin com.mfga.xposed.diagnostics.FontMetricsProbe
else
    CLASSPATH="$work/classes.dex" /data/adb/ksu/bin/busybox timeout 60 /system/bin/app_process /system/bin com.mfga.xposed.diagnostics.FontMetricsProbe
fi
