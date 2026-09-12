package com.mfga.xposed

import com.mfga.xposed.diagnostics.BadgeSamplePolicy
import java.util.concurrent.atomic.AtomicBoolean
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * Host-side (JVM) unit tests for the pure policy classes. This replaces the old
 * tests/run_java.sh + tests/java/PolicyTest.java, folding the same behavioural
 * assertions into the Gradle `test` task so `gradle test` is the single source
 * of policy verification. Only classes with no Android dependency are covered
 * here; Android/Xposed classes are exercised by the APK build.
 */
class PolicyTest {
    @Test
    fun geckoFontPolicyTransformsPrefsSafely() {
        val original: Map<String, Any> = mapOf(
            "browser.display.use_document_fonts" to 1,
            "font.size.variable.x-western" to 19,
            "unrelated" to "retained",
            "font.name-list.sans-serif.x-western" to "Roboto, Noto Sans, Noto Color Emoji",
            "font.name-list.serif.zh-CN" to GeckoFontPolicy.FAMILY + ", Noto Serif CJK SC"
        )
        assertSame(original, GeckoFontPolicy.apply(original, false))
        val changed = GeckoFontPolicy.apply(original, true)
        assertEquals(0, changed["browser.display.use_document_fonts"])
        assertEquals(1, original["browser.display.use_document_fonts"])
        assertEquals(19, changed["font.size.variable.x-western"])
        assertEquals("retained", changed["unrelated"])
        // font.name (preferred) is WenYuan for every generic/language.
        assertEquals(GeckoFontPolicy.FAMILY, changed["font.name.cursive.zh-CN"])
        assertEquals(GeckoFontPolicy.FAMILY, changed["font.name.serif.x-western"])
        // font.name-list keeps the ORIGINAL fallback chain, with WenYuan prepended,
        // so glyphs WenYuan lacks (rare codepoints, colour emoji) still resolve.
        assertEquals(
            GeckoFontPolicy.FAMILY + ", Roboto, Noto Sans, Noto Color Emoji",
            changed["font.name-list.sans-serif.x-western"]
        )
        // Already led by WenYuan: left unchanged, no duplication.
        assertEquals(
            GeckoFontPolicy.FAMILY + ", Noto Serif CJK SC",
            changed["font.name-list.serif.zh-CN"]
        )
        // Where Gecko exposes no list, we must NOT invent a WenYuan-only list.
        assertNull(changed["font.name-list.monospace.ja"])
        // Emoji preferences are untouched so system colour emoji fallback still applies.
        assertTrue(changed.keys.none { it.startsWith("font.name.emoji") || it.startsWith("font.name-list.emoji") })
        assertEquals(changed, GeckoFontPolicy.apply(changed, true))
        try {
            (changed as MutableMap<String, Any>)["oops"] = true
            fail("prefs map must be unmodifiable")
        } catch (expected: UnsupportedOperationException) {
        }
        assertTrue(changed.keys.none { it.contains("synthesis") || it.contains("variant") })
    }

    @Test
    fun prependFamilyPrependsDedupesAndIsIdempotent() {
        assertEquals(GeckoFontPolicy.FAMILY + ", A, B", GeckoFontPolicy.prependFamily("A, B"))
        assertNull(GeckoFontPolicy.prependFamily(GeckoFontPolicy.FAMILY + ", A"))
        assertEquals(
            GeckoFontPolicy.FAMILY + ", A, B",
            GeckoFontPolicy.prependFamily("A, " + GeckoFontPolicy.FAMILY + ", B")
        )
        assertNull(GeckoFontPolicy.prependFamily("   "))
    }

    @Test
    fun replacementGuardBlocksRecursionAndPreservesNullsAndExceptions() {
        assertNull(ReplacementGuard.replace<Any?>(null) { throw AssertionError() })
        assertEquals("original", ReplacementGuard.replace<String?>("original") { null })
        assertEquals("replacement", ReplacementGuard.replace("original") {
            assertTrue(ReplacementGuard.isActive())
            assertEquals("nested", ReplacementGuard.replace("nested") { throw AssertionError() })
            "replacement"
        })
        assertFalse(ReplacementGuard.isActive())
        try {
            ReplacementGuard.replace("original") { throw IllegalStateException("test") }
        } catch (expected: IllegalStateException) {
        }
        assertFalse(ReplacementGuard.isActive())
        val separateThread = AtomicBoolean()
        ReplacementGuard.replace("original") {
            val thread = Thread { separateThread.set(!ReplacementGuard.isActive()) }
            thread.start()
            thread.join()
            "replacement"
        }
        assertTrue(separateThread.get())
    }

    @Test
    fun targetPlatformGatesByApiVendorAndOverride() {
        assertTrue(TargetPlatform.supports(36, "OnePlus", "OPLUS"))
        assertTrue(TargetPlatform.supports(36, "realme", "unknown"))
        assertFalse(TargetPlatform.supports(35, "OnePlus", "OPLUS"))
        assertFalse(TargetPlatform.supports(36, "google", "google"))
        assertFalse(TargetPlatform.supports(36, null, null))
        // allowed(): natively supported platforms attach regardless of the override.
        assertTrue(TargetPlatform.allowed(36, "OnePlus", "OPLUS", false))
        assertTrue(TargetPlatform.allowed(36, "OnePlus", "OPLUS", true))
        // Untested platforms are blocked by default, but the user may force it.
        assertFalse(TargetPlatform.allowed(35, "google", "google", false))
        assertTrue(TargetPlatform.allowed(35, "google", "google", true))
        assertFalse(TargetPlatform.allowed(36, "google", "google", false))
        assertTrue(TargetPlatform.allowed(36, "google", "google", true))
    }

    @Test
    fun badgeSamplePolicySamplesFixedTextAndEnforcesBudget() {
        assertEquals("7", BadgeSamplePolicy.sample("7", 0, 1))
        assertEquals("10", BadgeSamplePolicy.sample(charArrayOf('x', '1', '0', 'y'), 1, 3))
        assertNull(BadgeSamplePolicy.sample("notification content", 0, 20))
        assertNull(BadgeSamplePolicy.sample("99", 0, 2))
        assertNull(BadgeSamplePolicy.sample(null, 0, 1))
        assertNull(BadgeSamplePolicy.sample("10", -1, 1))
        assertNull(BadgeSamplePolicy.sample("10", 0, 3))
        assertNull(BadgeSamplePolicy.sample("", 0, 0))
        val budget = BadgeSamplePolicy(2)
        assertTrue(budget.claim("one"))
        assertFalse(budget.claim("one"))
        assertTrue(budget.claim("two"))
        assertTrue(budget.full())
        assertFalse(budget.claim("three"))
    }
}
