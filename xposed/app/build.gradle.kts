plugins {
    id("com.android.application")
}

android {
    namespace = "com.mfga.xposed"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.mfga.xposed"
        minSdk = 36
        targetSdk = 36
        versionCode = 24
        versionName = "2.0.0"
    }
    buildTypes { release { isMinifyEnabled = false } }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_21
        targetCompatibility = JavaVersion.VERSION_21
    }
    // AGP 9 内置 Kotlin 从 compileOptions 推导 jvmTarget,无需 kotlinOptions 块。
    sourceSets["main"].resources.srcDirs("src/main/resources")
    testOptions { unitTests.all { it.useJUnit() } }
}

dependencies {
    compileOnly("io.github.libxposed:api:102.0.0")
    testImplementation("junit:junit:4.13.2")
}
