#!/usr/bin/env python3
"""One pin per named corner. Adjacent districts reuse the same pin so there
are no gaps. D6, D7, and D1 share the 40th / railroad line.
"""

from __future__ import annotations

import json

from shapely.geometry import LineString, MultiPolygon, Point, Polygon, mapping

from rebuild_d10_d11 import (
    OSM_PATH,
    OUT_PATH,
    follow,
    from_xy,
    load_named_graph,
    original_curve,
    to_xy,
)

# Shared latitudes so touching edges are the same line.
Y26 = 39.75465  # 26th Ave — D2 / D3 / D4 / D5 / D1
Y40 = 39.77274  # 40th / railroad — D6 / D7 / D1
Y35 = 39.76511  # 35th Ave — D3 / D6 / D7
YMLK = 39.75995  # MLK — D3 / D5 / D6 / D1
Y29P = 39.75850  # 29th Place — D2 north / D3 south

C = {
    "spruce_56": [-104.89734, 39.79840],
    "dallas_56": [-104.87547, 39.79831],
    "spruce_pm": [-104.89732, 39.79341],
    "dallas_pm": [-104.87586, 39.79037],
    "quebec_26": [-104.90339, Y26],
    "quebec_29p": [-104.90330, Y29P],
    "peoria_mlk": [-104.84689, YMLK],
    "spruce_nf": [-104.89737, 39.78564],
    "cp_56": [-104.88449, 39.79847],
    "havana_56": [-104.86598, 39.79840],
    "havana_64": [-104.86609, 39.81299],
    "park64": [-104.88442, 39.81297],
    "syracuse_mv": [-104.89876, 39.74743],
    "dallas_mv": [-104.87640, 39.74738],
    "quebec_29": [-104.90330, 39.75755],
    "syracuse_29": [-104.89888, 39.75755],
    "cp_29p": [-104.89074, Y29P],
    "pl29_w": [-104.90094, Y29P],
    # 26th — every district on 26th uses these
    "syracuse_26": [-104.89897, Y26],
    "cp_26": [-104.89075, Y26],
    "dallas_26": [-104.87646, Y26],
    "creek_26": [-104.87730, Y26],
    "havana_26": [-104.86592, Y26],
    "peoria_26": [-104.84689, Y26],
    # MLK
    "quebec_mlk": [-104.90320, YMLK],
    "syracuse_mlk": [-104.89889, YMLK],
    "cp_mlk": [-104.89077, YMLK],
    "creek_mlk": [-104.87730, YMLK],
    "dallas_mlk": [-104.87656, YMLK],
    "havana_mlk": [-104.86591, YMLK],
    # 35th
    "quebec_35": [-104.90339, Y35],
    "syracuse_35": [-104.89884, Y35],
    "cp_35": [-104.89063, Y35],
    "boston_35": [-104.87790, Y35],
    # railroad / 40th — D6, D7, D1 all use this line
    "quebec_40": [-104.90329, Y40],
    "cp_40": [-104.89063, Y40],
    "boston_40": [-104.87790, Y40],
    "havana_40": [-104.86595, Y40],
    "quebec_i70": [-104.90329, 39.77800],
    "havana_i70": [-104.86571, 39.77552],
    "creek_29p": [-104.87730, 39.75840],
}

NEIGHBORHOODS = {
    1: ["North Eastbridge", "Bluff Lake"],
    2: ["East 29th Avenue", "29th Ave Town Center", "Founders Green"],
    3: ["Westerly Creek"],
    4: ["South End", "Greenway Park"],
    5: ["Eastbridge"],
    6: ["Central Park North", "Central Park West"],
    7: ["Center Field", "Central Park Station"],
    8: ["Conservatory Green"],
    9: ["Willow Park East", "Wicker Park"],
    10: ["Beeler Park"],
    11: ["North End"],
}

COLORS = {
    1: "#8f9a5c",
    2: "#b7d9a8",
    3: "#d9a8c8",
    4: "#e0c090",
    5: "#9ecfe0",
    6: "#e8e090",
    7: "#e0b0a8",
    8: "#b0a8d4",
    9: "#d0b070",
    10: "#90d4cc",
    11: "#e0a8cc",
}


def close(pts):
    out = [list(p) for p in pts]
    if out[0] != out[-1]:
        out.append(out[0])
    return out


def along(street, a, b, lon_range, lat_range):
    """Follow one named OSM street between two pins. Straight line if unconnected."""
    osm = json.loads(OSM_PATH.read_text())
    G = load_named_graph(osm, {street}, lon_range=lon_range, lat_range=lat_range)
    path = follow(G, a, b)
    if len(path) >= 3:
        xy = [to_xy(*p) for p in path]
        path = [list(from_xy(x, y)) for x, y in LineString(xy).simplify(10.0, preserve_topology=True).coords]
    path[0] = list(a)
    path[-1] = list(b)
    return path


def i70_west_to_east(lon_w, lon_e):
    """Three pins on I-70. Do not trace the motorway."""
    west = [lon_w, 39.77800]
    mid = [-104.88312, 39.77753]
    east = [lon_e, 39.77552]
    if lon_e <= mid[0]:
        t = (lon_e - lon_w) / (mid[0] - lon_w)
        return [west, [lon_e, west[1] + t * (mid[1] - west[1])]]
    return [west, mid, east]


def prairie_between(a, b):
    osm = json.loads(OSM_PATH.read_text())
    pts = []
    for el in osm["elements"]:
        if (el.get("tags") or {}).get("name") != "East Prairie Meadow Drive":
            continue
        for p in el.get("geometry") or []:
            if -104.8980 <= p["lon"] <= -104.8755 and 39.7898 <= p["lat"] <= 39.7945:
                pts.append((p["lon"], p["lat"]))
    if len(pts) < 3:
        return [list(a), list(b)]
    pts = sorted({(round(x, 6), round(y, 6)) for x, y in pts}, key=lambda p: p[0])
    xy = [to_xy(*p) for p in pts]
    simple = LineString(xy).simplify(12.0, preserve_topology=True)
    line = [list(from_xy(x, y)) for x, y in simple.coords]
    if abs(line[0][0] - a[0]) > abs(line[-1][0] - a[0]):
        line.reverse()
    line[0] = list(a)
    line[-1] = list(b)
    return line


def poly(pts):
    r = close(pts)
    p = Polygon(r).buffer(0)
    return p


def to_geom(p):
    p = p.buffer(0)
    g = mapping(p)

    def rnd(c):
        if isinstance(c[0], (int, float)):
            return [round(float(c[0]), 6), round(float(c[1]), 6)]
        return [rnd(x) for x in c]

    g["coordinates"] = rnd(g["coordinates"])
    return g


def label_of(p):
    pt = p.representative_point()
    return round(float(pt.y), 6), round(float(pt.x), 6)


def main():
    pm = prairie_between(C["spruce_pm"], C["dallas_pm"])
    curve = original_curve()

    dallas_e = along(
        "North Dallas Street",
        C["dallas_56"],
        C["dallas_pm"],
        lon_range=(-104.8795, -104.8745),
        lat_range=(39.7895, 39.7988),
    )
    p9 = poly([C["spruce_56"], *dallas_e, *reversed(pm)])

    i70 = i70_west_to_east(-104.9040, -104.8650)
    i70_d8 = [p for p in i70 if p[0] <= C["dallas_pm"][0] + 0.0003]
    dallas_s = along(
        "North Dallas Street",
        C["dallas_pm"],
        i70_d8[-1] if i70_d8 else C["dallas_pm"],
        lon_range=(-104.8795, -104.8745),
        lat_range=(39.7755, 39.7910),
    )
    p8 = poly([*pm, *dallas_s, *reversed(i70_d8), C["spruce_nf"]])
    p10 = poly([C["cp_56"], *curve])
    p11 = poly([C["havana_56"], C["havana_64"], C["park64"], *reversed(curve)])

    n29 = along(
        "East 29th Place",
        C["pl29_w"],
        C["cp_29p"],
        lon_range=(-104.9040, -104.8895),
        lat_range=(39.7578, 39.7593),
    )
    p2 = poly(
        [
            C["quebec_29p"],
            *n29,
            C["cp_26"],
            C["quebec_26"],
        ]
    )
    # D4 meets D2 on 26th from Syracuse to CP Blvd, then 26th on to Dallas (meets D3)
    p4 = poly([C["syracuse_26"], C["cp_26"], C["dallas_26"], C["dallas_mv"], C["syracuse_mv"]])

    p3s = poly(
        [
            C["quebec_29p"],
            *n29,
            C["cp_26"],
            C["creek_26"],
            C["creek_mlk"],
            C["quebec_mlk"],
        ]
    )
    p3w = poly([C["quebec_mlk"], C["quebec_35"], C["syracuse_35"], C["syracuse_mlk"]])
    p3 = p3s.union(p3w).buffer(0)

    p6w = poly([C["syracuse_mlk"], C["syracuse_35"], C["cp_35"], C["cp_mlk"]])
    # East housing meets D7 on the railroad (40th) from CP Blvd to Boston
    p6e = poly([C["cp_35"], C["boston_35"], C["boston_40"], C["cp_40"]])
    p6 = p6w.union(p6e).buffer(0)

    # D7: same I-70 line as D8, then Havana / railroad / station
    p7 = poly(
        [
            *i70,
            C["havana_40"],
            C["boston_40"],
            C["cp_40"],
            C["cp_35"],
            C["quebec_35"],
        ]
    )

    p5 = poly([C["creek_mlk"], C["havana_mlk"], C["havana_26"], C["dallas_26"], C["creek_26"]])

    # D1 west of Havana (fan north of MLK) plus east finger to Peoria.
    # Two rings that share Havana so union does not bow-tie.
    p1w = poly([C["boston_40"], C["havana_40"], C["havana_mlk"], C["creek_mlk"]])
    # East of Havana: follow Havana, MLK to Peoria, Peoria, 26th. No diagonal through the lake.
    p1e = poly(
        [
            C["havana_mlk"],
            C["peoria_mlk"],
            C["peoria_26"],
            C["havana_26"],
        ]
    )
    p1 = p1w.union(p1e).buffer(0)

    geoms = {
        1: p1.buffer(0),
        2: p2.buffer(0),
        3: p3.buffer(0),
        4: p4.buffer(0),
        5: p5.buffer(0),
        6: p6.buffer(0),
        7: p7.buffer(0),
        8: p8.buffer(0),
        9: p9.buffer(0),
        10: p10.buffer(0),
        11: p11.buffer(0),
    }

    fc = json.loads(OUT_PATH.read_text())
    for feat in fc["features"]:
        i = feat["properties"]["id"]
        g = geoms[i]
        feat["geometry"] = to_geom(g)
        lat, lng = label_of(g)
        feat["properties"]["color"] = COLORS[i]
        feat["properties"]["neighborhoods"] = list(NEIGHBORHOODS[i])
        feat["properties"]["source"] = "official-map-corner-pins"
        feat["properties"]["labelLat"] = lat
        feat["properties"]["labelLng"] = lng
        if i == 8:
            feat["properties"]["blurb"] = (
                "North of I-70 around Conservatory Green Plaza. The Cube is in this district."
            )
    OUT_PATH.write_text(json.dumps(fc))

    failed = 0
    checks = [
        ("Aviator", -104.89483, 39.75642, 2),
        ("Founders Green", -104.90053, 39.7577, 2),
        ("Puddle Jumper", -104.88568, 39.75162, 4),
        ("Westerly Creek", -104.88, 39.7585, 3),
        ("Eastbridge", -104.873, 39.757, 5),
        ("35th & Uinta", -104.893, 39.765, 6),
        ("RTD station", -104.8918, 39.7699, 7),
        ("Willow 55th", -104.896, 39.7945, 9),
        ("Aurora 26th", -104.85596, 39.75469, 1),
        ("Jet Stream", -104.88166, 39.7666, 6),
        ("The Cube", -104.89087, 39.78577, 8),
        ("Maverick", -104.88598, 39.78912, 8),
        ("Splash Landing", -104.8688, 39.8052, 11),
        ("Fred Thomas", -104.9015, 39.7528, None),
        ("Park lawn", -104.885, 39.762, None),
    ]
    for name, lon, lat, exp in checks:
        hits = [i for i, g in geoms.items() if (not g.is_empty) and g.covers(Point(lon, lat))]
        ok = (hits == [exp]) if exp else (hits == [])
        if not ok:
            failed += 1
        print(("OK  " if ok else "FAIL"), name, "->", hits, "expected", exp)

    # gap check: shared 26th and railroad should have zero hole between neighbors
    def gap(a, b):
        u = geoms[a].buffer(0.00002).union(geoms[b].buffer(0.00002))
        return geoms[a].distance(geoms[b])

    for a, b in [(2, 4), (2, 3), (3, 4), (3, 6), (6, 7), (7, 1), (6, 1), (5, 1), (5, 4), (8, 9), (10, 11)]:
        d = geoms[a].distance(geoms[b])
        print(f"dist D{a}-D{b} {d:.8f} {'GAP' if d > 1e-7 else 'touch'}")
    print("failed", failed)
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
