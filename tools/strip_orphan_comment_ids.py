import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def patch_xml(name: str, data: bytes) -> bytes:
    if name == "word/_rels/document.xml.rels":
        root = ET.fromstring(data)
        for relationship in list(root):
            if relationship.get("Target") == "commentsIds.xml" or relationship.get("Type", "").endswith("/commentsIds"):
                root.remove(relationship)
        ET.register_namespace("", REL_NS)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if name == "[Content_Types].xml":
        root = ET.fromstring(data)
        for override in list(root):
            if override.get("PartName") == "/word/commentsIds.xml":
                root.remove(override)
        ET.register_namespace("", CT_NS)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return data


def main():
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    with zipfile.ZipFile(source, "r") as src, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if item.filename == "word/commentsIds.xml":
                continue
            dst.writestr(item, patch_xml(item.filename, src.read(item.filename)))
    print(output)


if __name__ == "__main__":
    main()
