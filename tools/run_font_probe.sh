#!/system/bin/sh
# Run the diagnostic from the WHOLE APK so secondary DEX definitions stay reachable.
# This never installs the APK or changes system font configuration.
set -eu
printf '[launcher] font-probe-v2; whole-APK classpath\n'
[ "$(id -u)" = 0 ] || { echo '[launcher-error] Root shell required.' >&2; exit 2; }
[ "$#" = 1 ] && [ -r "$1" ] || { echo 'Usage: run_font_probe.sh /path/to/probe-container.apk' >&2; exit 2; }
apk=$(realpath "$1")
umask 077
work=$(mktemp -d /data/local/tmp/selffont-font-probe.XXXXXX)
trap 'rm -f "$work/container.apk"; rmdir "$work"' EXIT
trap 'exit 1' HUP INT TERM

printf '[launcher] Copying complete container; no single-DEX extraction\n'
cp "$apk" "$work/container.apk"
chmod 0444 "$work/container.apk"
printf '[launcher-container] '
sha256sum "$work/container.apk"
printf '[launcher] class=com.mfga.xposed.diagnostics.FontMetricsProbe\n'
printf '[launcher] temporary classpath=%s\n' "$work/container.apk"

# Avoid Termux-specific library interposition in this system runtime process.
# Both the VM option and environment carry the same explicit, complete classpath.
unset LD_PRELOAD LD_LIBRARY_PATH
export PATH=/system/bin:/system/xbin
export CLASSPATH="$work/container.apk"
status=0
if [ -x /system/bin/timeout ]; then
    /system/bin/timeout 60 /system/bin/app_process \
        "-Djava.class.path=$CLASSPATH" /system/bin --nice-name=selffont-probe \
        com.mfga.xposed.diagnostics.FontMetricsProbe || status=$?
else
    /data/adb/ksu/bin/busybox timeout 60 /system/bin/app_process \
        "-Djava.class.path=$CLASSPATH" /system/bin --nice-name=selffont-probe \
        com.mfga.xposed.diagnostics.FontMetricsProbe || status=$?
fi
printf '[launcher-exit] %s\n' "$status"
exit "$status"
