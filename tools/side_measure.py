"""量母版里**非字母**（数字、标点、符号）逐字的左右侧距，写成 `tools/side_targets.bin`。

为什么这一类不能沿用「按边缘形状给三档」：母版的字母侧距是连续的（随贴边覆盖率单调走，
本字件用 `24 + 58 × 覆盖率` 拟合，中位误差 5.5 单位），但数字与标点是母版**逐个手调**的——
`[` 的前进量 317、`{` 389、`+` 922，而三档模型给它们的东西中位差 48、最差 194（`+` 被
压到 728），`[` `{` 甚至被 200 的下限夹住。这不是「间距还能再调」，是量错了对象：
三档模型对字母成立，对逐个手调的标点不成立（母版自己就没用同一套）。

所以这里量的不是「一个侧距常数」，而是**母版给每个非字母的两侧留白**（lsb / rsb），
存成逐字的表；构建期用本字自己的墨宽加上这两个留白算前进量（`advance = 墨宽 + lsb + rsb`），
再把轮廓平移到 lsb 上。抄的是「留白的目标」，不是「字宽」——本字的墨宽与母版不同
（拟合、整数网格都会改），所以字宽仍由本字算出来。这与 `tools/kern_targets.bin` 同一套做法：
目标逐字/逐对取自母版真排，字形仍自己画。

范围与排除：
  · 只收非汉字、非全角（全角固定一个 em，侧距 0）、非字母（字母走连续式）、有墨的字；
  · 母版缺这个码位的字不收（收了也没得量）；
  · 存的是**前进量**与**墨心**（`lsb + 墨宽/2`），不是原始 lsb/rsb：本字的墨宽与母版差着
    几个单位，照抄 lsb 会让「留白一边多一边少」；按墨心排，前进量照母版，两边留白随本字的
    墨宽自己分。母版自己也有两侧都负的（破折号 `—` 的 lsb/rsb 都是 −20），按墨心算才对得上；
  · 只收 ASCII 之外的那 360 个非汉字也在内——只要母版有。

输出格式（`side_targets.bin`）：
    4 字节 magic `SFS1` + N × (uint32 码位, int16 前进量, int16 墨心)（小端，按码位升序）

    .venv/bin/python tools/side_measure.py --master /path/maruko.ttf
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import design_cjk  # noqa: E402
import cjk_vf  # noqa: E402

MAGIC = b"SFS2"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "side_targets.bin")
    args = ap.parse_args()

    from fontTools.ttLib import TTFont

    master = TTFont(str(args.master), lazy=True)
    cmap = master.getBestCmap()
    glyf, hmtx = master["glyf"], master["hmtx"]
    data = design_cjk.load()

    rows, missing, blank, fullwidth = [], 0, 0, 0
    for cp in sorted(data):
        if cjk_vf.is_han(cp) or cjk_vf._is_letter(cp):
            continue
        if any(low <= cp <= high for low, high in cjk_vf.FULL_WIDTH):
            fullwidth += 1
            continue
        if not data[cp].get("strokes"):
            blank += 1
            continue
        name = cmap.get(cp)
        if name is None:
            missing += 1
            continue
        glyph = glyf[name]
        advance, lsb = hmtx[name]
        if glyph.numberOfContours == 0:
            blank += 1
            continue
        center = lsb + (glyph.xMax - glyph.xMin) / 2
        rows.append((cp, int(round(advance)) & 0xFFFF, max(-32000, min(32000, int(round(center))))))

    blob = MAGIC + b"".join(struct.pack("<IHh", *row) for row in rows)
    args.out.write_bytes(blob)
    print(f"{args.out} {len(blob)} B, {len(rows)} 字")
    print(f"跳过：全角 {fullwidth}、空白 {blank}、母版缺 {missing}")
    adv = sorted(r[1] for r in rows)
    cen = sorted(r[2] for r in rows)
    print(f"前进量：中位 {adv[len(adv) // 2]}、{adv[0]}..{adv[-1]}")
    print(f"墨心：中位 {cen[len(cen) // 2]}、{cen[0]}..{cen[-1]}")


if __name__ == "__main__":
    main()
