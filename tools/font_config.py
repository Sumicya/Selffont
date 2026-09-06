"""Build the Android-16 font-family policy without editing any font binary."""
import xml.etree.ElementTree as ET

METRIC_CARRIER = "Roboto-Regular.ttf"

PRIMARY_NAMES = {"sans-serif", "sans-serif-condensed", "serif", "monospace",
                 "serif-monospace", "casual", "cursive"}
METRIC_FAMILIES = {"sans-serif", "sans-serif-condensed"}
OLD_PRIMARY = {f"{weight}.ttf" for weight in range(100, 1000, 100)} | {METRIC_CARRIER}


def primary_fonts(family, filename):
    for child in list(family):
        if child.tag == "font":
            family.remove(child)
    for italic in (False, True):
        for weight in range(100, 1000, 100):
            font = ET.SubElement(family, "font", weight=str(weight),
                                 style="italic" if italic else "normal")
            font.text = filename
            ET.SubElement(font, "axis", tag="wght", stylevalue=str(weight))
            ET.SubElement(font, "axis", tag="ital", stylevalue="1" if italic else "0")


def configure_fonts(source, filename):
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        raise ValueError("Expected a simple font filename")
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.fromstring(source, parser=parser)
    if root.tag != "familyset":
        raise ValueError("Only familyset configurations may be replaced")
    default = root.find("family[@name='sans-serif']")
    if default is None:
        raise ValueError("Missing default sans-serif family")
    if {(node.text or "").strip() for node in default.findall("font")} != {METRIC_CARRIER}:
        raise ValueError("Default family must retain the verified metrics carrier")
    for family in list(root.findall("family")):
        files = {(f.text or "").strip() for f in family.findall("font")}
        if not family.get("name") and files and files <= OLD_PRIMARY:
            # Replace old numeric glyph faces and the redundant anonymous carrier,
            # but do not discard the named Android layout-metrics families.
            root.remove(family)
        elif family.get("name") in METRIC_FAMILIES and files == {METRIC_CARRIER}:
            continue
        elif family.get("name") in PRIMARY_NAMES or files & OLD_PRIMARY:
            primary_fonts(family, filename)
    glyph_family = ET.Element("family")
    primary_fonts(glyph_family, filename)
    # This is the first actual glyph fallback after the empty named default.
    # Visible glyphs remain WenYuan; fixed Android widgets retain Roboto metrics.
    root.insert(list(root).index(default) + 1, glyph_family)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
