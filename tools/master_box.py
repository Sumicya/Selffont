"""生成 `tools/master_box.bin`：母版逐字的**字面框**（墨迹外接框，去掉装饰残块）。

为什么不用「母版 glyf 的 bbox」
------------------------------
母版的 bbox 里混着不该算进字面的东西。`日`（U+65E5）在母版里有 4 条轮廓：

    0  (773, 788) – (828, 833)   9 点    55×45 的一小块，孤零零吊在右上角
    1  (201, -10) – (802, 763)  34 点    外框
    2  (263, 414) – (737, 703)  15 点    上字腔
    3  (263,  49) – (737, 354)  16 点    下字腔

第 0 条是母版里的一小块残墨（面积只有外框的 0.53%，和正文任何笔画都不相连；
`曰` `旦` `早` `旧` `白` `目` `田` `口` 都没有这东西）。若直接拿 glyf bbox 当目标，
`日` 的高度会比本版多 64 单位，对齐就会把整个字纵向拉长 4.5% 去盖那一小块。

所以目标框按「字面」的口径取，残块逐个点名，不用尺寸阈值蒙。阈值试过、不能用：
按「不相交 + 面积不到 1% + 最长边 ≤ 60」筛，全库会命中 39 个字，其中 38 个删掉的是
**真的点画**（`㲲` 一次有 8 个点、`氎` 8 个、`䴑` 8 个），只有 `日` 那一块不是笔画。
判定只能靠逐个看，所以写成点名表 `STRAY_CONTOURS`，目前只有一条。

用法
----
    python tools/master_box.py 母版.ttf            # 重写 tools/master_box.bin
    python tools/master_box.py 母版.ttf --dry-run  # 只打印会变的字
"""
from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent / "master_box.bin"

# 母版里不属于字面的残块：码位 → 要去掉的轮廓序号（按 glyf 里 contours 的顺序，从 0 起）。
# 加一条之前要满足两件事：量出它的框/点数/面积占比写进注释，并且确认同族的字里没有同样的块。
STRAY_CONTOURS = {
    0x65E5: (0,),  # 日：0 号轮廓 (773,788)–(828,833)，9 点，55×45，占外框面积 0.53%，
                   # 孤零零吊在右上角，与本字任何笔画都不相连；曰/旦/早/旧/白/目/田/口 都没有
}


def _contours(glyf, glyph):
    coords, ends, _ = glyph.getCoordinates(glyf)
    out, start = [], 0
    for end in ends:
        pts = coords[start:end + 1]
        start = end + 1
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        out.append((min(xs), min(ys), max(xs), max(ys)))
    return out


def _area(box) -> float:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])



def face_box(glyf, glyph, codepoint=None):
    """字面框：去掉点名残块后，全部轮廓的并集。"""
    boxes = _contours(glyf, glyph)
    if not boxes:
        return None
    drop = set(STRAY_CONTOURS.get(codepoint, ()))
    keep = [box for i, box in enumerate(boxes) if i not in drop] or boxes
    return (min(b[0] for b in keep), min(b[1] for b in keep),
            max(b[2] for b in keep), max(b[3] for b in keep))


def build(master: Path) -> dict[int, tuple[int, int, int, int]]:
    from fontTools.ttLib import TTFont

    with TTFont(str(master), lazy=True) as font:
        cmap, glyf = font.getBestCmap(), font["glyf"]
        out = {}
        for cp, name in cmap.items():
            glyph = glyf[name]
            if glyph.numberOfContours <= 0:
                continue
            box = face_box(glyf, glyph, cp)
            if box:
                out[cp] = tuple(int(round(v)) for v in box)
        return out


def encode(table: dict[int, tuple[int, int, int, int]]) -> bytes:
    buf = bytearray()
    prev = 0
    for cp in sorted(table):
        delta = cp - prev
        prev = cp
        while True:
            byte = delta & 0x7F
            delta >>= 7
            buf.append(byte | (0x80 if delta else 0))
            if not delta:
                break
        buf += struct.pack("<4h", *table[cp])
    return zlib.compress(bytes(buf), 9)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("master", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", type=Path, default=None, help="顺便把逐字框写成 JSON")
    args = ap.parse_args()

    table = build(args.master)
    print(f"字面框 {len(table)} 字")
    old = {}
    if OUT.exists():
        from box_align import load

        old = load()
    changed = [cp for cp in table if cp in old and tuple(old[cp]) != table[cp]]
    print(f"与旧表不同的字 {len(changed)}：{' '.join(chr(c) for c in changed[:40])}")
    if args.json:
        args.json.write_text(json.dumps({chr(k): v for k, v in sorted(table.items())},
                                        ensure_ascii=False), encoding="utf-8")
    if not args.dry_run:
        OUT.write_bytes(encode(table))
        print(f"写入 {OUT}（{OUT.stat().st_size} B）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
