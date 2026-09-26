# Selffont

Android 个人字体模块:**文渊圆体 v1.010 可变字体**(OFL,活跃维护;一个 VF 文件内含 `wght` 100–900 + `ital` 真字重)接管系统字体家族。原生 `fonts.xml` 挂载,模块即全部交付,无伴侣应用。

## 字体

照搬[文渊圆体](https://github.com/takushun-wu/WenYuanFonts/releases/tag/v1.010):字形、cmap 逐字节不动,仅安装副本做竖直行度量归一(修角标数字偏低/切下沿)+ 空壳映射剪除 + OFL 保留名改名(内部名 **Selffont Rounded SC VF**)。字重阶梯按现场读取的轴生成 9 档 × 2 风格(越界夹取)。备选寒蝉全圆体/圆黑体,换 `config/sources.json` 一个 URL 即可。

## 构建

```sh
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tests/selfcheck.py
.venv/bin/python tools/build.py    # --base/--font 接受任意本地文件或 URL
```

产物 `build/Selffont.zip`;CI(`.github/workflows/build.yml`)同一条流水线。

## 安装 / 卸载

KSU 装 zip,重启(模块 ID `MFGA`;脚本整份替换系统全部 `font*.xml`,不碰 `fonts_customization.xml`)。`action.sh diagnose` 只读诊断。卸载 = KSU 删模块 + 重启。

## 边界

- 真机验证过:Android 16 / OnePlus / KernelSU 一台,其他平台自担风险。
- Firefox 对新 emoji 的豆腐块属 Gecko 限制,不可修。
- MFGA 基础包只取字体资源,绝不执行其代码(归属见 `LICENSES.md`)。
