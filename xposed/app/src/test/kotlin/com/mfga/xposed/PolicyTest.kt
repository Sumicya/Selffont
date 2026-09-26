package com.mfga.xposed

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/** 纯策略的 JVM 单测;Android/Xposed 类由 APK 构建验证。 */
class PolicyTest {
    @Test
    fun geckoPrefsTransformSafely() {
        val original: Map<String, Any> = mapOf(
            "browser.display.use_document_fonts" to 1,
            "font.size.variable.x-western" to 19,
            "unrelated" to "retained",
            "font.name-list.sans-serif.x-western" to "Roboto, Noto Sans, Noto Color Emoji",
            "font.name-list.serif.zh-CN" to Policy.FAMILY + ", Noto Serif CJK SC"
        )
        assertSame(original, Policy.geckoPrefs(original, false))
        val changed = Policy.geckoPrefs(original, true)
        assertEquals(0, changed["browser.display.use_document_fonts"])
        assertEquals(1, original["browser.display.use_document_fonts"])
        assertEquals(19, changed["font.size.variable.x-western"])
        assertEquals("retained", changed["unrelated"])
        assertEquals(Policy.FAMILY, changed["font.name.cursive.zh-CN"])
        assertEquals(Policy.FAMILY, changed["font.name.serif.x-western"])
        // 回退链只前置不清空;文渊缺字仍能走系统回退。
        assertEquals(
            Policy.FAMILY + ", Roboto, Noto Sans, Noto Color Emoji",
            changed["font.name-list.sans-serif.x-western"]
        )
        // 已在首位:不变,不重复。
        assertEquals(Policy.FAMILY + ", Noto Serif CJK SC", changed["font.name-list.serif.zh-CN"])
        // Gecko 没给 list 就不造窄列表。
        assertNull(changed["font.name-list.monospace.ja"])
        // emoji 首选项不碰。
        assertTrue(changed.keys.none { it.startsWith("font.name.emoji") || it.startsWith("font.name-list.emoji") })
        assertEquals(changed, Policy.geckoPrefs(changed, true))
        try {
            (changed as MutableMap<String, Any>)["oops"] = true
            fail("prefs map must be unmodifiable")
        } catch (expected: UnsupportedOperationException) {
        }
        assertTrue(changed.keys.none { it.contains("synthesis") || it.contains("variant") })
    }

    @Test
    fun prependFamilyPrependsDedupesAndIsIdempotent() {
        assertEquals(Policy.FAMILY + ", A, B", Policy.prependFamily("A, B"))
        assertNull(Policy.prependFamily(Policy.FAMILY + ", A"))
        assertEquals(Policy.FAMILY + ", A, B", Policy.prependFamily("A, " + Policy.FAMILY + ", B"))
        assertNull(Policy.prependFamily("   "))
    }
}
