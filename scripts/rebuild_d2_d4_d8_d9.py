#!/usr/bin/env python3
"""Clean D2, D4, D8, D9 onto named streets.

D8's west side had followed I-70 ramps. D2's southwest had dipped through
Greenway Park. Shared D8/D9 border stays on Prairie Meadow Drive (the curve).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from shapely.geometry import Polygon

from rebuild_d10_d11 import (
    OSM_PATH,
    OUT_PATH,
    follow,
    from_xy,
    load_named_graph,
    nearest,
    to_xy,
)

HAND_PATH = Path(__file__).with_name("rebuild_d10_d11.py").resolve().parents[1] / "public" / "data" / "districts.handdrawn.geojson"
HAND_PATH = OUT_PATH.with_name("districts.handdrawn.geojson")


def close_ring(ring):
    out = []
    for lon, lat in ring:
        pt = [round(lon, 6), round(lat, 6)]
        if not out or out[-1] != pt:
            out.append(pt)
    if out and out[0] != out[-1]:
        out.append(out[0])
    p = Polygon(out)
    if p.exterior.is_ccw is False:
        out = list(reversed(out))
    return out


def as_ring(poly):
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    coords = []
    for x, y in poly.exterior.coords:
        lon, lat = from_xy(x, y)
        coords.append([round(lon, 6), round(lat, 6)])
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    if not Polygon(coords).exterior.is_ccw:
        coords = list(reversed(coords))
    return coords


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


def append_path(ring, path, skip_first=True):
    pts = path[1:] if skip_first and ring else path
    for p in pts:
        if not ring or ring[-1] != p:
            ring.append(list(p))


def rebuild():
    osm = json.loads(OSM_PATH.read_text())

    g29 = load_named_graph(osm, {"East 29th Avenue"}, lon_range=(-104.904, -104.885), lat_range=(39.7570, 39.7588))
    g26 = load_named_graph(osm, {"East 26th Avenue"}, lon_range=(-104.904, -104.878), lat_range=(39.7542, 39.7552))
    gqc = load_named_graph(osm, {"North Quebec Street"}, lon_range=(-104.9042, -104.9028), lat_range=(39.7465, 39.7595))
    gmv = load_named_graph(osm, {"East Montview Boulevard"}, lon_range=(-104.900, -104.878), lat_range=(39.7470, 39.7478))
    gsy = load_named_graph(osm, {"North Syracuse Street"}, lon_range=(-104.9000, -104.8984), lat_range=(39.7468, 39.7555))
    gdal = load_named_graph(osm, {"North Dallas Street"}, lon_range=(-104.8770, -104.8748), lat_range=(39.7468, 39.7992))
    gbee = load_named_graph(osm, {"North Beeler Street"}, lon_range=(-104.8832, -104.8805), lat_range=(39.7765, 39.7955))
    gpm = load_named_graph(osm, {"East Prairie Meadow Drive"}, lon_range=(-104.8985, -104.8748), lat_range=(39.7898, 39.7948))
    g56 = load_named_graph(osm, {"East 56th Avenue"}, lon_range=(-104.899, -104.874), lat_range=(39.7979, 39.7988))
    gspr = load_named_graph(osm, {"North Spruce Street"}, lon_range=(-104.8985, -104.8968), lat_range=(39.7845, 39.7990))
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

    # --- corners ---
    # D2: Quebec & 29th, Quebec south-notch, 26th & east, 29th & east
    q29, _ = nearest(g29, -104.9032, 39.7576)
    d2_nw = [g29.nodes[q29]["lon"], g29.nodes[q29]["lat"]]
    q_sw, _ = nearest(gqc, -104.90317, 39.75358)
    d2_quebec_s = [gqc.nodes[q_sw]["lon"], gqc.nodes[q_sw]["lat"]]
    e26, _ = nearest(g26, -104.88649, 39.75427)
    d2_se = [g26.nodes[e26]["lon"], g26.nodes[e26]["lat"]]
    e29, _ = nearest(g29, -104.88642, 39.75788)
    d2_ne = [g29.nodes[e29]["lon"], g29.nodes[e29]["lat"]]

    # D2 south step from the Earth trace, snapped onto 26th / 23rd-area streets
    # Keep the notch (town center south of 26th) but do not wander into Greenway.
    step = [
        [-104.90317, 39.75358],
        [-104.90076, 39.75367],
        [-104.90019, 39.75215],
        [-104.89692, 39.75221],
        [-104.89395, 39.75348],
        [-104.89164, 39.75423],
        [-104.88649, 39.75427],
    ]
    # snap step points onto 26th when they are on 26th; otherwise keep drawn
    g_step = load_named_graph(
        osm,
        {"East 26th Avenue", "East 23rd Avenue", "North Syracuse Street", "North Quebec Street"},
        lon_range=(-104.904, -104.885),
        lat_range=(39.7508, 39.7552),
    )
    step_snapped = []
    for lon, lat in step:
        nid, dist = nearest(g_step, lon, lat)
        if nid is not None and dist < 80:
            step_snapped.append([g_step.nodes[nid]["lon"], g_step.nodes[nid]["lat"]])
        else:
            step_snapped.append([lon, lat])

    d2 = []
    append_path(d2, follow(gqc, d2_nw, d2_quebec_s), skip_first=False)
    # along the south notch, following named streets when connected
    for a, b in zip(step_snapped, step_snapped[1:]):
        seg = follow(g_step, a, b, max_direct=1.8)
        append_path(d2, seg)
    # east side 26th → 29th (short N-S). No named arterial here; keep a straight.
    append_path(d2, [d2_se, d2_ne])
    append_path(d2, follow(g29, d2_ne, d2_nw))
    d2 = close_ring(d2)

    # D4: Syracuse & Montview, Montview to Dallas, Dallas to D2-south, shared south of D2, Syracuse down
    sy_mv, _ = nearest(gmv, -104.8988, 39.7474)
    d4_sw = [gmv.nodes[sy_mv]["lon"], gmv.nodes[sy_mv]["lat"]]
    da_mv, _ = nearest(gmv, -104.8790, 39.7474)
    d4_se = [gmv.nodes[da_mv]["lon"], gmv.nodes[da_mv]["lat"]]
    da_n, _ = nearest(gdal, -104.8790, 39.7544)
    d4_ne = [gdal.nodes[da_n]["lon"], gdal.nodes[da_n]["lat"]] if da_n else [-104.8790, 39.7544]

    d4 = []
    append_path(d4, follow(gmv, d4_sw, d4_se), skip_first=False)
    append_path(d4, follow(gdal, d4_se, d4_ne) if da_n else [d4_se, d4_ne])
    # north edge = D2 south reversed (the notch), then back to Syracuse/Montview
    d4_north = list(reversed(step_snapped))
    append_path(d4, d4_north)
    sy_n, _ = nearest(gsy, d4_north[-1][0], d4_north[-1][1])
    if sy_n:
        append_path(d4, follow(gsy, d4_north[-1], d4_sw))
    else:
        append_path(d4, [d4_sw])
    d4 = close_ring(d4)

    # D8 / D9 Prairie Meadow shared curve, Spruce → Beeler
    pm_w, _ = nearest(gpm, -104.89732, 39.7934)
    pm_e8, _ = nearest(gpm, -104.8825, 39.7913)
    pm_e9, _ = nearest(gpm, -104.8759, 39.7904)
    prairie_8 = follow(gpm, [gpm.nodes[pm_w]["lon"], gpm.nodes[pm_w]["lat"]], [gpm.nodes[pm_e8]["lon"], gpm.nodes[pm_e8]["lat"]])
    prairie_9 = follow(gpm, [gpm.nodes[pm_w]["lon"], gpm.nodes[pm_w]["lat"]], [gpm.nodes[pm_e9]["lon"], gpm.nodes[pm_e9]["lat"]])

    # D8 east: Beeler from Prairie Meadow down to I-70
    bee_n, _ = nearest(gbee, prairie_8[-1][0], prairie_8[-1][1])
    bee_s, _ = nearest(gbee, -104.88225, 39.77723)
    beeler = follow(gbee, [gbee.nodes[bee_n]["lon"], gbee.nodes[bee_n]["lat"]], [gbee.nodes[bee_s]["lon"], gbee.nodes[bee_s]["lat"]])

    i70 = lon_bins(
        osm,
        {"Tuskegee Airmen Memorial Highway", "Dwight D. Eisenhower Highway"},
        -104.9018,
        -104.8815,
        39.7762,
        39.7792,
        pick="north",
    )
    # west end of I-70 edge near Northfield Quebec, east end near Beeler
    if i70:
        # clip to Beeler longitude
        i70 = [p for p in i70 if p[0] <= beeler[-1][0] + 0.0003]

    # D8 west: Spruce south to Northfield, then named west roads down to I-70 (no ramps)
    spr_n, _ = nearest(gspr, prairie_8[0][0], prairie_8[0][1])
    spr_s, _ = nearest(gspr, -104.8974, 39.7857)
    spruce = follow(gspr, [gspr.nodes[spr_n]["lon"], gspr.nodes[spr_n]["lat"]], [gspr.nodes[spr_s]["lon"], gspr.nodes[spr_s]["lat"]])
    west_to_i70 = follow(gwest8, spruce[-1], i70[0] if i70 else [-104.9001, 39.7784], max_direct=2.2)

    d8 = []
    append_path(d8, spruce, skip_first=False)
    append_path(d8, west_to_i70)
    if i70:
        append_path(d8, i70)
    append_path(d8, list(reversed(beeler)))
    append_path(d8, list(reversed(prairie_8)))
    d8 = close_ring(d8)

    # D9: Spruce/56th → 56th east to Dallas → Dallas south to Prairie Meadow → Prairie Meadow west → Spruce north
    spr56, _ = nearest(g56, -104.8974, 39.7984)
    d9_nw = [g56.nodes[spr56]["lon"], g56.nodes[spr56]["lat"]]
    da56, _ = nearest(g56, -104.8753, 39.7984)
    d9_ne = [g56.nodes[da56]["lon"], g56.nodes[da56]["lat"]]
    da_pm = [gpm.nodes[pm_e9]["lon"], gpm.nodes[pm_e9]["lat"]]

    d9 = []
    append_path(d9, follow(g56, d9_nw, d9_ne), skip_first=False)
    append_path(d9, follow(gdal, d9_ne, da_pm, max_direct=2.0))
    append_path(d9, list(reversed(prairie_9)))
    append_path(d9, follow(gspr, prairie_9[0], d9_nw))
    d9 = close_ring(d9)

    def clean(ring):
        p = Polygon([to_xy(*pt) for pt in ring]).buffer(0)
        return as_ring(p)

    d2, d4, d8, d9 = map(clean, (d2, d4, d8, d9))

    fc = json.loads(OUT_PATH.read_text())
    mapping = {2: d2, 4: d4, 8: d8, 9: d9}
    for feat in fc["features"]:
        i = feat["properties"]["id"]
        if i in mapping:
            feat["geometry"] = {"type": "Polygon", "coordinates": [mapping[i]]}
            feat["properties"]["source"] = "named-streets-from-earth-trace"
    OUT_PATH.write_text(json.dumps(fc))

    def pip(lon, lat, ring):
        inside = False
        for i, j in zip(range(len(ring)), [len(ring) - 1] + list(range(len(ring) - 1))):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-16) + xi:
                inside = not inside
        return inside

    checks = [
        ("Aviator", -104.89483, 39.75642, 2),
        ("Puddle Jumper", -104.88568, 39.75162, 4),
        ("The Cube", -104.89087, 39.78577, 8),
        ("Maverick", -104.88598, 39.78912, 8),
        ("Willow west", -104.896, 39.7945, 9),
        ("north of I-70 ramp (should miss D8)", -104.9025, 39.7820, None),
        ("Greenway park south of D2", -104.8963, 39.7502, 4),
    ]
    print(f"D2 {len(d2)} D4 {len(d4)} D8 {len(d8)} D9 {len(d9)}")
    for name, lon, lat, exp in checks:
        hits = [i for i, ring in ((2, d2), (4, d4), (8, d8), (9, d9)) if pip(lon, lat, ring)]
        ok = (hits == [exp]) if exp else (hits == [])
        print(("OK" if ok else "FAIL"), name, "->", hits, "expected", exp)
    print("wrote", OUT_PATH)


if __name__ == "__main__":
    rebuild()
