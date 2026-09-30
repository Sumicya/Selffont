# Selffont

Android 个人字体模块:**文渊圆体 v1.010 可变字体**(OFL,活跃维护;一个 VF 文件内含 `wght` 100–900 + `ital` 真字重)接管系统字体家族。原生 `fonts.xml` 挂载,模块即全部交付,无伴侣应用。

## 字体

照搬[文渊圆体](https://github.com/takushun-wu/WenYuanFonts/releases/tag/v1.010):字形、cmap、可变轴逐字节不动(构建期逐字形守卫),安装副本只动三处——

1. 竖直行度量归一到基础包的 Roboto 空壳(真机验证:修角标数字偏低/切下沿);
2. 剪除映射到空白字形的码位(上游声称覆盖但字形空白,会吞掉回退链);
3. 按 OFL 保留名规则把内部家族名改成 **Selffont Rounded SC VF**。

字重阶梯现场从字体的 `wght`/`ital` 轴读取(越界夹取);静态字体也能打包(全档同文件,粗体交给系统合成)。

## 构建

整个构建链是一个 Python 文件,自检内建其中:

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python build.py --check    # 自检:无框架、无夹具,不下载不打包
.venv/bin/python build.py            # --font 文件或 URL / --base 本地 ZIP 或 URL
```

产物 `build/Selffont.zip`,CI(`.github/workflows/build.yml`)跑同一条流水线。默认来源与提示性哈希钉在 `build.py` 顶部(哈希漂移只警告,不拦构建);下载缓存在 `build/cache/`,删掉即重新下载。构建 stdout 就是构建报告;没有随包的 report.json。

版本号由构建时盖戳:**`version=vYY.M.D.<总构建数>`、`versionCode=<总构建数>`**(KSU 靠 versionCode 比新旧,所以它单调递增)。CI 传 `github.run_number`:

```sh
SELFFONT_BUILD=42 .venv/bin/python build.py   # 或 build.py --build 42
```

仓库里的 `module.prop` 是未盖戳的本地默认(`versionCode=0`);不是 CI 不许自己编构建数。日期按 UTC+8 取,免得 CI 在 UTC 下差一天。自检核对版本号末尾的构建数与 versionCode 一致。

## 安装 / 卸载

KSU 装 zip,重启(模块 ID `MFGA`;安装脚本整份替换系统全部 `font*.xml`,不碰 `fonts_customization.xml`)。卸载 = KSU 删模块 + 重启。

## 火狐

Gecko 不读系统的 `fonts.xml` 选家族:字体清单来自 Android 系统字体 API,选谁看它自己 `font.name-list.*` 里硬编码的**家族名**。所以字体装好了,Firefox 也不一定用——要单独接一次,走 GeckoView 官方的原生机制,不需要 LSPosed、不改 APK:

```sh
su -c 'sh /data/adb/modules/MFGA/firefox.sh'          # 接入
su -c 'sh /data/adb/modules/MFGA/firefox.sh remove'   # 退出
```

`firefox.sh` 只做两件事:把 `geckoview-config.yaml` 放到 `/data/local/tmp/org.mozilla.firefox-geckoview-config.yaml`,再把 Firefox 设成 Android「调试应用」(`am set-debug-app --persistent`,重启后仍在)——GeckoView 只在这两种情况下读那份配置。配置里每条首选项都是**前置**文渊、后面原样保留 Gecko 自己的回退链;整条覆盖会掐断回退,那才是缺字的来源。

**花体 / 随意 / 小型大写**(源码为证的三个坑,不是玄学):

- Gecko 的字体清单只收**字体文件内部家族名**(harfbuzz 读 name 表),fonts.xml 的别名(`cursive`、`sans-serif-smallcaps`)不在清单里——网页写这些名字时走的是泛型 pref 或默认字体回退。
- all.js 的 Android 段只有 `cursive.x-unicode/x-western` 两个默认,`fantasy` 一个都没有;zh/ja/ko 语言组下 `font-family: cursive` 解析成**空字体组**,不补默认泛型,直接落 `GetDefaultFont()`(清单第一个家族 = Roboto 空壳)——花体行因此不渲染文渊。配置里把 CJK + 西文的 cursive/fantasy 全部补齐。
- 小型大写:`sans-serif-smallcaps` 家族系统侧一并接管(原来漏了,CarroisGothicSC 还留在系统清单里可被按文件名解析);CSS `font-variant: small-caps` 由基础字体合成,基础字体是文渊就是文渊小型大写。
- 边界:网页**自带的 webfont**(站内装饰花体/小型大写)不读系统清单,pref 管不到;要一律压成文渊,打开配置里 `browser.display.use_document_fonts: 0` 那行。

验证:`logcat -s GeckoRuntime GeckoDebugConfig | grep -i 'config\|prefs'`,应出现 `Adding debug configuration from:` 与 `Adding prefs from debug config`。想让网页忽略自带字体、一律用文渊,把配置里 `browser.display.use_document_fonts: 0` 那行注释去掉。

emoji:Gecko 在 Android 上认的彩色字体是 `SamsungColorEmoji` / `Noto Color Emoji` / `Noto Color Emoji Flags`(对 emoji 表现字符它优先选带彩色的那张,所以前置不挡彩色);包内字体到底覆盖到哪个码位,拿 fontTools 查 cmap 即可——先拿数据,再谈 Gecko。

## 边界

- 真机验证过:Android 16 / OnePlus / KernelSU 一台,其他平台自担风险。
- 本仓库是 [MFGA](https://github.com/Numbersf/MakeFontsGreatAgain) 的 fork。上游领先的提交只动它自己的 Xposed 侧与文档(`fonts/`、`fonts.xml` 从 1717180003 起未变,已逐字节比对):用 `-s ours` 记录了祖先关系(不再显示"落后"),但**不取它的代码**,只取字体资源(见 `LICENSES.md`)。
- `fonts.xml` 里的字体名是「设备自带 + 基础包补充」的并集:基础包只带设备没有的补充字库(Plangothic、天珩、Unicode 新平面、SourceSansPro、ZDigit 等),Noto 全套与 OEM 字体(如 MiSans)由设备提供,不打包。引用两边都没有的字体只会让该条目失效,不中断渲染、也没法在构建期判断——构建只打一行摘要,不出名单。
- 火狐的家族名单来自 Gecko 自己的 `all.js`(Android 段),随 Firefox 版本可能变;名单变了 `firefox.sh install` 重放一次即可,不匹配时 Gecko 只是回到自己的默认字体。
- MFGA 基础包只取字体资源,绝不执行其代码(归属见 `LICENSES.md`)。
- 主字体必须能被 fontTools 解析;`.ttf`/`.otf`/`.ttc` 之外的后缀直接拒绝。
