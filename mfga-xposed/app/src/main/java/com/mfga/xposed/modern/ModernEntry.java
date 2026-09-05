package com.mfga.xposed.modern;

import android.graphics.Typeface;
import android.os.Build;
import android.util.Log;

import com.mfga.xposed.FontForceCore;
import com.mfga.xposed.GeckoFontPolicy;
import com.mfga.xposed.ReplacementGuard;
import com.mfga.xposed.TargetPlatform;

import java.io.File;
import java.lang.reflect.Method;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;

import io.github.libxposed.api.XposedInterface;
import io.github.libxposed.api.XposedModule;

/** Scope is owned exclusively by LSPosed. No package-name allowlist. */
public final class ModernEntry extends XposedModule {
    private static final String TAG = "Selffont";
    private final Set<Method> installed = new HashSet<>();

    @Override
    public void onPackageReady(PackageReadyParam param) {
        if (!TargetPlatform.supports(Build.VERSION.SDK_INT, Build.BRAND, Build.MANUFACTURER)) {
            log(Log.WARN, TAG, "[unsupported] requires Android 16 / API 36 and Oplus");
            return;
        }
        log(Log.INFO, TAG, "[attach] phase1 modern-api102 package=" + param.getPackageName());
        installTypefaceHooks();
        installGeckoHook(param.getClassLoader());
    }

    private void installTypefaceHooks() {
        for (Class<?> cls : new Class<?>[] {
                Typeface.Builder.class, Typeface.CustomFallbackBuilder.class, Typeface.class}) {
            for (Method method : cls.getDeclaredMethods()) {
                String name = method.getName();
                boolean wanted = cls == Typeface.class
                        ? name.equals("createFromAsset") || name.equals("createFromFile")
                        : name.equals("build") && method.getParameterCount() == 0;
                if (!wanted || method.getReturnType() != Typeface.class) continue;
                AtomicBoolean firstHit = new AtomicBoolean();
                AtomicBoolean firstFailure = new AtomicBoolean();
                install(method, chain -> {
                    // Never catch the application's original exception or replace an original null.
                    Object result = chain.proceed();
                    if (!(result instanceof Typeface) || ReplacementGuard.isActive()) return result;
                    try {
                        Typeface replacement = FontForceCore.systemReplacementFor((Typeface) result);
                        if (firstHit.compareAndSet(false, true)) {
                            log(Log.INFO, TAG, "[typeface-hit] " + method.toGenericString());
                        }
                        return replacement;
                    } catch (RuntimeException | LinkageError error) {
                        if (firstFailure.compareAndSet(false, true)) {
                            log(Log.WARN, TAG, "[replacement-failed] preserving original: " + error);
                        }
                        return result;
                    }
                });
            }
        }
    }

    private void installGeckoHook(ClassLoader loader) {
        try {
            Class<?> settings = Class.forName("org.mozilla.geckoview.RuntimeSettings", false, loader);
            Class<?> runtimeSettings = Class.forName(
                    "org.mozilla.geckoview.GeckoRuntimeSettings", false, loader);
            Method prefsMethod = settings.getDeclaredMethod("getPrefsMap");
            if (!Map.class.isAssignableFrom(prefsMethod.getReturnType())) {
                log(Log.WARN, TAG, "[gecko-unsupported] unexpected getPrefsMap signature");
                return;
            }
            AtomicBoolean firstHit = new AtomicBoolean();
            AtomicBoolean firstFailure = new AtomicBoolean();
            install(prefsMethod, chain -> {
                Object result = chain.proceed();
                // Nested settings also have getPrefsMap; only alter the root runtime settings.
                if (!runtimeSettings.isInstance(chain.getThisObject()) || !(result instanceof Map)) {
                    return result;
                }
                try {
                    boolean visible = new File(GeckoFontPolicy.FONT_PATH).canRead();
                    @SuppressWarnings("unchecked")
                    Map<String, Object> original = (Map<String, Object>) result;
                    Map<String, Object> patched = GeckoFontPolicy.apply(original, visible);
                    if (firstHit.compareAndSet(false, true)) {
                        log(visible ? Log.INFO : Log.WARN, TAG, visible
                                ? "[gecko-prefs] injected; rendered font still needs device verification"
                                : "[gecko-skip] target font not visible in this process; prefs unchanged");
                    }
                    return patched;
                } catch (RuntimeException | LinkageError error) {
                    if (firstFailure.compareAndSet(false, true)) {
                        log(Log.WARN, TAG, "[gecko-failed] preserving original prefs: " + error);
                    }
                    return result;
                }
            });
        } catch (ClassNotFoundException absent) {
            log(Log.INFO, TAG, "[gecko-absent] no GeckoView in this classloader");
        } catch (ReflectiveOperationException | LinkageError error) {
            log(Log.WARN, TAG, "[gecko-unsupported] " + error);
        }
    }

    private synchronized void install(Method method, XposedInterface.Hooker hooker) {
        if (installed.contains(method)) return;
        try {
            try {
                if (!deoptimize(method)) {
                    log(Log.WARN, TAG, "[deopt-not-applied] " + method.toGenericString());
                }
            } catch (RuntimeException | LinkageError error) {
                // A failed deoptimization must not prevent attempting the hook itself.
                log(Log.WARN, TAG, "[deopt-failed] " + method.getName() + ": " + error);
            }
            hook(method).intercept(hooker);
            installed.add(method);
            log(Log.INFO, TAG, "[hook-installed] " + method.toGenericString());
        } catch (RuntimeException | LinkageError error) {
            log(Log.ERROR, TAG, "[hook-failed] " + method.toGenericString() + ": " + error);
        }
    }
}
