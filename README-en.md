# Selffont · Maru

A personal font-family replacement setup targeting **Android 16 (API 36) / Oplus / KernelSU / LSPosed**, derived from MFGA.

**Font route:** five static weights of [Zen Maru Gothic](https://github.com/googlefonts/zen-marugothic) (OFL-1.1, pinned commit), renamed at build time to the derivative family **`Selffont Maru`** and installed as `SelffontMaru-{Light,Regular,Medium,Bold,Black}.ttf`. Android's 100–900 requests map to the nearest face (600→700, 800→900, ties go heavier); italics are synthesised by the platform. No `fvar` is fabricated.

**Handwriting-led glyph work** happens only through **explicit per-character point patches** (`config/glyph-patches/<Style>.json`). There is no charset-wide rewriting, no tracing from photos and no "smoothing/rounding" operator. The editor refuses composite glyphs, hinted glyphs, out-of-range indices and no-op edits.

> **Status (honest)**
> - Host side: 100 Python contract tests + 3 node tests + ruff are green, and the full chain (download → verify → rename → metric-normalise → package) has been rehearsed locally against the real Zen Maru faces with a synthetic base ZIP.
> - Device: **NOT TESTED**. Module install, webpage rendering and compact slots must be re-verified per `docs/validation.md`.
> - Known limit: Zen Maru is a *Japanese* face, so simplified-Chinese-only characters are largely absent. Auditing the author's handwriting list gives **30 editable / 14 not drawn** out of 44 text targets (`python3 tools/glyph_audit.py`). Those 14 need new outlines; they are never faked by a point patch.

## What changed in this rewrite

| | |
|---|---|
| Font | WenYuan Rounded (variable) → Zen Maru Gothic, five static faces, derivative name `Selffont Maru` |
| Glyph editing | Charset-wide geometric rewriting deleted with its tools; only the explicit point-patch editor plus its contract tests remain |
| Dead weight | `tools/otfcc*`, `tools/merge-otd`, the NotoSansPro merge workflow, the emoji-overlap script and the dormant badge/glyph probe classes are gone (~2.6 MB of binaries, two legacy workflows) |
| Single source of truth | The module ships a generated `font.conf` (face names + visibility file); shell scripts no longer hardcode font names, and `config/font-source.json` ↔ `FontIdentity.kt` drift is test-enforced |
| Modernisation | Python 3.11 + fontTools 4.65; JDK 21 / Gradle 9.5.0 / AGP 9.3.0 / SDK 36 / all-Kotlin; node 24 + ruff gate |
| Nativisation | Only framework `Typeface` factories and `fonts.xml`; no JNI, no private-address scanning |

## Build

```sh
python3 -m venv .venv
.venv/bin/pip install -r tools/requirements-dev.txt

.venv/bin/python tools/prepare_font.py                 # or --font-dir /path/to/zen-maru/ttf
.venv/bin/python tools/edit_font.py                    # optional point patches
.venv/bin/python tools/glyph_audit.py                  # editable vs not-drawn targets
.venv/bin/python tools/preview.py --serve              # browser review page
.venv/bin/python tools/prepare_base.py
.venv/bin/python tools/build_module.py --base build/base/MFGA-base.zip
```

The artifact is `build/Selffont-Maru.zip`; the KSU module id stays `MFGA` to avoid competing mounts. Fonts, the base ZIP, APKs and build output never enter Git.

## Boundaries

- The platform gate installs/hooks only on Android 16 + Oplus + KernelSU by default; `touch /data/adb/selffont_allow_unsupported` opts into untested platforms at your own risk, deleting it restores the strict gate.
- Firefox is adapted through in-memory default-font preferences at Gecko startup (family preferred, existing fallback chain prepended, emoji preferences untouched); no extensions, no profile edits, no native-address hooks. Whether a page truly uses the face still needs the diagnostics page and the log chain.
- Metric normalisation (`tools/metric_normalize.py`) scales only the install copy's `hhea`/`OS/2` line metrics to the Roboto carrier's nominal metrics to fix low/clipped badge digits; outlines, cmap, family name and weight stay byte-identical, with an anti-clip guard.
- GMS and reader-app font permissions remain manual fallbacks (explicit `--confirm`); install, boot and the WebUI never run them.
- Not adapted to other Android versions, ROMs or root managers; device results do not generalise.

Contracts and evidence: [`docs/architecture.md`](docs/architecture.md). Acceptance: [`docs/validation.md`](docs/validation.md). Glyph editing: [`docs/font-editing.md`](docs/font-editing.md). Swapping the font: [`docs/font-swap.md`](docs/font-swap.md).
