# Selffont

Android 个人字体模块:**文渊圆体 v1.010 可变字体**(OFL,活跃维护;一个 VF 文件内含 `wght` 100–900 + `ital` 真字重)接管系统字体家族。原生 `fonts.xml` 挂载,模块即全部交付,无伴侣应用。

## 字体

照搬[文渊圆体](https://github.com/takushun-wu/WenYuanFonts/releases/tag/v1.010):字形、cmap、可变轴逐字节不动(构建期逐字形守卫),安装副本只动三处——

1. 竖直行度量归一到基础包的 Roboto 空壳(真机验证:修角标数字偏低/切下沿);
2. 剪除映射到空白字形的码位(上游声称覆盖但字形空白,会吞掉回退链);
3. 按 OFL 保留名规则把内部家族名改成 **Selffont Rounded SC VF**。

字重阶梯现场从字体的 `wght`/`ital` 轴读取(越界夹取);静态字体也能打包,粗体交给系统合成。

## 构建

```sh
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tests/selfcheck.py
.venv/bin/python tools/build.py     # --font 文件或 URL(可重复) / --base 本地 ZIP 或 URL
```

产物 `build/Selffont.zip`(内含 `report.json` 构建报告),CI(`.github/workflows/build.yml`)跑同一条流水线。默认来源与提示性哈希钉在 `tools/build.py` 顶部(哈希漂移只警告,不拦构建);下载缓存在 `build/cache/`,删掉即重新下载。版本号在 `module/module.prop`(KSU 静态惯例)。

## 安装 / 卸载

KSU 装 zip,重启(模块 ID `MFGA`;安装脚本整份替换系统全部 `font*.xml`,不碰 `fonts_customization.xml`)。`action.sh` 是只读诊断。卸载 = KSU 删模块 + 重启。

## 火狐

Gecko 不读系统的 `fonts.xml` 选家族:字体清单来自 Android 系统字体 API,选谁看它自己 `font.name-list.*` 里硬编码的**家族名**。所以字体装好了,Firefox 也不一定用——要单独接一次,走 GeckoView 官方的原生机制,不需要 LSPosed、不改 APK:

```sh
su -c 'sh /data/adb/modules/MFGA/firefox.sh'          # 接入
su -c 'sh /data/adb/modules/MFGA/firefox.sh remove'   # 退出
```

`firefox.sh` 只做两件事:把 `geckoview-config.yaml` 放到 `/data/local/tmp/org.mozilla.firefox-geckoview-config.yaml`,再把 Firefox 设成 Android「调试应用」(`am set-debug-app --persistent`,重启后仍在)——GeckoView 只在这两种情况下读那份配置。配置里每条首选项都是**前置**文渊、后面原样保留 Gecko 自己的回退链;整条覆盖会掐断回退,那才是缺字的来源。

验证:`logcat -s GeckoRuntime GeckoDebugConfig | grep -i 'config\|prefs'`,应出现 `Adding debug configuration from:` 与 `Adding prefs from debug config`。想让网页忽略自带字体、一律用文渊,把配置里 `browser.display.use_document_fonts: 0` 那行注释去掉。

emoji:Gecko 在 Android 上认的彩色字体是 `SamsungColorEmoji` / `Noto Color Emoji` / `Noto Color Emoji Flags`(对 emoji 表现字符它优先选带彩色的那张,所以前置不挡彩色);包内字体到底覆盖到哪个码位,看 `report.json` 的 `emojiCoverage`——先拿数据,再谈 Gecko。

## 边界

- 真机验证过:Android 16 / OnePlus / KernelSU 一台,其他平台自担风险。
- 火狐的家族名单来自 Gecko 自己的 `all.js`(Android 段),随 Firefox 版本可能变;名单变了 `firefox.sh install` 重放一次即可,不匹配时 Gecko 只是回到自己的默认字体。
- emoji 新码位能不能显示,取决于包内字体覆盖(`emojiCoverage`)与 Gecko 的渲染,不写"不可修"这种断言。
- MFGA 基础包只取字体资源,绝不执行其代码(归属见 `LICENSES.md`)。
- 主字体必须能被 fontTools 解析;`.ttf`/`.otf`/`.ttc` 之外的后缀直接拒绝。
