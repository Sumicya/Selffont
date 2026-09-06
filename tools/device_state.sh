#!/system/bin/sh
# Read-only Android state snapshot. Stdout is the only output; no settings changes.
MOD=${SELFFONT_MODULE_ROOT:-/data/adb/modules/MFGA}
SYS=${SELFFONT_SYSTEM_ROOT:-/system}
PROC=${SELFFONT_PROC_ROOT:-/proc}
TARGET=Selffont-WenYuanRoundedSCVF.ttf

file_info() {
    if [ -r "$1" ]; then
        stat -c 'mode=%a uid=%u gid=%g bytes=%s file=%n' "$1"
        sha256sum "$1"
    else
        printf '[unreadable-or-missing] %s\n' "$1"
    fi
}

echo '=== Capture time / uptime ==='
date
[ ! -r "$PROC/uptime" ] || cat "$PROC/uptime"
echo '=== Installed font module ==='
if [ -r "$MOD/module.prop" ]; then
    grep -E '^(id|name|version|versionCode)=' "$MOD/module.prop"
else
    echo '[module-prop-missing]'
fi
for flag in disable remove update; do
    [ ! -e "$MOD/$flag" ] || printf '[module-flag] %s\n' "$flag"
done
echo '=== APK installation state (only the font module APK) ==='
if command -v dumpsys >/dev/null 2>&1; then
    dumpsys package com.mfga.xposed 2>/dev/null |
        grep -E 'versionCode=|versionName=|User [0-9]+:'
fi
echo '=== Firefox process ==='
pids=$(pidof org.mozilla.firefox 2>/dev/null)
if [ -n "$pids" ]; then
    printf 'main_pid=%s\n' "$pids"
else
    echo '[firefox-main-not-running]'
fi

echo '=== Font bytes: module storage versus root shell view ==='
for name in "$TARGET" Roboto-Regular.ttf; do
    file_info "$MOD/system/fonts/$name"
    file_info "$SYS/fonts/$name"
done
echo '=== Firefox filesystem view (read as root, not proof of app-UID access) ==='
for pid in $pids; do
    case "$pid" in ''|*[!0-9]*) continue ;; esac
    file_info "$PROC/$pid/root/system/fonts/$TARGET"
done

echo '=== Generated configuration ==='
file_info "$MOD/fonts.xml"
echo '=== Active system font configurations ==='
for dir in "$SYS/etc" "$SYS/product/etc" "$SYS/system_ext/etc"; do
    for file in "$dir"/font*.xml; do
        [ -f "$file" ] && [ -r "$file" ] || continue
        case "${file##*/}" in fonts_customization.xml) continue ;; esac
        file_info "$file"
        # Public font names / ordering only, not application or framework databases.
        grep -n -m 24 -E '<family|Roboto-Regular[.]ttf|Selffont-WenYuanRoundedSCVF[.]ttf' "$file"
    done
done

echo '=== Build metrics report (no unbundled-font list) ==='
if [ -r "$MOD/module-report.json" ]; then
    sed -n '1,/"baseArchiveSha256"/p' "$MOD/module-report.json"
fi
echo '=== Current own-module log summary ==='
# This does not list scopes or read the LSPosed configuration database.
if [ -r "$MOD/collect_logs.sh" ]; then
    sh "$MOD/collect_logs.sh"
else
    echo '[collector-missing]'
fi
