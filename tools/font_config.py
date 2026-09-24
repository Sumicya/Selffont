"""Generate the Android font-family policy for the static Selffont Maru faces.

The shipped faces are static (no ``fvar``): Android asks for nine weights, we map
each request to the nearest available face. Nothing here invents variable axes.
"""
import bisect
import xml.etree.ElementTree as ET

METRIC_CARRIER = "Roboto-Regular.ttf"
PRIMARY_NAMES = {
    "sans-serif",
    "sans-serif-condensed",
    "serif",
    "monospace",
    "serif-monospace",
    "casual",
    "cursive",
}
METRIC_FAMILIES = {"sans-serif", "sans-serif-condensed"}
OLD_PRIMARY = {f"{weight}.ttf" for weight in range(100, 1000, 100)} | {METRIC_CARRIER}
ANDROID_WEIGHTS = tuple(range(100, 1000, 100))


def face_weights(faces):
    """{weight: installedFile} with the duplicate check the ladder depends on."""
    result = {int(face["weight"]): face["installedFile"] for face in faces}
    if not result:
        raise ValueError("At least one static font face is required")
    if len(result) != len(faces):
        raise ValueError("Static font face weights must be unique")
    return result


def nearest_face(weight, faces):
    """Map an Android weight request to the nearest static face.

    Ties go to the heavier face, so 600 uses 700 and 800 uses 900 -- the same
    choice a CSS engine makes when the exact weight is missing.
    """
    mapping = face_weights(faces)
    available = sorted(mapping)
    index = bisect.bisect_left(available, weight)
    if index == 0:
        chosen = available[0]
    elif index == len(available):
        chosen = available[-1]
    else:
        lower, upper = available[index - 1], available[index]
        chosen = upper if weight - lower >= upper - weight else lower
    return mapping[chosen]


def weight_mapping(faces):
    return {weight: nearest_face(weight, faces) for weight in ANDROID_WEIGHTS}


def primary_fonts(family, faces):
    """Replace a family with the static weight ladder; italics stay synthetic."""
    for child in list(family):
        if child.tag == "font":
            family.remove(child)
    for weight, filename in weight_mapping(faces).items():
        font = ET.SubElement(family, "font", weight=str(weight), style="normal")
        font.text = filename


def configure_fonts(source, faces):
    """Rewrite the inherited base configuration to point at the shipped faces.

    The named Android layout families keep the no-visible-glyph Roboto carrier so
    fixed-height slots (notification counts, badges, clock) measure with the same
    nominal metrics the framework expects; the visible glyphs come from the first
    anonymous fallback family right after it.
    """
    mapping = face_weights(faces)
    if any("/" in name or "\\" in name or name in ("", ".", "..") for name in mapping.values()):
        raise ValueError("Expected simple installed font filenames")
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
            # Drop the inherited numeric glyph faces and the redundant anonymous
            # carrier, but never the named Android layout-metrics families.
            root.remove(family)
        elif family.get("name") in METRIC_FAMILIES and files == {METRIC_CARRIER}:
            continue
        elif family.get("name") in PRIMARY_NAMES or files & OLD_PRIMARY:
            primary_fonts(family, faces)
    glyph_family = ET.Element("family")
    primary_fonts(glyph_family, faces)
    root.insert(list(root).index(default) + 1, glyph_family)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
