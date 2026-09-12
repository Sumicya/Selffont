package com.mfga.xposed

import java.util.Collections

/** Pure preference transformation: no profile writes, DOM changes or text normalization. */
object GeckoFontPolicy {
    @JvmField
    val FAMILY: String = FontIdentity.FAMILY

    @JvmField
    val FONT_PATH: String = FontIdentity.FONT_PATH

    private val FAMILIES = listOf("serif", "sans-serif", "monospace", "cursive", "fantasy")

    // Gecko language groups, not Android locales. Missing glyphs still use Gecko's fallback.
    private val LANGUAGES = listOf(
        "x-western", "x-unicode", "zh-CN", "zh-TW", "zh-HK", "ja", "ko", "el",
        "x-cyrillic", "x-central-euro", "x-baltic", "tr", "ar", "he", "th",
        "x-armn", "x-beng", "x-cans", "x-devanagari", "x-ethi", "x-geor",
        "x-gujr", "x-guru", "x-khmr", "x-knda", "x-lao", "x-malayalam",
        "x-orya", "x-sinh", "x-tamil", "x-telu", "x-tibt"
    )

    @JvmStatic
    @JvmSuppressWildcards
    fun apply(original: Map<String, Any>, fontVisible: Boolean): Map<String, Any> {
        if (!fontVisible) return original
        val prefs = LinkedHashMap(original)
        // GeckoRuntimeSettings.webFontsEnabled uses this same integer preference.
        prefs["browser.display.use_document_fonts"] = 0
        for (language in LANGUAGES) {
            for (family in FAMILIES) {
                val nameKey = "font.name.$family.$language"
                val listKey = "font.name-list.$family.$language"
                // Prefer WenYuan as the default font for this generic/language.
                prefs[nameKey] = FAMILY
                // Prepend WenYuan to the EXISTING fallback list so Gecko keeps every
                // downstream fallback it already had (CJK, symbols, colour emoji, rare
                // codepoints). Never shrink the candidate set: if Gecko exposes no list
                // here, leave its built-in default untouched rather than forcing a
                // WenYuan-only list that would tofu anything WenYuan lacks.
                val existing = original[listKey]
                if (existing is String) {
                    val prepended = prependFamily(existing)
                    if (prepended != null) prefs[listKey] = prepended
                }
            }
        }
        // Intentionally do not modify sizes, weight, synthesis, features, CSS or Unicode.
        // Emoji preferences are left untouched so system colour emoji fallback still applies.
        return Collections.unmodifiableMap(prefs)
    }

    /** Put WenYuan first while preserving the rest of the list. Null means leave as-is. */
    @JvmStatic
    fun prependFamily(list: String): String? {
        val trimmed = list.trim()
        if (trimmed.isEmpty()) return null
        // Already led by WenYuan (idempotent re-application): keep the value unchanged.
        val firstComma = trimmed.indexOf(',')
        val head = (if (firstComma < 0) trimmed else trimmed.substring(0, firstComma)).trim()
        if (head == FAMILY) return null
        // Drop any later duplicate of WenYuan so it appears exactly once, at the front.
        val rebuilt = StringBuilder(FAMILY)
        for (part in trimmed.split(",")) {
            val entry = part.trim()
            if (entry.isEmpty() || entry == FAMILY) continue
            rebuilt.append(", ").append(entry)
        }
        return rebuilt.toString()
    }
}
