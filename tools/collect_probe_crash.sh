#!/system/bin/sh
# Read only text tombstones that name this diagnostic process in their command line.
# Never dump registers, memory, maps, protobuf tombstones, or other apps' reports.
DIR=${SELFFONT_TOMBSTONE_DIR:-/data/tombstones}
matched=0
readable=0
for file in "$DIR"/tombstone_*; do
    case "$file" in *.pb|*.tmp) continue ;; esac
    [ -f "$file" ] && [ -r "$file" ] || continue
    readable=$((readable + 1))
    if ! grep -qE '^Cmdline:.*(com[.]mfga[.]xposed[.]diagnostics[.]FontMetricsProbe|selffont-probe)([[:space:]]|$)' "$file"; then
        continue
    fi
    matched=$((matched + 1))
    printf '\n[probe-tombstone] %s\n' "${file##*/}"
    grep -E '^(Timestamp:|Process uptime:|Cmdline:|pid:|uid:|signal |Abort message:|backtrace:|[[:space:]]*#[0-9]+[[:space:]])' "$file"
done
printf '\n[crash-scan] readable_text=%s matched_probe=%s\n' "$readable" "$matched"
if [ "$matched" = 0 ]; then
    echo '[crash-unavailable] No retained readable text tombstone matched the probe command line.'
    echo 'This does not prove that no abort occurred; do not substitute another app_process report.'
fi
