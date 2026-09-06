package com.mfga.xposed.diagnostics;

import java.util.HashSet;
import java.util.Set;

/** Fixed diagnostic samples, never arbitrary notification text. */
public final class BadgeSamplePolicy {
    private final Set<String> seen = new HashSet<>();
    private final int limit;

    public BadgeSamplePolicy(int limit) { this.limit = limit; }

    public static String sample(Object text, int start, int end) {
        int size = text instanceof CharSequence ? ((CharSequence) text).length()
                : text instanceof char[] ? ((char[]) text).length : -1;
        if (start < 0 || end > size || end < start || end - start > 2) return null;
        if (end - start == 1 && at(text, start) == '7') return "7";
        if (end - start == 2 && at(text, start) == '1' && at(text, start + 1) == '0') return "10";
        return null;
    }

    private static char at(Object text, int index) {
        return text instanceof char[] ? ((char[]) text)[index] : ((CharSequence) text).charAt(index);
    }

    public synchronized boolean full() { return seen.size() >= limit; }

    public synchronized boolean claim(String key) {
        return !full() && seen.add(key);
    }
}
