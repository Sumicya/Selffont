# 第一阶段：行为契约与证据

## 已确认的边界

1. 只支持 Android 16（API 36）、Oplus 系、KSU、LSPosed 2.2.0（7854）；框架接口要求现代 API 102。
2. 统一字体家族，不抹平粗体、斜体、小型大写，也不改写 Unicode、DOM 或用户输入。
3. 文渊圆体为首选候选，资源圆体次选；SELFUSE 的 FZYJHK 是用户提供的外观参考，不作为可自由分发的字体来源推断。
4. 删除上色及整字体／区间屏蔽。其他进程数据的干预必须是手动兜底。
5. LSPosed 作用域唯一，不在模块里再加包名名单。
6. 未匹配系统 `font*.xml` 默认整体替换，保留明确的不同-schema 例外 `fonts_customization.xml`。这是一项用户选择的偏激进策略，不等于已验证所有配置路径。

## 职责划分

| 层 | 负责 | 不负责 |
|---|---|---|
| 字体来源 `config/font-source.json` | 版本、哈希、家族名、安装文件名、许可 | 下载后擅自换源或改字形 |
| 主机工具 `prepare_font.py` / `font_config.py` / `build_module.py` | 校验字体、生成字体族配置、从显式基础 ZIP 取补充字体 | 执行基础包脚本、操作设备 |
| KSU 安装 | 环境门槛、整份配置挂载准备 | 开机改权限、自动停应用、自动清理缓存 |
| `FontForceCore` | 在 Java Typeface 工厂结果层替换家族、保留 weight/italic | 覆盖所有原生引擎、替换原方法异常或 null |
| `GeckoFontPolicy` | 构造新的默认首选项 Map，保留原 Map 及无关设置 | 改浏览器 profile、CSS、原始文本 |
| `ModernEntry` | 作用域内安装 Hook、探测 Gecko 接口与字体可见性、分阶段日志 | 第二套应用名单、把安装成功当作渲染成功 |
| 手动 Shell / WebUI | 明确副作用与退出码、记录与恢复本版本修改的权限 | 从翻译字符串猜成功、开机自动干预 |

只为当前明确的两种加载路径建立接口，不预先创建覆盖所有 ROM 或所有渲染器的插件框架。Gecko 只依赖运行时类探测，不捆绑 GeckoView AAR。

## 核对过的外部证据

### 字体

- 上游：<https://github.com/takushun-wu/WenYuanFonts/releases/tag/v1.010>
- 原版文件 SHA-256：`e9ebde68d6d45ad5998765505677d1fb95821318fc693982f873e73fc27a2122`
- 已读取实物：family `WenYuan Rounded SC VF`；PostScript `WenYuanRoundedSCVF`；`wght` 100/400/900，`ital` 0/0/1；best cmap 33,029 个映射。
- 不以单个主字体的映射数量宣称 Unicode 全覆盖。缺字继续依赖补充字体和引擎回退。
- 不含 `smcp` 不代表应取消小型大写：浏览器可以合成。字体名匹配、CSS 特性和字符码点属于不同层。
- 原版字体保持字节不变；安装文件改名只是路径选择。附带完整 OFL/RFN 声明，不把衍生字体假冒为文渊原版。

### Firefox / GeckoView

用户报告：155.0.1 (Build #2016182535)，`5fdfd0092780e85643e2cddc0e1b590c8b9ef860`，GV 155.0.1-20260903215306，AS 155.0，Android 16。

用户报告的 revision 未作为 GitHub Git SHA 解析成功，因此没有把它直接等同于已检查的代码提交。检查的是官方发布标签 `FIREFOX_155_0_1_RELEASE`，GitHub 提交 `fb95137a04eb8fe1196cb12f26b100c1e060295c`：

- `mobile/android/geckoview/src/main/java/org/mozilla/geckoview/RuntimeSettings.java`：`getPrefsMap()` 返回只读映射。
- 同目录 `GeckoRuntime.java`：启动时调用 `settings.getPrefsMap()`，将结果传入 `GeckoThread.InitInfo`。
- 同目录 `GeckoRuntimeSettings.java`：`webFontsEnabled` 对应整数首选项 `browser.display.use_document_fonts`。
- Gecko 的 `gfx/thebes/gfxFT2FontList.cpp` 有独立的系统／文件／内存字体路径，不能用几个 Java Typeface 工厂当作网页渲染的充分入口。

源码链接基址：<https://github.com/mozilla-firefox/firefox/tree/FIREFOX_155_0_1_RELEASE>

本阶段的适配是在这个启动入口**复制** Map，再加入默认字体首选项。对照组不可见目标文件则原样返回。已进一步核对同标签下 `org/mozilla/gecko/mozglue/GeckoLoader.java`：启动 Map 序列化为 `MOZ_DEFAULT_PREFS` 环境变量，而非由本适配器写入 profile。没有锁定或重写已有 profile 用户首选项，已有覆盖值可能胜出，必须真机验证；若这一点阻止预期效果，需要进一步定位正确的运行时首选项接口，不能偷偷改 profile 文件。

### Xposed

使用 `io.github.libxposed:api:102.0.0`，对应上游标签：<https://github.com/libxposed/api/tree/102.0.0>。最低 API 也设为 102，不再声明能在 API 100 上运行 API 102 入口。

## 不变量与失败行为

- 原方法抛出的异常传播；原方法返回 null 仍为 null。
- 只有替换操作自身失败才回到原 Typeface；线程重入保护在异常时也释放，不跨线程串扰。
- `deoptimize` 失败不会阻止继续尝试安装 Hook；每个入口安装结果独立记录。
- 字体不可读不修改 Gecko 首选项；接口不存在只记录不支持，不扫描任意原生地址。
- 不记录页面文字、浏览记录或完整用户 profile。
- 权限先记账再修改，记录跨模块更新保存。只恢复对应文件身份且仍为 000 的文件；后续用户／应用更改、替换的文件不强行还原。
- `errno` 是当前 KernelSU bridge 的返回契约；非零不因输出含“成功”而变成零。

主要家族也包括 `monospace`。当前选择是将它统一为同一比例圆体，不能同时保证原来的代码列对齐／等宽度量；这是强制家族统一的明确代价，不属于保留粗斜体和小型大写的承诺。

## 尚不能承诺

- 完整字体模块安装、Oplus 的实际字体路径与 KSU 在 Firefox 进程中的字体挂载可见性。新 APK 加载已确认。
- 当前设备上的 Firefox 已保留并调用该方法，且进入了本适配器的可读性检查；这不外推其他发布版本、入口或后续偏好覆盖行为。
- Firefox 用户首选项、字体隐藏／指纹防护、缓存和原生内容进程是否影响选择。
- 网页专用图标字体或图形内容是否仍正确。强制族名可能让字体图标缺失。
- 完整真实基础包的端到端装机结果，以及未来 Firefox/LSPosed 版本的接口兼容性。
