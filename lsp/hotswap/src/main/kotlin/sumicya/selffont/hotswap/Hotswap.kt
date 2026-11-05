package sumicya.selffont.hotswap

import android.graphics.Typeface
import android.util.Log
import io.github.libxposed.api.XposedModule
import io.github.libxposed.api.XposedInterface
import io.github.libxposed.api.XposedModuleInterface.PackageLoadedParam
import java.io.File
import java.util.zip.ZipFile

/**
 * 进程内热切换：把 `android.graphics.Typeface` 的家族表换成模块自带的字体。
 *
 * 为什么走这条路：挂载的四条路在真机上都断了（内核 overlay EINVAL、bind 不能新增文件、
 * `/system/fonts` 是开机快照、`cmd font update` 要系统签名），见 README「运行期换字体」。
 * 进程内不碰分区、不碰 SELinux 挂载，只改当前进程里的那张 Map——所以换字体不用重启整机，
 * 重启目标应用就生效。
 *
 * 字体从**模块自己的 APK** 里取（`assets/fonts/<家族名>.ttf`）。不读 `/data/adb`：
 * 那是 root 专属，普通应用进程读不到，写了也是白写。
 *
 * 三个落点：
 *   1. `Typeface.create(String, int)`：每次按家族名取字都过这里，第一次调用时装好整张表；
 *   2. `Typeface.createFromFile(String)` / `(File)`：把 `/system/fonts/x.ttf` 换成同名热切换文件；
 *   3. `sSystemFontMap`：反射换家族。字段没了就只靠前两条，日志会写清楚。
 *
 * 全部包在 try/catch 里，`exceptionMode=protective` 兜底：失败只能让字体不生效，不能让应用崩。
 */
class Hotswap : XposedModule() {

    private var installed = false

    override fun onPackageLoaded(param: PackageLoadedParam) {
        val tag = "$TAG/${param.packageName.substringAfterLast('.')}"
        val loader = param.defaultClassLoader
        try {
            val typeface = loader.loadClass("android.graphics.Typeface")

            // 1. 家族表：第一次按名字取字时装好。
            val create = typeface.getDeclaredMethod(
                "create", String::class.java, Int::class.javaPrimitiveType
            )
            hook(create).intercept { chain: XposedInterface.Chain ->
                if (!installed) install(tag)
                chain.proceed()
            }

            // 2. 文件字体：按 basename 对上就换成自己的那份。
            for (name in arrayOf("java.lang.String", "java.io.File")) {
                val m = runCatching {
                    typeface.getDeclaredMethod("createFromFile", loader.loadClass(name))
                }.getOrNull() ?: continue
                hook(m).intercept { chain: XposedInterface.Chain ->
                    val arg = chain.getArg(0)
                    val path = (arg as? File)?.name ?: arg as? String
                    val swapped = path?.let { redirect(it, tag) }
                    if (swapped != null) swapped else chain.proceed()
                }
            }

            // 3. Typeface 已经初始化过（多数情况）就先试一次，省得等第一次 create。
            install(tag)
        } catch (t: Throwable) {
            Log.e(tag, "挂钩失败 ${t.javaClass.simpleName}: ${t.message}", t)
        }
    }

    /** 装上整张家族表。装好返回 true；拿不到缓存目录（进程还没起来）就下次再试。 */
    @Synchronized
    private fun install(tag: String): Boolean {
        if (installed) return true
        val fonts = extract(tag)
        if (fonts.isEmpty()) {
            installed = true          // 没有字体就别每次调用都去找一遍
            Log.i(tag, "模块里没有 assets/fonts/<家族名>.ttf，不替换")
            return true
        }
        try {
            val field = Typeface::class.java.getDeclaredField("sSystemFontMap")
            field.isAccessible = true
            val raw = field.get(null) as? Map<*, *>
            if (raw == null) {
                Log.w(tag, "sSystemFontMap 为 null，等下一次 create")
                return false
            }
            @Suppress("UNCHECKED_CAST")
            val map = raw as MutableMap<String, Typeface>
            var n = 0
            for ((family, file) in fonts) {
                if (!map.containsKey(family)) continue
                runCatching { Typeface.createFromFile(file) }
                    .onSuccess { map[family] = it; n++ }
                    .onFailure { Log.e(tag, "造字失败 ${file.name}: ${it.message}") }
            }
            installed = true
            Log.i(tag, "家族表替换 $n/${fonts.size} 个（共 ${map.size} 个家族）")
            return true
        } catch (t: Throwable) {
            Log.e(tag, "换家族表失败 ${t.javaClass.simpleName}: ${t.message}", t)
            installed = true            // 这条路断了就不再重试，别每次取字都抛一遍
            return true
        }
    }

    /** 把 `/system/fonts/x.ttf` 这类路径换成模块里同名的那份；没有就返回 null。 */
    private fun redirect(path: String, tag: String): Typeface? {
        val base = path.substringAfterLast('/')
        val hit = cacheFile(base) ?: return null
        return runCatching { Typeface.createFromFile(hit) }
            .onFailure { Log.e(tag, "重定向失败 ${hit.name}: ${it.message}") }
            .getOrNull()
    }

    /** 模块 APK 的 assets/fonts/<家族名>.ttf → 本进程缓存目录；返回「家族名 → 文件」。 */
    private fun extract(tag: String): Map<String, File> {
        val cache = cacheDir() ?: return emptyMap()
        val out = linkedMapOf<String, File>()
        val apk = moduleApk() ?: run { Log.w(tag, "取不到模块 APK 路径"); return emptyMap() }
        try {
            ZipFile(apk).use { zip ->
                val entries = zip.entries()
                while (entries.hasMoreElements()) {
                    val e = entries.nextElement()
                    val name = e.name
                    if (!name.startsWith("assets/fonts/") || !name.endsWith(".ttf", true)) continue
                    val family = name.substringAfterLast('/').removeSuffix(".ttf").removeSuffix(".TTF")
                    val dest = File(cache, "hotswap/$family.ttf")
                    dest.parentFile?.mkdirs()
                    if (!dest.exists() || dest.length() != e.size) {
                        zip.getInputStream(e).use { input ->
                            dest.outputStream().use { input.copyTo(it) }
                        }
                    }
                    if (dest.length() > 0) out[family] = dest
                }
            }
        } catch (t: Throwable) {
            Log.e(tag, "解包字体失败 ${t.javaClass.simpleName}: ${t.message}", t)
        }
        return out
    }

    /** 缓存里已有的那份（不重新解包）。 */
    private fun cacheFile(base: String): File? {
        val cache = cacheDir() ?: return null
        val f = File(cache, "hotswap/$base")
        return if (f.length() > 0) f else null
    }

    private fun cacheDir(): File? = try {
        val at = Class.forName("android.app.ActivityThread")
        val thread = at.getMethod("currentActivityThread").invoke(null)
        val app = at.getMethod("getApplication").invoke(thread) as? android.app.Application
        app?.cacheDir
    } catch (t: Throwable) {
        null
    }

    private fun moduleApk(): File? = runCatching {
        val loc = Hotswap::class.java.protectionDomain?.codeSource?.location ?: return null
        File(loc.toURI())
    }.getOrNull()

    private companion object {
        const val TAG = "SelfFontHotswap"
    }
}
