plugins { id("com.android.application") }

android {
    namespace = "com.mfga.xposed"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.mfga.xposed"
        minSdk = 36
        targetSdk = 36
        versionCode = 22
        versionName = "1.4-phase2"
    }
    buildTypes { release { isMinifyEnabled = false } }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    sourceSets["main"].resources.srcDirs("src/main/resources")
}
dependencies { compileOnly("io.github.libxposed:api:102.0.0") }

// Verify actual DEX definitions, including secondary DEX files, before CI uploads the container.
tasks.register<Exec>("verifyProbeContainer") {
    dependsOn("packageDebug")
    workingDir(rootProject.projectDir)
    commandLine("python3", "verify_probe_container.py", "app/build/outputs/apk/debug/app-debug.apk")
}
tasks.matching { it.name == "assembleDebug" }.configureEach {
    finalizedBy("verifyProbeContainer")
}
