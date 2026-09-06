#!/system/bin/sh
# Android mksh / KernelSU BusyBox ash. No execution at boot.
# SELFFONT_DATA_ROOT / SELFFONT_STATE_DIR allow isolated filesystem tests.
operation=${1:-}
[ "${2:-}" = --confirm ] || { echo 'Requires block|restore --confirm.' >&2; exit 2; }
case "$operation" in block|restore) ;; *) exit 2 ;; esac
DATA_ROOT=${SELFFONT_DATA_ROOT:-/data/user/0}
STATE=${SELFFONT_STATE_DIR:-/data/adb/selffont}
[ ! -L "$STATE" ] || exit 1
umask 077
mkdir -p "$STATE" || exit 1
# Kernel-managed advisory lock: released on exit/crash; no stale PID/directory lock.
command -v flock >/dev/null 2>&1 || { echo 'flock is unavailable; no app permissions changed.' >&2; exit 1; }
[ ! -L "$STATE/app-fonts.lock" ] || exit 1
exec 9>>"$STATE/app-fonts.lock" || exit 1
flock -n 9 || { echo 'Another permission operation is running.' >&2; exit 1; }
trap 'rm -f "$STATE/scan.tmp" "$STATE/remaining.tmp" "$STATE/rewrite.tmp"' EXIT
trap 'exit 1' HUP INT TERM
JOURNAL="$STATE/app-permissions.tsv"
[ ! -L "$JOURNAL" ] || exit 1
[ ! -e "$JOURNAL" ] || [ -f "$JOURNAL" ] || { echo "Invalid permission journal type." >&2; exit 1; }
status=0
tab=$(printf '\t')
newline='
'
allowed() {
    case "$1" in *"$tab"*|*"$newline"*) return 1 ;; esac
    case "$1" in *'/../'*|*'/./'*) return 1 ;; esac
    case "$1" in
        "$DATA_ROOT/com.dragon.read/files/font/"*|"$DATA_ROOT/com.qidian.QDReader/files/truetype_fonts/"*) return 0 ;;
    esac
    return 1
}
safe_file() {
    [ ! -L "$1" ] || return 1
    local package relative app_root resolved
    case "$1" in
        "$DATA_ROOT/com.dragon.read/"*) package=com.dragon.read; relative=files/font ;;
        "$DATA_ROOT/com.qidian.QDReader/"*) package=com.qidian.QDReader; relative=files/truetype_fonts ;;
        *) return 1 ;;
    esac
    app_root=$(realpath "$DATA_ROOT/$package") || return 1
    resolved=$(realpath "$1") || return 1
    case "$resolved" in "$app_root/$relative/"*) return 0 ;; esac
    return 1
}
if [ "$operation" = block ]; then
    touch "$JOURNAL" || exit 1
    : > "$STATE/scan.tmp" || exit 1
    for dir in "$DATA_ROOT/com.dragon.read/files/font" "$DATA_ROOT/com.qidian.QDReader/files/truetype_fonts"; do
        [ -d "$dir" ] || continue
        find "$dir" -type f \( -iname '*.ttf' -o -iname '*.otf' -o -iname '*.ttc' \) -print0 >> "$STATE/scan.tmp" || status=1
    done
    while IFS= read -r -d '' file; do
        allowed "$file" && safe_file "$file" || { status=1; continue; }
        mode=$(stat -c %a "$file") || { status=1; continue; }
        [ "$mode" != 0 ] || continue
        identity=$(stat -c '%d:%i' "$file") || { status=1; continue; }
        # A nonzero mode means a fresh operation (possibly on a replaced file).
        # Retire an older record for this path before recording the current mode.
        : > "$STATE/rewrite.tmp" || { status=1; continue; }
        record_error=0
        while IFS="$tab" read -r old_mode old_identity old_file; do
            [ "$old_file" = "$file" ] || printf '%s\t%s\t%s\n' "$old_mode" "$old_identity" "$old_file" >> "$STATE/rewrite.tmp" || record_error=1
        done < "$JOURNAL"
        [ "$record_error" = 0 ] || { status=1; continue; }
        printf '%s\t%s\t%s\n' "$mode" "$identity" "$file" >> "$STATE/rewrite.tmp" || { status=1; continue; }
        mv "$STATE/rewrite.tmp" "$JOURNAL" || { status=1; continue; }
        chmod 000 "$file" || status=1
    done < "$STATE/scan.tmp"
else
    [ -f "$JOURNAL" ] || { echo '[app-fonts] No recorded permissions to restore.'; exit 0; }
    : > "$STATE/remaining.tmp" || exit 1
    journal_error=0
    retain() { printf '%s\t%s\t%s\n' "$mode" "$identity" "$file" >> "$STATE/remaining.tmp" || journal_error=1; }
    while IFS="$tab" read -r mode identity file; do
        allowed "$file" || { echo '[restore-refused] invalid journal path' >&2; status=1; retain; continue; }
        case "$mode" in ''|*[!0-7]*) status=1; retain; continue ;; esac
        [ "${#mode}" -le 4 ] || { status=1; retain; continue; }
        [ -f "$file" ] || continue
        safe_file "$file" || { status=1; retain; continue; }
        current=$(stat -c '%d:%i' "$file") || { retain; status=1; continue; }
        # Do not alter a newly replaced file or undo a later permission change by the app/user.
        [ "$current" = "$identity" ] || continue
        current_mode=$(stat -c %a "$file") || { status=1; retain; continue; }
        [ "$current_mode" = 0 ] || continue
        if ! chmod "$mode" "$file"; then
            retain
            status=1
        fi
    done < "$JOURNAL"
    [ "$journal_error" = 0 ] && mv "$STATE/remaining.tmp" "$JOURNAL" || status=1
fi
echo "[app-fonts-$operation] exit=$status; restart the affected app manually."
exit "$status"
