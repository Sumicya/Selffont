package com.mfga.xposed.diagnostics;

import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.graphics.fonts.Font;
import android.graphics.fonts.FontVariationAxis;
import android.graphics.text.PositionedGlyphs;
import android.graphics.text.TextRunShaper;
import android.util.Log;

import java.io.File;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.BiConsumer;

import io.github.libxposed.api.XposedInterface;

/** Read-only, bounded observation of actual SystemUI draw calls. Never changes arguments. */
public final class BadgeDrawObserver {
    private final BadgeSamplePolicy samples = new BadgeSamplePolicy(12);
    private final ThreadLocal<Boolean> active = new ThreadLocal<>();
    private final AtomicBoolean started = new AtomicBoolean();
    private final AtomicBoolean failed = new AtomicBoolean();
    private final BiConsumer<Integer, String> report;

    public BadgeDrawObserver(BiConsumer<Integer, String> report) { this.report = report; }

    public void install(BiConsumer<Method, XposedInterface.Hooker> installer) {
        if (!started.compareAndSet(false, true)) return;
        int candidates = 0;
        for (String name : new String[]{"android.graphics.Canvas", "android.graphics.BaseCanvas",
                "android.graphics.RecordingCanvas", "android.graphics.BaseRecordingCanvas"}) {
            try {
                Class<?> type = Class.forName(name, false, Canvas.class.getClassLoader());
                for (Method method : type.getDeclaredMethods()) {
                    if (Modifier.isStatic(method.getModifiers()) || method.getReturnType() != void.class) continue;
                    String operation = method.getName();
                    if (!operation.equals("drawText") && !operation.equals("drawTextRun")) continue;
                    Class<?>[] params = method.getParameterTypes();
                    if (params.length < 4 || params[params.length - 1] != Paint.class) continue;
                    if (params[0] != String.class && params[0] != CharSequence.class && params[0] != char[].class) continue;
                    candidates++;
                    installer.accept(method, chain -> {
                        if (samples.full() || Boolean.TRUE.equals(active.get())) return chain.proceed();
                        active.set(true);
                        try {
                            try {
                                capture(method, chain.getThisObject(), chain.getArgs());
                            } catch (RuntimeException | LinkageError error) {
                                if (failed.compareAndSet(false, true)) {
                                    report.accept(Log.WARN, "[badge-observe-failed] drawing unchanged: " + error);
                                }
                            }
                            // Original drawing and its exceptions always proceed untouched.
                            return chain.proceed();
                        } finally {
                            active.remove();
                        }
                    });
                }
            } catch (ClassNotFoundException | LinkageError absent) {
                // Different Android builds may expose different canvas implementation classes.
            }
        }
        report.accept(Log.INFO, "[badge-observe-ready] read-only; samples=7,10; limit=12; candidate_methods=" + candidates);
    }

    private void capture(Method method, Object receiver, List<Object> args) {
        if (!(receiver instanceof Canvas)) return;
        Object text = args.get(0);
        if (text == null) return;
        int start = 0;
        int end;
        int xIndex;
        boolean rtl = false;
        if (args.size() == 4 && method.getName().equals("drawText")) {
            end = ((CharSequence) text).length();
            xIndex = 1;
        } else if (args.size() == 6 && method.getName().equals("drawText")) {
            start = (Integer) args.get(1);
            int extent = (Integer) args.get(2);
            end = text instanceof char[] ? start + extent : extent;
            xIndex = 3;
        } else if (args.size() == 9 && method.getName().equals("drawTextRun")) {
            start = (Integer) args.get(1);
            int extent = (Integer) args.get(2);
            end = text instanceof char[] ? start + extent : extent;
            xIndex = 5;
            rtl = (Boolean) args.get(7);
        } else {
            return;
        }
        String sample = BadgeSamplePolicy.sample(text, start, end);
        if (sample == null) return;
        Paint original = (Paint) args.get(args.size() - 1);
        if (original == null || original.getTextSize() <= 0 || original.getTextSize() > 96) return;
        String caller = callers();
        Typeface face = original.getTypeface();
        String key = caller + '|' + sample + '|' + original.getTextSize() + '|'
                + (face == null ? 0 : face.hashCode());
        if (!samples.claim(key)) return;

        // Measuring a copy cannot change the Paint supplied to the original draw call.
        Paint paint = new Paint(original);
        float x = (Float) args.get(xIndex);
        float y = (Float) args.get(xIndex + 1);
        Rect clip = new Rect();
        ((Canvas) receiver).getClipBounds(clip);
        Paint.FontMetrics fm = paint.getFontMetrics();
        Paint.FontMetricsInt fmi = paint.getFontMetricsInt();
        Rect textBounds = new Rect();
        paint.getTextBounds(sample, 0, sample.length(), textBounds);
        PositionedGlyphs run = TextRunShaper.shapeTextRun(sample, 0, sample.length(), 0,
                sample.length(), 0, 0, rtl, paint);
        RectF ink = new RectF();
        boolean hasInk = false;
        Set<String> fonts = new LinkedHashSet<>();
        for (int i = 0; i < run.glyphCount(); i++) {
            Font font = run.getFont(i);
            File file = font.getFile();
            StringBuilder identity = new StringBuilder(file == null ? "<memory-font>" : file.getPath());
            identity.append(" weight=").append(font.getStyle().getWeight());
            FontVariationAxis[] axes = font.getAxes();
            if (axes != null) for (FontVariationAxis axis : axes) {
                identity.append(' ').append(axis.getTag()).append('=').append(axis.getStyleValue());
            }
            fonts.add(identity.toString());
            RectF bounds = new RectF();
            font.getGlyphBounds(run.getGlyphId(i), paint, bounds);
            bounds.offset(run.getGlyphX(i), run.getGlyphY(i));
            if (!bounds.isEmpty()) {
                if (hasInk) ink.union(bounds); else ink.set(bounds);
                hasInk = true;
            }
        }
        report.accept(Log.INFO, "[badge-sample] text=" + sample + " px=" + paint.getTextSize()
                + " x=" + x + " baseline=" + y + " clip=" + clip.toShortString()
                + " canvas=" + receiver.getClass().getName() + " method=" + method.getName());
        report.accept(Log.INFO, String.format(Locale.ROOT,
                "[badge-metrics] float=%s int=%s run=(%.3f,%.3f) textBounds=%s ink=%s typefaceWeight=%s align=%s",
                fm.top + "," + fm.ascent + "," + fm.descent + "," + fm.bottom,
                fmi.top + "," + fmi.ascent + "," + fmi.descent + "," + fmi.bottom,
                run.getAscent(), run.getDescent(), textBounds.toShortString(),
                hasInk ? ink.toShortString() : "EMPTY", face == null ? "default" : face.getWeight(), paint.getTextAlign()));
        for (String font : fonts) report.accept(Log.INFO, "[badge-font] " + font);
        report.accept(Log.INFO, "[badge-caller] " + caller);
        if (samples.full()) report.accept(Log.INFO, "[badge-observe-limit] sampling stopped; all drawing still unchanged");
    }

    private static String callers() {
        StringBuilder result = new StringBuilder();
        int count = 0;
        for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
            String name = frame.getClassName();
            if (name.startsWith("com.mfga.xposed.") || name.startsWith("io.github.libxposed.")
                    || name.startsWith("org.lsposed.") || name.startsWith("de.robv.android.xposed.")
                    || name.startsWith("java.") || name.startsWith("android.graphics.")) continue;
            if (result.length() != 0) result.append(" <- ");
            result.append(name).append('.').append(frame.getMethodName());
            if (++count == 10) break;
        }
        return result.toString();
    }
}
