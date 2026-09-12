package com.mfga.xposed

import java.util.function.Supplier

/** Per-thread recursion guard; original nulls and exceptions are not turned into success. */
object ReplacementGuard {
    private val ACTIVE = ThreadLocal<Boolean>()

    @JvmStatic
    fun isActive(): Boolean = java.lang.Boolean.TRUE == ACTIVE.get()

    @JvmStatic
    fun <T> replace(original: T?, factory: Supplier<T>): T? {
        if (original == null || isActive()) return original
        ACTIVE.set(java.lang.Boolean.TRUE)
        return try {
            val replacement = factory.get()
            replacement ?: original
        } finally {
            ACTIVE.remove()
        }
    }
}
