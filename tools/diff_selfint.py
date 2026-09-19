#!/usr/bin/env python3
"""Compare self-intersections per changed contour: baseline font vs edited
font, for exactly the contours the report says were touched. Reports:
  fixed    : bad before, clean now
  regressed: clean before, bad now   <-- the danger signal
  still-bad: bad before, bad now"""
import sys
import json
import edit_font as ef
import selfint_scan as si


def contour_polys(glyph):
    spans = list(ef.split_contours(glyph))
    out = []
    for (s, e) in spans:
        pts = ef.contour_points(glyph, s, e)
        out.append(si.flatten_contour(pts))
    return out


def main(base_path, edited_path, report_path):
    from fontTools.ttLib import TTFont
    base = TTFont(base_path)
    edited = TTFont(edited_path)
    bcmap = base.getBestCmap()
    ecmap = edited.getBestCmap()
    rep = json.load(open(report_path))
    smooth = rep["smooth-strokes"]["changed"]
    fixed = regressed = stillbad = missing = 0
    reg_list = []
    fix_list = []
    still_list = []
    for ch, info in sorted(smooth.items()):
        gn = ecmap.get(ord(ch))
        gb = bcmap.get(ord(ch))
        if not gn or not gb:
            missing += 1
            continue
        bg = base["glyf"][gb]
        eg = edited["glyf"][gn]
        if bg.numberOfContours <= 0 or eg.numberOfContours <= 0:
            missing += 1
            continue
        _ = bg.coordinates
        _ = eg.coordinates
        bp = contour_polys(bg)
        ep = contour_polys(eg)
        for ci in info["contours"]:
            j = ci["contour"]
            if j >= len(bp) or j >= len(ep):
                missing += 1
                continue
            hb = si.contour_self_intersects(bp[j])
            he = si.contour_self_intersects(ep[j])
            if hb and not he:
                fixed += 1
                fix_list.append((ch, j, hb, he))
            elif hb and he:
                stillbad += 1
                still_list.append((ch, j, hb, he))
            elif not hb and he:
                regressed += 1
                reg_list.append((ch, j, hb, he))
    print(f"fixed={fixed}  still-bad={stillbad}  REGRESSED={regressed}  missing={missing}")
    print("regressed:", reg_list[:40])
    print("still-bad:", still_list[:40])
    if fix_list:
        print("fixed samples:", fix_list[:20])


if __name__ == "__main__":
    sys.path.insert(0, "tools")
    main(sys.argv[1], sys.argv[2], sys.argv[3])
