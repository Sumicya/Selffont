# Sourced by KernelSU's installer. Only mutate the installation staging directory.
SKIPUNZIP=0
# Opt-in escape hatch: an advanced user who accepts the risk of an untested
# platform can create this marker to bypass the API/vendor gates. The safe
# default is unchanged; the marker only adds a way through.
OVERRIDE=/data/adb/selffont_allow_unsupported
if [ -e "$OVERRIDE" ]; then
    ui_print "Selffont: override marker present; skipping platform checks (unverified, at your own risk)."
else
    # Platform gates mirror config/platform-support.json (see TargetPlatform.kt);
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
# The installed face filenames come from the generated font.conf (single source of
# truth, see tools/build_module.py and docs/font-swap.md); never hardcode them here.
[ -r "$MODPATH/font.conf" ] || abort "Missing font.conf. Rebuild the module with tools/build_module.py."
. "$MODPATH/font.conf"
for face in "$SELFFONT_INSTALLED_LIGHT" "$SELFFONT_INSTALLED_REGULAR" \
            "$SELFFONT_INSTALLED_MEDIUM" "$SELFFONT_INSTALLED_BOLD" "$SELFFONT_INSTALLED_BLACK"; do
    [ -n "$face" ] || abort "font.conf is incomplete. Rebuild the module."
    [ -s "$MODPATH/system/fonts/$face" ] || abort "Missing prepared face $face. Run tools/prepare_font.py and tools/build_module.py."
done
# The only supported Android version uses the main Emoji font.
rm -f "$MODPATH/system/fonts/NotoColorEmoji-fallback.ttf"
. "$MODPATH/search_dirs.sh" || abort "Font XML installation failed."
ui_print "Selffont: reboot, then cold-start scoped apps. No boot-time app/GMS mutations."
