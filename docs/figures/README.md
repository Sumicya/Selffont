# docs/figures/ —— 证据图与它们的重画通道

罚篇二十九（2026-11-27，「没图再罚5」）定下的规矩：图必须落盘进仓库、附
sha256 与字节数、并且**可重画**。不可重画的图是一次性图片；可重画的图才是证据。
重画通道是 `tools/draw_stray_proof.py`。

## 清单

| 文件 | 字节 | sha256 | 内容 |
| --- | --- | --- | --- |
| `yan-stray-before-after.png` | 12,070 | `3235ee4ec845b67f43ff4acbc04ce7e6c0d0be22c6ba9ba2291f2bf2a08be791` | 「谚」U+8C1A 左下区 x[0,320] y[-120,260]，红虚线=基线；左=母版原文 7 轮廓（基线以下有分离碎块 r6），右=drop_stray 输出 6 轮廓（碎块已删） |
| `stray-proof-谚.png` | 7,261 | `d9f35e094a6645baccd4d5bc78421058f786f82929c6d01c110192af10e7d6f3` | 同上内容，但窗口由 `draw_stray_proof.py` 按「判据命中轮廓的 bbox 外扩 150%」自动定为 x[13,221] y[-126,70]；本文件是脚本产物，可重画 |

## 重画命令

```bash
.venv/bin/python tools/draw_stray_proof.py /tmp/mother/Maruko.ttf /tmp/stray.ttf 谚 --out docs/figures
```

其中两个输入的产生方式：

- `/tmp/mother/Maruko.ttf`：上游 Regular，sha256
  `e3709389bce13fa75af28cc2370b6175520d97f74dfbf3894ca24838f47241b7`，20,084,736 B；
  取法 `gh api repos/max32002/maruko-gothic/git/blobs/63d79a450a9043f482e1ad024354a0660391147c -q .content | base64 -d`。
- `/tmp/stray.ttf`：`tools/drop_stray_ring.py /tmp/mother/Maruko.ttf -o /tmp/stray.ttf`
  的输出（20 个字各删一条碎块轮廓后 19,976,052 B）。

## 窗口纪律

渲染窗口由数据定，不由直觉定（罚篇二十九 §4）。第一次渲染用 y[0,400]，看不到
y[-52,-3] 的碎块，差点把「窗口里没看到」当成「不存在」。脚本里 `window()` 只接受
轮廓 bbox 外扩，不接受手填坐标。

## 降级声明

`yan-stray-before-after.png` 是手写 PIL 代码的产物（渲染代码当时在 /tmp heredoc 里，
未进仓库），故其地位是**证据副本**：字节可信、sha 可核，但重画要靠脚本重跑相近窗口。
`stray-proof-谚.png` 是脚本产物，为**可复算证据**。今后新增图一律走脚本路径。
