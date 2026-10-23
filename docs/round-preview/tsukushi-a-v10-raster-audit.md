# V10 sample-wide raster/topology audit

- Sample scope: 63 entries / 62 unique glyphs.
- Intentional source-to-geometry redraw allowance: 鸟.
- Recorded intentional redraw topology changes: 1.
  - 鸟 U+9E1F: source → geometry 3/0 → 1/0
- Independent renderer: Pillow 13.0.0 / FreeType 2.14.3; FontTools 4.66.0; large audit size 1000 px per em.
- Raster method: alpha threshold ≥128; 8-connected components; counters = components minus Euler number; binary-mask IoU.
- Hard checks: source → geometry component/counter topology except the explicitly listed redraws; geometry → candidate topology, cmap mapping, UPM/weight, and advance widths.
- Hard-check topology failures: 0.
- Advance-width failures: 0.
- Font/sample mapping failures: 0.
- Diagnostic only: source-vs-candidate topology differs in 11 unique glyph(s) at 48 px/em (U+56FD, U+8FDB, U+8FDC, U+4E66, U+89C4, U+4E3D, U+9526, U+7EE3, U+98CE, U+96E8, U+9E1F); low-resolution rasterization is not a vector-topology pass/fail gate.

## U+7535 exterior-width constraint

- Advance widths (source / geometry / candidate): 950 / 950 / 950 FU.
- Ink-bbox widths (source / geometry / candidate): 819 / 819 / 814 FU.
- Candidate x bounds: source (111, 930) FU → candidate (108, 922) FU. Any residual difference is reported, not represented as exact exterior-width preservation.

## Stroke-width proxies (900 px skeleton-distance audit)

| Stage | Glyphs | Median of per-glyph medians (FU) | Across-glyph CV | Within-glyph CV mean | Within-glyph CV max |
| --- | ---: | ---: | ---: | ---: | ---: |
| source | 62 | 76.739 | 0.07813 | 0.07454 | 0.17484 |
| geometry | 62 | 76.826 | 0.07834 | 0.07709 | 0.19756 |
| candidate | 62 | 74.946 | 0.02585 | 0.05477 | 0.15849 |

These width values are skeleton-distance proxies, not proof of equal perceived weight at joins or small device sizes.

## Per-entry evidence

See [`tsukushi-a-v10-sample-audit.csv`](tsukushi-a-v10-sample-audit.csv) for all 63 sample entries, including the duplicate entry, advances, full glyph bounds, FreeType component/counter counts, and geometry-to-candidate IoU.

The 48 px diagnostic is intentionally reported separately because the source contains hinting and the research candidate does not; pixel-level component counts at small sizes are renderer-dependent.
