package com.mfga.xposed

import java.util.Locale

object TargetPlatform {
    // These values are the single source of truth in config/platform-support.json,
    // inlined here for the on-device runtime. tests/test_platform_support.py fails
    // if they drift; changing support means editing the manifest and both call sites.
    private const val SUPPORTED_API = 36
    private val VENDORS = setOf("oplus", "oppo", "oneplus", "realme")

    /** User opt-in marker: run on an untested platform at the user's own risk. */
    const val OVERRIDE_MARKER = "/data/adb/selffont_allow_unsupported"

    /** Natively verified support: Android 16 on an Oplus-family device. */
    @JvmStatic
    fun supports(api: Int, brand: String?, manufacturer: String?): Boolean =
        api == SUPPORTED_API && (isVendor(brand) || isVendor(manufacturer))

    /**
     * Whether the module should attach. Natively supported platforms always attach;
     * otherwise the user may force it by creating [OVERRIDE_MARKER]. The safe
     * default (block untested platforms) is unchanged; the override only adds a way in.
     */
    @JvmStatic
    fun allowed(api: Int, brand: String?, manufacturer: String?, userOverride: Boolean): Boolean =
        supports(api, brand, manufacturer) || userOverride

    private fun isVendor(value: String?): Boolean =
        value != null && VENDORS.contains(value.lowercase(Locale.ROOT))
}
