# Sourced by KernelSU's installer. Only mutate the installation staging directory.
SKIPUNZIP=0
# Opt-in escape hatch: an advanced user who accepts the risk of an untested
# platform can create this marker to bypass the API/vendor gates. The safe
# default is unchanged; the marker only adds a way through.
OVERRIDE=/data/adb/selffont_allow_unsupported
if [ -e "$OVERRIDE" ]; then
    ui_print "Selffont: override marker present; skipping platform checks (unverified, at your own risk)."
else
    # Platform gates mirror config/platform-support.json (see TargetPlatform.java);
    # tests/test_platform_support.py enforces that all three stay in sync.
    [ "${API:-}" = 36 ] || abort "Selffont requires Android 16 (API 36). Create $OVERRIDE to force-install at your own risk."
    [ "${KSU:-}" = true ] || abort "Selffont requires KernelSU; other managers are not supported."
    oplus=0
    for identity in "$(getprop ro.product.brand)" "$(getprop ro.product.manufacturer)"; do
        case "$(printf '%s' "$identity" | tr '[:upper:]' '[:lower:]')" in
            oplus|oppo|oneplus|realme) oplus=1 ;;
        esac
    done
    [ "$oplus" = 1 ] || abort "Selffont supports Oplus devices only. Create $OVERRIDE to force-install at your own risk."
fi
[ -s "$MODPATH/system/fonts/Selffont-WenYuanRoundedSCVF.ttf" ] || abort "Missing prepared WenYuan font. Use tools/build_module.py."
# The only supported Android version uses the main Emoji font.
rm -f "$MODPATH/system/fonts/NotoColorEmoji-fallback.ttf"
. "$MODPATH/search_dirs.sh" || abort "Font XML installation failed."
ui_print "Selffont: reboot, then cold-start scoped apps. No boot-time app/GMS mutations."
