#!/usr/bin/env python3
"""Rebuild delegate districts from the official printed MCA map.

Topology is the colored outlines on public/maps/mca-delegates-official.jpg.
Borders follow named OSM streets and the existing Beeler Park / Prairie Meadow
curves. Central Park's 80-acre lawn is left in D6 (CP North) so the park is not
a hole; Fred Thomas Park stays outside every district.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import unary_union

from rebuild_d10_d11 import (
    OSM_PATH,
    OUT_PATH,
    close_ring,
    follow,
    from_xy,
    load_named_graph,
    nearest,
    to_xy,
)


def append_path(ring, path, skip_first=True):
    pts = path[1:] if skip_first and ring else path
    for p in pts:
        if not ring or ring[-1] != p:
            ring.append(list(p))


def lon_bins(osm, names, lon_min, lon_max, lat_min, lat_max, pick="north"):
    bins = {}
    for way in osm.get("elements", []):
        if (way.get("tags") or {}).get("name") not in names:
            continue
        for p in way.get("geometry") or []:
            if not (lon_min <= p["lon"] <= lon_max and lat_min <= p["lat"] <= lat_max):
                continue
            key = round(p["lon"] / 0.00008)
            prev = bins.get(key)
            if prev is None:
                bins[key] = (p["lon"], p["lat"])
            elif pick == "north" and p["lat"] > prev[1]:
                bins[key] = (p["lon"], p["lat"])
            elif pick == "south" and p["lat"] < prev[1]:
                bins[key] = (p["lon"], p["lat"])
    return [[lon, lat] for lon, lat in sorted(bins.values())]


def as_ring(poly):
    if poly.is_empty:
        return []
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    poly = poly.buffer(0)
    coords = []
    for x, y in poly.exterior.coords:
        lon, lat = from_xy(x, y)
        coords.append([round(lon, 6), round(lat, 6)])
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    if not Polygon(coords).exterior.is_ccw:
        coords = list(reversed(coords))
    return coords


def poly_of(ring):
    return Polygon([to_xy(*p) for p in ring]).buffer(0)


def node_ll(G, nid, fallback):
    if nid is None:
        return list(fallback)
    return [G.nodes[nid]["lon"], G.nodes[nid]["lat"]]


# Official printed outline colors (fills on the Leaflet map).
OFFICIAL_COLORS = {
    1: "#7aa35a",
    2: "#8fbf6a",
    3: "#d06aa8",
    4: "#e39a3c",
    5: "#4eb8d0",
    6: "#d6c94a",
    7: "#e05454",
    8: "#4a72d4",
    9: "#d4923a",
    10: "#2ebfb6",
    11: "#e878a8",
}


def rebuild():
    osm = json.loads(OSM_PATH.read_text())
    fc = json.loads(OUT_PATH.read_text())
    existing = {f["properties"]["id"]: f for f in fc["features"]}

    gqc = load_named_graph(osm, {"North Quebec Street"}, lon_range=(-104.9042, -104.9028), lat_range=(39.7465, 39.7795))
    gsy = load_named_graph(osm, {"North Syracuse Street"}, lon_range=(-104.9000, -104.8984), lat_range=(39.7468, 39.7555))
    gcp = load_named_graph(osm, {"North Central Park Boulevard"}, lon_range=(-104.8925, -104.8825), lat_range=(39.7468, 39.7995))
    gdal = load_named_graph(osm, {"North Dallas Street"}, lon_range=(-104.8770, -104.8748), lat_range=(39.7468, 39.7995))
    ghav = load_named_graph(osm, {"North Havana Street"}, lon_range=(-104.8670, -104.8645), lat_range=(39.7530, 39.8145))
    gpeo = load_named_graph(osm, {"North Peoria Street"}, lon_range=(-104.8485, -104.8455), lat_range=(39.7525, 39.7565))
    gmv = load_named_graph(osm, {"East Montview Boulevard"}, lon_range=(-104.900, -104.874), lat_range=(39.7470, 39.7478))
    g26 = load_named_graph(osm, {"East 26th Avenue"}, lon_range=(-104.904, -104.846), lat_range=(39.7542, 39.7555))
    gmlk = load_named_graph(osm, {"East Martin Luther King Jr Boulevard"}, lon_range=(-104.904, -104.864), lat_range=(39.7595, 39.7616))
    g35 = load_named_graph(osm, {"East 35th Avenue"}, lon_range=(-104.904, -104.888), lat_range=(39.7645, 39.7660))
    g40 = load_named_graph(osm, {"East 40th Avenue", "East Smith Road"}, lon_range=(-104.904, -104.864), lat_range=(39.7705, 39.7735))
    g56 = load_named_graph(osm, {"East 56th Avenue"}, lon_range=(-104.899, -104.874), lat_range=(39.7979, 39.7988))
    gspr = load_named_graph(osm, {"North Spruce Street"}, lon_range=(-104.8985, -104.8968), lat_range=(39.7845, 39.7990))
    gpm = load_named_graph(osm, {"East Prairie Meadow Drive"}, lon_range=(-104.8985, -104.8748), lat_range=(39.7898, 39.7948))
    gbee = load_named_graph(osm, {"North Beeler Street"}, lon_range=(-104.8832, -104.8805), lat_range=(39.7765, 39.7955))
    gwest8 = load_named_graph(
        osm,
        {
            "North Spruce Street",
            "East Northfield Boulevard",
            "North Northfield Quebec Street",
            "Sand Creek Drive South",
        },
        lon_range=(-104.904, -104.896),
        lat_range=(39.7768, 39.795),
    )

    def corner(G, lon, lat):
        nid, _ = nearest(G, lon, lat)
        return node_ll(G, nid, (lon, lat))

    # --- D2 East 29th: Quebec–MLK–Central Park Blvd–26th. Fred Thomas is south of 26th. ---
    d2_nw = corner(gmlk, -104.9034, 39.7600)
    d2_ne = corner(gmlk, -104.8908, 39.7599)
    d2_se = corner(g26, -104.8908, 39.7547)
    d2_sw = corner(g26, -104.9034, 39.7547)
    d2 = []
    append_path(d2, follow(gqc, d2_nw, d2_sw), skip_first=False)
    append_path(d2, follow(g26, d2_sw, d2_se))
    append_path(d2, follow(gcp, d2_se, d2_ne) if gcp.number_of_nodes() else [d2_se, d2_ne])
    append_path(d2, follow(gmlk, d2_ne, d2_nw))
    d2 = close_ring(d2)

    # --- D4 South End: Syracuse–Montview–Dallas–26th ---
    d4_sw = corner(gmv, -104.89876, 39.74743)
    d4_se = corner(gmv, -104.8764, 39.74738)
    d4_ne = corner(g26, -104.8764, 39.7547)
    d4_nw = corner(g26, -104.8988, 39.7547)
    d4 = []
    append_path(d4, follow(gsy, d4_nw, d4_sw), skip_first=False)
    append_path(d4, follow(gmv, d4_sw, d4_se))
    append_path(d4, follow(gdal, d4_se, d4_ne) if gdal.number_of_nodes() else [d4_se, d4_ne])
    append_path(d4, follow(g26, d4_ne, d4_nw))
    d4 = close_ring(d4)

    # --- D3 Westerly Creek: CP Blvd–MLK–creek/Dallas–26th ---
    d3_nw = d2_ne
    d3_ne = corner(gmlk, -104.8780, 39.7599)
    d3_se = corner(g26, -104.8780, 39.7547)
    d3_sw = d2_se
    d3 = []
    append_path(d3, follow(gcp, d3_nw, d3_sw), skip_first=False)
    append_path(d3, follow(g26, d3_sw, d3_se))
    append_path(d3, [d3_se, d3_ne])
    append_path(d3, follow(gmlk, d3_ne, d3_nw))
    d3 = close_ring(d3)

    # --- D5 Eastbridge: 26th–Havana–MLK/creek. Keep current east finger of D5, snap arterials. ---
    old5 = existing[5]["geometry"]["coordinates"][0]
    d5_poly = poly_of(old5).simplify(8.0, preserve_topology=True)
    d5 = as_ring(d5_poly)

    # --- D1 North Eastbridge & Bluff Lake: keep the east-finger community edge ---
    old1 = existing[1]["geometry"]["coordinates"][0]
    d1_poly = poly_of(old1).simplify(4.0, preserve_topology=True)
    d1 = as_ring(d1_poly)

    # --- D7 Center Field: I-70 band + RTD station block ---
    i70 = lon_bins(
        osm,
        {"Tuskegee Airmen Memorial Highway", "Dwight D. Eisenhower Highway"},
        -104.9040,
        -104.8645,
        39.7750,
        39.7795,
        pick="south",
    )
    d7_nw = corner(gqc, -104.9034, 39.7783)
    d7_sw_st = corner(g35, -104.9035, 39.7651)  # station south-west (35th & Quebec)
    d7_se_st = corner(g35, -104.8907, 39.7651)  # 35th & CP Blvd
    d7_cp_40 = corner(g40, -104.8907, 39.7725)
    d7_hav_40 = corner(g40, -104.8660, 39.7725)
    d7_hav_i70 = corner(ghav, -104.8660, 39.7757)
    d7 = []
    # west: Quebec I-70 down to 35th
    append_path(d7, follow(gqc, d7_nw, d7_sw_st), skip_first=False)
    append_path(d7, follow(g35, d7_sw_st, d7_se_st))
    append_path(d7, follow(gcp, d7_se_st, d7_cp_40))
    append_path(d7, follow(g40, d7_cp_40, d7_hav_40) if g40.number_of_nodes() else [d7_cp_40, d7_hav_40])
    append_path(d7, follow(ghav, d7_hav_40, d7_hav_i70))
    if i70:
        # I-70 westbound along the south edge, Havana → Quebec
        i70_w = [p for p in i70 if p[0] <= d7_hav_i70[0] + 0.0004]
        append_path(d7, list(reversed(i70_w)))
    else:
        append_path(d7, [d7_nw])
    d7 = close_ring(d7)

    # --- D6 CP North & CP West: Quebec–35th–MLK–creek, plus park housing north of MLK ---
    d6_nw = d7_sw_st
    d6_sw = d2_nw
    d6_se = corner(gmlk, -104.8775, 39.7599)
    d6_ne_park = corner(g40, -104.8775, 39.7725) if g40.number_of_nodes() else [-104.8775, 39.772]
    d6 = []
    append_path(d6, follow(gqc, d6_nw, d6_sw), skip_first=False)
    append_path(d6, follow(gmlk, d6_sw, d6_se))
    append_path(d6, [d6_se, d6_ne_park])
    # north edge = D7 south, reversed: 40th Havana is too far; use 40th to CP Blvd then 35th
    append_path(d6, follow(g40, d6_ne_park, d7_cp_40) if g40.number_of_nodes() else [d6_ne_park, d7_cp_40])
    append_path(d6, follow(gcp, d7_cp_40, d7_se_st))
    append_path(d6, follow(g35, d7_se_st, d6_nw))
    d6 = close_ring(d6)

    # --- D8 Conservatory Green: Spruce / greenbelt / I-70 / Dallas / Prairie Meadow ---
    pm_w = corner(gpm, -104.89732, 39.7934)
    pm_e = corner(gpm, -104.8759, 39.7904)
    prairie = follow(gpm, pm_w, pm_e)
    spr_n = corner(gspr, prairie[0][0], prairie[0][1])
    spr_s = corner(gspr, -104.8974, 39.7857)
    spruce = follow(gspr, spr_n, spr_s)
    i70_n = lon_bins(
        osm,
        {"Tuskegee Airmen Memorial Highway", "Dwight D. Eisenhower Highway"},
        -104.9018,
        -104.8748,
        39.7760,
        39.7792,
        pick="north",
    )
    west_to_i70 = follow(gwest8, spruce[-1], i70_n[0] if i70_n else [-104.9001, 39.7784], max_direct=2.2)
    da_s = corner(gdal, -104.8755, 39.7772)
    da_n = corner(gdal, prairie[-1][0], prairie[-1][1])
    dallas_8 = follow(gdal, da_s, da_n)
    d8 = []
    append_path(d8, spruce, skip_first=False)
    append_path(d8, west_to_i70)
    if i70_n:
        i70_clip = [p for p in i70_n if p[0] <= da_s[0] + 0.0004]
        append_path(d8, i70_clip)
    append_path(d8, dallas_8)
    append_path(d8, list(reversed(prairie)))
    d8 = close_ring(d8)

    # --- D9 Willow Park: 56th / Dallas / Prairie Meadow / Spruce ---
    d9_nw = corner(g56, -104.8974, 39.7984)
    d9_ne = corner(g56, -104.8755, 39.7983)
    d9 = []
    append_path(d9, follow(g56, d9_nw, d9_ne), skip_first=False)
    append_path(d9, follow(gdal, d9_ne, pm_e, max_direct=2.0))
    append_path(d9, list(reversed(prairie)))
    append_path(d9, follow(gspr, prairie[0], d9_nw))
    d9 = close_ring(d9)

    # --- D10 / D11 already match the official north-inset split ---
    d10 = existing[10]["geometry"]["coordinates"][0]
    d11 = existing[11]["geometry"]["coordinates"][0]

    rings = {1: d1, 2: d2, 3: d3, 4: d4, 5: d5, 6: d6, 7: d7, 8: d8, 9: d9, 10: d10, 11: d11}
    polys = {i: poly_of(r) for i, r in rings.items() if r}

    # Pull D7 out of D6 (station vs 35th band) and D8/D9 out of each other.
    if 6 in polys and 7 in polys:
        polys[6] = polys[6].difference(polys[7]).buffer(0)
    if 8 in polys and 9 in polys:
        # shared prairie edge: keep D9 north of the curve
        pass
    if 2 in polys and 3 in polys:
        polys[3] = polys[3].difference(polys[2]).buffer(0)
    if 2 in polys and 4 in polys:
        polys[4] = polys[4].difference(polys[2]).buffer(0)
    if 3 in polys and 4 in polys:
        polys[4] = polys[4].difference(polys[3]).buffer(0)
    if 3 in polys and 5 in polys:
        polys[3] = polys[3].difference(polys[5]).buffer(0)
    if 5 in polys and 1 in polys:
        # D1 keeps F-15 / Bluff Lake / the Aurora 26th finger
        polys[5] = polys[5].difference(polys[1]).buffer(0)
    if 6 in polys and 3 in polys:
        polys[6] = polys[6].difference(polys[3]).buffer(0)
    if 7 in polys and 1 in polys:
        polys[1] = polys[1].difference(polys[7]).buffer(0)
    if 8 in polys and 9 in polys:
        polys[9] = polys[9].difference(polys[8]).buffer(0)
    if 10 in polys and 11 in polys:
        polys[11] = polys[11].difference(polys[10]).buffer(0)

    skip_simplify = {10, 11, 1}
    for i, p in list(polys.items()):
        if i not in skip_simplify:
            p = p.buffer(0).simplify(6.0, preserve_topology=True)
        rings[i] = as_ring(p)
        polys[i] = poly_of(rings[i]) if rings[i] else p

    for feat in fc["features"]:
        i = feat["properties"]["id"]
        if i in rings and rings[i]:
            feat["geometry"] = {"type": "Polygon", "coordinates": [rings[i]]}
            feat["properties"]["color"] = OFFICIAL_COLORS[i]
            feat["properties"]["source"] = "official-printed-map-streets"
    OUT_PATH.write_text(json.dumps(fc))

    checks = [
        ("Aviator Pool", -104.89483, 39.75642, 2),
        ("Founders Green", -104.90053, 39.7577, 2),
        ("Puddle Jumper", -104.88568, 39.75162, 4),
        ("Westerly Creek", -104.88, 39.757, 3),
        ("Eastbridge", -104.873, 39.757, 5),
        ("CP West", -104.895, 39.763, 6),
        ("RTD station", -104.8918, 39.7699, 7),
        ("Willow west", -104.896, 39.7945, 9),
        ("F-15 Pool", -104.86692, 39.7568, 1),
        ("Aurora 26th", -104.85596, 39.75469, 1),
        ("Jet Stream", -104.88166, 39.7666, 6),
        ("The Cube", -104.89087, 39.78577, 8),
        ("Maverick", -104.88598, 39.78912, 8),
        ("Prairie Meadow", -104.88327, 39.7914, 8),
        ("51st Dr", -104.87918, 39.79206, 8),
        ("Beeler Plaza", -104.876, 39.8004, 10),
        ("Splash Landing", -104.8688, 39.8052, 11),
        ("Fred Thomas (outside)", -104.9015, 39.7528, None),
    ]

    def pip(lon, lat, ring):
        inside = False
        for a, b in zip(range(len(ring)), [len(ring) - 1] + list(range(len(ring) - 1))):
            xi, yi = ring[a]
            xj, yj = ring[b]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-16) + xi:
                inside = not inside
        return inside

    failed = 0
    for name, lon, lat, exp in checks:
        hits = [i for i, ring in rings.items() if ring and pip(lon, lat, ring)]
        ok = (hits == [exp]) if exp else (hits == [])
        if not ok:
            failed += 1
        print(("OK  " if ok else "FAIL"), name, "->", hits, "expected", exp)
    print("verts", {i: len(r) for i, r in rings.items()})
    print("wrote", OUT_PATH, "failed", failed)
    return failed


if __name__ == "__main__":
    raise SystemExit(rebuild())
