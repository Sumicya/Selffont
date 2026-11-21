// 热切换模块：compileSdk 36 / minSdk 36 / 包名 sumicya.selffont.hotswap。
// 只做一件事——在目标进程里把 Typeface 的家族表换成自己带的字体，不碰挂载、不改系统分区。
// 换字 = 换这个 APK 里的 assets/fonts/*.ttf（装新 APK、重启目标应用），不用重启整机。
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "sumicya.selffont.hotswap"
    compileSdk = 36

    defaultConfig {
        applicationId = "sumicya.selffont.hotswap"
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
