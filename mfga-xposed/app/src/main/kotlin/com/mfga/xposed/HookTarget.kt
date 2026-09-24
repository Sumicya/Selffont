package com.mfga.xposed

/**
 * Which framework factory entry points the module hooks, decided purely from
 * class/method signatures so host unit tests (PolicyTest) can pin the coverage
 * without an Android runtime. The device-side loop in
 * [com.mfga.xposed.modern.ModernEntry] applies this same predicate to the
 * declared methods of [android.graphics.Typeface] and its builder inner
 * classes.
 *
 * Coverage follows the framework's own factory surface:
 *  - `Typeface.Builder#build()` and `Typeface$CustomFallbackBuilder#build()`
 *    (resource / font-XML families on Android 10+);
 *  - `Typeface#createFromAsset` / `Typeface#createFromFile` (asset and file
 *    fonts);
 *  - `Typeface#create(Typeface, int, boolean)` (API 28+) and
 *    `Typeface#create(Typeface, int)` (the classic weight/style static
 *    factories apps call directly).
 *
 * `Typeface#create(String, int)` is deliberately NOT hooked: callers that ask
 * for a family by name keep framework / familyset resolution (fonts.xml
 * already remaps the named families), and forcing the default there would be a
 * semantic change beyond the result-replacement policy.
 */
object HookTarget {
    private val BUILDER_CLASSES = setOf("Builder", "CustomFallbackBuilder")
    private val STATIC_FILE_FACTORIES = setOf("createFromAsset", "createFromFile")
    private val CREATE_OVERLOADS = listOf(
        listOf("android.graphics.Typeface", "int", "boolean"),
        listOf("android.graphics.Typeface", "int")
    )

    @JvmStatic
    fun isWanted(
        classSimpleName: String,
        methodName: String,
        parameterTypeNames: List<String>
    ): Boolean = when {
        classSimpleName in BUILDER_CLASSES ->
            methodName == "build" && parameterTypeNames.isEmpty()
        classSimpleName == "Typeface" ->
            methodName in STATIC_FILE_FACTORIES ||
                (methodName == "create" && parameterTypeNames in CREATE_OVERLOADS)
        else -> false
    }
}
