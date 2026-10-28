"""用 FreeType（PIL 底层）渲染字形并算 IoU。

为什么不用「按有向面积判内外」的自绘渲染
-------------------------------------------
早先那版自绘按轮廓**有向面积的符号**决定填白还是挖黑：面积最大的当外轮廓，符号相反的
当洞。这只是在模仿"非零环绕"，遇到同向重叠的轮廓就出错——`鬱` 上游 11 条轮廓**全
是同向**，该函数会把重叠区当洞挖掉。Android 上 FreeType 用的是真正的非零环绕，
所以量产的相似度必须用 FreeType 算。

同一网格：两个字体都用 `anchor="ls"` 在同一个原点落笔，按字宽对齐，不按外接框
归一化（否则整字会被重新缩放，相似度全是假的）。
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def render(path, char, size=300, margin=None):
    """用 FreeType 渲染单个字符，返回 bool 掩膜。"""
    margin = size if margin is None else margin
    font = ImageFont.truetype(str(path), size)
    image = Image.new("L", (size + 2 * margin, size + 2 * margin), 0)
    ImageDraw.Draw(image).text((margin, margin), char, font=font, fill=255, anchor="ls")
    return np.array(image) > 127


def iou(a, b):
    union = (a | b).sum()
    return float((a & b).sum() / union) if union else 1.0


def compare(path_a, path_b, char, size=300):
    return iou(render(path_a, char, size), render(path_b, char, size))
