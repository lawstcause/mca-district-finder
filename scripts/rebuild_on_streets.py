#!/usr/bin/env python3
"""Rebuild all 11 districts on named OSM streets from the official MCA map.

Dashed borders on public/maps/mca-delegates-streets.jpg follow:

D2  Quebec/Roslyn, 29th Place, Central Park Blvd, 26th, Syracuse (around Fred Thomas)
D3  MLK, 29th Place, Westerly Creek, plus Quebec–Syracuse north of MLK to 35th
D4  26th, Montview, Syracuse, Dallas
D5  MLK, 26th, Westerly Creek, Havana (+ 26th Ave Park east arm)
D6  MLK, 35th, Syracuse, Central Park Blvd, plus park housing to Boston/creek
D7  I-70, Havana, 40th, Central Park Blvd, 35th, Quebec (station block)
D8  Prairie Meadow Dr, Dallas, I-70, Spruce/Northfield greenbelt
D9  56th, Dallas, Prairie Meadow Dr, Spruce
D10 Central Park Blvd, 56th, Beeler Park curve
D11 Havana, 64th, 56th, Beeler Park curve
D1  Havana/MLK fan, 26th–Peoria finger, north to D7
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from shapely.geometry import Polygon

from rebuild_d10_d11 import (
    OSM_PATH,
    OUT_PATH,
    close_ring,
    follow,
    from_xy,
    load_named_graph,
    nearest,
    original_curve,
    park_east_edge,
    to_xy,
)

# Printed-map fills (muted, not neon).
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


def append_path(ring, path, skip_first=True):
    pts = path[1:] if skip_first and ring else path
    for p in pts:
        if not ring or ring[-1] != p:
            ring.append(list(p))


def node_ll(G, lon, lat):
    nid, _ = nearest(G, lon, lat)
    if nid is None:
        return [lon, lat]
    return [G.nodes[nid]["lon"], G.nodes[nid]["lat"]]


def i70_line(osm, lon_min, lon_max, pick="north"):
    """One smooth I-70 edge. Motorway only — no ramps."""
    from shapely.geometry import LineString as _LS

    bins = {}
    for way in osm.get("elements", []):
        tags = way.get("tags") or {}
        if tags.get("highway") != "motorway":
            continue
        if tags.get("name") not in {"Tuskegee Airmen Memorial Highway", "Dwight D. Eisenhower Highway"}:
            continue
        for p in way.get("geometry") or []:
            if not (lon_min <= p["lon"] <= lon_max and 39.7750 <= p["lat"] <= 39.7805):
                continue
            key = round(p["lon"] / 0.0004)  # ~35 m bins, not 8 m scribbles
            prev = bins.get(key)
            if prev is None:
                bins[key] = (p["lon"], p["lat"])
            elif pick == "north" and p["lat"] > prev[1]:
                bins[key] = (p["lon"], p["lat"])
            elif pick == "south" and p["lat"] < prev[1]:
                bins[key] = (p["lon"], p["lat"])
    pts = [[lon, lat] for lon, lat in sorted(bins.values())]
    if len(pts) < 2:
        return pts
    xy = [to_xy(*p) for p in pts]
    simple = _LS(xy).simplify(25.0, preserve_topology=True)
    return [list(from_xy(x, y)) for x, y in simple.coords]


def lon_bins(osm, names, lon_min, lon_max, lat_min, lat_max, pick="north"):
    return i70_line(osm, lon_min, lon_max, pick=pick)


def ring_coords(poly):
    poly = poly.buffer(0)
    if poly.is_empty:
        return []
    coords = []
    for x, y in poly.exterior.coords:
        lon, lat = from_xy(x, y)
        coords.append([round(lon, 6), round(lat, 6)])
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    if not Polygon(coords).exterior.is_ccw:
        coords = list(reversed(coords))
    return coords


def as_ring(poly):
    if poly.is_empty:
        return []
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    return ring_coords(poly)


def as_geom(shapely_poly):
    """GeoJSON geometry; keeps every piece of a MultiPolygon."""
    shapely_poly = shapely_poly.buffer(0)
    if shapely_poly.is_empty:
        return None
    if shapely_poly.geom_type == "MultiPolygon":
        rings = [ring_coords(g) for g in shapely_poly.geoms]
        rings = [r for r in rings if len(r) >= 4]
        if not rings:
            return None
        if len(rings) == 1:
            return {"type": "Polygon", "coordinates": [rings[0]]}
        return {"type": "MultiPolygon", "coordinates": [[r] for r in rings]}
    ring = ring_coords(shapely_poly)
    if len(ring) < 4:
        return None
    return {"type": "Polygon", "coordinates": [ring]}


def poly(ring):
    return Polygon([to_xy(*p) for p in ring]).buffer(0)


def clean(ring):
    return as_ring(poly(close_ring(ring)))


def rebuild():
    osm = json.loads(OSM_PATH.read_text())
    fc = json.loads(OUT_PATH.read_text())

    gqc = load_named_graph(osm, {"North Quebec Street"}, lon_range=(-104.9042, -104.9005), lat_range=(39.7465, 39.7795))
    gsy = load_named_graph(osm, {"North Syracuse Street"}, lon_range=(-104.9000, -104.8984), lat_range=(39.7468, 39.7715))
    groz = load_named_graph(osm, {"North Roslyn Street"}, lon_range=(-104.9020, -104.8985), lat_range=(39.7520, 39.7595))
    gcp = load_named_graph(osm, {"North Central Park Boulevard"}, lon_range=(-104.8920, -104.8825), lat_range=(39.7468, 39.8080))
    gdal = load_named_graph(osm, {"North Dallas Street"}, lon_range=(-104.8775, -104.8745), lat_range=(39.7468, 39.7995))
    ghav = load_named_graph(osm, {"North Havana Street"}, lon_range=(-104.8670, -104.8645), lat_range=(39.7525, 39.8145))
    gpeo = load_named_graph(osm, {"North Peoria Street"}, lon_range=(-104.8480, -104.8458), lat_range=(39.7525, 39.7565))
    gbos = load_named_graph(osm, {"North Boston Street"}, lon_range=(-104.8785, -104.8765), lat_range=(39.7595, 39.7705))
    gmv = load_named_graph(osm, {"East Montview Boulevard"}, lon_range=(-104.900, -104.874), lat_range=(39.7470, 39.7478))
    g26 = load_named_graph(osm, {"East 26th Avenue"}, lon_range=(-104.904, -104.846), lat_range=(39.7542, 39.7555))
    g28 = load_named_graph(osm, {"East 28th Avenue"}, lon_range=(-104.904, -104.885), lat_range=(39.7558, 39.7574))
    g29 = load_named_graph(osm, {"East 29th Avenue"}, lon_range=(-104.904, -104.868), lat_range=(39.7575, 39.7587))
    g29p = load_named_graph(osm, {"East 29th Place"}, lon_range=(-104.904, -104.878), lat_range=(39.7578, 39.7592))
    gmlk = load_named_graph(osm, {"East Martin Luther King Jr Boulevard"}, lon_range=(-104.904, -104.864), lat_range=(39.7595, 39.7618))
    g31 = load_named_graph(osm, {"East 31st Avenue", "East 31st Place"}, lon_range=(-104.878, -104.864), lat_range=(39.7605, 39.7625))
    g35 = load_named_graph(osm, {"East 35th Avenue"}, lon_range=(-104.904, -104.876), lat_range=(39.7647, 39.7660))
    g40 = load_named_graph(osm, {"East 40th Avenue", "East Smith Road"}, lon_range=(-104.904, -104.864), lat_range=(39.7695, 39.7745))
    g56 = load_named_graph(osm, {"East 56th Avenue"}, lon_range=(-104.899, -104.864), lat_range=(39.7979, 39.7988))
    g64 = load_named_graph(osm, {"East 64th Avenue"}, lon_range=(-104.887, -104.864), lat_range=(39.8127, 39.8140))
    gspr = load_named_graph(osm, {"North Spruce Street"}, lon_range=(-104.8985, -104.8965), lat_range=(39.7768, 39.7990))
    gpm = load_named_graph(osm, {"East Prairie Meadow Drive"}, lon_range=(-104.8985, -104.8748), lat_range=(39.7898, 39.7948))
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

    # ----- D2 East 29th: south of 29th Place, north of 26th, west of CP Blvd.
    # West: Quebec at 29th (Founders Green), Syracuse at 26th (Fred Thomas stays out).
    d2_ne = node_ll(g29p, -104.8908, 39.7585)
    d2_nw = node_ll(g29p, -104.9011, 39.7584)  # 29th Place west end
    d2_qc29 = node_ll(gqc, -104.9032, 39.7578)
    d2_qc28 = node_ll(g28, -104.9033, 39.7565)
    d2_sy28 = node_ll(gsy, -104.8988, 39.7565)
    d2_sy26 = node_ll(g26, -104.8988, 39.7547)
    d2_se = node_ll(g26, -104.8908, 39.7547)
    d2 = []
    append_path(d2, follow(g29p, d2_nw, d2_ne) if g29p.number_of_nodes() else [d2_nw, d2_ne], skip_first=False)
    append_path(d2, follow(gcp, d2_ne, d2_se))
    append_path(d2, follow(g26, d2_se, d2_sy26))
    append_path(d2, follow(gsy, d2_sy26, d2_sy28) if gsy.number_of_nodes() else [d2_sy26, d2_sy28])
    if g28.number_of_nodes():
        append_path(d2, follow(g28, d2_sy28, d2_qc28))
        append_path(d2, follow(gqc, d2_qc28, d2_qc29))
    else:
        append_path(d2, [d2_sy28, d2_qc29])
    # up to 29th Place west
    append_path(d2, follow(g29, d2_qc29, d2_nw) if g29.number_of_nodes() else [d2_qc29, d2_nw])
    d2 = clean(d2)

    # ----- D4 South End: Syracuse – Montview – Dallas – 26th -----
    d4_nw = d2_sy26
    d4_sw = node_ll(gmv, -104.89876, 39.74743)
    d4_se = node_ll(gmv, -104.8764, 39.74738)
    d4_ne = node_ll(g26, -104.8764, 39.7547)
    d4 = []
    append_path(d4, follow(gsy, d4_nw, d4_sw), skip_first=False)
    append_path(d4, follow(gmv, d4_sw, d4_se))
    append_path(d4, follow(gdal, d4_se, d4_ne))
    append_path(d4, follow(g26, d4_ne, d4_nw))
    d4 = clean(d4)

    # ----- D3 Westerly Creek -----
    # South band: 29th Place → MLK, Quebec → Westerly Creek.
    # West strip: MLK → 35th, Quebec → Syracuse (CP West is east of Syracuse).
    g35_d3 = load_named_graph(osm, {"East 35th Avenue"}, lon_range=(-104.9040, -104.8980), lat_range=(39.7647, 39.7660))
    d3_qc_mlk = node_ll(gqc, -104.9034, 39.7605)
    d3_qc_29 = node_ll(gqc, -104.9032, 39.7580)
    d3_creek_mlk = node_ll(gmlk, -104.8773, 39.7599)
    d3_creek_29 = [-104.8773, 39.7584]
    d3_sy_mlk = node_ll(gmlk, -104.8988, 39.7600)
    d3_sy_35 = node_ll(g35_d3, -104.8988, 39.7651)
    d3_qc_35 = node_ll(g35_d3, -104.9035, 39.7651)
    south3 = [
        d3_qc_29,
        d3_creek_29,
        d3_creek_mlk,
        d3_qc_mlk,
        d3_qc_29,
    ]
    # snap the long sides onto MLK / Quebec
    s3 = []
    append_path(s3, follow(gqc, d3_qc_mlk, d3_qc_29), skip_first=False)
    append_path(s3, [d3_qc_29, d3_creek_29, d3_creek_mlk])
    append_path(s3, follow(gmlk, d3_creek_mlk, d3_qc_mlk))
    west3 = []
    append_path(west3, follow(gqc, d3_qc_mlk, d3_qc_35), skip_first=False)
    append_path(west3, follow(g35_d3, d3_qc_35, d3_sy_35) if g35_d3.number_of_nodes() else [d3_qc_35, d3_sy_35])
    append_path(west3, follow(gsy, d3_sy_35, d3_sy_mlk))
    append_path(west3, follow(gmlk, d3_sy_mlk, d3_qc_mlk))
    d3 = as_ring(poly(close_ring(s3)).union(poly(close_ring(west3))).buffer(0))

    # ----- D6 CP North & CP West: Syracuse–CP Blvd–MLK–35th, plus park housing -----
    g35_d6 = load_named_graph(osm, {"East 35th Avenue"}, lon_range=(-104.9000, -104.8765), lat_range=(39.7647, 39.7660))
    d6_nw = d3_sy_35
    d6_sw = d3_sy_mlk
    d6_cp_mlk = node_ll(gmlk, -104.8908, 39.7599)
    d6_cp_35 = node_ll(g35_d6, -104.8907, 39.7651)
    d6_bos_35 = node_ll(g35, -104.8775, 39.7652)
    d6_bos_n = node_ll(g40, -104.8775, 39.7700) if g40.number_of_nodes() else [-104.8775, 39.7700]
    d6_40_cp = node_ll(g40, -104.8907, 39.7705) if g40.number_of_nodes() else [-104.8907, 39.770]
    west6 = close_ring([d6_sw, d6_nw, d6_cp_35, d6_cp_mlk])
    east6 = close_ring([d6_cp_35, d6_bos_35, d6_bos_n, d6_40_cp])
    wpoly, epoly = poly(west6), poly(east6)
    print("west6 valid", wpoly.is_valid, "area", wpoly.area, "east6", epoly.is_valid, epoly.area)
    d6 = as_ring(wpoly.union(epoly).buffer(0))

    # ----- D7 Center Field: I-70 + station -----
    i70_s = lon_bins(
        osm,
        {"Tuskegee Airmen Memorial Highway", "Dwight D. Eisenhower Highway"},
        -104.9040,
        -104.8648,
        39.7750,
        39.7795,
        pick="south",
    )
    d7_qc_i70 = node_ll(gqc, -104.9034, 39.7783)
    d7_qc_35 = d3_qc_35
    d7_cp_35 = d6_cp_35
    d7_cp_40 = node_ll(g40, -104.8907, 39.7720) if g40.number_of_nodes() else d6_40_cp
    d7_hav_40 = node_ll(g40, -104.8660, 39.7720) if g40.number_of_nodes() else node_ll(ghav, -104.8660, 39.772)
    d7_hav_i70 = node_ll(ghav, -104.8660, 39.7757)
    d7 = []
    append_path(d7, follow(gqc, d7_qc_i70, d7_qc_35), skip_first=False)
    append_path(d7, follow(g35, d7_qc_35, d7_cp_35))
    append_path(d7, follow(gcp, d7_cp_35, d7_cp_40))
    append_path(d7, follow(g40, d7_cp_40, d7_hav_40) if g40.number_of_nodes() else [d7_cp_40, d7_hav_40])
    append_path(d7, follow(ghav, d7_hav_40, d7_hav_i70))
    if i70_s:
        i70_clip = [p for p in i70_s if p[0] <= d7_hav_i70[0] + 0.0005]
        append_path(d7, list(reversed(i70_clip)))
    d7 = clean(d7)

    # ----- D5 Eastbridge: MLK – 26th – creek – Havana -----
    d5_nw = node_ll(gmlk, -104.8780, 39.7599)
    d5_ne = node_ll(gmlk, -104.8660, 39.7600)
    d5_se = node_ll(g26, -104.8660, 39.7548)
    d5_sw = node_ll(g26, -104.8785, 39.7546)
    # east arm along 26th to ~-104.854 (26th Ave Park + a block east of Havana)
    d5 = []
    append_path(d5, follow(gmlk, d5_nw, d5_ne), skip_first=False)
    append_path(d5, follow(ghav, d5_ne, d5_se))
    append_path(d5, follow(g26, d5_se, d5_sw))
    append_path(d5, [d5_sw, d5_nw])
    d5 = clean(d5)

    # ----- D1 North Eastbridge & Bluff Lake -----
    d1_hav_n = node_ll(ghav, -104.8660, 39.7691)
    d1_hav_mlk = d5_ne
    d1_mlk_w = node_ll(gmlk, -104.8774, 39.7599)
    d1_n_w = [-104.8774, 39.7692]
    d1_peo_26 = [-104.8468, 39.75450]
    d1_26_hav = [-104.8660, 39.75450]
    west_blk = close_ring([
        d1_hav_n,
        d1_hav_mlk,
        d1_mlk_w,
        d1_n_w,
    ])
    hand = json.loads(OUT_PATH.with_name("districts.handdrawn.geojson").read_text())
    h1 = next(f for f in hand["features"] if f["properties"]["id"] == 1)["geometry"]["coordinates"][0]
    arc = sorted([p for p in h1 if p[0] >= -104.8660], key=lambda p: p[0])
    finger = close_ring(
        [d1_26_hav, d1_peo_26]
        + (list(reversed(arc)) if arc else [[-104.8468, 39.7565], [-104.8660, 39.7691]])
        + [d1_hav_n]
    )
    d1 = as_ring(poly(west_blk).union(poly(finger)).buffer(0))

    # ----- D8 Conservatory Green: Prairie Meadow / Dallas / I-70 / Spruce -----
    pm_w = node_ll(gpm, -104.89732, 39.7934)
    pm_e = node_ll(gpm, -104.8759, 39.7904)
    prairie = follow(gpm, pm_w, pm_e)
    spr_n = node_ll(gspr, prairie[0][0], prairie[0][1])
    spr_s = node_ll(gspr, -104.8974, 39.7857)
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
    da_s = node_ll(gdal, -104.8755, 39.7770)
    da_n = node_ll(gdal, prairie[-1][0], prairie[-1][1])
    d8 = []
    append_path(d8, spruce, skip_first=False)
    append_path(d8, west_to_i70)
    if i70_n:
        i70_clip = [p for p in i70_n if p[0] <= da_s[0] + 0.0004]
        append_path(d8, i70_clip)
    append_path(d8, follow(gdal, da_s, da_n))
    append_path(d8, list(reversed(prairie)))
    d8 = clean(d8)

    # ----- D9 Willow Park: 56th / Dallas / Prairie Meadow / Spruce -----
    d9_nw = node_ll(g56, -104.8974, 39.7984)
    d9_ne = node_ll(g56, -104.8755, 39.7983)
    d9 = []
    append_path(d9, follow(g56, d9_nw, d9_ne), skip_first=False)
    append_path(d9, follow(gdal, d9_ne, pm_e, max_direct=2.0))
    append_path(d9, list(reversed(prairie)))
    append_path(d9, follow(gspr, prairie[0], d9_nw))
    d9 = clean(d9)

    # ----- D10 / D11 from named streets + Beeler Park curve -----
    curve = original_curve()
    se56 = curve[0]
    nw_cp = curve[-1]
    n56_se, _ = nearest(g56, *se56)
    se56 = [g56.nodes[n56_se]["lon"], g56.nodes[n56_se]["lat"]] if n56_se else se56
    ncp, _ = nearest(gcp, *nw_cp)
    nw_cp = [gcp.nodes[ncp]["lon"], gcp.nodes[ncp]["lat"]] if ncp else nw_cp
    n56_sw, _ = nearest(g56, nw_cp[0], 39.7984)
    sw56 = [g56.nodes[n56_sw]["lon"], g56.nodes[n56_sw]["lat"]] if n56_sw else [nw_cp[0], 39.7984]
    hav64 = node_ll(g64, -104.86609, 39.8130)
    hav56 = node_ll(g56, -104.86609, 39.7984)
    west11 = park_east_edge(osm, "Prairie Gateway Open Space", -104.88485, -104.88420, 39.80705, 39.81315)
    if len(west11) < 2:
        west11 = [[-104.88442, 39.80714], [-104.88442, 39.81297]]
    c64_west = west11[-1]

    d10 = []
    d10 += follow(g56, sw56, se56)
    d10 += curve[1:]
    d10 += follow(gcp, nw_cp, sw56)[1:]
    d10 = clean(d10)

    d11 = []
    d11 += follow(ghav, hav56, hav64)
    along64 = follow(g64, hav64, c64_west)
    d11 += along64[1:]
    d11 += list(reversed(west11[:-1]))
    d11 += list(reversed(curve[1:-1]))
    d11 += follow(g56, se56, hav56)[1:]
    d11 = clean(d11)

    rings = {1: d1, 2: d2, 3: d3, 4: d4, 5: d5, 6: d6, 7: d7, 8: d8, 9: d9, 10: d10, 11: d11}
    polys = {i: poly(r) for i, r in rings.items() if r and len(r) >= 4}

    # Shared edges: subtract in map order so neighbors don't overlap.
    pairs = [
        (2, 3), (2, 4), (3, 4), (3, 6), (5, 1), (5, 3),
        (6, 7), (6, 3), (7, 1), (8, 9), (10, 11), (4, 5),
    ]
    for keep, clip in pairs:
        if keep in polys and clip in polys:
            polys[clip] = polys[clip].difference(polys[keep]).buffer(0)

    for i, p in list(polys.items()):
        rings[i] = as_ring(p)

    for feat in fc["features"]:
        i = feat["properties"]["id"]
        if i in rings and len(rings[i]) >= 4:
            feat["geometry"] = {"type": "Polygon", "coordinates": [rings[i]]}
            feat["properties"]["color"] = COLORS[i]
            feat["properties"]["source"] = "official-map-named-streets"
    OUT_PATH.write_text(json.dumps(fc))

    def pip(lon, lat, ring):
        inside = False
        for a, b in zip(range(len(ring)), [len(ring) - 1] + list(range(len(ring) - 1))):
            xi, yi = ring[a]
            xj, yj = ring[b]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-16) + xi:
                inside = not inside
        return inside

    checks = [
        ("Aviator (29th/Ulster)", -104.89483, 39.75642, 2),
        ("Founders Green", -104.90053, 39.7577, 2),
        ("Puddle Jumper", -104.88568, 39.75162, 4),
        ("Westerly Creek 29th Pl", -104.88, 39.7585, 3),
        ("Eastbridge 28th", -104.873, 39.757, 5),
        ("35th & Uinta (D6)", -104.893, 39.765, 6),
        ("RTD station", -104.8918, 39.7699, 7),
        ("Willow 55th", -104.896, 39.7945, 9),
        ("Aurora 26th finger", -104.85596, 39.75469, 1),
        ("Jet Stream / 35th housing", -104.88166, 39.7666, 6),
        ("The Cube", -104.89087, 39.78577, 8),
        ("Conservatory Plaza", -104.89224, 39.78702, 8),
        ("Maverick", -104.88598, 39.78912, 8),
        ("Splash Landing", -104.8688, 39.8052, 11),
        ("Fred Thomas (out)", -104.9015, 39.7528, None),
        ("Central Park lawn (out)", -104.885, 39.762, None),
    ]
    failed = 0
    for name, lon, lat, exp in checks:
        hits = [i for i, r in rings.items() if r and pip(lon, lat, r)]
        ok = (hits == [exp]) if exp else (hits == [])
        if not ok:
            failed += 1
        print(("OK  " if ok else "FAIL"), name, "->", hits, "expected", exp)
    print("verts", {i: len(r) for i, r in rings.items()})
    print("failed", failed)
    return failed


if __name__ == "__main__":
    raise SystemExit(rebuild())
