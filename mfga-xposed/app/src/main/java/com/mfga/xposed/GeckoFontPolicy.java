package com.mfga.xposed;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/** Pure preference transformation: no profile writes, DOM changes or text normalization. */
public final class GeckoFontPolicy {
    public static final String FAMILY = "WenYuan Rounded SC VF";
    public static final String FONT_PATH = "/system/fonts/Selffont-WenYuanRoundedSCVF.ttf";
    private static final String[] FAMILIES = {
            "serif", "sans-serif", "monospace", "cursive", "fantasy"
    };
    // Gecko language groups, not Android locales. Missing glyphs still use Gecko's fallback.
    private static final String[] LANGUAGES = {
            "x-western", "x-unicode", "zh-CN", "zh-TW", "zh-HK", "ja", "ko", "el",
            "x-cyrillic", "x-central-euro", "x-baltic", "tr", "ar", "he", "th",
            "x-armn", "x-beng", "x-cans", "x-devanagari", "x-ethi", "x-geor",
            "x-gujr", "x-guru", "x-khmr", "x-knda", "x-lao", "x-malayalam",
            "x-orya", "x-sinh", "x-tamil", "x-telu", "x-tibt"
    };

    private GeckoFontPolicy() {}

    public static Map<String, Object> apply(Map<String, Object> original, boolean fontVisible) {
        if (!fontVisible) return original;
        Map<String, Object> prefs = new LinkedHashMap<>(original);
        // GeckoRuntimeSettings.webFontsEnabled uses this same integer preference.
        prefs.put("browser.display.use_document_fonts", 0);
        for (String language : LANGUAGES) {
            for (String family : FAMILIES) {
                prefs.put("font.name." + family + "." + language, FAMILY);
                prefs.put("font.name-list." + family + "." + language, FAMILY);
            }
        }
        // Intentionally do not modify sizes, weight, synthesis, features, CSS or Unicode.
        return Collections.unmodifiableMap(prefs);
    }
}
