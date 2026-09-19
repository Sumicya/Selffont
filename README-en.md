# Selffont — phase one

A personal font-family replacement setup targeting **Android 16 (API 36) / Oplus / KernelSU / LSPosed 2.2.0 (7854)**, derived from MFGA. The system font family is unified on **WenYuan Rounded SC VF v1.010** (variable, `wght` 100–900 + `ital`), preserving bold, italic, small caps and original Unicode text. No recoloring, no whole-font/range blocking, no rewriting.

> **Status**: host tests and CI (Kotlin policy unit tests, diagnostic APK, font module build) pass. Device-confirmed: module mount, target font visibility, Gecko preference injection, and the badge-digit fix via line-metric normalisation. Pending device acceptance: full module install and webpage rendering. Firefox's newest Unicode 15.1/16 emoji tofu is a Gecko backend limitation (A/B-proven), unrelated to this module.

## Design boundaries

- Unifies the font family, not typographic semantics; LSPosed scope is the only scope source; no in-module app list.
- Modern Xposed API 102 only; hooks cover the framework font-factory entry points (`Typeface.Builder` / `CustomFallbackBuilder`, asset/file factories, the `Typeface.create` static factories).
- Only the install copy's line metrics are normalised to the Roboto carrier's nominal metrics (fixes badge digits); outlines, cmap, family and axes are byte-identical, with a build-time anti-clip guard (`tools/metric_normalize.py`).
- `fonts.xml` is supplemental configuration input; the packager renders the real install config; default/condensed families keep the Roboto metrics carrier.
- Firefox: in-memory default font preferences injected at Gecko startup (primary family preferred + prepended to the existing fallback chain; emoji prefs untouched); no extensions, no profile edits, no native-address hooks.
- GMS and reader-app font permissions are manual fallbacks only (explicit confirmation); install/boot/WebUI run none of them.
- Platform gate: installs/hook only on the verified combination by default; `touch /data/adb/selffont_allow_unsupported` opts into untested platforms at your own risk; deleting it restores the strict gate.
- Not adapted to other Android/ROM/root managers; results do not generalise.

## Build

Font module (Python 3.11+):

```sh
python3 -m venv .venv
.venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tools/prepare_font.py   # or --font /path/to/WenYuanRoundedSCVF.ttf
.venv/bin/python tools/prepare_base.py
.venv/bin/python tools/build_module.py --base build/base/MFGA-base.zip
```

Diagnostic APK (JDK 21 / Gradle 9.5.0 / Android SDK 36 / AGP 9.3.0, all Kotlin):

```sh
cd mfga-xposed && gradle --no-daemon assembleDebug
```

CI: **Build Selffont font module** (`Selffont-phase1.zip` + SHA-256 + build report), **Build Selffont diagnostic APK** (development-signed), **Check Selffont contracts** (host tests). The base ZIP supplies font resources and attribution only; its scripts, boot hooks, native tools and numeric primary fonts are never inherited. Fonts, base ZIP, APKs and build outputs stay out of Git; do not install a ZIP of this checkout. Module ID remains `MFGA`.

Host tests (same commands as CI):

```sh
.venv/bin/python -m unittest discover -s tests -v
node --test tests/commands.test.mjs
(cd mfga-xposed && gradle test)   # Kotlin policy unit tests
```

## Validation and recovery

- Install the module → reboot → select target apps in LSPosed → fully stop and relaunch them.
- Open `webroot/diagnostics.html` (with `probe.ttf` beside it) in the target Firefox; compare cold starts with scope enabled/disabled; the control `A`s should render as triangles.
- LSPosed log chain: `[attach] → [hook-installed] → [typeface-hit] | [gecko-prefs]`; `[gecko-skip]` = font not visible in that process.
- Manual fallbacks (root shell): `sh /data/adb/modules/MFGA/action.sh diagnose | logs | gms --confirm | app-fonts block|restore --confirm`.
- Full procedure, failure criteria and rollback: `docs/validation.md`; responsibilities and evidence: `docs/architecture.md`.

## Changing the primary font

Edit `config/font-source.json` + `FontIdentity.kt` + `licenses/` only (plus `config/module.json` name/description); contract tests keep every other code path free of the old name, and the module generates `font.conf` / `webroot/font.json` automatically. See `docs/font-swap.md`.
