"""Static safety contracts complement the JVM sample policy and APK compilation."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BadgeObservationContracts(unittest.TestCase):
    def test_systemui_is_not_recommended_or_automatically_added(self):
        scope = (ROOT/'mfga-xposed/app/src/main/resources/META-INF/xposed/scope.list').read_text()
        self.assertNotIn('com.android.systemui', scope)
        entry = (ROOT/'mfga-xposed/app/src/main/kotlin/com/mfga/xposed/modern/ModernEntry.kt').read_text()
        branch = entry.split('if ("com.android.systemui" == param.packageName) {', 1)[1].split('\n        }', 1)[0]
        self.assertIn('badges.install', branch)
        self.assertIn('return', branch)
        self.assertNotIn('installTypefaceHooks', branch)

    def test_observer_does_not_change_draw_arguments_or_paint(self):
        source = (ROOT/'mfga-xposed/app/src/main/kotlin/com/mfga/xposed/diagnostics/BadgeDrawObserver.kt').read_text()
        self.assertIn('Paint(original)', source)
        self.assertIn('chain.proceed()', source)
        self.assertNotIn('chain.proceedWith', source)
        self.assertNotIn('paint.typeface =', source)
        self.assertNotIn('paint.textSize =', source)
        self.assertNotIn('receiver.translate', source)
        self.assertIn('BadgeSamplePolicy(12)', source)

    def test_observer_skips_keyboard_and_large_text(self):
        source = (ROOT/'mfga-xposed/app/src/main/kotlin/com/mfga/xposed/diagnostics/BadgeDrawObserver.kt').read_text()
        # Badge counts are small; the security keypad paints large "7"/"10" that are not badges.
        self.assertIn('textSize > 48', source)
        self.assertIn('caller.contains("eyboard")', source)
