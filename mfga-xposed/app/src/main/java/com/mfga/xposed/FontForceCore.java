package com.mfga.xposed;

import android.graphics.Typeface;

/** Android 16 text-family replacement, not a universal/native rendering hook. */
public final class FontForceCore {
    private FontForceCore() {}

    public static Typeface systemReplacementFor(Typeface original) {
        return ReplacementGuard.replace(original, () ->
                Typeface.create(Typeface.DEFAULT, original.getWeight(), original.isItalic()));
    }
}
