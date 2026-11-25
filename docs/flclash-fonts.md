# FlClash 字体事实（2026-11-26 查证）

对象：`chen08209/FlClash`，分支 `main`。只读，未改。

## 1 它自带什么（pubspec.yaml:91-97）

```yaml
fonts:
  - family: JetBrainsMono
    fonts: [{asset: assets/fonts/JetBrainsMono-Regular.ttf}]      # 273,900 B
  - family: Twemoji
    fonts: [{asset: assets/fonts/Twemoji.Mozilla.ttf}]            # 1,454,532 B
```

`lib/ui/fonts.dart` 的枚举只有这两个：`twEmoji('Twemoji')`、`jetBrainsMono('JetBrainsMono')`。
**没有打包任何 CJK 字体**，也没有把 `fontFamily` 写死成自带家族。

## 2 它怎么选字体（lib/manager/theme_manager.dart:36-46）

```dart
final theme = ThemeData(
  fontFamily: fontFamily,                       // 用户设置，默认 null
  fontFamilyFallback: appFontFamilyFallback(...),
);
```

- `fontFamily` 来自 `themeSettingProvider.fontFamily`，默认 `null`。
- `appFontFamilyFallback` 来自 `package:prism_ui/font.dart`。它自己的测试写死了 Android 的行为
  （`test/common/font_test.dart:89-96`）：

  ```dart
  test('leaves Android to its own locale-aware fallback', () {
    expect(fallback(TargetPlatform.android, const [Locale('en')]), isEmpty);
    expect(fallback(TargetPlatform.android, const [Locale('en')], fontFamily: 'serif'),
           ['Roboto']);
  });
  ```

  ⇒ Android 上 fallback 默认是空表，交给系统自己回退。

## 3 它读系统字体清单的地方（关键）

`lib/common/system_fonts.dart` → `rust_api.systemFontFamilies` →
`plugins/rust_api/rust/src/fonts/android.rs:1-6`：

```rust
const FONTS_XML: &str = "/system/etc/fonts.xml";
pub fn families() -> Result<Vec<String>, String> {
    let xml = std::fs::read_to_string(FONTS_XML).map_err(...)?;
    Ok(named_families(&xml))
}
```

⇒ **FlClash 自己直接读 `/system/etc/fonts.xml`**，只取 `<family name="...">` 的 name 属性，
用来填设置里的「字体」选择器。匿名族（无 name）它看不见。

## 4 由此得到的判据

1. 默认（用户没选字体）时，Flutter 侧 `fontFamily` 为 null，引擎用平台默认族，Android 上是
   `sans-serif`——**正是 `module/skia.sh` 现在插的那一族**（见 CHANGELOG 2026-11-26 第一条）。
   所以「插入 sans-serif 对 FlClash 应该有效」这个推理成立。
2. 但主人实测**没变**。那么剩下的可能是：
   - 甲：ColorOS 17 的 Skia 不读 `/system/etc/fonts.xml`（本仓只有 AOSP Skia 源码证据，
     没有 ColorOS 实测证据）。
   - 乙：读到了，但我们的字件按 `name="sans-serif"` **被建成第二个独立族**而不是替换原有族，
     Skia 取到的是先建成的那个（Skia 源码注释明说 `customizationType` 被忽略、同名族会遮蔽）。
   - 丙：FlClash 用的 Flutter 引擎版本里 `GetDefaultFontFamilies()` 返回的不是 `sans-serif`。
3. 有一个**零成本的判定动作**，不需要改任何配置：FlClash 的设置里有字体选择器，它列的就是
   `/system/etc/fonts.xml` 里的命名族。打开设置 → 字体，看列表里有没有我们的家族名。
   - 有 ⇒ 文件读到了（排掉甲），问题在族匹配（乙/丙）。
   - 没有 ⇒ 甲成立，Skia 那条路对我们无效，必须换路（进程内 hotswap／整份替换）。

## 5 与 MFGA 的对比（同一份文件）

本仓 `fonts.xml` 与 MFGA 的 `fonts.xml` diff 只有 9 行，全是我们加的
`NotoMusic`/`NotoEmoji`/`Noto-COLRv1` 三族。MFGA 的投放是**整份 `cp` 替换**
（`script/search_dirs.sh:70-84`），本仓是**插入**。MFGA 的「全字符覆盖」依赖设备自带的
`NotoSansCJK-Regular.ttc` 等字件（它一支 CJK 都不打包），与本仓现状相同。
