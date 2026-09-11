package com.mfga.xposed;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Pure preference transformation: no profile writes, DOM changes or text normalization. */
public final class GeckoFontPolicy {
    public static final String FAMILY = FontIdentity.FAMILY;
    public static final String FONT_PATH = FontIdentity.FONT_PATH;
    private static final List<String> FAMILIES = List.of(
            "serif", "sans-serif", "monospace", "cursive", "fantasy");
    // Gecko language groups, not Android locales. Missing glyphs still use Gecko's fallback.
    private static final List<String> LANGUAGES = List.of(
            "x-western", "x-unicode", "zh-CN", "zh-TW", "zh-HK", "ja", "ko", "el",
            "x-cyrillic", "x-central-euro", "x-baltic", "tr", "ar", "he", "th",
            "x-armn", "x-beng", "x-cans", "x-devanagari", "x-ethi", "x-geor",
            "x-gujr", "x-guru", "x-khmr", "x-knda", "x-lao", "x-malayalam",
            "x-orya", "x-sinh", "x-tamil", "x-telu", "x-tibt");

    private GeckoFontPolicy() {}

    public static Map<String, Object> apply(Map<String, Object> original, boolean fontVisible) {
        if (!fontVisible) return original;
        Map<String, Object> prefs = new LinkedHashMap<>(original);
        // GeckoRuntimeSettings.webFontsEnabled uses this same integer preference.
        prefs.put("browser.display.use_document_fonts", 0);
        for (String language : LANGUAGES) {
            for (String family : FAMILIES) {
                String nameKey = "font.name." + family + "." + language;
                String listKey = "font.name-list." + family + "." + language;
                // Prefer WenYuan as the default font for this generic/language.
                prefs.put(nameKey, FAMILY);
                // Prepend WenYuan to the EXISTING fallback list so Gecko keeps every
                // downstream fallback it already had (CJK, symbols, colour emoji, rare
                // codepoints). Never shrink the candidate set: if Gecko exposes no list
                // here, leave its built-in default untouched rather than forcing a
                // WenYuan-only list that would tofu anything WenYuan lacks.
                Object existing = original.get(listKey);
                if (existing instanceof String) {
                    String prepended = prependFamily((String) existing);
                    if (prepended != null) prefs.put(listKey, prepended);
                }
            }
        }
        // Intentionally do not modify sizes, weight, synthesis, features, CSS or Unicode.
        // Emoji preferences are left untouched so system colour emoji fallback still applies.
        return Collections.unmodifiableMap(prefs);
    }

    /** Put WenYuan first while preserving the rest of the list. Null means leave as-is. */
    public static String prependFamily(String list) {
        String trimmed = list.trim();
        if (trimmed.isEmpty()) return null;
        // Already led by WenYuan (idempotent re-application): keep the value unchanged.
        int firstComma = trimmed.indexOf(',');
        String head = (firstComma < 0 ? trimmed : trimmed.substring(0, firstComma)).trim();
        if (head.equals(FAMILY)) return null;
        // Drop any later duplicate of WenYuan so it appears exactly once, at the front.
        StringBuilder rebuilt = new StringBuilder(FAMILY);
        for (String part : trimmed.split(",")) {
            String entry = part.trim();
            if (entry.isEmpty() || entry.equals(FAMILY)) continue;
            rebuilt.append(", ").append(entry);
        }
        return rebuilt.toString();
    }
}
