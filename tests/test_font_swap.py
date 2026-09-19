"""Font-swap preparation contract.

Swapping the primary font must touch the single sources of truth only
(`config/font-source.json`, `FontIdentity.kt`, `licenses/`, `config/module.json`)
plus human-readable docs - never shell, Python, Kotlin or web code. This test
fails if the configured family name, installed filename or license filename is
hardcoded anywhere in the code, so a future font change (docs/font-swap.md)
cannot silently leave stale references behind.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "config/font-source.json").read_text())

# Code surfaces that must stay font-agnostic.
CODE_GLOBS = [
    "script/*.sh",
    "tools/*.py",
    "tools/*.sh",
    "lang/*.sh",
    "fonts_list.yaml",
    "mfga-xposed/app/src/main/kotlin/**/*.kt",
    "mfga-xposed/app/src/test/kotlin/**/*.kt",
    "webroot/**/*.html",
    "webroot/**/*.js",
    "webroot/**/*.mjs",
    "webroot/**/*.json",
    "tests/*.py",
]

# Explicit, documented exceptions:
EXCEPTIONS = {
    # Kotlin single source of truth for the on-device runtime (mirrored from
    # config/font-source.json by tests/test_refactor.py).
    ROOT / "mfga-xposed/app/src/main/kotlin/com/mfga/xposed/FontIdentity.kt",
    # Static offline fallback for the local() probe; the module build injects
    # webroot/font.json and the page repoints the probe at the configured
    # family at runtime, so the HTML copy only matters when opening the repo
    # without a build.
    ROOT / "webroot/diagnostics.html",
}


def code_files():
    files = set()
    for pattern in CODE_GLOBS:
        files.update(ROOT.glob(pattern))
    return sorted(f for f in files if f.is_file() and f not in EXCEPTIONS)


class FontSwapContractTests(unittest.TestCase):
    def test_manifest_declares_the_full_swap_surface(self):
        for key in ("project", "version", "family", "file", "installedFile", "bytes",
                    "sha256", "url", "licenseFile", "baselineCharacters"):
            self.assertTrue(MANIFEST.get(key), f"config/font-source.json missing {key}")
        self.assertTrue((ROOT / "licenses" / MANIFEST["licenseFile"]).is_file())

    def test_no_hardcoded_font_identity_in_code(self):
        needles = (MANIFEST["family"], MANIFEST["installedFile"],
                   MANIFEST["licenseFile"], MANIFEST["file"])
        offenders = []
        for path in code_files():
            text = path.read_text(errors="replace")
            for needle in needles:
                if needle in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {needle}")
        self.assertEqual(offenders, [], "Font identity is hardcoded in code:\n" +
                         "\n".join(offenders))

    # On-device font.conf binding and Kotlin identity mirroring are pinned by
    # tests/test_font_paths.py and tests/test_refactor.py respectively.


if __name__ == '__main__':
    unittest.main()
