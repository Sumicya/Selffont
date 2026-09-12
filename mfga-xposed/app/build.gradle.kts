plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.mfga.xposed"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.mfga.xposed"
        minSdk = 36
        targetSdk = 36
        versionCode = 23
        versionName = "1.4.0"
    }
    buildTypes { release { isMinifyEnabled = false } }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_21
        targetCompatibility = JavaVersion.VERSION_21
    }
    kotlinOptions {
        jvmTarget = "21"
    }
    sourceSets["main"].resources.srcDirs("src/main/resources")
    testOptions { unitTests.all { it.useJUnit() } }
}
dependencies {
    compileOnly("io.github.libxposed:api:102.0.0")
    testImplementation("junit:junit:4.13.2")
}

// Verify actual DEX definitions, including secondary DEX files, before CI uploads the container.
tasks.register<Exec>("verifyProbeContainer") {
    dependsOn("packageDebug")
    workingDir(rootProject.projectDir)
    commandLine("python3", "verify_probe_container.py", "app/build/outputs/apk/debug/app-debug.apk")
}
tasks.matching { it.name == "assembleDebug" }.configureEach {
    finalizedBy("verifyProbeContainer")
}
