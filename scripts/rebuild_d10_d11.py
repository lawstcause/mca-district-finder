#!/usr/bin/env python3
"""Rebuild D10 (Beeler Park) and D11 (North End) on real streets + the drawn park curve.

The generic road-snapper sent D11 north of 64th onto Wildlife Drive and chewed the
shared Beeler Park loop into inner park paths. These two districts are a rectangle
of 56th / Havana / 64th / Central Park Blvd, meeting on the green-space curve.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import networkx as nx
from shapely.geometry import LineString, Polygon

ROOT = Path(__file__).resolve().parents[1]
OSM_PATH = Path(__file__).with_name("osm_network.json")
HAND_PATH = ROOT / "public" / "data" / "districts.handdrawn.geojson"
OUT_PATH = ROOT / "public" / "data" / "districts.geojson"

LAT0 = 39.78
M_LAT = 111_320.0
M_LON = 111_320.0 * math.cos(math.radians(LAT0))


def to_xy(lon, lat):
    return (lon + 104.88) * M_LON, (lat - LAT0) * M_LAT


def from_xy(x, y):
    return x / M_LON - 104.88, y / M_LAT + LAT0


def nid_of(x, y):
    return (int(round(x / 2.0)), int(round(y / 2.0)))


def load_named_graph(osm, names, lon_range=None, lat_range=None):
    G = nx.Graph()

    def ok(lon, lat):
        if lon_range and not (lon_range[0] <= lon <= lon_range[1]):
            return False
        if lat_range and not (lat_range[0] <= lat <= lat_range[1]):
            return False
        return True

    for way in osm.get("elements", []):
        tags = way.get("tags") or {}
        if tags.get("name") not in names:
            continue
        geom = [p for p in (way.get("geometry") or []) if ok(p["lon"], p["lat"])]
        if len(geom) < 2:
            continue
        ids = []
        for p in geom:
            x, y = to_xy(p["lon"], p["lat"])
            nid = nid_of(x, y)
            if nid not in G:
                G.add_node(nid, lon=p["lon"], lat=p["lat"], x=x, y=y)
            ids.append(nid)
        for a, b in zip(ids, ids[1:]):
            if a == b:
                continue
            length = math.hypot(G.nodes[a]["x"] - G.nodes[b]["x"], G.nodes[a]["y"] - G.nodes[b]["y"])
            if not G.has_edge(a, b) or length < G[a][b]["length"]:
                G.add_edge(a, b, length=length)
    return G


def nearest(G, lon, lat):
    x, y = to_xy(lon, lat)
    best, best_d = None, 1e18
    for nid, d in G.nodes(data=True):
        dist = math.hypot(d["x"] - x, d["y"] - y)
        if dist < best_d:
            best, best_d = nid, dist
    return best, best_d


def follow(G, start_ll, end_ll, max_direct=2.4):
    a, da = nearest(G, *start_ll)
    b, db = nearest(G, *end_ll)
    if a is None or b is None:
        return [list(start_ll), list(end_ll)]
    if not nx.has_path(G, a, b):
        return [list(start_ll), list(end_ll)]
    path = nx.shortest_path(G, a, b, weight="length")
    length = sum(G[u][v]["length"] for u, v in zip(path, path[1:]))
    direct = math.hypot(G.nodes[a]["x"] - G.nodes[b]["x"], G.nodes[a]["y"] - G.nodes[b]["y"])
    if direct > 20 and length > direct * max_direct:
        return [list(start_ll), list(end_ll)]
    out = [[G.nodes[n]["lon"], G.nodes[n]["lat"]] for n in path]
    return out


def park_east_edge(osm, name, lon_min, lon_max, lat_min, lat_max):
    """North–south run on the east side of a named park, south→north."""
    pts = []
    for way in osm.get("elements", []):
        tags = way.get("tags") or {}
        if tags.get("name") != name:
            continue
        for p in way.get("geometry") or []:
            if lon_min <= p["lon"] <= lon_max and lat_min <= p["lat"] <= lat_max:
                pts.append((p["lon"], p["lat"]))
    # keep the easternmost point in each ~8 m latitude bin so the south
    # edge of the park cannot sneak in
    bins = {}
    for lon, lat in pts:
        key = round(lat / 0.00007)
        prev = bins.get(key)
        if prev is None or lon > prev[0]:
            bins[key] = (lon, lat)
    return [[lon, lat] for lon, lat in sorted(bins.values(), key=lambda p: p[1])]


def close_ring(ring):
    out = []
    for lon, lat in ring:
        pt = [round(lon, 6), round(lat, 6)]
        if not out or out[-1] != pt:
            out.append(pt)
    if out[0] != out[-1]:
        out.append(out[0])
    p = Polygon(out)
    if not p.exterior.is_ccw:
        out = list(reversed(out))
    return out


def original_curve():
    """Shared Beeler Park green-space curve from the Earth trace, 56th → CP Blvd."""
    hand = json.loads(HAND_PATH.read_text())
    d10 = next(f for f in hand["features"] if f["properties"]["id"] == 10)
    ring = d10["geometry"]["coordinates"][0]
    # ring: NW, SW, SE, then curve back to NW
    # keep from SE (index 2) through NW (last/first)
    curve = ring[2:]
    if curve[-1] != ring[0]:
        curve = curve + [ring[0]]
    # light smooth (~4 m) so it stays a park edge, not a scribble
    xy = [to_xy(lon, lat) for lon, lat in curve]
    simple = LineString(xy).simplify(4.0, preserve_topology=True)
    out = [list(from_xy(x, y)) for x, y in simple.coords]
    return out


def rebuild():
    osm = json.loads(OSM_PATH.read_text())
    g56 = load_named_graph(osm, {"East 56th Avenue"}, lon_range=(-104.887, -104.864), lat_range=(39.7975, 39.7992))
    g64 = load_named_graph(osm, {"East 64th Avenue"}, lon_range=(-104.887, -104.864), lat_range=(39.8127, 39.8140))
    ghav = load_named_graph(osm, {"North Havana Street"}, lon_range=(-104.8670, -104.8640), lat_range=(39.7975, 39.8145))
    gcp = load_named_graph(osm, {"North Central Park Boulevard"}, lon_range=(-104.889, -104.8835), lat_range=(39.7975, 39.809))

    curve = original_curve()  # 56th east → CP Blvd north
    se56 = curve[0]           # ~56th & park
    nw_cp = curve[-1]         # ~CP Blvd north of Beeler Park

    # Prairie Gateway east edge: 64th down to the park curve (N–S only)
    west11 = park_east_edge(osm, "Prairie Gateway Open Space", -104.88485, -104.88420, 39.80705, 39.81315)
    if len(west11) < 2:
        west11 = [[-104.88442, 39.80714], [-104.88442, 39.81297]]
    # south→north already
    c64_west = west11[-1]
    c_curve_west = west11[0]

    # snap curve ends onto 56th / CP Blvd
    n56_se, _ = nearest(g56, *se56)
    se56 = [g56.nodes[n56_se]["lon"], g56.nodes[n56_se]["lat"]] if n56_se else se56
    ncp, _ = nearest(gcp, *nw_cp)
    nw_cp = [gcp.nodes[ncp]["lon"], gcp.nodes[ncp]["lat"]] if ncp else nw_cp

    sw = follow(gcp, (nw_cp[0], 39.7984), (nw_cp[0], 39.7984))  # dummy
    n56_sw, _ = nearest(g56, nw_cp[0], 39.7984)
    sw56 = [g56.nodes[n56_sw]["lon"], g56.nodes[n56_sw]["lat"]] if n56_sw else [nw_cp[0], 39.7984]
    ncp_sw, _ = nearest(gcp, *sw56)
    sw56 = [gcp.nodes[ncp_sw]["lon"], gcp.nodes[ncp_sw]["lat"]] if ncp_sw else sw56

    n64_e, _ = nearest(g64, -104.86609, 39.8130)
    hav64 = [g64.nodes[n64_e]["lon"], g64.nodes[n64_e]["lat"]] if n64_e else [-104.86609, 39.81299]
    n56_e, _ = nearest(g56, -104.86609, 39.7984)
    hav56 = [g56.nodes[n56_e]["lon"], g56.nodes[n56_e]["lat"]] if n56_e else [-104.86609, 39.7984]

    # D10: CP Blvd & 56th → 56th east → park curve → CP Blvd south
    d10 = []
    d10 += follow(g56, sw56, se56)
    d10 += curve[1:]
    d10 += follow(gcp, nw_cp, sw56)[1:]
    d10 = close_ring(d10)

    # D11: Havana & 56th → Havana north → 64th west → park west edge south
    #      → shared curve reversed to 56th → 56th east to Havana
    d11 = []
    d11 += follow(ghav, hav56, hav64)
    along64 = follow(g64, hav64, c64_west)
    straight64 = math.hypot(to_xy(*hav64)[0] - to_xy(*c64_west)[0], to_xy(*hav64)[1] - to_xy(*c64_west)[1])
    along64_len = 0.0
    for a, b in zip(along64, along64[1:]):
        along64_len += math.hypot(to_xy(*a)[0] - to_xy(*b)[0], to_xy(*a)[1] - to_xy(*b)[1])
    if along64_len > straight64 * 1.2 or any(p[1] > 39.8140 for p in along64):
        along64 = [hav64, c64_west]
    d11 += along64[1:]
    # west edge south (reverse of south→north list)
    d11 += list(reversed(west11[:-1]))
    # shared curve from CP Blvd back to 56th
    d11 += list(reversed(curve[1:-1]))
    d11 += follow(g56, se56, hav56)[1:]
    d11 = close_ring(d11)

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

    p10 = Polygon([to_xy(*p) for p in d10]).buffer(0)
    p11 = Polygon([to_xy(*p) for p in d11]).buffer(0)
    d10, d11 = as_ring(p10), as_ring(p11)

    fc = json.loads(OUT_PATH.read_text())
    for feat in fc["features"]:
        if feat["properties"]["id"] == 10:
            feat["geometry"] = {"type": "Polygon", "coordinates": [d10]}
            feat["properties"]["source"] = "streets-and-beeler-park-curve"
        elif feat["properties"]["id"] == 11:
            feat["geometry"] = {"type": "Polygon", "coordinates": [d11]}
            feat["properties"]["source"] = "streets-and-beeler-park-curve"
    OUT_PATH.write_text(json.dumps(fc))

    print(f"D10 verts {len(d10)}  D11 verts {len(d11)}")
    p10 = Polygon([to_xy(*p) for p in d10]).buffer(0)
    p11 = Polygon([to_xy(*p) for p in d11]).buffer(0)
    print(f"D10 valid={p10.is_valid} {p10.area/1e4:.1f} ha")
    print(f"D11 valid={p11.is_valid} {p11.area/1e4:.1f} ha")
    try:
        print(f"overlap {p10.intersection(p11).area:.0f} m2")
    except Exception as exc:
        print("overlap failed", exc)
    checks = {
        "Beeler Park plaza": (-104.8810, 39.8030, 10),
        "Splash Landing": (-104.8688, 39.8052, 11),
        "North End interior": (-104.8720, 39.8080, 11),
        "56th & Havana": (-104.8662, 39.7985, 11),
        "south of 64th west": (-104.8830, 39.8115, 11),
        "north of 64th (should miss)": (-104.8750, 39.8155, None),
    }

    def pip(lon, lat, ring):
        inside = False
        for i, j in zip(range(len(ring)), [len(ring) - 1] + list(range(len(ring) - 1))):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-16) + xi:
                inside = not inside
        return inside

    for name, (lon, lat, exp) in checks.items():
        hits = []
        if pip(lon, lat, d10):
            hits.append(10)
        if pip(lon, lat, d11):
            hits.append(11)
        ok = (hits == [exp]) if exp else (hits == [])
        print(("OK" if ok else "FAIL"), name, "->", hits, "expected", exp)
    print("wrote", OUT_PATH)


if __name__ == "__main__":
    rebuild()
