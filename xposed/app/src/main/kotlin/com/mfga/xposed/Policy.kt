package com.mfga.xposed

import java.util.Collections

/**
 * 纯策略,无 Android 依赖,JVM 可测。
 * 换字体时改 [FAMILY](与 config/sources.json 的 font.family 一致)即可。
 */
object Policy {
    /** 字体的内部家族名(Gecko 首选项按它指名)。 */
    const val FAMILY = "WenYuan Rounded SC VF"

    /** 与 tools/build.py 的 INSTALLED_FILE 一致。 */
    const val FONT_PATH = "/system/fonts/Selffont-primary.ttf"

    private val FAMILIES = listOf("serif", "sans-serif", "monospace", "cursive", "fantasy")

    // Gecko 语言组,不是 Android locale。缺字仍走 Gecko 自身回退。
    private val LANGUAGES = listOf(
        "x-western", "x-unicode", "zh-CN", "zh-TW", "zh-HK", "ja", "ko", "el",
        "x-cyrillic", "x-central-euro", "x-baltic", "tr", "ar", "he", "th",
        "x-armn", "x-beng", "x-cans", "x-devanagari", "x-ethi", "x-geor",
        "x-gujr", "x-guru", "x-khmr", "x-knda", "x-lao", "x-malayalam",
        "x-orya", "x-sinh", "x-tamil", "x-telu", "x-tibt"
    )

    /**
     * 把文渊前置为 Gecko 各 generic/language 的首选;回退链只前置不清空,
     * emoji 首选项不碰——文渊缺的字(彩色 emoji、生僻码位)继续走系统回退。
     */
    @JvmStatic
    fun geckoPrefs(original: Map<String, Any>, fontVisible: Boolean): Map<String, Any> {
        if (!fontVisible) return original
        val prefs = LinkedHashMap(original)
        // GeckoRuntimeSettings.webFontsEnabled 用的是同一个整数首选项。
        prefs["browser.display.use_document_fonts"] = 0
        for (language in LANGUAGES) {
            for (family in FAMILIES) {
                prefs["font.name.$family.$language"] = FAMILY
                val existing = original["font.name-list.$family.$language"]
                if (existing is String) {
                    prependFamily(existing)?.let { prefs["font.name-list.$family.$language"] = it }
                }
            }
        }
        return Collections.unmodifiableMap(prefs)
    }

    /** 文渊放最前,其余原序保留;重复项去重。返回 null 表示保持原值。 */
    @JvmStatic
    fun prependFamily(list: String): String? {
        val trimmed = list.trim()
        if (trimmed.isEmpty()) return null
        val head = trimmed.substringBefore(',').trim()
        if (head == FAMILY) return null
        return listOf(FAMILY, *trimmed.split(',').map { it.trim() }
            .filter { it.isNotEmpty() && it != FAMILY }.toTypedArray())
            .joinToString(", ")
    }
}
