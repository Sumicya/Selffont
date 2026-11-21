// 探针 APK：compileSdk 36 / minSdk 36 / 包名 sumicya.selfprobe。
// 只做一件事——在 com.android.settings 进程里反射读 Typeface.sSystemFontMap 并打日志。
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "sumicya.selfprobe"
    compileSdk = 36

    defaultConfig {
        applicationId = "sumicya.selfprobe"
        minSdk = 36
        targetSdk = 36
        versionCode = 1
        versionName = "dev-1"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_21
        targetCompatibility = JavaVersion.VERSION_21
    }

    kotlinOptions {
        jvmTarget = "21"
    }
}

dependencies {
    // libxposed 现代 API：只编译期可见，运行时由 LSPosed 提供。
    compileOnly("io.github.libxposed:api:102.0.0")
}
