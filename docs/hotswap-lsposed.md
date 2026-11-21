### 进程内热切换：`hotswap`（LSPosed，未真机验证）

挂载四条路全断（见上表），只剩进程内。模块名 `sumicya.selffont.hotswap`，工作流 `hotswap`，
产物 `hotswap-<SHA8>`（可直接装的 APK），源码在 `lsp/hotswap/`。

它做的三件事，全在目标进程里，不碰分区、不碰挂载：

1. `Typeface.create(String, int)`——第一次按家族名取字时，把 `sSystemFontMap` 里能对上文件的家族换掉；
2. `Typeface.createFromFile(String)` / `(File)`——路径 basename 对得上就换成自己的那份；
3. 反射 `sSystemFontMap` 直接替换（字段不可写就只靠前两条，日志写清楚）。

字体放在模块 APK 的 `assets/fonts/<家族名>.ttf`（`sans-serif.ttf`、`serif.ttf`、`monospace.ttf` …），
**不放 `/data/adb`**：那是 root 专属，普通应用进程读不到。所以换字 = 装新 APK + 重启目标应用，
不用重启整机。

```sh
# 拿包：Actions → hotswap → 最新一次 → Artifacts → hotswap-<SHA8>
# 装：adb install 或手机文件管理器点开；LSPosed 管理器 → 模块 → 勾选；
#     作用域先只勾 com.android.settings，验证过再扩。
# 看日志：logcat -s SelfFontHotswap
# 删：LSPosed 管理器关闭模块 → 卸载 APK → 重启目标应用（无挂载残留，不用 panic）
```

| logcat | 含义 |
| --- | --- |
| `家族表替换 n/m 个` | 生效，n 个家族被换 |
| `模块里没有 assets/fonts/*.ttf` | APK 里没编进字体 |
| `换家族表失败 … ` | 字段不可写或 Map 只读，看异常名 |
| 一行都没有 | 模块没加载（作用域没勾 / 目标应用没重启） |

**未验证**：ColorOS 16 上 `sSystemFontMap` 是否可写、替换后 `cmd font update` 之外是否还要软重启
system_server、系统 UI 的性能影响。装完先看设置应用的界面，再扩作用域。
