package com.mfga.xposed

import android.graphics.Typeface
import android.os.Build
import android.util.Log
import io.github.libxposed.api.XposedInterface
import io.github.libxposed.api.XposedModule
import io.github.libxposed.api.XposedModuleInterface.PackageReadyParam
import java.io.File
import java.lang.reflect.Method
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 原生化:系统字体走 fonts.xml 原生挂载,这里只处理两条系统管不到的路径——
 * 应用自带字体(Typeface 工厂)和 Gecko 网页字体(启动首选项)。只用公开 API,无 JNI。
 * 自由化:无平台闸门,LSPosed 作用域是唯一作用范围。
 */
class Entry : XposedModule() {
    private val installed = HashSet<Method>()

    override fun onPackageReady(param: PackageReadyParam) {
        log(Log.INFO, TAG, "[attach] api=${Build.VERSION.SDK_INT} brand=${Build.BRAND} package=${param.packageName}")
        installTypefaceHooks()
        installGeckoHook(param.classLoader)
    }

    private fun installTypefaceHooks() {
        for (cls in arrayOf(
            Typeface.Builder::class.java, Typeface.CustomFallbackBuilder::class.java, Typeface::class.java
        )) {
            for (method in cls.declaredMethods) {
                val wanted = if (cls == Typeface::class.java) {
                    method.name == "createFromAsset" || method.name == "createFromFile"
                } else {
                    method.name == "build" && method.parameterCount == 0
                }
                if (!wanted || method.returnType != Typeface::class.java) continue
                val firstHit = AtomicBoolean()
                val firstFailure = AtomicBoolean()
                install(method, XposedInterface.Hooker { chain ->
                    // 原方法的异常原样传播,null 原样返回。
                    val result = chain.proceed()
                    if (result !is Typeface || REPLACING.get() == true) return@Hooker result
                    try {
                        REPLACING.set(true)
                        val replacement = Typeface.create(Typeface.DEFAULT, result.weight, result.isItalic)
                        if (firstHit.compareAndSet(false, true)) {
                            log(Log.INFO, TAG, "[typeface-hit] " + method.toGenericString())
                        }
                        replacement ?: result
                    } catch (error: Throwable) {
                        if (error !is RuntimeException && error !is LinkageError) throw error
                        if (firstFailure.compareAndSet(false, true)) {
                            log(Log.WARN, TAG, "[replacement-failed] preserving original: $error")
                        }
                        result
                    } finally {
                        REPLACING.remove()
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
                // 嵌套 settings 也有 getPrefsMap;只改根 runtime settings。
                if (!runtimeSettings.isInstance(chain.thisObject) || result !is Map<*, *>) {
                    return@Hooker result
                }
                try {
                    @Suppress("UNCHECKED_CAST")
                    val patched = Policy.geckoPrefs(result as Map<String, Any>, File(Policy.FONT_PATH).canRead())
                    if (firstHit.compareAndSet(false, true)) {
                        log(
                            if (File(Policy.FONT_PATH).canRead()) Log.INFO else Log.WARN, TAG,
                            if (File(Policy.FONT_PATH).canRead()) "[gecko-prefs] injected"
                            else "[gecko-skip] target font not visible in this process; prefs unchanged"
                        )
                    }
                    patched
                } catch (error: Throwable) {
                    if (error !is RuntimeException && error !is LinkageError) throw error
                    if (firstFailure.compareAndSet(false, true)) {
                        log(Log.WARN, TAG, "[gecko-failed] preserving original prefs: $error")
                    }
                    result
                }
            })
        } catch (absent: ClassNotFoundException) {
            log(Log.INFO, TAG, "[gecko-absent] no GeckoView in this classloader")
        } catch (error: Throwable) {
            if (error !is ReflectiveOperationException && error !is LinkageError) throw error
            log(Log.WARN, TAG, "[gecko-unsupported] $error")
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
                // deoptimize 失败不阻止继续尝试安装 Hook。
                if (error !is RuntimeException && error !is LinkageError) throw error
                log(Log.WARN, TAG, "[deopt-failed] " + method.name + ": " + error)
            }
            hook(method).intercept(hooker)
            installed.add(method)
            log(Log.INFO, TAG, "[hook-installed] " + method.toGenericString())
        } catch (error: Throwable) {
            if (error !is RuntimeException && error !is LinkageError) throw error
            log(Log.ERROR, TAG, "[hook-failed] " + method.toGenericString() + ": " + error)
        }
    }

    companion object {
        private const val TAG = "Selffont"

        /** 重入保护:替换内部再创建 Typeface 时不递归。 */
        private val REPLACING = ThreadLocal<Boolean>()
    }
}
