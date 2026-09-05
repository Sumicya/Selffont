plugins { id("com.android.application") }

android {
    namespace = "com.mfga.xposed"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.mfga.xposed"
        minSdk = 36
        targetSdk = 36
        versionCode = 14
        versionName = "1.4-phase1"
    }
    buildTypes { release { isMinifyEnabled = false } }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    sourceSets["main"].resources.srcDirs("src/main/resources")
}
dependencies { compileOnly("io.github.libxposed:api:102.0.0") }
