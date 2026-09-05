#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
OUT="$ROOT/build/policy-tests"
mkdir -p "$OUT"
javac --release 17 -d "$OUT" \
    "$ROOT/mfga-xposed/app/src/main/java/com/mfga/xposed/GeckoFontPolicy.java" \
    "$ROOT/mfga-xposed/app/src/main/java/com/mfga/xposed/ReplacementGuard.java" \
    "$ROOT/mfga-xposed/app/src/main/java/com/mfga/xposed/TargetPlatform.java" \
    "$ROOT/tests/java/PolicyTest.java"
java -cp "$OUT" PolicyTest
