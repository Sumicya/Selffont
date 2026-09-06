package com.mfga.xposed;

import java.util.Locale;

public final class TargetPlatform {
    private TargetPlatform() {}

    public static boolean supports(int api, String brand, String manufacturer) {
        if (api != 36) return false;
        for (String value : new String[] {brand, manufacturer}) {
            if (value == null) continue;
            switch (value.toLowerCase(Locale.ROOT)) {
                case "oplus": case "oppo": case "oneplus": case "realme": return true;
                default: break;
            }
        }
        return false;
    }
}
