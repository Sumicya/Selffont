package com.mfga.xposed;

import java.util.function.Supplier;

/** Per-thread recursion guard; original nulls and exceptions are not turned into success. */
public final class ReplacementGuard {
    private static final ThreadLocal<Boolean> ACTIVE = new ThreadLocal<>();

    private ReplacementGuard() {}

    public static boolean isActive() {
        return Boolean.TRUE.equals(ACTIVE.get());
    }

    public static <T> T replace(T original, Supplier<T> factory) {
        if (original == null || isActive()) return original;
        ACTIVE.set(Boolean.TRUE);
        try {
            T replacement = factory.get();
            return replacement != null ? replacement : original;
        } finally {
            ACTIVE.remove();
        }
    }
}
