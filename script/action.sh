#!/system/bin/sh
MODPATH=${0%/*}
case "${1:-diagnose}" in
    logs) exec sh "$MODPATH/collect_logs.sh" ;;
    diagnose) exec sh "$MODPATH/diagnose.sh" ;;
    gms) shift; exec sh "$MODPATH/gms_fallback.sh" "$@" ;;
    app-fonts) shift; exec sh "$MODPATH/app_fonts.sh" "$@" ;;
    *) echo 'Usage: action.sh [diagnose | logs | gms --confirm | app-fonts block|restore --confirm]' >&2; exit 2 ;;
esac
