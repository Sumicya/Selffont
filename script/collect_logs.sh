#!/system/bin/sh
# Read-only collector. The caller chooses where to save stdout.
MODPATH=${0%/*}
LOGDIR=${SELFFONT_LOG_DIR:-/data/adb/lspd/log}
set --
for file in "$LOGDIR"/modules*.log "$LOGDIR"/verbose*.log; do
    [ -f "$file" ] && [ -r "$file" ] && set -- "$@" "$file"
done
[ "$#" -gt 0 ] || { echo '[logs-missing] No readable LSPosed module/verbose files in the expected directory.'; exit 0; }
if command -v awk >/dev/null 2>&1; then
    exec awk -f "$MODPATH/filter_logs.awk" "$@"
elif [ -x /data/adb/ksu/bin/busybox ]; then
    exec /data/adb/ksu/bin/busybox awk -f "$MODPATH/filter_logs.awk" "$@"
fi
echo '[logs-error] awk/KernelSU BusyBox unavailable.' >&2
exit 1
