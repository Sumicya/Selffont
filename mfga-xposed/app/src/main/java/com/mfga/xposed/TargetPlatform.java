package com.mfga.xposed;

import java.util.Locale;
import java.util.Set;

public final class TargetPlatform {
    // These values are the single source of truth in config/platform-support.json,
    // inlined here for the on-device runtime. tests/test_platform_support.py fails
    // if they drift; changing support means editing the manifest and both call sites.
    private static final int SUPPORTED_API = 36;
    private static final Set<String> VENDORS = Set.of("oplus", "oppo", "oneplus", "realme");

    /** User opt-in marker: run on an untested platform at the user's own risk. */
    public static final String OVERRIDE_MARKER = "/data/adb/selffont_allow_unsupported";

    private TargetPlatform() {}

    /** Natively verified support: Android 16 on an Oplus-family device. */
    public static boolean supports(int api, String brand, String manufacturer) {
        return api == SUPPORTED_API && (isVendor(brand) || isVendor(manufacturer));
    }

    /**
     * Whether the module should attach. Natively supported platforms always attach;
     * otherwise the user may force it by creating {@link #OVERRIDE_MARKER}. The safe
     * default (block untested platforms) is unchanged; the override only adds a way in.
     */
    public static boolean allowed(int api, String brand, String manufacturer, boolean userOverride) {
        return supports(api, brand, manufacturer) || userOverride;
    }

    private static boolean isVendor(String value) {
        return value != null && VENDORS.contains(value.toLowerCase(Locale.ROOT));
    }
}
