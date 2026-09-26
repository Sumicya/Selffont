# Selffont

Android 个人字体模块:**文渊圆体 v1.010 可变字体**(takushun-wu;OFL,活跃维护,2026-08 还在发版;一个 VF 文件内含 `wght` 100–900 + `ital` 真字重)接管系统字体家族。原生 `fonts.xml` 挂载——模块本身即全部交付,无伴侣应用。

## 字体

主字体照搬[文渊圆体](https://github.com/takushun-wu/WenYuanFonts/releases/tag/v1.010)(OFL-1.1)——字形、cmap 逐字节不动,仅安装副本做竖直行度量归一(修角标数字偏低/切下沿,构建期字形守卫)+ 空壳映射剪除 + OFL 保留名改名。因 OFL 保留字体名 `'WenYuan'/'文渊'`,归一(=修改)后的安装副本内部名整体改为 **Selffont Rounded SC VF**,OFL 文本随包附带(`module/licenses/`)。

单 VF 文件:`wght` 100–900 + `ital` 真字重,`fonts.xml` 按现场读取的轴生成 9 档 × 2 风格阶梯(轴越界值夹取,不拒绝)。

备选:寒蝉全圆体/圆黑体(OFL,小杉丸/思源骨架圆体),换 `config/sources.json` 一个 URL 即可。

## 模块结构

```
tools/build.py       打包器:主字体 + 扩展字库 + 任意基础包 → KSU 模块 zip
config/sources.json  来源声明(主字体默认源;基础包默认源;可任意替换)
fonts.xml            系统字体配置输入(MFGA 补充字体引用,不改动)
module/              装进 zip 的运行时:customize.sh / action.sh / webroot / 许可
tests/selfcheck.py   一个自检文件:归一、配置生成、端到端构建、脚本行为
```

- **原生化**:系统字体走 `fonts.xml` 原生挂载;零 JNI、零开机脚本、零伴侣应用——无 LSPosed,无 APK。
- **自由化**:无平台闸门;基础包 `--base` 任意本地文件或 URL,哈希只是提示;主字体度量归一在现场从字体读取。
- **简单化**:打包器 1 个、模块脚本 2 个、WebUI 1 页、CI 1 job、自检 1 文件。没有第二种语言,没有第二条工具链。
- **现代化**:Python 3.14 / fontTools 4.66;Kotlin、Gradle、Android SDK 不在仓库里。

## 构建

```sh
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tests/selfcheck.py
# 一条命令:下载文渊圆体 VF → 剪除空壳映射 → 度量归一+改名 → 打包。
# 基础包默认源自动下载;--base/--font 可换任意来源:
.venv/bin/python tools/build.py
```

产物 `build/Selffont.zip`。CI(`.github/workflows/build.yml`)同一条流水线:自检 → 下载文渊圆体 VF → 模块 zip。

打包时把主字体安装副本的竖直行度量归一到 Roboto 空壳载体的名义度量(修角标数字偏低/切下沿);只改行度量,字形、cmap、家族名、轴逐字节守卫。字重阶梯按现场读取的字体轴生成(VF 取 fvar 100–900,越界夹取;静态多字重取 `OS/2` 最近声明字重,并列取较重)。

## 安装与验证

1. KSU 安装 `build/Selffont.zip`,重启。模块 ID 保持 `MFGA`。
2. `action.sh diagnose` 只读诊断。

安装脚本把本模块 `fonts.xml` 整份替换到系统所有 `font*.xml` 位置(`fonts_customization.xml` 除外)。

## 卸载

KSU 删除模块,重启即恢复——模块不写任何系统外的持久状态。

## 边界(诚实条款)

- 真机验证过:Android 16 / OnePlus(Oplus)/ KernelSU 一台。其他平台自担风险。
- Firefox 对新 emoji 的豆腐块属 Gecko 后端限制,本模块不可修。
- 上游 MFGA 资源归属见 `LICENSES.md`;基础包只取字体资源,绝不执行其代码。
