# 字形工作台 / Glyph Lab

A static, local-first browser workspace for comparing a source font with an optional licensed reference, trying per-glyph raster weight and proportion adjustments, and recording review decisions.

## Run

From the repository root:

```sh
python3 -m http.server 4173 --bind 0.0.0.0 --directory tools/glyph-lab
```

Open `http://localhost:4173` in a desktop browser. The preview sandbox can serve the same directory on `0.0.0.0`.

## Use

1. Load a local TTF/OTF/WOFF file as the source font. Optionally load a second font for visual comparison.
2. Select any glyph in the fixed 63-entry / 62-unique sample, or filter by character/code point.
3. Adjust raster weight, width, height, and position per glyph. Mark its review state, intent, and notes.
4. Export a PNG for the current preview or export/import a JSON file containing all per-glyph settings and comments. A local-storage copy is also kept in this browser.

Suggested licensed references are linked in the app: [LXGW WenKai](https://github.com/lxgw/LxgwWenKai) (OFL-1.1; a Chinese handwriting-oriented design reference) and [Noto Sans SC](https://github.com/google/fonts/tree/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/notosanssc) (OFL-1.1; a useful weight reference). Use them to compare design principles; do not trace or copy their glyph outlines. For direct outline work in a desktop editor, see [FontForge](https://github.com/fontforge/fontforge).

## Important limits

- Font files stay in the browser and are not uploaded. The app does not bundle a font.
- The weight slider uses a binary-style raster morphology preview; width/height/position are canvas transforms. These controls are **not** vector contour edits and do not produce a TTF/OTF.
- PNG and JSON exports are review artifacts only. Use the JSON and notes to guide later, explicit vector-outline work; visually approve every glyph at actual font sizes before accepting a candidate.
- The per-glyph intent selector is an annotation only; it does not automatically straighten, remove hooks, round endpoints, or redraw glyphs. Use it and the note field to record the desired vector edit.
