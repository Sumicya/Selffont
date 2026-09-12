package com.mfga.xposed.diagnostics

/** Fixed diagnostic samples, never arbitrary notification text. */
class BadgeSamplePolicy(private val limit: Int) {
    private val seen = HashSet<String>()

    @Synchronized
    fun full(): Boolean = seen.size >= limit

    @Synchronized
    fun claim(key: String): Boolean = !full() && seen.add(key)

    companion object {
        @JvmStatic
        fun sample(text: Any?, start: Int, end: Int): String? {
            val size = when (text) {
                is CharSequence -> text.length
                is CharArray -> text.size
                else -> -1
            }
            if (start < 0 || end > size || end < start || end - start > 2) return null
            if (end - start == 1 && at(text, start) == '7') return "7"
            if (end - start == 2 && at(text, start) == '1' && at(text, start + 1) == '0') return "10"
            return null
        }

        private fun at(text: Any?, index: Int): Char =
            if (text is CharArray) text[index] else (text as CharSequence)[index]
    }
}
