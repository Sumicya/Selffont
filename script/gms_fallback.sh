#!/system/bin/sh
# Deliberately manual and destructive; never called by installation or service.sh.
[ "${1:-}" = --confirm ] || { echo 'Requires --confirm: stops Chrome/Gmail, disables GMS font components and deletes font caches.' >&2; exit 2; }
command -v pm >/dev/null 2>&1 || { echo 'pm is unavailable.' >&2; exit 1; }
status=0
am force-stop com.android.chrome || status=1
am force-stop com.google.android.gm || status=1
found=0
for profile in /data/user/*; do
    [ -d "$profile" ] || continue
    user=${profile##*/}
    case "$user" in ''|*[!0-9]*) continue ;; esac
    found=1
    for component in update.UpdateSchedulerService provider.FontsProvider; do
        pm disable --user "$user" "com.google.android.gms/com.google.android.gms.fonts.$component" || status=1
    done
    cache="$profile/com.google.android.gms/files/fonts"
    [ ! -d "$cache" ] || rm -rf -- "$cache" || status=1
done
[ "$found" = 1 ] || status=1
if [ -d /data/fonts ]; then
    for entry in /data/fonts/*; do
        [ ! -e "$entry" ] || rm -rf -- "$entry" || status=1
    done
fi
echo "[gms-exit] $status (cache deletion is not reversible; component state persists after uninstall)"
exit "$status"
