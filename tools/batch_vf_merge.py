#!/usr/bin/env python3
"""把同一字符集的多个圆角化静态字重，分批合成多份小可变字体（VF），绕开
`fontTools.varLib.build` 在全量 CJK 规模下的 OOM（2026-10-15 实测：35089 字形 ×
7 字重一次性喂给 varLib.build，"Generating gvar" 这一步会把本沙箱 3.8GiB 内存吃穿，
进程被 OOM-killed，期间沙箱一度卡死到连 `echo` 都要等几十秒才有响应——这不是"再加大
batch 就行"的误差，是这一步的内存需求和字形数基本线性，4GiB 机器上限大概在几千到一万
字形/批之间）。

思路：varLib.build 本身不支持增量/分批合并，但"一个 VF 文件"不是 Android 系统接管
这些字符的唯一方式——fonts.xml 的 fallback family 链本来就是按字符路由到不同文件
（本仓库 CJK 扩展 B/兼容表意文字等本来就是交给基础包的补充字库，走的是同一机制）。
所以不勉强把全部字形拼进一份 VF，而是：

1. 把参照字重（通常是 Regular）的完整字形表按顺序切成 N 批（每批几千字形，具体数字
   按本机可用内存试出来，不是写死的理论值）。
2. 每批用 `fontTools.subset` 对所有字重各自取子集（会自动做 composite 闭包，缺啥
   依赖补啥，不用手工算）——同一批里 7 个字重的字形数必须相等，不等就是闭包算出了
   分歧，不能继续合并（本脚本每批做这个断言）。
3. 每批单独跑一次 `fontTools.varLib`（独立进程/独立内存空间，批与批之间完全不共享
   内存，前一批退出后操作系统自然回收，不会累积）。
4. N 份小 VF 的 cmap 并起来必须等于源字体 cmap、互相之间不重叠——本脚本验证这两条，
   不满足就报错，不当"大概率没问题"糊弄过去。

产物是 N 个独立的小 VF 文件，不是一个大文件：装进 fonts.xml 时作为同一个
`lang="zh"`（或适用语言区）下的 N 条相邻 fallback family，Android 的 minikin 按
字符在这条链里找第一个覆盖该字符的文件，谁的 cmap 覆盖这个字符就落到谁身上——对
最终用户是透明的，看不出和"一个文件"有什么差别。这跟"装一个文件等于装全部字重"这句
话字面上不一致（见 TODO.md），是拿"一次装多个文件、缺一个都不能正常工作"换
"绕开内存上限"的工程取舍，产物形态变了，交main人确认是否接受。

用法：
  python3 batch_vf_merge.py \\
    --weights Thin=.../Thin.ttf Light=.../Light.ttf Regular=.../Regular.ttf \\
              Medium=.../Medium.ttf SemiBold=.../SemiBold.ttf Bold=.../Bold.ttf \\
              Heavy=.../Heavy.ttf \\
    --batch-size 4400 --outdir out/
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

from fontTools import subset
from fontTools.ttLib import TTFont

AXIS_LOCATIONS = {
    "Thin": 100, "Light": 300, "Regular": 400, "Medium": 500,
    "SemiBold": 600, "Bold": 700, "Heavy": 900,
}


def subset_weight(src_path: str, names: list[str], out_path: str) -> int:
    font = TTFont(src_path)
    subsetter = subset.Subsetter()
    subsetter.options.glyph_names = True
    subsetter.options.name_IDs = ["*"]
    subsetter.options.notdef_glyph = True
    subsetter.options.notdef_outline = True
    subsetter.options.recommended_glyphs = True
    subsetter.options.recalc_bounds = True
    subsetter.options.recalc_timestamp = False
    subsetter.options.layout_features = ["*"]
    subsetter.populate(glyphs=names)
    subsetter.subset(font)
    font.save(out_path)
    return len(font.getGlyphOrder())


def write_designspace(batch_dir: str, weights: dict, batch_name: str) -> str:
    sources = []
    for name, wght in AXIS_LOCATIONS.items():
        path = os.path.join(batch_dir, f"{name}.ttf")
        extra = ' copy-lib="1" copy-info="1" copy-groups="1" copy-feature="1"' if name == "Regular" else ""
        sources.append(
            f'<source filename="{path}" name="{name}"{extra}>'
            f'<location><dimension name="Weight" xvalue="{wght}"/></location></source>')
    designspace = f"""<?xml version="1.0" encoding="UTF-8"?>
<designspace format="4.1">
  <axes>
    <axis tag="wght" name="Weight" minimum="100" maximum="900" default="400"/>
  </axes>
  <sources>
    {''.join(sources)}
  </sources>
  <instances>
    <instance name="Regular" filename="{os.path.join(batch_dir, 'Regular.ttf')}"
              stylename="Regular" familyname="{batch_name}">
      <location><dimension name="Weight" xvalue="400"/></location>
    </instance>
  </instances>
</designspace>
"""
    out = os.path.join(batch_dir, "designspace.xml")
    with open(out, "w") as fh:
        fh.write(designspace)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weights", nargs="+", required=True, help="NAME=PATH.ttf，七个字重缺一不可")
    parser.add_argument("--batch-size", type=int, default=4400,
                         help="每批的「主字形」数量（闭包会再拉入依赖，实际每批字形数会更多）")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--family-prefix", default="Selfrounds Batch")
    args = parser.parse_args()

    weight_paths = dict(spec.split("=", 1) for spec in args.weights)
    missing = set(AXIS_LOCATIONS) - set(weight_paths)
    if missing:
        sys.exit(f"缺字重：{missing}（七个字重必须一次性给全，批内部用它们各自的 wght 坐标）")

    ref = TTFont(weight_paths["Regular"], lazy=True)
    glyph_order = ref.getGlyphOrder()
    n_glyphs = len(glyph_order)
    n_batches = (n_glyphs + args.batch_size - 1) // args.batch_size
    print(f"参照字重 {n_glyphs} 个字形，按 {args.batch_size}/批 切成 {n_batches} 批")

    os.makedirs(args.outdir, exist_ok=True)
    source_cmap = ref.getBestCmap()
    all_cps: set[int] = set()
    batch_outputs = []

    with tempfile.TemporaryDirectory() as tmp:
        for i in range(n_batches):
            names = glyph_order[i * args.batch_size:(i + 1) * args.batch_size]
            batch_dir = os.path.join(tmp, f"batch{i}")
            os.makedirs(batch_dir, exist_ok=True)
            counts = {}
            for name, path in weight_paths.items():
                out_path = os.path.join(batch_dir, f"{name}.ttf")
                counts[name] = subset_weight(path, names, out_path)
            if len(set(counts.values())) != 1:
                sys.exit(f"batch{i}：七个字重闭包后字形数不一致 {counts}，没法合并，"
                         f"说明某个字重的 composite 依赖和其它字重对不上，需要先查字体本身")
            designspace = write_designspace(batch_dir, weight_paths, f"{args.family_prefix}{i}")
            out_vf = os.path.join(args.outdir, f"batch{i}.ttf")
            result = subprocess.run(
                [sys.executable, "-m", "fontTools.varLib", designspace, "-o", out_vf],
                capture_output=True, text=True)
            if result.returncode != 0:
                sys.exit(f"batch{i} varLib.build 失败（{list(counts.values())[0]} 字形/字重）：\n"
                         f"{result.stderr[-2000:]}")
            vf = TTFont(out_vf, lazy=True)
            cmap = vf.getBestCmap()
            overlap = all_cps & set(cmap)
            if overlap:
                sys.exit(f"batch{i} 的 cmap 和之前批次重叠 {len(overlap)} 个码位，"
                         f"分批切分没做到互斥，不能当 fallback 链拼接")
            all_cps |= set(cmap)
            batch_outputs.append(out_vf)
            print(f"batch{i}: {list(counts.values())[0]} 字形(含闭包)/字重，"
                  f"cmap {len(cmap)} 码位 -> {out_vf}")

    missing_cps = set(source_cmap) - all_cps
    if missing_cps:
        sys.exit(f"合并后缺 {len(missing_cps)} 个源字体有的码位，分批切分漏字，"
                 f"不能当「覆盖不变」交付：{sorted(hex(cp) for cp in list(missing_cps)[:20])}")
    print(f"=== {n_batches} 批全部成功，源字体 {len(source_cmap)} 个码位全部覆盖，"
          f"互相不重叠，产物见 {args.outdir}/batch*.ttf ===")


if __name__ == "__main__":
    main()
