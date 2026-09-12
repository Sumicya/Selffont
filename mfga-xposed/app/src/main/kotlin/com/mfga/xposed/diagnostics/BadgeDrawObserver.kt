package com.mfga.xposed.diagnostics

import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.fonts.Font
import android.graphics.text.TextRunShaper
import android.util.Log
import io.github.libxposed.api.XposedInterface
import java.io.File
import java.lang.reflect.Method
import java.lang.reflect.Modifier
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean
import java.util.function.BiConsumer

/** Read-only, bounded observation of actual SystemUI draw calls. Never changes arguments. */
class BadgeDrawObserver(private val report: BiConsumer<Int, String>) {
    private val samples = BadgeSamplePolicy(12)
    private val active = ThreadLocal<Boolean>()
    private val started = AtomicBoolean()
    private val failed = AtomicBoolean()

    fun install(installer: BiConsumer<Method, XposedInterface.Hooker>) {
        if (!started.compareAndSet(false, true)) return
        var candidates = 0
        for (name in arrayOf(
            "android.graphics.Canvas", "android.graphics.BaseCanvas",
            "android.graphics.RecordingCanvas", "android.graphics.BaseRecordingCanvas"
        )) {
            try {
                val type = Class.forName(name, false, Canvas::class.java.classLoader)
                for (method in type.declaredMethods) {
                    if (Modifier.isStatic(method.modifiers) || method.returnType != Void.TYPE) continue
                    val operation = method.name
                    if (operation != "drawText" && operation != "drawTextRun") continue
                    val params = method.parameterTypes
                    if (params.size < 4 || params[params.size - 1] != Paint::class.java) continue
                    if (params[0] != String::class.java && params[0] != CharSequence::class.java &&
                        params[0] != CharArray::class.java
                    ) continue
                    candidates++
                    installer.accept(method, XposedInterface.Hooker { chain ->
                        if (samples.full() || active.get() == true) return@Hooker chain.proceed()
                        active.set(true)
                        try {
                            try {
                                capture(method, chain.thisObject, chain.args)
                            } catch (error: Throwable) {
                                when (error) {
                                    is RuntimeException, is LinkageError ->
                                        if (failed.compareAndSet(false, true)) {
                                            report.accept(
                                                Log.WARN,
                                                "[badge-observe-failed] drawing unchanged: $error"
                                            )
                                        }
                                    else -> throw error
                                }
                            }
                            // Original drawing and its exceptions always proceed untouched.
                            chain.proceed()
                        } finally {
                            active.remove()
                        }
                    })
                }
            } catch (absent: Throwable) {
                when (absent) {
                    is ClassNotFoundException, is LinkageError -> {
                        // Different Android builds may expose different canvas implementation classes.
                    }
                    else -> throw absent
                }
            }
        }
        report.accept(
            Log.INFO,
            "[badge-observe-ready] read-only; samples=7,10; limit=12; candidate_methods=$candidates"
        )
    }

    private fun capture(method: Method, receiver: Any?, args: List<Any?>) {
        if (receiver !is Canvas) return
        val text = args[0] ?: return
        var start = 0
        val end: Int
        val xIndex: Int
        var rtl = false
        if (args.size == 4 && method.name == "drawText") {
            end = (text as CharSequence).length
            xIndex = 1
        } else if (args.size == 6 && method.name == "drawText") {
            start = args[1] as Int
            val extent = args[2] as Int
            end = if (text is CharArray) start + extent else extent
            xIndex = 3
        } else if (args.size == 9 && method.name == "drawTextRun") {
            start = args[1] as Int
            val extent = args[2] as Int
            end = if (text is CharArray) start + extent else extent
            xIndex = 5
            rtl = args[7] as Boolean
        } else {
            return
        }
        val sample = BadgeSamplePolicy.sample(text, start, end) ?: return
        val original = args[args.size - 1] as Paint?
        // Badge counts are small text. Skip large draws such as the security keypad (~70px)
        // so the bounded sample budget is spent on the notification badge itself.
        if (original == null || original.textSize <= 0 || original.textSize > 48) return
        val caller = callers()
        // The on-screen number keypad also paints "7"/"10"; it is not a badge. Read-only skip.
        if (caller.contains("eyboard")) return
        val face = original.typeface
        val key = caller + '|' + sample + '|' + original.textSize + '|' +
            (face?.hashCode() ?: 0)
        if (!samples.claim(key)) return

        // Measuring a copy cannot change the Paint supplied to the original draw call.
        val paint = Paint(original)
        val x = args[xIndex] as Float
        val y = args[xIndex + 1] as Float
        val clip = Rect()
        receiver.getClipBounds(clip)
        val fm = paint.fontMetrics
        val fmi = paint.fontMetricsInt
        val textBounds = Rect()
        paint.getTextBounds(sample, 0, sample.length, textBounds)
        val run = TextRunShaper.shapeTextRun(sample, 0, sample.length, 0, sample.length, 0f, 0f, rtl, paint)
        val ink = RectF()
        var hasInk = false
        val fonts = LinkedHashSet<String>()
        for (i in 0 until run.glyphCount()) {
            val font = run.getFont(i)
            val file = font.file
            val identity = StringBuilder(file?.path ?: "<memory-font>")
            identity.append(" weight=").append(font.style.weight)
            val axes = font.axes
            if (axes != null) for (axis in axes) {
                identity.append(' ').append(axis.tag).append('=').append(axis.styleValue)
            }
            fonts.add(identity.toString())
            val bounds = RectF()
            font.getGlyphBounds(run.getGlyphId(i), paint, bounds)
            bounds.offset(run.getGlyphX(i), run.getGlyphY(i))
            if (!bounds.isEmpty) {
                if (hasInk) ink.union(bounds) else ink.set(bounds)
                hasInk = true
            }
        }
        report.accept(
            Log.INFO,
            "[badge-sample] text=$sample px=${paint.textSize}" +
                " x=$x baseline=$y clip=${clip.toShortString()}" +
                " canvas=${receiver.javaClass.name} method=${method.name}"
        )
        report.accept(
            Log.INFO,
            String.format(
                Locale.ROOT,
                "[badge-metrics] float=%s int=%s run=(%.3f,%.3f) textBounds=%s ink=%s typefaceWeight=%s align=%s",
                "${fm.top},${fm.ascent},${fm.descent},${fm.bottom}",
                "${fmi.top},${fmi.ascent},${fmi.descent},${fmi.bottom}",
                run.ascent, run.descent, textBounds.toShortString(),
                if (hasInk) ink.toShortString() else "EMPTY",
                if (face == null) "default" else face.weight, paint.textAlign
            )
        )
        for (font in fonts) report.accept(Log.INFO, "[badge-font] $font")
        report.accept(Log.INFO, "[badge-caller] $caller")
        if (samples.full()) {
            report.accept(Log.INFO, "[badge-observe-limit] sampling stopped; all drawing still unchanged")
        }
    }

    private fun callers(): String {
        val result = StringBuilder()
        var kept = 0
        var appFrames = 0
        for (frame in Thread.currentThread().stackTrace) {
            val name = frame.className
            if (name.startsWith("com.mfga.xposed.") || name.startsWith("io.github.libxposed.") ||
                name.startsWith("org.lsposed.") || name.startsWith("de.robv.android.xposed.") ||
                name.startsWith("java.") || name.startsWith("dalvik.") ||
                name.startsWith("android.graphics.")
            ) continue
            val framework = name.startsWith("android.")
            // Keep the immediate drawing context (first frames), then only non-framework
            // frames up the hierarchy. The badge inherits onDraw from TextView, so its
            // concrete class never shows here; its named SystemUI/Oplus container does.
            if (framework && kept >= 8) continue
            if (!framework) appFrames++
            if (result.isNotEmpty()) result.append(" <- ")
            result.append(name).append('.').append(frame.methodName)
            kept++
            if (appFrames >= 12 || kept >= 40) break
        }
        return result.toString()
    }
}
