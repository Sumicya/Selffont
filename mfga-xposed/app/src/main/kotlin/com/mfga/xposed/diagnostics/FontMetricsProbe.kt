package com.mfga.xposed.diagnostics

import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.fonts.Font
import android.graphics.fonts.FontFamily
import android.graphics.fonts.FontStyle
import android.graphics.text.TextRunShaper
import android.os.Build
import com.mfga.xposed.FontIdentity
import java.io.File
import java.lang.reflect.InvocationTargetException
import java.util.Locale
import kotlin.system.exitProcess

/**
 * Standalone app_process entry point, NOT an Xposed lifecycle callback.
 * Uses fixed sample text and stdout only. It never edits files, settings or other processes.
 */
object FontMetricsProbe {
    private val WENYUAN = FontIdentity.FONT_PATH
    private val CARRIER = FontIdentity.CARRIER_PATH

    @JvmStatic
    fun main(args: Array<String>) {
        println("[probe] selffont-font-metrics-v1")
        println("[context] standalone process; fresh preinstalled font map, not the live SystemUI Paint/cache")
        println("[platform] api=" + Build.VERSION.SDK_INT + " brand=" + Build.BRAND)
        println("[font-readable] wenyuan=" + File(WENYUAN).canRead() + " carrier=" + File(CARRIER).canRead())
        if (Build.VERSION.SDK_INT != 36) {
            println("[probe-error] This probe targets Android 16 / API 36.")
            exitProcess(2)
        }
        try {
            // app_process does not receive ActivityThread's application font-map binding.
            // Initialize this NEW probe process from the mounted XML; never replace a live app map.
            val init = Typeface::class.java.getDeclaredMethod("loadPreinstalledSystemFontMap")
            init.isAccessible = true
            init.invoke(null)
        } catch (error: Throwable) {
            if (error !is ReflectiveOperationException && error !is RuntimeException &&
                error !is LinkageError
            ) throw error
            val cause = if (error is InvocationTargetException) error.cause else error
            println("[probe-init-error] $cause")
            exitProcess(2)
        }

        val cases = LinkedHashMap<String, Typeface>()
        cases["DEFAULT"] = Typeface.DEFAULT
        for (family in arrayOf("sans-serif", "sans-serif-medium", "sans-serif-condensed", "serif")) {
            cases[family] = Typeface.create(family, Typeface.NORMAL)
        }
        try {
            cases["explicit-carrier-wenyuan-500"] = explicit(true, 500)
            cases["direct-wenyuan-500"] = explicit(false, 500)
        } catch (error: Throwable) {
            if (error !is Exception && error !is LinkageError) throw error
            println("[probe-explicit-font-error] $error")
        }

        var failures = 0
        for ((name, face) in cases) {
            for (locale in arrayOf("zh-CN", "en-US")) {
                for (size in floatArrayOf(28f, 1000f)) {
                    val texts = if (size == 28f) arrayOf("10", "7", "已连接") else arrayOf("10")
                    for (text in texts) {
                        try {
                            measure(name, face, locale, size, text)
                        } catch (error: Throwable) {
                            if (error !is RuntimeException && error !is LinkageError) throw error
                            failures++
                            println("[probe-case-error] $name: $error")
                        }
                    }
                }
            }
        }
        println("[probe-done] failed_cases=$failures")
        if (failures != 0) exitProcess(1)
    }

    private fun explicit(withCarrier: Boolean, weight: Int): Typeface {
        val glyphFont = Font.Builder(File(WENYUAN))
            .setWeight(weight).setSlant(FontStyle.FONT_SLANT_UPRIGHT)
            .setFontVariationSettings("'wght' $weight, 'ital' 0")
            .build()
        val glyphFamily = FontFamily.Builder(glyphFont).build()
        val builder: Typeface.CustomFallbackBuilder
        if (withCarrier) {
            val metricFont = Font.Builder(File(CARRIER))
                .setWeight(weight).setSlant(FontStyle.FONT_SLANT_UPRIGHT)
                .setFontVariationSettings("'wght' $weight, 'wdth' 100")
                .build()
            builder = Typeface.CustomFallbackBuilder(FontFamily.Builder(metricFont).build())
                .addCustomFallback(glyphFamily)
        } else {
            builder = Typeface.CustomFallbackBuilder(glyphFamily)
        }
        return builder.setStyle(FontStyle(weight, FontStyle.FONT_SLANT_UPRIGHT))
            .setSystemFallback("sans-serif").build()
    }

    private fun measure(name: String, face: Typeface?, locale: String, size: Float, text: String) {
        if (face == null) throw IllegalStateException("Typeface was not initialized")
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        paint.typeface = face
        paint.textSize = size
        paint.textLocale = Locale.forLanguageTag(locale)
        val fm = paint.fontMetrics
        val fmi = paint.fontMetricsInt
        val bounds = Rect()
        paint.getTextBounds(text, 0, text.length, bounds)
        val run = TextRunShaper.shapeTextRun(text, 0, text.length, 0, text.length, 0f, 0f, false, paint)

        val ink = RectF()
        var hasInk = false
        val fonts = LinkedHashSet<String>()
        for (i in 0 until run.glyphCount()) {
            val font = run.getFont(i)
            fonts.add(describe(font))
            val glyph = RectF()
            font.getGlyphBounds(run.getGlyphId(i), paint, glyph)
            glyph.offset(run.getGlyphX(i), run.getGlyphY(i))
            if (!glyph.isEmpty) {
                if (!hasInk) ink.set(glyph) else ink.union(glyph)
                hasInk = true
            }
        }

        println()
        println("[case] $name locale=$locale px=$size text=$text weight=${face.weight} italic=${face.isItalic}")
        System.out.printf(
            Locale.ROOT,
            "[paint] top=%.3f ascent=%.3f descent=%.3f bottom=%.3f leading=%.3f%n",
            fm.top, fm.ascent, fm.descent, fm.bottom, fm.leading
        )
        println("[paint-int] top=${fmi.top} ascent=${fmi.ascent} descent=${fmi.descent} bottom=${fmi.bottom}")
        println("[text-bounds] " + bounds.toShortString())
        System.out.printf(
            Locale.ROOT, "[run] glyphs=%d advance=%.3f ascent=%.3f descent=%.3f%n",
            run.glyphCount(), run.advance, run.ascent, run.descent
        )
        println("[run-ink] " + if (hasInk) ink.toShortString() else "EMPTY")
        for (font in fonts) println("[resolved-font] $font")
        if (hasInk) {
            // Model a vertically centred badge using the common ascent/descent formula.
            // Positive means visible ink below the box centre. This is not a measurement of a live view.
            val inkCentre = (ink.top + ink.bottom) / 2f
            System.out.printf(
                Locale.ROOT,
                "[centre-model] float=%.3fpx int=%.3fpx run=%.3fpx (positive=down)%n",
                -(fm.ascent + fm.descent) / 2f + inkCentre,
                -(fmi.ascent + fmi.descent) / 2f + inkCentre,
                -(run.ascent + run.descent) / 2f + inkCentre
            )
        }
    }

    private fun describe(font: Font): String {
        val result = StringBuilder()
        val file = font.file
        result.append(file?.path ?: "<memory-font>")
        result.append(" index=").append(font.ttcIndex)
        result.append(" weight=").append(font.style.weight)
        result.append(" slant=").append(font.style.slant)
        result.append(" axes=")
        val axes = font.axes
        if (axes != null) {
            for (axis in axes) {
                result.append(axis.tag).append(':').append(axis.styleValue).append(';')
            }
        }
        return result.toString()
    }
}
