package com.mfga.xposed.diagnostics

import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.fonts.Font
import android.graphics.fonts.FontFamily
import android.graphics.fonts.SystemFonts
import android.graphics.text.TextRunShaper
import android.util.Log
import java.io.File
import java.util.function.BiConsumer

/**
 * Read-only: ask the real Android font system which installed font (if any) covers the
 * reported Unicode 15/16 emoji, and whether this process can see it. Answers the tofu
 * question with facts instead of guesses. No rendering is changed; no page/profile data
 * is read; only fixed diagnostic codepoints are queried.
 *
 * Dormant: not wired into any package path. The emoji-tofu investigation concluded
 * it is a Gecko backend limitation (see docs/validation.md), so this probe is kept only
 * for future re-diagnosis. Re-enable by calling [run] from a scoped package; it
 * scans every system font, so run it once and off the hot startup path.
 */
object GlyphCoverageProbe {
    // The exact codepoints the user saw as tofu in Firefox (Unicode 15.1/16 emoji).
    private val SAMPLES = intArrayOf(
        0x1F6D9, 0x1FA8B, 0x1FA8C, 0x1FA8D, 0x1FACC, 0x1FADD, 0x1FAEB, 0x1FAF9, 0x1FAFA
    )

    @JvmStatic
    fun run(report: BiConsumer<Int, String>) {
        try {
            // 1) Does the DEFAULT typeface (what Gecko-less framework text uses) cover them?
            val paint = Paint()
            paint.typeface = Typeface.DEFAULT
            val covered = StringBuilder()
            val missing = StringBuilder()
            for (cp in SAMPLES) {
                val s = String(Character.toChars(cp))
                (if (paint.hasGlyph(s)) covered else missing)
                    .append(if (covered.length + missing.length == 0) "" else ",")
                    .append(String.format("U+%X", cp))
            }
            report.accept(Log.INFO, "[glyph-default] hasGlyph covered=[$covered] missing=[$missing]")

            // 2) For each sample, which actual font file does the shaper resolve it to,
            //    and is that file readable from THIS (Firefox) process?
            for (cp in SAMPLES) {
                val s = String(Character.toChars(cp))
                val run = TextRunShaper.shapeTextRun(s, 0, s.length, 0, s.length, 0f, 0f, false, paint)
                var resolved = "<none>"
                var readable = false
                var notdef = true
                if (run.glyphCount() > 0) {
                    // A resolved glyph id of 0 means .notdef => tofu.
                    notdef = run.getGlyphId(0) == 0
                    val font = run.getFont(0)
                    val file = font.file
                    resolved = file?.path ?: "<memory>"
                    readable = file != null && file.canRead()
                }
                report.accept(
                    Log.INFO,
                    String.format(
                        "[glyph-resolve] U+%X -> %s readable=%s notdef=%s glyphs=%d",
                        cp, resolved, readable, notdef, run.glyphCount()
                    )
                )
            }

            // 3) Enumerate installed system fonts that actually cover the first sample,
            //    so we can see whether a covering font exists at all and where it lives.
            val coveringFiles = LinkedHashSet<String>()
            var total = 0
            for (font in SystemFonts.getAvailableFonts()) {
                total++
                val fp = Paint()
                val file = font.file ?: continue
                // Build a typeface from this specific font file to test coverage directly.
                try {
                    fp.typeface = Typeface.CustomFallbackBuilder(
                        FontFamily.Builder(font).build()
                    ).build()
                } catch (e: Throwable) {
                    when (e) {
                        is RuntimeException, is Error -> continue
                        else -> throw e
                    }
                }
                var any = false
                for (cp in SAMPLES) {
                    if (fp.hasGlyph(String(Character.toChars(cp)))) {
                        any = true
                        break
                    }
                }
                if (any) coveringFiles.add(file.path + if (file.canRead()) "" else " (UNREADABLE)")
            }
            report.accept(
                Log.INFO,
                "[glyph-system] scanned=$total coveringFonts=" +
                    if (coveringFiles.isEmpty()) "[NONE]" else coveringFiles.toString()
            )
        } catch (error: Throwable) {
            when (error) {
                is RuntimeException, is LinkageError -> report.accept(Log.WARN, "[glyph-probe-failed] $error")
                else -> throw error
            }
        }
    }
}
