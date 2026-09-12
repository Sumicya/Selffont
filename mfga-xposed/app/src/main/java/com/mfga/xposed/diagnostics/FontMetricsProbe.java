package com.mfga.xposed.diagnostics;

import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.graphics.fonts.Font;
import android.graphics.fonts.FontFamily;
import android.graphics.fonts.FontStyle;
import android.graphics.fonts.FontVariationAxis;
import android.graphics.text.PositionedGlyphs;
import android.graphics.text.TextRunShaper;
import android.os.Build;

import java.io.File;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Standalone app_process entry point, NOT an Xposed lifecycle callback.
 * Uses fixed sample text and stdout only. It never edits files, settings or other processes.
 */
public final class FontMetricsProbe {
    private static final String WENYUAN = com.mfga.xposed.FontIdentity.FONT_PATH;
    private static final String CARRIER = com.mfga.xposed.FontIdentity.CARRIER_PATH;

    private FontMetricsProbe() {}

    public static void main(String[] args) {
        System.out.println("[probe] selffont-font-metrics-v1");
        System.out.println("[context] standalone process; fresh preinstalled font map, not the live SystemUI Paint/cache");
        System.out.println("[platform] api=" + Build.VERSION.SDK_INT + " brand=" + Build.BRAND);
        System.out.println("[font-readable] wenyuan=" + new File(WENYUAN).canRead()
                + " carrier=" + new File(CARRIER).canRead());
        if (Build.VERSION.SDK_INT != 36) {
            System.out.println("[probe-error] This probe targets Android 16 / API 36.");
            System.exit(2);
        }
        try {
            // app_process does not receive ActivityThread's application font-map binding.
            // Initialize this NEW probe process from the mounted XML; never replace a live app map.
            Method init = Typeface.class.getDeclaredMethod("loadPreinstalledSystemFontMap");
            init.setAccessible(true);
            init.invoke(null);
        } catch (ReflectiveOperationException | RuntimeException | LinkageError error) {
            Throwable cause = error instanceof InvocationTargetException
                    ? ((InvocationTargetException) error).getCause() : error;
            System.out.println("[probe-init-error] " + cause);
            System.exit(2);
        }

        Map<String, Typeface> cases = new LinkedHashMap<>();
        cases.put("DEFAULT", Typeface.DEFAULT);
        for (String family : new String[]{"sans-serif", "sans-serif-medium", "sans-serif-condensed", "serif"}) {
            cases.put(family, Typeface.create(family, Typeface.NORMAL));
        }
        try {
            cases.put("explicit-carrier-wenyuan-500", explicit(true, 500));
            cases.put("direct-wenyuan-500", explicit(false, 500));
        } catch (Exception | LinkageError error) {
            System.out.println("[probe-explicit-font-error] " + error);
        }

        int failures = 0;
        for (Map.Entry<String, Typeface> item : cases.entrySet()) {
            for (String locale : new String[]{"zh-CN", "en-US"}) {
                for (float size : new float[]{28f, 1000f}) {
                    String[] texts = size == 28f ? new String[]{"10", "7", "已连接"} : new String[]{"10"};
                    for (String text : texts) {
                        try {
                            measure(item.getKey(), item.getValue(), locale, size, text);
                        } catch (RuntimeException | LinkageError error) {
                            failures++;
                            System.out.println("[probe-case-error] " + item.getKey() + ": " + error);
                        }
                    }
                }
            }
        }
        System.out.println("[probe-done] failed_cases=" + failures);
        if (failures != 0) System.exit(1);
    }

    private static Typeface explicit(boolean withCarrier, int weight) throws Exception {
        Font glyphFont = new Font.Builder(new File(WENYUAN))
                .setWeight(weight).setSlant(FontStyle.FONT_SLANT_UPRIGHT)
                .setFontVariationSettings("'wght' " + weight + ", 'ital' 0")
                .build();
        FontFamily glyphFamily = new FontFamily.Builder(glyphFont).build();
        Typeface.CustomFallbackBuilder builder;
        if (withCarrier) {
            Font metricFont = new Font.Builder(new File(CARRIER))
                    .setWeight(weight).setSlant(FontStyle.FONT_SLANT_UPRIGHT)
                    .setFontVariationSettings("'wght' " + weight + ", 'wdth' 100")
                    .build();
            builder = new Typeface.CustomFallbackBuilder(new FontFamily.Builder(metricFont).build())
                    .addCustomFallback(glyphFamily);
        } else {
            builder = new Typeface.CustomFallbackBuilder(glyphFamily);
        }
        return builder.setStyle(new FontStyle(weight, FontStyle.FONT_SLANT_UPRIGHT))
                .setSystemFallback("sans-serif").build();
    }

    private static void measure(String name, Typeface face, String locale, float size, String text) {
        if (face == null) throw new IllegalStateException("Typeface was not initialized");
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        paint.setTypeface(face);
        paint.setTextSize(size);
        paint.setTextLocale(Locale.forLanguageTag(locale));
        Paint.FontMetrics fm = paint.getFontMetrics();
        Paint.FontMetricsInt fmi = paint.getFontMetricsInt();
        Rect bounds = new Rect();
        paint.getTextBounds(text, 0, text.length(), bounds);
        PositionedGlyphs run = TextRunShaper.shapeTextRun(text, 0, text.length(), 0,
                text.length(), 0, 0, false, paint);

        RectF ink = new RectF();
        boolean hasInk = false;
        Set<String> fonts = new LinkedHashSet<>();
        for (int i = 0; i < run.glyphCount(); i++) {
            Font font = run.getFont(i);
            fonts.add(describe(font));
            RectF glyph = new RectF();
            font.getGlyphBounds(run.getGlyphId(i), paint, glyph);
            glyph.offset(run.getGlyphX(i), run.getGlyphY(i));
            if (!glyph.isEmpty()) {
                if (!hasInk) ink.set(glyph); else ink.union(glyph);
                hasInk = true;
            }
        }

        System.out.println();
        System.out.println("[case] " + name + " locale=" + locale + " px=" + size
                + " text=" + text + " weight=" + face.getWeight() + " italic=" + face.isItalic());
        System.out.printf(Locale.ROOT,
                "[paint] top=%.3f ascent=%.3f descent=%.3f bottom=%.3f leading=%.3f%n",
                fm.top, fm.ascent, fm.descent, fm.bottom, fm.leading);
        System.out.println("[paint-int] top=" + fmi.top + " ascent=" + fmi.ascent
                + " descent=" + fmi.descent + " bottom=" + fmi.bottom);
        System.out.println("[text-bounds] " + bounds.toShortString());
        System.out.printf(Locale.ROOT, "[run] glyphs=%d advance=%.3f ascent=%.3f descent=%.3f%n",
                run.glyphCount(), run.getAdvance(), run.getAscent(), run.getDescent());
        System.out.println("[run-ink] " + (hasInk ? ink.toShortString() : "EMPTY"));
        for (String font : fonts) System.out.println("[resolved-font] " + font);
        if (hasInk) {
            // Model a vertically centred badge using the common ascent/descent formula.
            // Positive means visible ink below the box centre. This is not a measurement of a live view.
            float inkCentre = (ink.top + ink.bottom) / 2f;
            System.out.printf(Locale.ROOT,
                    "[centre-model] float=%.3fpx int=%.3fpx run=%.3fpx (positive=down)%n",
                    -(fm.ascent + fm.descent) / 2f + inkCentre,
                    -(fmi.ascent + fmi.descent) / 2f + inkCentre,
                    -(run.getAscent() + run.getDescent()) / 2f + inkCentre);
        }
    }

    private static String describe(Font font) {
        StringBuilder result = new StringBuilder();
        File file = font.getFile();
        result.append(file == null ? "<memory-font>" : file.getPath());
        result.append(" index=").append(font.getTtcIndex());
        result.append(" weight=").append(font.getStyle().getWeight());
        result.append(" slant=").append(font.getStyle().getSlant());
        result.append(" axes=");
        FontVariationAxis[] axes = font.getAxes();
        if (axes != null) {
            for (FontVariationAxis axis : axes) {
                result.append(axis.getTag()).append(':').append(axis.getStyleValue()).append(';');
            }
        }
        return result.toString();
    }
}
