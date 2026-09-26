plugins {
    // AGP 9 内置 Kotlin;独立的 org.jetbrains.kotlin.android 插件与 AGP 9 不兼容,不能应用。
    id("com.android.application") version "9.3.0" apply false
}
