// 独立 Gradle 工程：出探针 APK 与热切换 APK，不参与字体构建（font 线的 build.py 一行都不读这里）。
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "SelffontLsp"
include(":app")
include(":hotswap")
