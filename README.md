# Selffont

Android 个人字体模块:自研圆体字库 **Selffont Round SC** 接管系统字体家族——**笔画端头圆、接口锐利**,没有资源圆体一类「逢角必圆」流派的接口凸起。原生 `fonts.xml` 挂载 + 可选 LSPosed 应用内替换。

## 自研字库(圆角引擎)

`tools/round.py`:对 Noto Sans SC(OFL)做结构化的「自由端头半圆化」——

- 只圆**自由笔画端头**(短直线封口 + 两侧平行长边 + 近垂直交角);T 形接口、L 形拐角、口框一概不动 → **接口处零凸起**
- CFF → TrueType(cu2qu),字形骨架、字重、字面不变;五字重 30,889 码位(含扩展 A)
- 衍生字库依 OFL 保留名条款改名 `Selffont Round SC` 发布(`module/licenses/Noto-OFL.txt`)

生成(约 30 秒/字重,仅需 fontTools):

```sh
git clone -q --depth 1 --filter=blob:none --sparse https://github.com/notofonts/noto-cjk
git -C noto-cjk sparse-checkout set Sans/SubsetOTF/SC
mkdir -p build/fonts
for w in Light Regular Medium Bold Black; do
  python3 tools/round.py "noto-cjk/Sans/SubsetOTF/SC/NotoSansSC-$w.otf" \
    "build/fonts/Selffont-RoundSC-$w.ttf" --family "Selffont Round SC"
done
```

## 模块结构

```
tools/round.py       圆角引擎(自由端头检测 + 半圆替换 + OFL 改名)
tools/build.py       打包器:主字体 + 任意基础包 → KSU 模块 zip
config/sources.json  来源声明(主字体本地生成;基础包默认源,可任意替换)
fonts.xml            系统字体配置输入(MFGA 补充字体引用,不改动)
module/              装进 zip 的运行时:customize.sh / action.sh / webroot / 许可
xposed/              LSPosed 模块:Entry.kt(挂钩)+ Policy.kt(纯策略)
tests/selfcheck.py   一个自检文件:归一、配置生成、端到端构建、引擎冒烟、脚本行为
```

- **原生化**:系统字体走 `fonts.xml` 原生挂载;LSPosed 只管应用自带字体与 Gecko 网页首选项两条路径;零 JNI、零开机脚本。
- **自由化**:无平台闸门;基础包 `--base` 任意本地文件或 URL,哈希只是提示;主字体度量归一在现场从字体读取。
- **简单化**:Kotlin 2 文件、打包器 1 个、模块脚本 2 个、CI 1 个、自检 1 个。
- **现代化**:AGP 9.3(内置 Kotlin)/ JDK 21 / SDK 36 / Python 3.11 / fontTools。

## 构建

```sh
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tests/selfcheck.py
# 先生成主字体(见上),再打包(基础包默认源自动下载,也可 --base 换任意):
.venv/bin/python tools/build.py --font build/fonts
```

产物 `build/Selffont.zip`。CI(`.github/workflows/build.yml`)一条流水线:自检 → 从 Noto 现场生成五字重 → 打包模块 zip + 诊断 APK。

打包时把主字体安装副本的竖直行度量归一到 Roboto 空壳载体的名义度量(修角标数字偏低/切下沿);只改行度量,字形、cmap、家族名、轴逐字节守卫。字重阶梯按现场读取的 `OS/2` 字重映射(100–900 每档取最近声明字重,并列取较重)。

## 安装与验证

1. KSU 安装 `build/Selffont.zip`,重启。模块 ID 保持 `MFGA`。
2. 安装 APK,LSPosed 勾选目标应用(Firefox 等),冷启动。
3. 日志:`[attach]` → `[hook-installed]` → `[typeface-hit]` / `[gecko-prefs]`;`[gecko-skip]` = 该进程读不到字体。`action.sh diagnose` 只读诊断。

安装脚本把本模块 `fonts.xml` 整份替换到系统所有 `font*.xml` 位置(`fonts_customization.xml` 除外)。

## 卸载

KSU 删除模块,重启即恢复——模块不写任何系统外的持久状态。

## 边界(诚实条款)

- 真机验证过:Android 16 / OnePlus(Oplus)/ KernelSU / LSPosed 2.2.0(7854)一台。其他平台自担风险。
- 圆角引擎只动端头:斜体变体的端头同样处理;连笔、书法笔触(撇捺尖)保持原样,这是设计取舍。
- Firefox 对新 emoji 的豆腐块属 Gecko 后端限制,本模块不可修。
- Hook 安装成功 ≠ 网页已使用目标字体;Gecko 用户首选项可能覆盖注入值。
- 上游 MFGA 资源归属见 `LICENSES.md`;基础包只取字体资源,绝不执行其代码。
