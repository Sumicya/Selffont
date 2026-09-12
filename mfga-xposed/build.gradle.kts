plugins {
    // AGP 9 provides built-in Kotlin support; the standalone
    // org.jetbrains.kotlin.android plugin is incompatible with AGP 9
    // (it casts to the removed BaseExtension) and must not be applied.
    id("com.android.application") version "9.3.0" apply false
}
