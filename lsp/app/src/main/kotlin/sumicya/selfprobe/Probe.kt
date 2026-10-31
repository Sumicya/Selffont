package sumicya.selfprobe

import android.graphics.Typeface
import android.util.Log
import io.github.libxposed.api.XposedModule
import io.github.libxposed.api.XposedModuleInterface.PackageLoadedParam

/**
 * 探针：只证明 `android.graphics.Typeface.sSystemFontMap` 能不能在进程内读到。
 *
 * 不替换任何字体、不 hook 任何返回值、不读 /system/fonts、不挂载——只读一次字段并打日志。
 * 三种输出各自对应一个结论：
 *   · `字段存在 class=… size=… 家族样例=…` → 字段可读，map 类型与家族数都拿到了（下一步才谈替换）
 *   · `NoSuchFieldException: …`             → 这台 ROM 上字段名不同或不可见，改法要从这里重新查
 *   · `IllegalAccessException` / 其它 Throwable → 字段在但 setAccessible 被拦
 */
class Probe : XposedModule() {

    override fun onPackageLoaded(param: PackageLoadedParam) {
        if (param.packageName != "com.android.settings") return   // 作用域只声明了 settings，再挡一次

        try {
            val field = Typeface::class.java.getDeclaredField("sSystemFontMap")
            field.isAccessible = true
            val map = field.get(null) as Map<*, *>
            Log.i(TAG, "字段存在 class=" + map.javaClass.name + " size=" + map.size +
                    " 家族样例=" + map.keys.take(3).joinToString(","))
        } catch (e: NoSuchFieldException) {
            Log.e(TAG, "NoSuchFieldException: " + e.message)
        } catch (e: IllegalAccessException) {
            Log.e(TAG, "IllegalAccessException: " + e.message)
        } catch (e: Throwable) {
            Log.e(TAG, e.javaClass.name + ": " + e.message)
        }
    }

    private companion object {
        const val TAG = "SelfFontProbe"
    }
}
