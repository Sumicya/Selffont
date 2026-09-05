import com.mfga.xposed.GeckoFontPolicy;
import com.mfga.xposed.ReplacementGuard;
import com.mfga.xposed.TargetPlatform;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

public final class PolicyTest {
    private static void check(boolean condition) {
        if (!condition) throw new AssertionError();
    }
    public static void main(String[] args) throws Exception {
        Map<String, Object> original = Map.of("browser.display.use_document_fonts", 1,
                "font.size.variable.x-western", 19, "unrelated", "retained");
        check(GeckoFontPolicy.apply(original, false) == original);
        Map<String, Object> changed = GeckoFontPolicy.apply(original, true);
        check(changed.get("browser.display.use_document_fonts").equals(0));
        check(original.get("browser.display.use_document_fonts").equals(1));
        check(changed.get("font.size.variable.x-western").equals(19));
        check(changed.get("unrelated").equals("retained"));
        check(changed.get("font.name.cursive.zh-CN").equals(GeckoFontPolicy.FAMILY));
        check(changed.get("font.name.serif.x-western").equals(GeckoFontPolicy.FAMILY));
        check(GeckoFontPolicy.apply(changed, true).equals(changed));
        try { changed.put("oops", true); throw new AssertionError(); }
        catch (UnsupportedOperationException expected) { }
        check(changed.keySet().stream().noneMatch(key -> key.contains("synthesis") || key.contains("variant")));

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
        System.out.println("Java policy tests passed");
    }
}
