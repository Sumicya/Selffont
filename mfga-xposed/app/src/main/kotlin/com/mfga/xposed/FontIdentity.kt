package com.mfga.xposed

/**
 * Single source of truth for the installed primary font family and visibility path.
 *
 * The public build uses the OFL-derived Selffont Maru family. Its five static
 * faces are selected by fonts.xml for Android weights 100..900; the regular face
 * is enough to prove that the family is visible in a Firefox process.
 */
object FontIdentity {
    /** Matches `family` in config/font-source.json. */
    const val FAMILY = "Selffont Maru"

    /** Matches the visibilityFile in config/font-source.json. */
    const val FONT_PATH = "/system/fonts/SelffontMaru-Regular.ttf"

    /** Static face paths emitted by fonts.xml; Android weights use nearest-face mapping. */
    private val FACE_PATHS = mapOf(
        300 to "/system/fonts/SelffontMaru-Light.ttf",
        400 to FONT_PATH,
        500 to "/system/fonts/SelffontMaru-Medium.ttf",
        700 to "/system/fonts/SelffontMaru-Bold.ttf",
        900 to "/system/fonts/SelffontMaru-Black.ttf",
    )

    fun facePathForWeight(weight: Int): String = FACE_PATHS.entries.minWithOrNull(
        compareBy<Map.Entry<Int, String>> { kotlin.math.abs(it.key - weight) }
            .thenByDescending { it.key }
    )!!.value

    /**
     * The verified no-visible-glyph metrics carrier whose nominal line metrics
     * each Selffont Maru face is normalised to. Matches `METRIC_CARRIER` in
     * tools/font_config.py.
     */
    const val CARRIER_PATH = "/system/fonts/Roboto-Regular.ttf"
}
