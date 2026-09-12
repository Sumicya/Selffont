package com.mfga.xposed.modern

import android.graphics.Typeface
import android.os.Build
import android.util.Log
import com.mfga.xposed.FontForceCore
import com.mfga.xposed.GeckoFontPolicy
import com.mfga.xposed.ReplacementGuard
import com.mfga.xposed.TargetPlatform
import com.mfga.xposed.diagnostics.BadgeDrawObserver
import io.github.libxposed.api.XposedInterface
import io.github.libxposed.api.XposedModule
import io.github.libxposed.api.XposedModuleInterface.PackageReadyParam
import java.io.File
import java.lang.reflect.Method
import java.util.concurrent.atomic.AtomicBoolean

/** Scope is owned exclusively by LSPosed. No package-name allowlist. */
class ModernEntry : XposedModule() {
    private val installed = HashSet<Method>()
    private val badges = BadgeDrawObserver { priority, message -> log(priority, TAG, message) }

    override fun onPackageReady(param: PackageReadyParam) {
        val nativelySupported =
            TargetPlatform.supports(Build.VERSION.SDK_INT, Build.BRAND, Build.MANUFACTURER)
        val override = !nativelySupported && File(TargetPlatform.OVERRIDE_MARKER).exists()
        if (!nativelySupported && !override) {
            log(
                Log.WARN, TAG, "[unsupported] requires Android 16 / API 36 and Oplus; " +
                    "create " + TargetPlatform.OVERRIDE_MARKER + " to force-enable at your own risk"
            )
            return
        }
        if (override) {
            log(
                Log.WARN, TAG, "[override] user opted into an untested platform via " +
                    TargetPlatform.OVERRIDE_MARKER + "; behaviour is unverified here"
            )
        }
        log(Log.INFO, TAG, "[attach] phase1 modern-api102 package=" + param.packageName)
        if ("com.android.systemui" == param.packageName) {
            // Manager scope is still required. Never opt SystemUI in automatically.
            // Diagnostic mode must not change the Typeface we are trying to observe.
            log(Log.INFO, TAG, "[badge-diagnostic-only] SystemUI drawing is observed, not replaced")
            badges.install(this::install)
            return
        }
        installTypefaceHooks()
        installGeckoHook(param.classLoader)
    }

    private fun installTypefaceHooks() {
        for (cls in arrayOf(
            Typeface.Builder::class.java, Typeface.CustomFallbackBuilder::class.java, Typeface::class.java
        )) {
            for (method in cls.declaredMethods) {
                val name = method.name
                val wanted = if (cls == Typeface::class.java) {
                    name == "createFromAsset" || name == "createFromFile"
                } else {
                    name == "build" && method.parameterCount == 0
                }
                if (!wanted || method.returnType != Typeface::class.java) continue
                val firstHit = AtomicBoolean()
                val firstFailure = AtomicBoolean()
                install(method, XposedInterface.Hooker { chain ->
                    // Never catch the application's original exception or replace an original null.
                    val result = chain.proceed()
                    if (result !is Typeface || ReplacementGuard.isActive()) return@Hooker result
                    try {
                        val replacement = FontForceCore.systemReplacementFor(result)
                        if (firstHit.compareAndSet(false, true)) {
                            log(Log.INFO, TAG, "[typeface-hit] " + method.toGenericString())
                        }
                        replacement
                    } catch (error: Throwable) {
                        when (error) {
                            is RuntimeException, is LinkageError -> {
                                if (firstFailure.compareAndSet(false, true)) {
                                    log(Log.WARN, TAG, "[replacement-failed] preserving original: $error")
                                }
                                result
                            }
                            else -> throw error
                        }
                    }
                })
            }
        }
    }

    private fun installGeckoHook(loader: ClassLoader) {
        try {
            val settings = Class.forName("org.mozilla.geckoview.RuntimeSettings", false, loader)
            val runtimeSettings = Class.forName("org.mozilla.geckoview.GeckoRuntimeSettings", false, loader)
            val prefsMethod = settings.getDeclaredMethod("getPrefsMap")
            if (!Map::class.java.isAssignableFrom(prefsMethod.returnType)) {
                log(Log.WARN, TAG, "[gecko-unsupported] unexpected getPrefsMap signature")
                return
            }
            val firstHit = AtomicBoolean()
            val firstFailure = AtomicBoolean()
            install(prefsMethod, XposedInterface.Hooker { chain ->
                val result = chain.proceed()
                // Nested settings also have getPrefsMap; only alter the root runtime settings.
                if (!runtimeSettings.isInstance(chain.thisObject) || result !is Map<*, *>) {
                    return@Hooker result
                }
                try {
                    val visible = File(GeckoFontPolicy.FONT_PATH).canRead()
                    @Suppress("UNCHECKED_CAST")
                    val original = result as Map<String, Any>
                    val patched = GeckoFontPolicy.apply(original, visible)
                    if (firstHit.compareAndSet(false, true)) {
                        log(
                            if (visible) Log.INFO else Log.WARN, TAG,
                            if (visible)
                                "[gecko-prefs] injected; rendered font still needs device verification"
                            else
                                "[gecko-skip] target font not visible in this process; prefs unchanged"
                        )
                    }
                    patched
                } catch (error: Throwable) {
                    when (error) {
                        is RuntimeException, is LinkageError -> {
                            if (firstFailure.compareAndSet(false, true)) {
                                log(Log.WARN, TAG, "[gecko-failed] preserving original prefs: $error")
                            }
                            result
                        }
                        else -> throw error
                    }
                }
            })
        } catch (absent: ClassNotFoundException) {
            log(Log.INFO, TAG, "[gecko-absent] no GeckoView in this classloader")
        } catch (error: Throwable) {
            when (error) {
                is ReflectiveOperationException, is LinkageError ->
                    log(Log.WARN, TAG, "[gecko-unsupported] $error")
                else -> throw error
            }
        }
    }

    @Synchronized
    private fun install(method: Method, hooker: XposedInterface.Hooker) {
        if (installed.contains(method)) return
        try {
            try {
                if (!deoptimize(method)) {
                    log(Log.WARN, TAG, "[deopt-not-applied] " + method.toGenericString())
                }
            } catch (error: Throwable) {
                when (error) {
                    // A failed deoptimization must not prevent attempting the hook itself.
                    is RuntimeException, is LinkageError ->
                        log(Log.WARN, TAG, "[deopt-failed] " + method.name + ": " + error)
                    else -> throw error
                }
            }
            hook(method).intercept(hooker)
            installed.add(method)
            log(Log.INFO, TAG, "[hook-installed] " + method.toGenericString())
        } catch (error: Throwable) {
            when (error) {
                is RuntimeException, is LinkageError ->
                    log(Log.ERROR, TAG, "[hook-failed] " + method.toGenericString() + ": " + error)
                else -> throw error
            }
        }
    }

    companion object {
        private const val TAG = "Selffont"
    }
}
