# Maruko Gothic 字符覆盖基线审计

固定源提交：`97e9dd4a2fdde58084dde8d022de253f8d8415e9`。输入是该提交的静态 TTF；此报告只审计 cmap / 轮廓存在性，
不等同于完整标准认证、字形视觉合格或设备上的最终回退结果。

## 字体元数据与覆盖概况

| 文件标签 | 内部家族 / 子家族 | UPM | OS/2 字重 | 可变轴 | cmap 映射数 | glyph 数 | SHA-256 |
|---|---|---:|---:|---|---:|---:|---|
| Light | Maruko Gothic CJKsc Light / Light | 1000 | 300 | 无（静态字体） | 31,943 | 31,904 | `5236beda2cc5019ed8f1bfc02dbd18f4e59e7286ddf9f2948ad23dfde6836391` |
| Regular | Maruko Gothic CJKsc Regular / Regular | 1000 | 400 | 无（静态字体） | 33,944 | 33,889 | `e3709389bce13fa75af28cc2370b6175520d97f74dfbf3894ca24838f47241b7` |
| Medium | Maruko Gothic CJKsc Medium / Medium | 1000 | 500 | 无（静态字体） | 33,996 | 33,871 | `b357990f8a1a30cec5e4502fb318b71b35e9e86b5ccd92e017c0f494d436f79d` |

## OpenType 区域／脚本替换能力

| 文件标签 | GSUB features / scripts | GPOS features / scripts |
|---|---|---|
| Light | `aalt, case, ccmp, frac, fwid, hwid, ordn, sups, vert, vkna, vrt2` / `DFLT` | `kern, mark, mkmk` / DFLT |
| Regular | `aalt, case, ccmp, frac, fwid, hwid, ordn, sups, vert, vkna, vrt2` / `DFLT` | `kern, mark, mkmk` / DFLT |
| Medium | `aalt, case, ccmp, frac, fwid, hwid, ordn, sups, vert, vkna, vrt2` / `DFLT` | `kern, mark, mkmk` / DFLT |

`locl` locale-specific GSUB feature: absent in all inputs. Without it, the font cannot select different glyph outlines by locale through `locl`; regional shaping must come from locale-specific fallback fonts or separately authored regional forms.

| Unicode 区块（范围计数，不是目标集合百分比） | Light | Regular | Medium |
|---|---:|---:|---:|
| CJK Radicals Supplement | 112 | 114 | 114 |
| Kangxi Radicals | 20 | 20 | 20 |
| CJK Symbols and Punctuation | 29 | 64 | 64 |
| Hiragana | 93 | 93 | 93 |
| Katakana | 96 | 96 | 96 |
| Bopomofo | 41 | 43 | 43 |
| Bopomofo Extended | 24 | 28 | 28 |
| CJK Strokes | 36 | 36 | 36 |
| CJK Compatibility Forms | 20 | 32 | 32 |
| Halfwidth and Fullwidth Forms | 158 | 225 | 225 |
| CJK Unified Ideographs Extension A | 6,579 | 6,582 | 6,582 |
| CJK Unified Ideographs | 20,976 | 20,977 | 20,977 |
| CJK Compatibility Ideographs | 361 | 363 | 363 |
| CJK Unified Ideographs Extensions B onward | 2,285 | 2,471 | 2,471 |
| Hangul Jamo | 0 | 255 | 255 |
| Hangul Compatibility Jamo | 0 | 42 | 42 |
| Hangul Syllables | 0 | 0 | 0 |
| Latin-1 Supplement | 96 | 96 | 96 |
| Latin Extended A/B | 8 | 226 | 227 |
| Greek and Coptic | 73 | 84 | 84 |
| Cyrillic | 66 | 115 | 115 |
| Hebrew | 0 | 29 | 44 |
| General Punctuation | 25 | 38 | 38 |
| Mathematical Operators | 36 | 77 | 77 |
| Box Drawing | 32 | 128 | 128 |
| Musical Symbols | 0 | 0 | 0 |

## 同字重覆盖差异

下表只说某档的 cmap 是否有该码位，不表示对应轮廓是否好看。

- `Light` 相对 `Regular`：少 2,001 个码位，多 0 个码位。
  - CJK/地区区块中少 314 个，例：U+2E80, U+2EBD, U+3016, U+3017, U+3018, U+3019, U+301A, U+301B, U+301E, U+3021, U+3022, U+3023, U+3024, U+3025, U+3026, U+3027, U+3028, U+3029, U+302A, U+302B …
- `Medium` 相对 `Regular`：少 0 个码位，多 52 个码位。

## 可打印编码表对照（仅作目标集代理）

集合由当前 Python 运行时的 codec 映射枚举，并排除了 Unicode 控制、格式、分隔符、
私用区及未分配码位；它不是标准机构的正式合规测试。特别是 CP949 的覆盖缺口反映
韩文块是否存在，不应被解释成简体中文的缺字率。

| 比较集合 | 可打印码位数 | Light 命中 / 缺失 | Regular 命中 / 缺失 | Medium 命中 / 缺失 |
|---|---:|---:|---:|---:|
| GB2312 (CPython codec) | 7,538 | 7,447 / 91 | 7,538 / 0 | 7,538 / 0 |
| GBK (CPython codec) | 21,884 | 21,672 / 212 | 21,884 / 0 | 21,884 / 0 |
| Big5-HKSCS (CPython codec) | 18,479 | 18,251 / 228 | 18,477 / 2 | 18,477 / 2 |
| Shift_JIS (CPython codec) | 7,037 | 7,033 / 4 | 7,037 / 0 | 7,037 / 0 |
| CP949 (CPython codec) | 17,140 | 5,676 / 11,464 | 5,912 / 11,228 | 5,912 / 11,228 |

## 轮廓存在性提示（不是缺字判定）

空轮廓映射可能是空格、占位符或组合字元，也可能是缺陷，必须结合 Unicode 类别、
排版行为与视觉结果逐项分类；零 advance 同样可能是合法组合符。

- `Light`：空轮廓映射 4 个（U+0020, U+00A0, U+2003, U+3000）；零 advance 8 个（U+0300, U+0301, U+0302, U+0303, U+0307, U+0308, U+030A, U+0327）；复合 glyph 映射 123 个。
- `Regular`：空轮廓映射 13 个（U+0020, U+00A0, U+0339, U+0345, U+037A, U+0384, U+0457, U+04E8, U+115F, U+2002, U+2003, U+3000, U+FFA0）；零 advance 8 个（U+0300, U+0301, U+0302, U+0303, U+0307, U+0308, U+030A, U+0327）；复合 glyph 映射 123 个。
- `Medium`：空轮廓映射 13 个（U+0020, U+00A0, U+02BE, U+037A, U+0384, U+0457, U+04E8, U+115F, U+2002, U+2003, U+2779, U+3000, U+FFA0）；零 advance 8 个（U+0300, U+0301, U+0302, U+0303, U+0307, U+0308, U+030A, U+0327）；复合 glyph 映射 123 个。

## 初步结论与下一步

1. Light 的 cmap 映射数明显少于 Regular / Medium，差异不仅是冷僻 CJK；先分开确认
   是上游字重覆盖差异还是需要制作 Light 轮廓，不能直接把较重字形复制到 Light。
2. 三档上游都没有 Hangul 音节区；Regular / Medium 有 Hangul Jamo，Light 的 Jamo 覆盖也不同。当前用户方向是不只依赖系统回退；因此已从 SC Regular 自有 Jamo 生成 11,172 个音节作原型，**不代表** Light/Medium、TC/JP 或 KR Han 地区覆盖完成（见 [全映射 Hangul 原型报告](full-map-sc-regular-korean-prototype.md)）。
3. CPython `GB2312` / `GBK` / `Big5-HKSCS` / `Shift_JIS` / `CP949` 只用于发现差异；
   后续应依据用户确定的码位目标和设备回退链复核，不能把 codec 命中率冒充标准认证。
4. 覆盖审计与字形美术审查是两项工作：下一步分别建立码位缺口清单和常用字形视觉问题清单。
5. 这是 CJK SC 三档基线；固定提交中还存在同源 CJK TC / CJK JP 静态字重，完整地区对照见 [regional-coverage-audit.md](regional-coverage-audit.md)。
6. 上游 TTF 未改写；本轮另在 `/tmp` 生成了未入库的 SC Regular + Hangul 静态研究候选，包含 62 唯一字形样本的笔宽原型及全映射曲线重拟合。它没有接入 `build.py` 或生产字体路由，也未变成要求 `wght` 可变轴的生产构建（范围见 [当前候选报告](full-map-sc-regular-korean-prototype.md)）。

编码表与字重差异逐码位清单：[`coverage-gaps.tsv`](coverage-gaps.tsv)（13,282 行；
同一码位可出现在多个比较集合）。
