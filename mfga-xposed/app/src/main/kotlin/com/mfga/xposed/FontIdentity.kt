package com.mfga.xposed

/**
 * Single source of truth for the installed primary font's family name and path.
 *
 * De-hardcoding: the family/path used to be repeated in every class that needed
 * them. Centralising here means swapping the installed font (e.g. a different
 * variable family) only touches one place. The values still match
 * `config/font-source.json` (`family` / `installedFile`); the font packager
 * remains the authority that verifies the file's hash and axes.
 */
object FontIdentity {
    /** Matches `family` in config/font-source.json. */
    const val FAMILY = "WenYuan Rounded SC VF"

    /** Matches `/system/fonts/` + `installedFile` in config/font-source.json. */
    const val FONT_PATH = "/system/fonts/Selffont-WenYuanRoundedSCVF.ttf"

    /**
     * The verified no-visible-glyph metrics carrier whose nominal line metrics
     * WenYuan is normalised to. Matches `METRIC_CARRIER` in tools/font_config.py.
     */
    const val CARRIER_PATH = "/system/fonts/Roboto-Regular.ttf"
}
