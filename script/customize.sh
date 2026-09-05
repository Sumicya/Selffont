# Sourced by KernelSU's installer. Only mutate the installation staging directory.
SKIPUNZIP=0
[ "${API:-}" = 36 ] || abort "Selffont requires Android 16 (API 36)."
[ "${KSU:-}" = true ] || abort "Selffont requires KernelSU; other managers are not supported."
oplus=0
for identity in "$(getprop ro.product.brand)" "$(getprop ro.product.manufacturer)"; do
    case "$(printf '%s' "$identity" | tr '[:upper:]' '[:lower:]')" in
        oplus|oppo|oneplus|realme) oplus=1 ;;
    esac
done
[ "$oplus" = 1 ] || abort "Selffont supports Oplus devices only."
[ -s "$MODPATH/system/fonts/Selffont-WenYuanRoundedSCVF.ttf" ] || abort "Missing prepared WenYuan font. Use tools/build_module.py."
# The only supported Android version uses the main Emoji font.
rm -f "$MODPATH/system/fonts/NotoColorEmoji-fallback.ttf"
. "$MODPATH/search_dirs.sh" || abort "Font XML installation failed."
ui_print "Selffont: reboot, then cold-start scoped apps. No boot-time app/GMS mutations."
