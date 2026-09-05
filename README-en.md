# Selffont — phase one

A personal font-family replacement setup targeting **Android 16 / Oplus / KernelSU / LSPosed 2.2.0 (7854)**, derived from MFGA. This is not a general Android compatibility claim.

The primary candidate is the unmodified **WenYuan Rounded SC VF v1.010**, pinned by SHA-256 in `config/font-source.json`. Preserve weight, italic, small caps and Unicode text. Whole-font/range blocking and recoloring have been removed, including their tools and workflows.

- Modern Xposed API 102 only. LSPosed owns scope; there is no internal package allowlist.
- A Gecko startup-preference adapter targets Firefox 155.0.1. The adapter and a Java font factory have now been hit on the target device. Gecko preferences were deliberately left unchanged because the target font was unreadable; **webpage rendering is not yet verified**.
- No browser extensions, profile edits or native-address hooks. If the target font is not visible in Firefox's process, no Gecko preferences are injected.
- GMS and reader-app permission interventions require explicit manual confirmation. No boot-time application-data changes.

## Build

```sh
python3 -m venv .venv
.venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tools/prepare_font.py
# Or verify an existing original release file:
.venv/bin/python tools/prepare_font.py --font /path/to/WenYuanRoundedSCVF.ttf
.venv/bin/python tools/prepare_base.py
.venv/bin/python tools/build_module.py --base build/base/MFGA-base.zip
```

A complete MFGA base ZIP is an explicit supplemental-font input, pinned by size and SHA-256 in `config/base-source.json` when using `prepare_base.py`. A separate font-module workflow prepares resources; it does not rebuild the APK. The assembler does **not** inherit its scripts, native tools, Zygisk, updater or numeric primary fonts. Do not install a ZIP of this checkout. Module ID remains `MFGA` to avoid competing mounts. Large inputs and outputs stay out of Git.

For an installable development APK, use JDK 17, Gradle 8.11.1 and Android SDK 36:

```sh
cd mfga-xposed
gradle --no-daemon assembleDebug
```

The host-contract checks (including Java policies) and diagnostic APK build passed CI for commit `16457fb`. See `docs/validation.md` for the run links and remaining device checks. The CI workflow builds a diagnostic APK, not a stable production-signed release. A signature change requires uninstalling the previous APK and selecting scope again. No APK build or device success should be inferred from host-side tests.

## Validation and recovery

Open `webroot/diagnostics.html` with `probe.ttf` beside it in the target Firefox. Compare after cold starts with the module scope disabled/enabled. The original test font renders ASCII A as a triangle; small caps and italic should remain after the family changes. Logs distinguish attachment, hook installation, actual hit and missing-font/unsupported-interface cases.

Reader-app permissions are journaled before modification and restored by identity and recorded mode, not guessed as 600. Uninstall attempts that restoration. Old unrecorded changes cannot be reconstructed. GMS cache deletion is irreversible and disabled GMS components remain disabled after uninstall.

Full scope, evidence, limitations and device test procedure: [Chinese README](README.md), [architecture](docs/architecture.md), [validation](docs/validation.md).
