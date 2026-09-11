import com.mfga.xposed.GeckoFontPolicy;
import com.mfga.xposed.ReplacementGuard;
import com.mfga.xposed.TargetPlatform;
import com.mfga.xposed.diagnostics.BadgeSamplePolicy;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

public final class PolicyTest {
    private static void check(boolean condition) {
        if (!condition) throw new AssertionError();
    }
    public static void main(String[] args) throws Exception {
        Map<String, Object> original = Map.of("browser.display.use_document_fonts", 1,
                "font.size.variable.x-western", 19, "unrelated", "retained",
                "font.name-list.sans-serif.x-western", "Roboto, Noto Sans, Noto Color Emoji",
                "font.name-list.serif.zh-CN", GeckoFontPolicy.FAMILY + ", Noto Serif CJK SC");
        check(GeckoFontPolicy.apply(original, false) == original);
        Map<String, Object> changed = GeckoFontPolicy.apply(original, true);
        check(changed.get("browser.display.use_document_fonts").equals(0));
        check(original.get("browser.display.use_document_fonts").equals(1));
        check(changed.get("font.size.variable.x-western").equals(19));
        check(changed.get("unrelated").equals("retained"));
        // font.name (preferred) is WenYuan for every generic/language.
        check(changed.get("font.name.cursive.zh-CN").equals(GeckoFontPolicy.FAMILY));
        check(changed.get("font.name.serif.x-western").equals(GeckoFontPolicy.FAMILY));
        // font.name-list keeps the ORIGINAL fallback chain, with WenYuan prepended,
        // so glyphs WenYuan lacks (rare codepoints, colour emoji) still resolve.
        check(changed.get("font.name-list.sans-serif.x-western")
                .equals(GeckoFontPolicy.FAMILY + ", Roboto, Noto Sans, Noto Color Emoji"));
        // Already led by WenYuan: left unchanged, no duplication.
        check(changed.get("font.name-list.serif.zh-CN")
                .equals(GeckoFontPolicy.FAMILY + ", Noto Serif CJK SC"));
        // Where Gecko exposes no list, we must NOT invent a WenYuan-only list.
        check(changed.get("font.name-list.monospace.ja") == null);
        // Emoji preferences are untouched so system colour emoji fallback still applies.
        check(changed.keySet().stream().noneMatch(key -> key.startsWith("font.name.emoji")
                || key.startsWith("font.name-list.emoji")));
        check(GeckoFontPolicy.apply(changed, true).equals(changed));
        try { changed.put("oops", true); throw new AssertionError(); }
        catch (UnsupportedOperationException expected) { }
        check(changed.keySet().stream().noneMatch(key -> key.contains("synthesis") || key.contains("variant")));

        // prependFamily: prepend, dedupe, idempotence, empty handling.
        check(GeckoFontPolicy.prependFamily("A, B").equals(GeckoFontPolicy.FAMILY + ", A, B"));
        check(GeckoFontPolicy.prependFamily(GeckoFontPolicy.FAMILY + ", A") == null);
        check(GeckoFontPolicy.prependFamily("A, " + GeckoFontPolicy.FAMILY + ", B")
                .equals(GeckoFontPolicy.FAMILY + ", A, B"));
        check(GeckoFontPolicy.prependFamily("   ") == null);

        check(ReplacementGuard.replace(null, () -> { throw new AssertionError(); }) == null);
        check(ReplacementGuard.replace("original", () -> null).equals("original"));
        check(ReplacementGuard.replace("original", () -> {
            check(ReplacementGuard.isActive());
            check(ReplacementGuard.replace("nested", () -> { throw new AssertionError(); }).equals("nested"));
            return "replacement";
        }).equals("replacement"));
        check(!ReplacementGuard.isActive());
        try { ReplacementGuard.replace("original", () -> { throw new IllegalStateException("test"); }); }
        catch (IllegalStateException expected) { }
        check(!ReplacementGuard.isActive());
        AtomicBoolean separateThread = new AtomicBoolean();
        ReplacementGuard.replace("original", () -> {
            Thread thread = new Thread(() -> separateThread.set(!ReplacementGuard.isActive()));
            thread.start();
            try { thread.join(); } catch (InterruptedException e) { throw new RuntimeException(e); }
            return "replacement";
        });
        check(separateThread.get());
        check(TargetPlatform.supports(36, "OnePlus", "OPLUS"));
        check(TargetPlatform.supports(36, "realme", "unknown"));
        check(!TargetPlatform.supports(35, "OnePlus", "OPLUS"));
        check(!TargetPlatform.supports(36, "google", "google"));
        check(!TargetPlatform.supports(36, null, null));
        // allowed(): natively supported platforms attach regardless of the override.
        check(TargetPlatform.allowed(36, "OnePlus", "OPLUS", false));
        check(TargetPlatform.allowed(36, "OnePlus", "OPLUS", true));
        // Untested platforms are blocked by default, but the user may force it.
        check(!TargetPlatform.allowed(35, "google", "google", false));
        check(TargetPlatform.allowed(35, "google", "google", true));
        check(!TargetPlatform.allowed(36, "google", "google", false));
        check(TargetPlatform.allowed(36, "google", "google", true));
        check(BadgeSamplePolicy.sample("7", 0, 1).equals("7"));
        check(BadgeSamplePolicy.sample(new char[]{'x', '1', '0', 'y'}, 1, 3).equals("10"));
        check(BadgeSamplePolicy.sample("notification content", 0, 20) == null);
        check(BadgeSamplePolicy.sample("99", 0, 2) == null);
        check(BadgeSamplePolicy.sample(null, 0, 1) == null);
        check(BadgeSamplePolicy.sample("10", -1, 1) == null);
        check(BadgeSamplePolicy.sample("10", 0, 3) == null);
        check(BadgeSamplePolicy.sample("", 0, 0) == null);
        BadgeSamplePolicy budget = new BadgeSamplePolicy(2);
        check(budget.claim("one"));
        check(!budget.claim("one"));
        check(budget.claim("two"));
        check(budget.full());
        check(!budget.claim("three"));
        System.out.println("Java policy tests passed");
    }
}
