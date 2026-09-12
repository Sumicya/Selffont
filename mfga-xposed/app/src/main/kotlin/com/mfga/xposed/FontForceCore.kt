package com.mfga.xposed

import android.graphics.Typeface

/** Android 16 text-family replacement, not a universal/native rendering hook. */
object FontForceCore {
    @JvmStatic
    fun systemReplacementFor(original: Typeface): Typeface? =
        ReplacementGuard.replace(original) {
            Typeface.create(Typeface.DEFAULT, original.weight, original.isItalic)
        }
}
