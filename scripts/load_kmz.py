#!/usr/bin/env python3
"""Load official KMZ district polygons. Point marks (pools, Cube, greens) are ignored."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[1]
KMZ = Path("/Users/lawrenceuhling/Downloads/LOAD THIS EXACTLY.kmz")
OUT = ROOT / "public" / "data" / "districts.geojson"
COPY_KMZ = ROOT / "public" / "data" / "LOAD THIS EXACTLY.kmz"
COPY_KML = ROOT / "public" / "data" / "districts.from-kmz.kml"

NS = {"k": "http://www.opengis.net/kml/2.2"}

NAME_TO_ID = {
    "NORTH EASTBRIDGE & BLUFF LAKE": 1,
    "EAST 29TH AVE.": 2,
    "WESTERLY CREEK": 3,
    "SOUTH END": 4,
    "EAST BRIDGE": 5,
    "CP NORTH & CP WEST": 6,
    "CENTER FIELD": 7,
    "CONSERVATORY GREEN": 8,
    "WILLOW PARK EAST & WICKER PARK": 9,
    "BEELER PARK": 10,
    "NORTH END": 11,
}

def parse_ring(text: str) -> list[list[float]]:
    pts = []
    for token in text.split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        pts.append([float(parts[0]), float(parts[1])])
    if pts and pts[0] != pts[-1]:
        pts.append(list(pts[0]))
    return pts


def placemark_name(pm) -> str:
    name_el = pm.find("k:name", NS)
    if name_el is None:
        return ""
    return re.sub(r"\s+", " ", "".join(name_el.itertext()).strip())


def main() -> None:
    COPY_KMZ.write_bytes(KMZ.read_bytes())
    with zipfile.ZipFile(KMZ) as zf:
        kml_name = next(n for n in zf.namelist() if n.lower().endswith(".kml"))
        kml_bytes = zf.read(kml_name)
    COPY_KML.write_bytes(kml_bytes)

    root = ET.fromstring(kml_bytes)
    rings: dict[int, list[list[float]]] = {}
    for pm in root.findall(".//k:Placemark", NS):
        raw = placemark_name(pm)
        poly = pm.find(".//k:Polygon", NS)
        if poly is None:
            continue
        did = NAME_TO_ID.get(raw)
        if did is None:
            raise SystemExit(f"unknown district polygon {raw!r}")
        coord_el = poly.find(".//k:coordinates", NS)
        rings[did] = parse_ring(coord_el.text or "")

    missing = sorted(set(NAME_TO_ID.values()) - set(rings))
    if missing:
        raise SystemExit(f"KMZ missing districts {missing}")

    fc = json.loads(OUT.read_text())
    by_id = {f["properties"]["id"]: f for f in fc["features"]}
    for did, ring in rings.items():
        feat = by_id[did]
        poly = Polygon(ring)
        feat["geometry"] = {"type": "Polygon", "coordinates": [ring]}
        pt = poly.representative_point()
        feat["properties"]["labelLat"] = float(pt.y)
        feat["properties"]["labelLng"] = float(pt.x)
        feat["properties"]["source"] = "LOAD THIS EXACTLY.kmz"
        print(f"D{did:02d} vertices={len(ring)} valid={poly.is_valid}")

    OUT.write_text(json.dumps(fc, indent=2) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
