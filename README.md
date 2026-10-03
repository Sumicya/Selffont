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

模块 zip 由本地 `python build.py` 产出。CI(`.github/workflows/build.yml`)只做校验(自检 + 一次验证性构建),**没有任何产物**:不发版、不出 artifact、不写 sha256 边车。默认来源与提示性哈希钉在 `build.py` 顶部(哈希漂移只警告,不拦构建);下载缓存在 `build/cache/`,删掉即重新下载。构建 stdout 就是构建报告;没有随包的 report.json。

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

**花体 / 小型大写(Unicode 字符本身,如 𝓐𝓑𝓒、ᴀʙᴄ)**——这类字符不选字体,走逐字回退,而 Gecko 的逐字回退**不读 fonts.xml 顺序**(先按字符语言组查 `font.name-list.*`,再全清单乱序扫描),选中的兜底字体和系统不同 → 同一字符两副面孔。修法 = 让火狐的回退链与 fonts.xml 同序:

- 数学字母数字区(𝓐𝓑𝓒)的语言组是 `x-math`,Gecko 在 Android 的默认名单全是桌面数学字体(设备上没有)——配置补上 x-math 三条(前置文渊);
- 其余语言组的名单,构建时把模块补充字库的**内部家族名按 fonts.xml 顺序**追加到每条 `font.name-list.*` 末尾(火狐只认字件内部名,构建期现场从基础包读取);
- 配置是 `firefox.sh` 装的拷贝:**模块更新时 `customize.sh` 检测到已接入就自动换新**,不用记得重放 `firefox.sh`。

**泛型与家族名的坑**(CSS 写法不同,路径完全不同):

- 泛型关键字(`font-family: cursive/fantasy`,不带引号):all.js 的 Android 段只有 `cursive.x-unicode/x-western` 默认、`fantasy` 一个都没有,zh/ja/ko 下解析成空字体组落平台默认——配置把 cursive/fantasy × 7 语言组补齐。
- 带引号的家族名(`"cursive"`、`"sans-serif-smallcaps"`):走名字解析,而 Gecko 清单只收**字体文件内部家族名**(harfbuzz 读 name 表),fonts.xml 别名进不去 → 落默认字体(Roboto 空壳)。系统侧 `sans-serif-smallcaps` 家族已接管(挤掉 CarroisGothicSC);火狐侧这条路 pref 管不到,是把别名做成真实字件才能修的事(主字体 48.7MB ×4 份,不值)。
- CSS `font-variant: small-caps` 由基础字体合成:基础字体是文渊,小型大写就是文渊。
- 边界:网页**自带的 webfont**(站内装饰字体)不读系统清单,pref 管不到;要一律压成文渊,打开配置里 `browser.display.use_document_fonts: 0` 那行。

验证:`logcat -s GeckoRuntime GeckoDebugConfig | grep -i 'config\|prefs'`,应出现 `Adding debug configuration from:` 与 `Adding prefs from debug config`。想让网页忽略自带字体、一律用文渊,把配置里 `browser.display.use_document_fonts: 0` 那行注释去掉。

emoji:Gecko 在 Android 上认的彩色字体是 `SamsungColorEmoji` / `Noto Color Emoji` / `Noto Color Emoji Flags`(对 emoji 表现字符它优先选带彩色的那张,所以前置不挡彩色);包内字体到底覆盖到哪个码位,拿 fontTools 查 cmap 即可——先拿数据,再谈 Gecko。

## 装完自查(约一分钟)

1. 系统:设置里随便看几行字——字形变圆即生效;通知栏角标数字不再偏低/切下沿(度量归一修复的目标)。
2. 火狐:`logcat -s GeckoRuntime GeckoDebugConfig | grep -i 'config\|prefs'` 应有两行;没有就先跑 `firefox.sh`。
3. emoji:拿一个较新的 emoji 看是否彩色;想看包内覆盖上限,用 fontTools 查 cmap(没有随包报告——查 cmap 是一行的事)。
4. 复原:卸载 = KSU 删模块 + 重启,一切回到系统自带字体。

## 边界

- 真机验证过:Android 16 / OnePlus / KernelSU 一台,其他平台自担风险。
- 本仓库是 [MFGA](https://github.com/Numbersf/MakeFontsGreatAgain) 的 fork。上游领先的提交只动它自己的 Xposed 侧与文档(`fonts/`、`fonts.xml` 从 1717180003 起未变,已逐字节比对):用 `-s ours` 记录了祖先关系(不再显示"落后"),但**不取它的代码**,只取字体资源(见 `LICENSES.md`)。
- `fonts.xml` 里的字体名是「设备自带 + 基础包补充」的并集:基础包只带设备没有的补充字库(Plangothic、天珩、Unicode 新平面、SourceSansPro、ZDigit 等),Noto 全套与 OEM 字体(如 MiSans)由设备提供,不打包。引用两边都没有的字体只会让该条目失效,不中断渲染、也没法在构建期判断——构建只打一行摘要,不出名单。
- 火狐的家族名单来自 Gecko 自己的 `all.js`(Android 段),随 Firefox 版本可能变;名单变了 `firefox.sh install` 重放一次即可,不匹配时 Gecko 只是回到自己的默认字体。
- MFGA 基础包只取字体资源,绝不执行其代码(归属见 `LICENSES.md`)。
- 主字体必须能被 fontTools 解析;`.ttf`/`.otf`/`.ttc` 之外的后缀直接拒绝。
