#!/system/bin/sh
# Restore only changes recorded by this version; do not guess a mode such as 600.
MODPATH=${0%/*}
sh "$MODPATH/app_fonts.sh" restore --confirm
