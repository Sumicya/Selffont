# V9 sample-wide raster/topology audit

- Sample scope: 63 entries / 62 unique glyphs.
- Independent renderer: Pillow 13.0.0 / FreeType 2.14.3; FontTools 4.66.0; large audit size 1000 px per em.
- Raster method: alpha threshold ≥128; 8-connected components; counters = components minus Euler number; binary-mask IoU.
- Hard checks: source → geometry and geometry → candidate component/counter topology, cmap mapping, UPM/weight, and advance widths.
- Hard-check topology failures: 0.
- Advance-width failures: 0.
- Font/sample mapping failures: 0.
- Diagnostic only: source-vs-candidate topology differs in 15 unique glyph(s) at 48 px/em (U+56FD, U+8FDB, U+8FDC, U+4E66, U+89C4, U+4E3D, U+989C, U+9526, U+7EE3, U+98CE, U+96E8, U+9F99, U+9E1F, U+4E5F, U+6696); low-resolution rasterization is not a vector-topology pass/fail gate.

## U+7535 exterior-width constraint

- Advance widths (source / geometry / candidate): 950 / 950 / 950 FU.
- Ink-bbox widths (source / geometry / candidate): 819 / 819 / 814 FU.
- Candidate x bounds: source (111, 930) FU → candidate (108, 922) FU. Any residual difference is reported, not represented as exact exterior-width preservation.

## Stroke-width proxies (900 px skeleton-distance audit)

| Stage | Glyphs | Median of per-glyph medians (FU) | Across-glyph CV | Within-glyph CV mean | Within-glyph CV max |
| --- | ---: | ---: | ---: | ---: | ---: |
| source | 62 | 76.739 | 0.07813 | 0.07454 | 0.17484 |
| geometry | 62 | 76.979 | 0.07886 | 0.07890 | 0.19756 |
| candidate | 62 | 74.913 | 0.00952 | 0.05101 | 0.15849 |

These width values are skeleton-distance proxies, not proof of equal perceived weight at joins or small device sizes.

## Per-entry evidence

See [`tsukushi-a-v9-sample-audit.csv`](tsukushi-a-v9-sample-audit.csv) for all 63 sample entries, including the duplicate entry, advances, full glyph bounds, FreeType component/counter counts, and geometry-to-candidate IoU.

The 48 px diagnostic is intentionally reported separately because the source contains hinting and the research candidate does not; pixel-level component counts at small sizes are renderer-dependent.
