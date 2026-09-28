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

## 边界

- 真机验证过:Android 16 / OnePlus / KernelSU 一台,其他平台自担风险。
- Firefox 对新 emoji 的豆腐块属 Gecko 限制,不可修。
- MFGA 基础包只取字体资源,绝不执行其代码(归属见 `LICENSES.md`)。
- 主字体必须能被 fontTools 解析;`.ttf`/`.otf`/`.ttc` 之外的后缀直接拒绝。
