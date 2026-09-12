#!/bin/sh
# Compile the pure Kotlin policy classes and run the Java interop test against them.
# PolicyTest is deliberately kept in Java: it proves the Kotlin classes still expose
# Java-callable static/const shapes (@JvmStatic / const val / @JvmField) that the
# still-Java Xposed code and this host-side test both depend on.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
OUT="$ROOT/build/policy-tests"
JAR="$OUT/policy.jar"
rm -rf "$OUT"
mkdir -p "$OUT"

SRC="$ROOT/mfga-xposed/app/src/main/kotlin/com/mfga/xposed"

# -include-runtime bundles kotlin-stdlib into the jar, so both javac and java can
# resolve the Kotlin classes without hunting for the stdlib on this machine.
kotlinc \
    "$SRC/FontIdentity.kt" \
    "$SRC/GeckoFontPolicy.kt" \
    "$SRC/ReplacementGuard.kt" \
    "$SRC/TargetPlatform.kt" \
    "$SRC/diagnostics/BadgeSamplePolicy.kt" \
    -jvm-target 21 -include-runtime -d "$JAR"

javac --release 21 -cp "$JAR" -d "$OUT" "$ROOT/tests/java/PolicyTest.java"

java -cp "$JAR:$OUT" PolicyTest
