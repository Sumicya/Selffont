# Selffont

Android 个人字体模块：**Selfrounds CJK**（自研，SIL OFL 1.1 衍生物；可变字体 `wght` 300–500）接管系统的主字体家族。

## 要求

- 设备需带 `font_fallback*.xml`（Android 15+）；没有该文件的机器安装直接中止，参见「项目限制」。
- 已安装 KernelSU，且挂载了类元模块（metamodule）——缺了它模块装得上但不生效。
- 本地构建需要 Python 3 与 `requirements.txt` 里的依赖（主要是 `fontTools`）；CI 只做校验，不代替本地构建产出发布物。

## 功能

**本来各有自己字体的命名族（等宽 / 手写 / 小型大写等）保持原样**，缺 CJK 时才落到主字体。原生 `fonts.xml` 挂载，模块即全部交付，无伴侣应用。模块 zip 由本地构建产出，CI 只做校验。

照搬 [Maruko Gothic](https://github.com/max32002/maruko-gothic)（固定提交 `97e9dd4`，`CJK SC` 目录）：字形、cmap 逐字节不动（构建期逐字形守卫），安装副本只动三处——

1. 竖直行度量归一到基础包的 Roboto 空壳（真机验证：修角标数字偏低/切下沿）；
2. 剪除映射到空白字形的码位（上游声称覆盖但字形空白，会吞掉回退链）；
3. 内部家族名统一改成 **Selffont SC**（母版的 OFL 没有保留名，改名不是许可要求，是为了配置与火狐名单写一个名字）。

字重是**两档静态**（Regular 400 / Medium 500，取自母版同目录的两个文件），配置里逐档列出；请求 700 落 500，请求 300 落 400。母版另有 Light（33.8 MB），需要三档时在 `MARUKO_SC["files"]` 里加一项即可。

模块只带**一份字体配置**：`font_fallback.xml`（Android 15+ 的新配置）。可变主字体走的是一条 `supportedAxes` 字件（运行时实例化），本模块的两档静态按 weight 逐条列出——两条路 `configure_fonts()` 都支持，由主字体来源决定。

缺字回退分两个区，两边都要放主字体（AOSP `font_fallback.xml` 头注：家族分默认家族、命名家族、**locale fallback family** 三类，缺字时按「完整 BCP-47 标签（含 script）→ 仅语言 → 顺序」匹配）：

- **默认区**（不带 `lang` 的匿名家族，按文件顺序）：主字体作为一条匿名家族紧随默认家族，排在最前。
- **语言区**（带 `lang` / `variant` 的 locale fallback family，按语言标签优先匹配）：中日韩语言区（`zh` / `zh-Hans` / `zh-Hant,zh-Bopo` / `ja` / `ko`…）一律把主字体前置，区内原有字件（`NotoSansCJK` 等）原样留在后面——**覆盖只加不减**。只往默认区插一条是不够的：中文场景缺字会先在语言区里命中厂商字体，主字体根本轮不到。
- 非 CJK 语言区（`und-Arab` 之类）与 emoji 区（`und-Zsye`）逐字不动：那些字形主字体没有，插进去只会挡路。
- **不要的厂商字体连引用一起清掉**：`MiSans`（模板里 `lang="zh"` 那条 `MiSansL3.otf`，以及火狐名单里的 `MiSans VF` / `MiSans TC` 等）在生成的配置与火狐名单里都不留——中文缺字不落到它上面，继续往默认区的补充字库（天珩 / Unicode 新平面等）走。清掉后空掉的家族节点一并删除，标注它的注释也删。安装时把它投放到设备实际会读的每一份配置上（内容都是这同一份新语法）：AOSP 的 `font_fallback*.xml`，以及 ColorOS 的 `/system_ext/etc/fonts_base.xml` 与 `fonts_ule.xml`——**读哪份按厂商而定**，只换 AOSP 那份时 ColorOS 会继续用厂商配置，字体看起来「没生效」；**库存 `fonts.xml` 另走一条路，且只插不换**：Android 框架读上面那几份，而 Skia 把配置路径写死成 `/system/etc/fonts.xml`（`SkFontMgr_android_parser.cpp` 第 31/777 行），Flutter（FlClash 这类）、WebView、部分厂商小组件全走 Skia。只换框架那几份时这些程序一个字都不变（2026-10-28 真机：Selffont 在该文件里出现 **0** 次，另三份各 16 次）。安装脚本在设备自己那份文件上做最小插入：新建匿名默认族、`sans-serif` 族与中日韩语言族的最前面加我们的字件，**OEM 字件（OPPO Sans 等）一行都不许删**——整份替换会把它们删掉，天气小组件就掉回 OPPO Sans。设备一份可替换的框架配置都没有（Android 15 以下）时安装直接中止，不留下半套配置。

## 安装与使用

### 安装 / 卸载

KSU 装 zip，重启（模块 ID `MFGA`；安装脚本替换设备实际会读的框架配置（AOSP 的 `font_fallback*.xml`、ColorOS 的 `fonts_base.xml` / `fonts_ule.xml`），并在 `/system/etc/fonts.xml` 上做只插不换的最小插入（Skia 程序靠它）；`fonts_customization.xml` 不碰；框架配置一份都没有的设备中止安装）。卸载 = KSU 删模块 + 重启。Release 只放最新一版的 zip 与 `SHA256SUMS.txt`（Actions artifact 5 天过期，别从那里下）。

管理器安装：KernelSU → 模块 → 从存储安装 → 选解压出的 zip → 重启。Magisk：模块 → 从本地安装 → 选同一个 zip → 重启（不重启也能先看效果时，用下面的热切换）。

命令行安装（Termux / adb，需 root）：先把 zip 搬到 `/data/local/tmp` 再装——`ksud` 直接读 Termux 家目录或 `/sdcard` 路径常因挂载命名空间 / SELinux 报 `No such file or directory`：

```sh
ZIP=$(ls -t "$PWD"/Selffont-*.zip | head -1)            # 定位刚解出的模块 zip
ls -l "$ZIP" && unzip -l "$ZIP" | head -5               # 约 100 MB；根部有 module.prop 才对
su -c "cp '$ZIP' /data/local/tmp/selffont-module.zip"   # 搬进 root 能读的 /data/local/tmp
su -c 'ls -l /data/local/tmp/selffont-module.zip'       # 字节数应与上一步一致
su -c 'ksud module install /data/local/tmp/selffont-module.zip'
su -c 'rm -f /data/local/tmp/selffont-module.zip'
su -c reboot                                            # 或手动重启
```

装完字体没变时，按序查三条：管理器里模块已启用且已重启；`su -c 'for f in /system/etc/font_fallback.xml /system_ext/etc/fonts_base.xml /system_ext/etc/fonts_ule.xml; do [ -f "$f" ] && echo "$f Selffont=$(grep -c Selffont "$f")"; done'`——设备读了哪份，就该有哪份被换（ColorOS 只查后两行；全是 0 或文件不存在说明选错了配置文件）；KernelSU 需要挂载类元模块（metamodule）才能把模块内容挂进系统——缺了它模块装得上但不生效（`mount | grep MFGA` 能看到才说明挂上了）。

若 `cp` 被 SELinux 拦：先在 Termux 里 `cp "$ZIP" ~/storage/downloads/`（`termux-setup-storage` 给的软链），再 `su -c 'cp /sdcard/Download/<文件名> /data/local/tmp/'` 后照上装。

### 热切换（不重启）

**要解决的问题**：模块平时靠 KernelSU 的 magic mount 在**开机时**把字件叠到只读分区上，
改一次字体就要重启一次；系统设置里换字体是当场生效的。

**五条硬规矩**（2026-10-31 两次真机事故之后定的，脚本里逐条守，`build.py --check` 逐条验）：

1. **不许任何形式的整目录 bind 到 /system 路径**。目录只走 overlay；`mount --bind` 只收
   **常规文件**，而且目标必须是系统里已经存在的文件。事故现场：`mount --bind
   /data/adb/selffont/merged /system/fonts` → `/proc/mounts` 里成了
   `/dev/block/dm-76 on /system/fonts type f2fs`（bind 继承源文件系统的设备与类型）。
   守卫只有一处 `guard_mount()`：源不是常规文件、或源落在 `upper/ work/ merged/` 里，直接拒。
2. **空文件占位只在 `SELFFONT_SYSTEM_ROOT` 假根下建**。真机上 `/system` 只读，建了也是
   `Read-only file system`；而且会在 `/data` 里留下成排 0 字节文件（事故现场：
   `merged/` 246 个 0 字节、`du` 15 KB）。真机路径上遇到系统里没有的配置文件是**跳过并说明**。
3. **挂之前记录 mnt_id，摘的时候认 mnt_id**。每个单元挂之前把目标当前顶层 mnt_id 记进
   `/data/adb/selffont-hotswap.pre`，挂完再记我们这一层的 mnt_id 进账（
   `kind|相对路径|mnt_id`）。`off`/`panic` 只摘「顶层 mnt_id 等于我们记的那个」的挂载点；
   被别的东西盖住就打印「我们这层 mnt_id X 上面还压着 Y」，**不猜、不摘别人的层**。
   路径相同不是证据，mnt_id 才是。
4. **失败一定回滚**：计划先落 `journal`，每挂成功一个追加 `done`；任何单元失败、或结束时
   数出我们的 overlay 不是恰好一条，就按 `done` 反序摘回去、清账，打印「已回滚到挂之前」。
   上一次挂到一半被打断（`journal` 还在）时，`on` 先跑一次 `panic` 再挂。
5. **`panic`**：摘掉本脚本挂过的全部挂载点（认账里的 mnt_id + 只扫「`upperdir=` 是我们的」
   或「挂载点就在 `upper/work/merged` 里」的孤儿，**不按 `/data` 前缀乱认**），删
   `merged/`、`upper/`、`work/` 与全部账，最后打印 `/proc/mounts` 里与 `fonts` 相关的剩余行。
   还有层摘不掉时**不删 `upper/`**——正挂着的 overlay 还在用它，删了 `/system/fonts` 会读失败；
   这时报「重启后再跑一次 panic」，退出码 1。

**具体怎么挂**：

```sh
mount -t overlay overlay -o lowerdir=/system/fonts,upperdir=/data/adb/selffont/upper,workdir=/data/adb/selffont/work /system/fonts
```

upper 里放模块字件的**副本**（不硬链接——upper 里的文件不能有指向外面的第二个链接，
否则挂载阶段就可能 `EINVAL`）。26 个文件约 147 MB，一次几秒；workdir 每次挂之前清空。
`SelfroundsCJK-VF-<版本>.ttf` 这类新名字从 upper 长出来，系统原有的字件仍从 lower 读到。

进 init 的挂载命名空间：`nsenter -t 1 -m sh <本脚本> __ns apply <计划文件>`。
nsenter 后面只许跟 `sh`——`nsenter -t 1 -m mount --bind …` 会被它的 getopt 把 `--bind`
当成自己的选项（真机原样输出：`nsenter: Unknown option 'bind'`）。

**命令**（`su -c` 里跑；管理器里点模块的「操作」按钮等于第一条）：

```sh
su -c 'sh /data/adb/modules/MFGA/action.sh'                  # 切换：off→on / on→off
su -c 'sh /data/adb/modules/MFGA/action.sh status'           # on / off / partial
su -c 'sh /data/adb/modules/MFGA/action.sh verify'           # 逐文件 sha256，0=一致
su -c 'sh /data/adb/modules/MFGA/hotswap.sh panic'           # 出事时的清场（认 mnt_id，不摘别人的层）
su -c 'sh /data/adb/modules/MFGA/hotswap.sh on --dry-run'    # 只打印计划
```

| 命令 | 正常输出 | 不对时看什么 |
| --- | --- | --- |
| `action.sh` | `挂上 N 个单元、M 个文件（字体目录一次 overlay，配置逐个 bind）` | `挂载失败：…（mount: …）` 后必须跟 `回滚：…` + `已回滚到挂之前`，否则跑 `panic` |
| `action.sh status` | `on` / `off` / `partial` | `partial` = 挂载表里认得出的单元不够数 |
| `action.sh verify` | `verify：一致 N，不一致 0`，退出码 0 | 退出码 1 且列 `不一致：`/`缺：`/`没挂：`；空账也返回 1 |
| `hotswap.sh panic` | `摘下：…` 若干、`删掉了 …`、`---- /proc/mounts 里与 fonts 相关的剩余行 ----` | 剩下 `umount` 不掉的会注明「重启后会消失」 |

**边界**：已开的程序不会自己重画（Typeface 是进程内缓存），除 `--reload=system` 外都要
重开那个程序；挂进去的是 **init 的挂载命名空间**，你的 `su` 若带命名空间隔离，
`ls /system/fonts` 看不到属正常，用 `ls /proc/1/root/system/fonts`；`off` 只摘这一次运行时的
挂载，重启后 magic mount 按模块状态重新叠上。

**没验的部分照实说**：overlay 能不能在这台 ROM 的 init 命名空间里一次挂成功、
SELinux 放不放行、`cmd font update` 会不会真推新 Typeface、软重启后是否全局重读——都是
真机事实。`build.py --check` 每次只验我自己的部分：计划形状（恰好一条 overlay、没有逐字体
bind）、守卫（目录 bind 被拒）、记账与回滚（overlay 失败时把已挂的摘回去）、`panic` 清场。

**真机验收**（原样贴回来）：

```sh
su -c 'sh /data/adb/modules/MFGA/hotswap.sh on'
su -c 'awk "\$2 == \"/system/fonts\"" /proc/1/mountinfo | wc -l'   # 我们挂完应当比开机多 1 层
su -c 'sh /data/adb/modules/MFGA/hotswap.sh verify'; echo "退出码 $?"
su -c 'ls /proc/1/root/system/fonts | grep -c .'
su -c 'cat /proc/uptime'
```

### 火狐

Gecko 不读系统的 `fonts.xml` 选家族：字体清单来自 Android 系统字体 API，选谁看它自己 `font.name-list.*` 里硬编码的**家族名**。所以字体装好了，Firefox 也不一定用——要单独接一次，走 GeckoView 官方的原生机制，不需要 LSPosed、不改 APK：

```sh
su -c 'sh /data/adb/modules/MFGA/firefox.sh'          # 接入
su -c 'sh /data/adb/modules/MFGA/firefox.sh remove'   # 退出
```

`firefox.sh` 只做两件事：把 `geckoview-config.yaml` 放到 `/data/local/tmp/org.mozilla.firefox-geckoview-config.yaml`，再把 Firefox 设成 Android「调试应用」（`am set-debug-app --persistent`，重启后仍在）——GeckoView 只在这两种情况下读那份配置。配置里每条首选项都只**插入**不清空，后面原样保留 Gecko 自己的回退链（整条覆盖会掐断回退，那才是缺字的来源）。谁排在最前，看这个泛型在系统里本来是什么字体：`sans-serif` / `serif` / `emoji` 本来就是主字体（`serif` 是旧数字字件、`sans-serif` 是度量空壳），主字体在最前是把火狐改掉的恢复回来；`monospace` / `cursive` / `fantasy` 本来是 Droid Sans Mono / Dancing Script / Coming Soon（`fonts.xml` 的 `monospace` / `cursive` / `casual`），**本来是什么字体就保持什么字体**，主字体只紧随其后兜这些字体没有的 CJK。

**花体 / 小型大写（Unicode 字符本身，如 𝓐𝓑𝓒、ᴀʙᴄ）**——这类字符不选字体，走逐字回退，而 Gecko 的逐字回退**不读 fonts.xml 顺序**（先按字符语言组查 `font.name-list.*`，再全清单乱序扫描），选中的兜底字体和系统不同 → 同一字符两副面孔。修法 = 让火狐的回退链与 fonts.xml 同序：

- 数学字母数字区（𝓐𝓑𝓒）的语言组是 `x-math`，Gecko 在 Android 的默认名单全是桌面数学字体（设备上没有）——配置补上 x-math 三条（前置主字体）；
- 其余语言组的名单，构建时把模块补充字库的**内部家族名按 fonts.xml 顺序**追加到每条 `font.name-list.*` 末尾（火狐只认字件内部名，构建期现场从基础包读取）；
- 配置是 `firefox.sh` 装的拷贝：**模块更新时 `customize.sh` 检测到已接入就按当前开关状态重生成**，不用记得重放 `firefox.sh`，也不会把你切过的网页字体开关覆盖掉。

**泛型与家族名的坑**（CSS 写法不同，路径完全不同）：

- 泛型关键字（`font-family: cursive/fantasy`，不带引号）：all.js 的 Android 段只有 `cursive.x-unicode/x-western` 默认、`fantasy` 一个都没有，zh/ja/ko 下解析成空字体组落平台默认——配置把 cursive/fantasy × 7 语言组补齐。
- 带引号的家族名（`"cursive"`、`"sans-serif-smallcaps"`）：走名字解析，而 Gecko 的字体清单只收**写进系统配置的字件**。曾试过给这些别名各发一枚「别名字件」（家族名 = 别名、无字形），2026-10-05 真机实测（OnePlus / ColorOS 16）**解析不到**：20 个空格的宽度与默认链完全相同，别名字件的 0.5em 空格没有出现。又因为每条 `font.name-list.*` 都被我们前置了主字体，命中与不命中最终渲染一致——既不可见也无收益，**已删除**（`build.py` 不再产别名字件、也无 `--no-alias-fonts` 开关）。
- 网页**自带的 webfont**（站内装饰字体、Google Fonts、图标字体）：不读系统清单，字体 pref 管不到，只有 `browser.display.use_document_fonts` 一个开关——**默认压成主字体**（全系统同一副面孔）。放行的两条路：打包时 `--keep-web-fonts`（当默认值烧进 zip），或运行时在 KernelSU 管理器里点模块的**「操作」按钮**切换（命令行等价 `su -c 'sh /data/adb/modules/MFGA/web-fonts.sh keep'`，状态存 `/data/local/tmp/selffont-web-fonts.state`）。放行后网页按自己的字体渲染、图标字体正常，代价是网页上的装饰字体不再是主字体；`web-fonts.sh status` 看当前状态。
- CSS `font-variant: small-caps` 由基础字体合成：基础字体是主字体，小型大写就是主字体。

验证：`logcat -s GeckoRuntime GeckoDebugConfig | grep -i 'config\|prefs'`，应出现 `Adding debug configuration from:` 与 `Adding prefs from debug config`。

emoji：Gecko 在 Android 上认的彩色字体是 `SamsungColorEmoji` / `Noto Color Emoji` / `Noto Color Emoji Flags`（对 emoji 表现字符它优先选带彩色的那张，所以前置不挡彩色）；包内字体到底覆盖到哪个码位，拿 fontTools 查 cmap 即可——先拿数据，再谈 Gecko。

### 装完自查（约一分钟）

1. 系统：设置里随便看几行字——字形变圆即生效；通知栏角标数字不再偏低/切下沿（度量归一修复的目标）。
2. 火狐：`logcat -s GeckoRuntime GeckoDebugConfig | grep -i 'config\|prefs'` 应有两行；没有就先跑 `firefox.sh`。
3. emoji：拿一个较新的 emoji 看是否彩色；想看包内覆盖上限，用 fontTools 查 cmap（没有随包报告——查 cmap 是一行的事）。
4. 复原：卸载 = KSU 删模块 + 重启，一切回到系统自带字体。

## 构建

整个构建链是一个 Python 文件，自检内建其中：

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python build.py --check                  # 自检:无框架、无夹具,不下载不打包
.venv/bin/python build.py --build 47 --day 3 --date 26.10.6   # 或手工传三段(离线;缺一段就报错不出包)
.venv/bin/python build.py --font 文件或URL --base 本地ZIP或URL
.venv/bin/python build.py --keep-web-fonts         # 放行网页自带字体（默认压成主字体）

# 改一个字的预览路径：只编选中的字，17 秒出母版对照图（全量构建约 53 分钟）
.venv/bin/python build.py --preview 鬱響鬢 --compare 母版.ttf
# 两把验收尺，都只吃字体文件、不经过构建期代码
.venv/bin/python tools/freetype_iou.py 母版.ttf 本版.ttf --all          # 汉字全码位逐像素 IoU
.venv/bin/python tools/kern_measure.py --master 母版.ttf --verify 本版.ttf  # 8,347 对字偶距白
```

设计取向写在 `docs/design-principles.md`，其中能复算的条目给了命令、阈值与现值。

**复算上面几组数要什么**：母版是公开发布的字件（Maruko Gothic，钉在提交 `97e9dd4`，不进仓库），
下面这条命令取到的 20,084,736 B 文件 sha256 = `e3709389bce13fa75af28cc2370b6175520d97f74dfbf3894ca24838f47241b7`（2026-10-31 10:18 UTC+8 现取核对）：

```sh
gh api -H "Accept: application/vnd.github.raw" \
  "repos/max32002/maruko-gothic/contents/CJK%20SC/MarukoGothicCJKsc-Regular.ttf?ref=97e9dd4" -o maruko.ttf
```

| 数 | 命令 | 额外需要 | 实测耗时（2026-10-31 UTC+8） |
| --- | --- | --- | --- |
| 3 字预览 IoU 0.908 | `build.py --preview 鬱響鬢 --compare maruko.ttf` | 只要母版 | 19.5 s（10:19） |
| 8,347 对 Δ白中位 1.3 | `tools/kern_measure.py --master maruko.ttf --verify 本版.ttf` | 母版 + 本版 | 3.2 s（09:59） |
| 20,977 字 IoU 中位 0.929、最低 0.731 | `tools/freetype_iou.py maruko.ttf 本版.ttf --all` | 母版 + 本版 | 3 分 23 秒（10:02） |

「本版」= `build.py --cjk-font DIR` 出的 `SelfroundsCJK-VF.ttf`（全量构建约 53 分钟，2026-10-31 09:30 UTC+8 那次构建的产物）。

产物名跟版本走：`build/Selffont-<版本>.zip`；没有规范版本数据就不出包（取数失败停止出包和上传）。输入侧不降级：基础包缺 Roboto 空壳、或 `--font` 给的字体没有 `wght` 轴，都直接报错退出（不做「跳过归一」或「全档同文件」的降级）。默认来源与提示性哈希钉在 `build.py` 顶部（哈希漂移只警告，不拦构建）；下载缓存在 `build/cache/`，删掉即重新下载。构建 stdout 就是构建报告；没有随包的 report.json。

**版本号（展示不含 `v`）**：五段 `yy.m.d.当日序号.总序号`；`versionCode` = 最后一段（总序号，KSU 靠它比新旧，单调递增）。日期按 UTC+8 取，免得 CI 在 UTC 下差一天。

- **号源只有一处：CI 运行数**。总序号 = `build.yml` 本次运行的 `run_number` 原值，不做基线相减；改工作流文件名或换号源后数值变小照常使用（设备端模块覆盖安装即可）。不读 git 提交数、不读时间戳、不读本地计数。
- **当日序号用差值锚定法**：当日（`run_started_at` 转 UTC+8）现存 `build.yml` 运行的最小 `run_number`，与当日现存产物 `Selffont-yy.m.d.d0.r0` 反推的 `r0 - d0 + 1`，两者取小作当日首条运行号 `R_first`（都没有就取当前 `run_number`），当日序号 = 当前 `run_number - R_first + 1`。失败运行同样占号，PR 运行永不计入；同一 `run_id` 重试保持同一版本号。
- **取号留痕**：`build.py --query-ci` 打印 head SHA、run_id、run_number、R_first、当日序号与最终版本，取不到即退出，不降级、不编数。
- **五段恒定**：CI 一定有当日序号；四段只在本地手工省略 `--day` 时出现。
- **本地不出 CI 号**：`--query-ci` 只在 CI 里成立，本地打包必须显式传齐 `--date/--day/--build`，数的可追溯性由打包的人负责。
- `module/module.prop` 在仓库里保持 `version=dev` / `versionCode=0` 只是入库默认值，盖戳时被覆盖，自检核对盖戳格式与 versionCode 一致。

CI 固定两个工作流：`build.yml`（`Build`，只接 `push`[不限分支] / `workflow_dispatch`）三个 job——`build` 只读（`contents: read` + `actions: read`），取号出包上传；`cleanup-artifacts`（`needs: build` + `if: always()`）清产物与运行记录；`cleanup-releases`（`if: always()` 且限默认分支，只授 `contents: write`）清 Release 与孤立 tag。`pr-check.yml`（`PR check`，只接 `pull_request`）的 `check` job 只跑自检、不取号不出包，`cleanup-artifacts` job 不带 `needs`、始终运行。artifact 名 = `Selffont-<版本>`，**包内根目录就是 `module.prop`，网页下载下来可直接刷**（构建仍先产出 `build/Selffont-<版本>.zip`，CI 解开后上传目录内容），`retention-days: 5` 只是时间兜底，`overwrite: true` 让重试不撞名。

清理统一由 `.github/scripts/cleanup.py` 执行，按 `CLEANUP_SCOPE` 分两种互不混权的任务；两个工作流顶层的 `SEGMENTS: "5"` 与 `CLEANUP_APPLY: "true"` 保持一致。

- **artifact/run**：两个工作流的 `cleanup-artifacts` job 共用同一份 `.github/scripts/cleanup.py` 与同一个 `selffont-cleanup` concurrency 锁（`cancel-in-progress: false`），均声明 `actions: write` + `contents: read`，只动 `Selffont-` 前缀的对象。artifact 五条判据按序执行：① 版本段数 = `SEGMENTS`；② 来源运行是 `pull_request` 一律删；③ 同日同当日序号按来源运行的 `run_started_at` 删旧留新；④ 号源口径——末段总序号必须等于来源运行的 `run_number`，切换过渡期全仓还没有新口径产物时暂留最新 1 个旧产物；⑤ 数量——全仓按 `created_at` 保留最新 5 个，且来源运行必须仍在所属工作流保留的最新 5 条内。每个工作流的 run 最多保留最新 5 条，超限的未完成 run 先取消、转成 completed 后由下一轮删除；当前运行永不取消、不删除。
- **Release/tag**：`build.yml` 的独立 `cleanup-releases` job 只在默认分支运行，只声明 `contents: write`；保留最新一个 Release，删除不再关联保留 Release 的 `Selffont-` 前缀 tag。CI 不创建 Release、tag 或正式 asset。
- **安全与失败处理**：所有待执行对象和端点先完整打印，再开始删除；checkout 一律默认浅克隆（取号与清理都只读 API，不再读 git 历史）。403 明确打印对象、端点和状态，标为未执行并继续；复核会注明清理未完成，不将权限缺口说成成功。403 以外的失败使 job 标红。Release/tag 清理删除 tag 前还会重新核对 Release 仍否引用该 tag，避免 Release 删除失败后误删其 tag。

```sh
# 下载最近一次 build.yml 运行的 artifact；artifact 包内根目录直接是 module.prop，可直接刷
RUN=$(gh api 'repos/Sumicya/Selffont/actions/workflows/build.yml/runs?per_page=20' --jq '.workflow_runs[0].id')
set -- $(gh api "repos/Sumicya/Selffont/actions/runs/$RUN/artifacts" --jq '.artifacts[0] | "\(.id) \(.name)"')
curl -fL -H "Authorization: token $(gh auth token)" -o "$2.zip" \
  "https://api.github.com/repos/Sumicya/Selffont/actions/artifacts/$1/zip"
ls -l "$2.zip" && unzip -p "$2.zip" module.prop

# 只读查看 Release、tag、artifact 与工作流运行记录；以下命令本身不删除
gh api --paginate repos/Sumicya/Selffont/releases --jq '.[] | "\(.published_at) \(.id) \(.tag_name)"'
gh api --paginate repos/Sumicya/Selffont/tags --jq '.[] | .name'
gh api --paginate repos/Sumicya/Selffont/actions/artifacts \
  --jq '.artifacts[] | "\(.created_at) \(.id) \(.name) \(.size_in_bytes)"'
gh api --paginate repos/Sumicya/Selffont/actions/workflows/build.yml/runs \
  --jq '.workflow_runs[] | "\(.created_at) \(.id) \(.run_number) \(.status)"'
gh api --paginate repos/Sumicya/Selffont/actions/workflows/pr-check.yml/runs \
  --jq '.workflow_runs[] | "\(.created_at) \(.id) \(.run_number) \(.status)"'
```

### 产物构成（为什么约 100 MB）

| 内容 | 大小量级 |
| --- | --- |
| 主字体（Maruko SC Regular 20.0 MiB + Medium 20.9 MiB，归一度量后的安装副本） | 约 41 MiB |
| 补充字库（`fonts.xml` 引用、基础包里有的那几个：Plangothic、Unicode*-New、NotoSansPro、ZDigit 等） | 约 54 MiB |
| 配置与脚本（`font_fallback.xml`、`customize.sh`、火狐配置） | 不到 0.1 MiB |

主字体从「一个 46 MiB 的可变字体」换成「两个 20 MiB 的静态字体」，产物总量基本持平。装完想自己看构成：`unzip -l Selffont-<版本>.zip | sort -k1 -nr | head -15`。

## 项目限制

- 只支持带 `font_fallback*.xml` 的设备（Android 15+）：装在没有该文件的机器上会中止安装。装机核对过：Android 16 / OnePlus / KernelSU 一台。其中**配置层有命令输出为证**（三份配置的 `grep -c`、`/proc/mounts`）；**渲染层只有 2026-10-05 当次目视，未留图像**（系统字形变圆、火狐网页字体开关切换生效都属这一类）；别名字件实验留下了可复核的量化依据（20 个空格宽度与默认链相同、0.5em 未出现），判定无效后已删除。其他平台自担风险。**未验证**：纯 AOSP 机器的配置路径、CJK 语言区改动——装机核对清单见下方「未验证项的真机清单」。
- 本仓库是 [MFGA](https://github.com/Numbersf/MakeFontsGreatAgain) 的 fork。上游领先的提交只动它自己的 Xposed 侧与文档（`fonts/`、`fonts.xml` 从 1717180003 起未变，已逐字节比对）：用 `-s ours` 记录了祖先关系（不再显示「落后」），但**不取它的代码**，只取字体资源（见 `LICENSES.md`）。
- `fonts.xml` 里的字体名是「设备自带 + 基础包补充」的并集：基础包只带设备没有的补充字库（Plangothic、天珩、Unicode 新平面、SourceSansPro、ZDigit 等），Noto 全套与其余 OEM 字体由设备提供，不打包（`MiSans` 不要，引用已在构建期清掉，见「功能」）。引用两边都没有的字体只会让该条目失效，不中断渲染、也没法在构建期判断——构建只打一行摘要，不出名单。
- 火狐的家族名单来自 Gecko 自己的 `all.js`（Android 段），随 Firefox 版本可能变；名单变了 `firefox.sh install` 重放一次即可，不匹配时 Gecko 只是回到自己的默认字体。
- MFGA 基础包只取字体资源，绝不执行其代码（归属见 `LICENSES.md`）。
- 主字体必须能被 fontTools 解析；`.ttf`/`.otf`/`.ttc` 之外的后缀、缺空壳的基础包都直接拒绝。单个文件的主字体必须是含 `wght` 轴的可变字体（否则无法声明 `supportedAxes`）；多档静态只能像 `MARUKO_SC` 那样成组给出。自研汉字字件是**可变字体**，装机表现与主字体同一条路径，未单独验证。

### 自研汉字：可变字体

模块的主字体是**自研汉字字库**：从 Maruko 的骨架量出笔画中线与逐笔半宽，构建时按固定拓扑描边，
编成一份可变字体（`wght` 300–500，默认 400，三档命名实例 Light / Regular / Medium），
作为独立 `<family>` 排在主字体之前（同族混静态与可变会让 ColorOS 16 卡第一屏）。

**当前产物**（2026-10-31 构建，数字以 `build.py --cjk-font` 的输出为准）：

| 项 | 值 |
| --- | --- |
| 数据 | `tools/design_cjk.bin` 33,931 码位（汉字 30,519、非汉字 3,412） |
| 可变字件 | `SelfroundsCJK-VF.ttf` 70,071,540 B、33,932 字形、零拒 |
| 静态实例 | 300 / 400 / 500 = 30,424,648 / 30,516,792 / 30,552,556 B |
| 行框 | `hhea` 与 typo 930 / −250 / 0；`usWin` 1307 / 529，盖住墨迹 −529…1307 |
| 字宽 | `一` 1000、`a` 541（母版 535）、`A` 667（653）、`e` 521（524）、`o` 563（539）、`1` 383（383）、空格 250（母版 280） |
| 字偶距 | GPOS **5,682 对**、23,186 B；目标表 `tools/kern_targets.bin` 18,054 B（95×95） |

**构建期的硬规则**（逐条断言，不靠「差不多」）：

1. **逐笔半宽**：同一字里每一笔按自己的横截面量，不许整字共用一个数。
2. **三档点数逐一相同**：可变字体的前提。所以描边不走布尔运算，走固定拓扑（等参数采样 + 法向偏移 + 固定段数半圆）；
   `pathops` 的点数会随粗细变（88~90、116~117），不能用。
3. **母版只提供中线与笔宽**：轮廓数、面积比、包围盒不拿来当验收标尺。
4. **行框锚定设备上的度量空壳**：`hhea`/typo 取空壳的 930 / −250 / 0，`usWin` 盖住全库墨迹包络。
   字宽自算：全角固定一个 em，半角按本字墨宽 + 侧距，空白四分之一 em。
   **墨迹位置按母版**：符号不重新居中、不改 `lsb` 的排版位置（只让 `lsb == xMin` 自洽）。
5. **空白字符要有零画笔字形**：空格 / 不断行空格 / 全角空格在母版里没有轮廓，不补就会逐字回退。
6. **不是每个码位都是笔画**：实心几何符号走**面填**（5 单位行距切横带、每带半径 3.25 的胶囊、相邻行重叠 1.5）。
7. **半宽沿中线逐点变化**：SFCJ5 每笔存一段剖面，描边按剖面偏移、外角补局部半径的圆弧；剖面只乘比例不加点，三档点数不变。
8. **描边输出二次曲线**：密采样（弦高 0.10 单位 + 弧长 8 单位）→ 最小二乘拟合 → 二次曲线写入 `glyf`；
   三档共用同一套段划分与 on/off 序列，切分只在 400 档判。端点切向用三点圆，不用弦方向。

**间距的两把尺**（2026-10-31 重做，之前那把是坏的）：

- **字母侧距**：`21 + 60 × 贴边覆盖率`，夹 16–88。覆盖率只看**字身带**（baseline…cap，y ∈ −20…700）的
  逐行左右缘——钩、尾、`Q` 的下摆伸到字身外，不能参与决定侧距（否则 `j` 会整体右移）。系数在母版
  52 个字母 104 个侧面上最小二乘，中位误差 **4.0** 单位。
- **数字、标点、符号**：母版对它们是逐个手调的，套公式中位误差 48、最大 194（`+` 922 被压到 728）。
  改成**逐字表**：`tools/side_measure.py` 量母版的前进量 + 墨心，存 `tools/side_targets.bin`
  （1,095 字、8,764 B），构建期按墨心摆、前进量照表。ASCII 前进量误差中位 **1** 单位。
- **字偶距**：目标是母版**真排**时每一对的最小墨迹白（`tools/kern_measure.py` 用 HarfBuzz 读 GPOS 量，
  存 95×95 的表），构建期用本字**画出来之后**的轮廓算同一个白再相减。`Ay` −183、`AT` −288、
  `HH` 0、`oo` −26、`te` −9；|差| < 5 单位不写。
- **验收用独立的尺**：FreeType 逐行出像素 + HarfBuzz 真排，ASCII 全部 **8,347 对**逐对比最小墨迹白
  （不经过构建期代码）：Δ 中位 **1.3** 单位、p90 **3.3**、≤5 单位 **97.4%**、≤10 单位 **99.8%**。
  汉字用同一把 FreeType 尺比**母版 cmap 里的全部 20,977 个字**（同基线、同像素尺寸），不是挑几个字。

**判据（与母版无关）**：轮廓不自交、不越字身框、笔画半宽 0.02–0.09 em；交叉口量胖的短笔在构建期
收回整字中位 0.7–1.25 倍；汉字里与所有中线都不相交、长边 < 0.10 em 的孤立碎墨按脏污清掉，
非汉字的小墨点一律不动（独立字点按母版里那团圆墨的半径画，交叉口的接点标记不画）。

### 还剩多少（2026-10-31 量，不挑好看的报）

每一条都写「怎么量的」，不只写结论。

- **拉丁字对：已对上**。同一把独立尺（FreeType 逐行出像素 + HarfBuzz 真排，不用构建期代码）
  量 ASCII 可打印区全部 **8,347 对**：Δ白（母版 vs 本版的最小墨迹白）中位 **1.3** 单位、
  p90 **3.3**、≤5 单位 **97.4%**、≤10 单位 **99.8%**；`te` 164.5/164.5、`Ay` 55.5/54、
  `HH` 168/168、`oo` 94/94.5。剩下 17 对超 10 的（`~a` 408/226、`%+` 329/464、`FJ` −32/101）
  是母版自身就极端的组合（负白、被压到撞墨），GPOS 的 −320 下限与目标口径咬不上，未修。
- **单字侧距**：52 个字母的 lsb/rsb 与母版差中位 **5 单位**（最大 `S` 22、`Y` 14）；
  前进量差中位 **10.5 单位**（最大 `S` 40）。字母宽度是自算的（墨宽 + 侧距），没照搬母版。
- **汉字：全码位 IoU 中位 0.929，最低 0.731**。`.venv/bin/python tools/freetype_iou.py 母版.ttf 本版.ttf --all`
  比两个字体 cmap 交集里 **U+4E00–U+9FFF 的全部 20,977 个字**（200 px、同基线、允许 ±1 px 整格对齐）：
  中位 **0.929**、p10 0.912、最低 **0.731**（`墫` `巽` `瑨`）；不对齐时中位 0.927、最低 0.724，
  说明差异是**形状与边缘**，不是整体错位。墨量比中位 **0.977**；19.5% 的字需要 1 px 对齐（中位 5 单位）。
  最差 8 字见 `docs/evidence/2026-10-31-hanzi-worst.png`（上排母版、下排本版）。
- **汉字点数仍是母版的 1.49 倍**（22 字抽样：`鸞` 667/391、`龘` 950/540）：这是边缘位移的直接来源，
  也是「不如母版」最可量的一面。下一轮按字复杂度分档收紧拟合容差，以 `docs/design-principles.md`
  第 2 条的「中位 ≥0.95、最低 ≥0.85」为验收，不以点数为唯一目标。
- **`A` 尖 `y −16..673`（母 0..700）、`V` 起点 `29..709`（母 −1..700）、`4` 高 `−4..666`（母 0..704）**：
  取笔与字面校准的差，不是间距。
- **空格 250 vs 母版 280**：四分之一 em 是 2026-10-28 定的规则，不是量错。
- **热切换**：2026-10-31 真机两轮都失败——第一轮 30 个文件全挂；第二轮我给的命令把
  `/data` 下的合并目录 `mount --bind` 到 `/system/fonts`（`mount` 输出里成了
  `/dev/block/dm-76 … f2fs`），并在 init 里留下 per-file overlay 残渣。已改成「一次目录级
  overlay + 失败回滚 + 目录 bind 守卫 + `panic`」四条硬规矩，并写进 `build.py --check`。
  **真机仍未验证**：overlay 能否一次挂成功、SELinux 策略、`cmd font update`、软重启重读。

### 未验证项的真机清单

**已真机验证**（2026-10-05，一加 / ColorOS 16 / Android 16 / KernelSU）：① 系统字体生效——三份配置（`/system/etc/font_fallback.xml`、`/system_ext/etc/fonts_base.xml`、`/system_ext/etc/fonts_ule.xml`）替换后字形变圆，模块版本 `26.10.5.23.86`；② 火狐网页字体开关（运行时「操作」按钮 / `web-fonts.sh keep|block|toggle`）切换生效；③ 别名字件已实测**无效**并删除（见「火狐」一节「泛型与家族名的坑」）。**2026-10-07 装机核对（配置层已核对，渲染层未验证）**（同一台设备）：装「清掉 MiSans 引用（10-06）+ 卡开机修复 + 语言区改法 + 五个命名族恢复本来字体（10-07）」之后的构建，**正常开机、不再重启循环**，三条自查 **8 / 0 / 3** —— `grep -c Selffont /system_ext/etc/fonts_base.xml` = **8**（与构建期「主字体被 8 族引用：匿名回退区 + `serif` + CJK 语言区」逐项吻合）、`grep -ci misans` = **0**、`grep -aic mfga /proc/mounts` = **3**（模块已挂载）。**这三条只覆盖配置层**：证明设备上那份配置的内容符合构建预期、模块挂上了；**渲染层没有任何证据**——字形是否变圆、角标数字是否被切、等宽是否回到 Droid Sans Mono，都不在这三条命令的射程里，需要设备截图，取证命令与存放位置见 `docs/evidence/`。**仍无真机数据**：⓪ **热切换（`action.sh` / `hotswap.sh`）2026-10-31 在真机上第一次跑就全挂**（30 个文件没挂上、`nsenter: Unknown option 'bind'`、`verify` 空账判过），已改成 init 命名空间里一次 overlayfs + `nsenter … sh __ns`；改后的状态是**真机未验证**：overlayfs 能不能在这个 init 命名空间挂上、`nsenter` 是否被 SELinux 放行、`cmd font update` 是否真推新 Typeface、软重启 system_server 后是否全局重读，四件都等真机原样输出；① 纯 AOSP（非 ColorOS）机器上的 `font_fallback.xml` 路径；② 三项只影响观感、不影响开机的观察——生僻字是否仍渲染成圆体（清掉 MiSans 后这些字改由补充字库接管）、终端 / 代码类 App 的等宽字体是否回到 Droid Sans Mono（不该是圆体）、WebView 的 `font-variant: small-caps` 会不会去查 `sans-serif-smallcaps`；③ artifact「包直出」格式实测用的是哪个包未记录（`.102` 旧格式解一层、`.103` 起直接刷，两者字体配置相同）。装上一分钟后按顺序看三条，任一条不对就按对应的回退走：

1. 基础项：系统字体变圆、角标数字正常 → 模块本身生效（ColorOS 上已通过；纯 AOSP `font_fallback.xml` 路径尚未在非 ColorOS 机器上验证）。
2. 火狐接入：`logcat -s GeckoRuntime GeckoDebugConfig | grep -i 'config\|prefs'` 出现 `Adding debug configuration from:` 与 `Adding prefs from debug config` 两行。
3. 网页字体（**已真机验证**）：开一个图标站点（如 FontAwesome 示例页）——**默认压掉**时图标会显示成方块/异常，这是预期代价；点管理器里模块的「操作」按钮切成「放行」（`web-fonts.sh status` 可核对），再重启火狐，图标恢复。两种表现都算「按设计工作」，选哪种看你要全系统同一副面孔还是保图标。

回退都不用卸载：开关随时可切；要回到旧行为就重新打包（`--keep-web-fonts`）→ KSU 装新 zip → 重启。

## 许可证

按目录分工，两条许可各自只覆盖自己的部分：

- **字体与字形源文件**（`tools/design_cjk.bin`、构建出的 `SelfroundsCJK-VF.ttf` 与三个静态实例、模块内随包的字体）——SIL OFL 1.1，全文见 [`OFL.txt`](OFL.txt)。二创字库的笔画中线由 Maruko Gothic（SIL OFL 1.1）量出，属 OFL 意义上的修改作品，改名 `Selfrounds CJK`、不使用保留名。
- **构建脚本与生成器**（`build.py`、`tools/*.py`、`module/*.sh`、`.github/`）——GPL-3.0，全文见 [`LICENSE`](LICENSE)。
- 模块里随包的**第三方补充字库**沿用各自原许可，逐项来源与保留名处理见 [`LICENSES.md`](LICENSES.md)。

不对同一份字体做 GPL-3 与 OFL 双许可（OFL 条件 5 要求字体整体只按该许可分发）。

遵循 [Sumicya/selfs](https://github.com/Sumicya/selfs) 最新 GLOBAL.md。
