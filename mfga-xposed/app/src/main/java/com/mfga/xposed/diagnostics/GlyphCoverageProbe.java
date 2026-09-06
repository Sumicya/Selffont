package com.mfga.xposed.diagnostics;

import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.fonts.Font;
import android.graphics.fonts.SystemFonts;
import android.graphics.text.PositionedGlyphs;
import android.graphics.text.TextRunShaper;
import android.util.Log;

import java.io.File;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.function.BiConsumer;

/**
 * Read-only: ask the real Android font system which installed font (if any) covers the
 * reported Unicode 15/16 emoji, and whether this process can see it. Answers the tofu
 * question with facts instead of guesses. No rendering is changed; no page/profile data
 * is read; only fixed diagnostic codepoints are queried.
 *
 * <p>Dormant: not wired into any package path. The emoji-tofu investigation concluded
 * it is a Gecko backend limitation (see docs/validation.md), so this probe is kept only
 * for future re-diagnosis. Re-enable by calling {@link #run} from a scoped package; it
 * scans every system font, so run it once and off the hot startup path.
 */
public final class GlyphCoverageProbe {
    // The exact codepoints the user saw as tofu in Firefox (Unicode 15.1/16 emoji).
    private static final int[] SAMPLES = {
            0x1F6D9, 0x1FA8B, 0x1FA8C, 0x1FA8D, 0x1FACC, 0x1FADD, 0x1FAEB, 0x1FAF9, 0x1FAFA
    };

    private GlyphCoverageProbe() {}

    public static void run(BiConsumer<Integer, String> report) {
        try {
            // 1) Does the DEFAULT typeface (what Gecko-less framework text uses) cover them?
            Paint paint = new Paint();
            paint.setTypeface(Typeface.DEFAULT);
            StringBuilder covered = new StringBuilder();
            StringBuilder missing = new StringBuilder();
            for (int cp : SAMPLES) {
                String s = new String(Character.toChars(cp));
                (paint.hasGlyph(s) ? covered : missing)
                        .append(covered.length() + missing.length() == 0 ? "" : ",")
                        .append(String.format("U+%X", cp));
            }
            report.accept(Log.INFO, "[glyph-default] hasGlyph covered=[" + covered
                    + "] missing=[" + missing + "]");

            // 2) For each sample, which actual font file does the shaper resolve it to,
            //    and is that file readable from THIS (Firefox) process?
            for (int cp : SAMPLES) {
                String s = new String(Character.toChars(cp));
                PositionedGlyphs run = TextRunShaper.shapeTextRun(
                        s, 0, s.length(), 0, s.length(), 0, 0, false, paint);
                String resolved = "<none>";
                boolean readable = false;
                boolean notdef = true;
                if (run.glyphCount() > 0) {
                    // A resolved glyph id of 0 means .notdef => tofu.
                    notdef = run.getGlyphId(0) == 0;
                    Font font = run.getFont(0);
                    File file = font.getFile();
                    resolved = file == null ? "<memory>" : file.getPath();
                    readable = file != null && file.canRead();
                }
                report.accept(Log.INFO, String.format("[glyph-resolve] U+%X -> %s readable=%s notdef=%s glyphs=%d",
                        cp, resolved, readable, notdef, run.glyphCount()));
            }

            // 3) Enumerate installed system fonts that actually cover the first sample,
            //    so we can see whether a covering font exists at all and where it lives.
            Set<String> coveringFiles = new LinkedHashSet<>();
            int total = 0;
            for (Font font : SystemFonts.getAvailableFonts()) {
                total++;
                Paint fp = new Paint();
                File file = font.getFile();
                if (file == null) continue;
                // Build a typeface from this specific font file to test coverage directly.
                try {
                    fp.setTypeface(new Typeface.CustomFallbackBuilder(
                            new android.graphics.fonts.FontFamily.Builder(font).build()).build());
                } catch (RuntimeException | Error e) {
                    continue;
                }
                boolean any = false;
                for (int cp : SAMPLES) {
                    if (fp.hasGlyph(new String(Character.toChars(cp)))) { any = true; break; }
                }
                if (any) coveringFiles.add(file.getPath() + (file.canRead() ? "" : " (UNREADABLE)"));
            }
            report.accept(Log.INFO, "[glyph-system] scanned=" + total
                    + " coveringFonts=" + (coveringFiles.isEmpty() ? "[NONE]" : coveringFiles));
        } catch (RuntimeException | LinkageError error) {
            report.accept(Log.WARN, "[glyph-probe-failed] " + error);
        }
    }
}
