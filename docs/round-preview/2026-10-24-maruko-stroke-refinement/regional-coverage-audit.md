# Maruko Gothic 多地区静态字重覆盖审计

固定来源为同一上游提交 [`97e9dd4a2fdde58084dde8d022de253f8d8415e9`](https://github.com/max32002/maruko-gothic/tree/97e9dd4a2fdde58084dde8d022de253f8d8415e9)。
三套地区字形均来自 Maruko Gothic 本身；本报告的 cmap/轮廓签名差异是技术审计，不等同于字形美术验收或国家标准认证。

## 来源与元数据

| 地区 | 字重 | 内部家族 / 子家族 | OS/2 weight | UPM | cmap | glyph 数 | 轴 | SHA-256 |
|---|---|---|---:|---:|---:|---:|---|---|
| SC | Light | Maruko Gothic CJKsc Light / Light | 300 | 1000 | 31,943 | 31,904 | 静态 | `5236beda2cc5019ed8f1bfc02dbd18f4e59e7286ddf9f2948ad23dfde6836391` |
| SC | Regular | Maruko Gothic CJKsc Regular / Regular | 400 | 1000 | 33,944 | 33,889 | 静态 | `e3709389bce13fa75af28cc2370b6175520d97f74dfbf3894ca24838f47241b7` |
| SC | Medium | Maruko Gothic CJKsc Medium / Medium | 500 | 1000 | 33,996 | 33,871 | 静态 | `b357990f8a1a30cec5e4502fb318b71b35e9e86b5ccd92e017c0f494d436f79d` |
| TC | Light | Maruko Gothic CJKtc Light / Light | 300 | 1000 | 31,938 | 31,904 | 静态 | `e1ace552ee2f1e6f322b225252457522cf901233a40d7a2d82ce22b2f12ea041` |
| TC | Regular | Maruko Gothic CJKtc Regular / Regular | 400 | 1000 | 33,663 | 33,609 | 静态 | `c45c89a986fb0b2ef604ec9ddf2e0294a6598473dfb154ca85134339969d258c` |
| TC | Medium | Maruko Gothic CJKtc Medium / Medium | 500 | 1000 | 33,996 | 33,871 | 静态 | `ca4e7a70066f005bf6e0cd9e6a984851c73cdb11f099da0e4fc112e28e44f1ec` |
| JP | Light | Maruko Gothic CJKjp Light / Light | 300 | 1000 | 32,011 | 31,952 | 静态 | `55dd6adf26b87d8f3d09683b63b7002184bc1a98d206e8c4338b782209320e97` |
| JP | Regular | Maruko Gothic CJKjp Regular / Regular | 400 | 1000 | 33,650 | 33,584 | 静态 | `f0a6d7a44fba6c3e55c803fa9443a9a747ff6385408cb9feac60055ee3c0e93a` |
| JP | Medium | Maruko Gothic CJKjp Medium / Medium | 500 | 1000 | 33,995 | 33,929 | 静态 | `387d649001a83bb0c45021d19e726ff9dd741013e0f182a3bd0e273243b2074f` |

本矩阵仅比较三地区共有的 Light / Regular / Medium；固定提交还提供 JP Bold / Black，但 SC / TC 没有对应静态文件，故未纳入横向比较。

## CJK 区块映射数

### SC

| 区块 | Light | Regular | Medium |
|---|---:|---:|---:|
| Han BMP | 20,976 | 20,977 | 20,977 |
| Han Extension A | 6,579 | 6,582 | 6,582 |
| Han Compatibility | 361 | 363 | 363 |
| Han Supplementary B onward | 2,285 | 2,471 | 2,471 |
| CJK Punctuation | 29 | 64 | 64 |
| CJK Radicals and Kangxi | 132 | 134 | 134 |
| Bopomofo | 41 | 43 | 43 |
| Kana | 189 | 189 | 189 |
| Hangul Jamo | 0 | 255 | 255 |
| Hangul Compatibility Jamo | 0 | 42 | 42 |
| Hangul Syllables | 0 | 0 | 0 |

### TC

| 区块 | Light | Regular | Medium |
|---|---:|---:|---:|
| Han BMP | 20,976 | 20,977 | 20,977 |
| Han Extension A | 6,579 | 6,582 | 6,582 |
| Han Compatibility | 361 | 363 | 363 |
| Han Supplementary B onward | 2,285 | 2,471 | 2,471 |
| CJK Punctuation | 29 | 64 | 64 |
| CJK Radicals and Kangxi | 132 | 134 | 134 |
| Bopomofo | 41 | 43 | 43 |
| Kana | 189 | 189 | 189 |
| Hangul Jamo | 0 | 255 | 255 |
| Hangul Compatibility Jamo | 0 | 42 | 42 |
| Hangul Syllables | 0 | 0 | 0 |

### JP

| 区块 | Light | Regular | Medium |
|---|---:|---:|---:|
| Han BMP | 20,976 | 20,977 | 20,977 |
| Han Extension A | 6,579 | 6,582 | 6,582 |
| Han Compatibility | 361 | 363 | 363 |
| Han Supplementary B onward | 2,360 | 2,471 | 2,471 |
| CJK Punctuation | 26 | 64 | 64 |
| CJK Radicals and Kangxi | 133 | 123 | 134 |
| Bopomofo | 41 | 43 | 43 |
| Kana | 189 | 189 | 189 |
| Hangul Jamo | 0 | 255 | 255 |
| Hangul Compatibility Jamo | 0 | 42 | 42 |
| Hangul Syllables | 0 | 0 | 0 |

## 地区 cmap 差异与同码位轮廓差异

`轮廓签名差异`按 expanded TrueType coordinates、contour endpoints 与 on-curve flags 的精确值比较。
这不是曲线几何等价测试：点序/组件展开方式不同会被记为差异；报告也不判断地区字形是否正确，需独立人工校稿。

| 字重 | 比较 | 共同 Han 码位 | 仅左侧 Han 码位 | 仅右侧 Han 码位 | 仅坐标不同 | 点数/端点/on-curve flags 不同 |
|---|---|---:|---:|---:|---:|---:|
| Light | SC ↔ TC | 30,201 | 0 | 0 | 190 | 1,295 |
| Light | SC ↔ JP | 30,201 | 0 | 75 | 1 | 28,416 |
| Light | TC ↔ JP | 30,201 | 0 | 75 | 1 | 28,416 |
| Regular | SC ↔ TC | 30,393 | 0 | 0 | 2 | 30,292 |
| Regular | SC ↔ JP | 30,393 | 0 | 0 | 1 | 30,362 |
| Regular | TC ↔ JP | 30,393 | 0 | 0 | 0 | 28,017 |
| Medium | SC ↔ TC | 30,393 | 0 | 0 | 0 | 29,879 |
| Medium | SC ↔ JP | 30,393 | 0 | 0 | 0 | 29,970 |
| Medium | TC ↔ JP | 30,393 | 0 | 0 | 0 | 30,091 |

All nine inputs are static; locale-specific GSUB `locl` is absent in every input. For regional forms, select the matching SC/TC/JP font family by locale instead of expecting one file to switch itself.

## Korean coverage and other script limits

The pinned repository tree has SC, TC, and JP families, but no KR family; all nine source fonts have zero mapped Hangul syllables `U+AC00..U+D7AF`. Regular and Medium each map 255 modern Hangul Jamo, while Light maps none. Following the user's direction not to stop at system fallback, a SC Regular research prototype now composes all 11,172 Hangul syllables from Maruko's own Jamo; see [the prototype report](full-map-sc-regular-korean-prototype.md). This is not a complete KR font: no Light/Medium/TC/JP Hangul work or KR Han forms are included, and production still relies on its configured fallback because the prototype is not integrated.
No Music Symbols are mapped. Arabic and Devanagari are also outside these CJK files' current cmap coverage. Keep script-specific fonts in the fallback chain rather than silently borrowing their outlines.

## Implications for expansion

1. This same Maruko commit already provides separate SC / TC / JP static families. Use them as the first-party source for those three locales; do not synthesize regional Han forms from SC alone.
2. Coverage differs by region and weight. Audit the exact target codepoint sets before editing; the `Light` family is substantially smaller than Regular/Medium in all three locales.
3. Cmap presence is not proof of a usable outline or correct region glyph. The next visual pass must review common/standard test strings per locale, then classify missing-codepoint, topology, local-stroke, and style issues separately.
4. The current production builder expects a variable `wght` font. All nine source files are static. Integrating them requires a deliberate static-family build path or validated variable-font construction; none has been done here.

Regional/weight cmap differences: [`regional-coverage-gaps.tsv`](regional-coverage-gaps.tsv) (2,074 rows; codepoints not present in all nine files).
