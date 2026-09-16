#!/usr/bin/env python3
"""Snap hand-drawn district polygons onto the OSM street (and creek) network."""

from __future__ import annotations

import json
import math
from pathlib import Path

import networkx as nx
from shapely.geometry import LineString, Point, Polygon, mapping  # noqa: F401
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
OSM_PATH = Path(__file__).with_name("osm_network.json")
SRC_PATH = ROOT / "public" / "data" / "districts.handdrawn.geojson"
OUT_PATH = ROOT / "public" / "data" / "districts.geojson"

LAT0 = 39.78
M_LAT = 111_320.0
M_LON = 111_320.0 * math.cos(math.radians(LAT0))

CLASS_PENALTY = {
    "motorway": 1.0,
    "trunk": 1.0,
    "primary": 1.0,
    "secondary": 1.05,
    "tertiary": 1.2,
    "unclassified": 1.6,
    "residential": 2.2,
    "living_street": 2.8,
    "stream": 1.15,
    "river": 1.1,
    "canal": 1.2,
    "park": 1.08,
    "nature_reserve": 1.08,
    "garden": 1.2,
}

MAJOR = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "stream",
    "river",
    "park",
    "nature_reserve",
}


def to_xy(lon: float, lat: float) -> tuple[float, float]:
    return (lon + 104.88) * M_LON, (lat - LAT0) * M_LAT


def from_xy(x: float, y: float) -> tuple[float, float]:
    return x / M_LON - 104.88, y / M_LAT + LAT0


def nid_of(x: float, y: float) -> tuple[int, int]:
    return (int(round(x / 2.0)), int(round(y / 2.0)))


def interp_line(coords: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    if len(coords) < 2:
        return coords
    out = [coords[0]]
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            continue
        n = max(1, int(dist // step))
        for i in range(1, n + 1):
            t = i / n
            out.append((x1 + dx * t, y1 + dy * t))
    return out


def load_osm() -> tuple[nx.Graph, dict]:
    raw = json.loads(OSM_PATH.read_text())
    G = nx.Graph()
    segs = []  # (linestring_xy, kind, name, way_id)
    for way in raw.get("elements", []):
        tags = way.get("tags") or {}
        geom = way.get("geometry") or []
        if len(geom) < 2:
            continue
        kind = tags.get("highway") or tags.get("waterway") or tags.get("leisure") or "other"
        name = tags.get("name") or ""
        penalty = CLASS_PENALTY.get(kind, 2.5)
        xy = [to_xy(p["lon"], p["lat"]) for p in geom]
        dense = interp_line(xy, 12.0)
        ids = []
        for x, y in dense:
            nid = nid_of(x, y)
            if nid not in G:
                lon, lat = from_xy(x, y)
                G.add_node(
                    nid,
                    x=x,
                    y=y,
                    lon=lon,
                    lat=lat,
                    major=kind in MAJOR,
                    names=set(),
                    kinds=set(),
                )
            G.nodes[nid]["names"].add(name)
            G.nodes[nid]["kinds"].add(kind)
            if kind in MAJOR:
                G.nodes[nid]["major"] = True
            ids.append(nid)
        for a, b, (x1, y1), (x2, y2) in zip(ids, ids[1:], dense, dense[1:]):
            if a == b:
                continue
            length = math.hypot(x2 - x1, y2 - y1)
            w = length * penalty
            if G.has_edge(a, b):
                if w < G[a][b]["weight"]:
                    G[a][b]["weight"] = w
                    G[a][b]["length"] = length
            else:
                G.add_edge(a, b, weight=w, length=length, name=name, kind=kind)
        segs.append((LineString(xy), kind, name, way.get("id")))
    return G, {"segs": segs}


def snap_vertex(G: nx.Graph, tree: STRtree, points: list, lon: float, lat: float) -> int:
    """Snap a drawn corner to a nearby intersection, preferring major roads."""
    x, y = to_xy(lon, lat)
    pt = Point(x, y)
    # candidates within 160 m
    idxs = tree.query(pt.buffer(160))
    best_i = None
    best_score = 1e18
    best_maj = None
    best_maj_score = 1e18
    best_x = None
    best_x_score = 1e18
    for i in idxs:
        node = points[int(i)]
        d = math.hypot(node["x"] - x, node["y"] - y)
        if d > 160:
            continue
        deg = G.degree(node["id"])
        # prefer intersections
        score = d + (0 if deg >= 3 else 28)
        if score < best_score:
            best_score = score
            best_i = node["id"]
        if node["major"] and score < best_maj_score:
            best_maj_score = score
            best_maj = node["id"]
        if deg >= 3 and d < 90 and score < best_x_score:
            best_x_score = score
            best_x = node["id"]
    if best_x is not None and best_x_score <= 90:
        return best_x
    if best_maj is not None and best_maj_score <= 70:
        return best_maj
    if best_i is None:
        raise RuntimeError(f"no road near {lon},{lat}")
    return best_i


def corridor_nodes(tree: STRtree, points: list, corridor) -> list:
    idxs = tree.query(corridor)
    out = []
    for i in idxs:
        node = points[int(i)]
        if corridor.contains(Point(node["x"], node["y"])):
            out.append(node["id"])
    return out


def corridor_path(
    G: nx.Graph,
    tree: STRtree,
    points: list,
    a: int,
    b: int,
    edge_xy: list[tuple[float, float]],
) -> list[int]:
    if a == b:
        return [a]
    line = LineString(edge_xy) if len(edge_xy) >= 2 else LineString([edge_xy[0], edge_xy[0]])
    for buf in (80, 130, 200, 320):
        corridor = line.buffer(buf)
        nodes = corridor_nodes(tree, points, corridor)
        if a not in nodes:
            nodes.append(a)
        if b not in nodes:
            nodes.append(b)
        H = G.subgraph(nodes).copy()
        if not nx.has_path(H, a, b):
            continue
        for u, v, edata in H.edges(data=True):
            mx = (G.nodes[u]["x"] + G.nodes[v]["x"]) / 2
            my = (G.nodes[u]["y"] + G.nodes[v]["y"]) / 2
            dist = Point(mx, my).distance(line)
            edata["cweight"] = edata["weight"] * (1.0 + dist / 90.0)
        return nx.shortest_path(H, a, b, weight="cweight")
    if nx.has_path(G, a, b):
        path = nx.shortest_path(G, a, b, weight="weight")
        length = sum(G[u][v]["length"] for u, v in zip(path, path[1:]))
        direct = math.hypot(G.nodes[a]["x"] - G.nodes[b]["x"], G.nodes[a]["y"] - G.nodes[b]["y"])
        if length < direct * 2.8 or direct < 40:
            return path
    return [a, b]


def ring_follow(G: nx.Graph, tree: STRtree, points: list, ring: list[list[float]]) -> list[list[float]]:
    coords = ring[:-1] if ring[0] == ring[-1] else ring
    snapped = [snap_vertex(G, tree, points, lon, lat) for lon, lat in coords]
    # drop consecutive duplicates
    compact = [snapped[0]]
    compact_src = [coords[0]]
    for nid, src in zip(snapped[1:], coords[1:]):
        if nid != compact[-1]:
            compact.append(nid)
            compact_src.append(src)
    if compact[0] == compact[-1] and len(compact) > 1:
        compact.pop()
        compact_src.pop()

    path_nodes = []
    n = len(compact)
    for i in range(n):
        a = compact[i]
        b = compact[(i + 1) % n]
        src_a = compact_src[i]
        src_b = compact_src[(i + 1) % n]
        edge_xy = [to_xy(*src_a), to_xy(*src_b)]
        seg = corridor_path(G, tree, points, a, b, edge_xy)
        if path_nodes and seg and path_nodes[-1] == seg[0]:
            path_nodes.extend(seg[1:])
        else:
            path_nodes.extend(seg)

    if not path_nodes:
        return ring
    if path_nodes[0] != path_nodes[-1]:
        path_nodes.append(path_nodes[0])

    out = []
    for nid in path_nodes:
        lon, lat = G.nodes[nid]["lon"], G.nodes[nid]["lat"]
        if not out or abs(out[-1][0] - lon) > 1e-7 or abs(out[-1][1] - lat) > 1e-7:
            out.append([round(lon, 6), round(lat, 6)])
    if out[0] != out[-1]:
        out.append(out[0])
    # light simplify while keeping road vertices (0.8 m)
    poly = Polygon([(to_xy(lon, lat)) for lon, lat in out])
    if poly.is_valid and poly.area > 0:
        simp = poly.simplify(1.5, preserve_topology=True)
        if simp.geom_type == "Polygon" and not simp.is_empty:
            xs, ys = simp.exterior.coords.xy
            out = [[round(from_xy(x, y)[0], 6), round(from_xy(x, y)[1], 6)] for x, y in zip(xs, ys)]
            if out[0] != out[-1]:
                out.append(out[0])
    # force CCW
    p = Polygon(out)
    if p.exterior.is_ccw is False:
        out = list(reversed(out))
    return out


def pip(lon, lat, ring):
    inside = False
    for i, j in zip(range(len(ring)), [len(ring) - 1] + list(range(len(ring) - 1))):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-16) + xi:
            inside = not inside
    return inside


def as_poly(ring):
    p = Polygon([to_xy(lon, lat) for lon, lat in ring])
    if not p.is_valid:
        p = p.buffer(0)
    return p


def geom_to_lonlat(geom):
    def ring_xy(coords):
        out = []
        for x, y in coords:
            lon, lat = from_xy(x, y)
            out.append([round(lon, 6), round(lat, 6)])
        if out and out[0] != out[-1]:
            out.append(out[0])
        return out

    geom = geom.buffer(0)
    if geom.is_empty:
        return None
    if geom.geom_type == "GeometryCollection":
        polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon") and not g.is_empty]
        if not polys:
            return None
        geom = unary_union(polys)
    if geom.geom_type == "Polygon":
        if geom.area < 100:
            return None
        holes = [h for h in geom.interiors if Polygon(h).area >= 2500]
        if geom.exterior.is_ccw is False:
            geom = Polygon(list(geom.exterior.coords)[::-1], holes)
        else:
            geom = Polygon(geom.exterior, holes)
        coords = [ring_xy(geom.exterior.coords)]
        for hole in geom.interiors:
            coords.append(ring_xy(hole.coords))
        return {"type": "Polygon", "coordinates": coords}
    if geom.geom_type == "MultiPolygon":
        parts = []
        for p in geom.geoms:
            if p.area < 100:
                continue
            if p.exterior.is_ccw is False:
                p = Polygon(list(p.exterior.coords)[::-1], p.interiors)
            coords = [ring_xy(p.exterior.coords)]
            for hole in p.interiors:
                coords.append(ring_xy(hole.coords))
            parts.append(coords)
        if not parts:
            return None
        if len(parts) == 1:
            return {"type": "Polygon", "coordinates": parts[0]}
        return {"type": "MultiPolygon", "coordinates": parts}
    return None


def resolve_overlaps(snapped, original):
    """Give overlapping land to the district whose hand-drawn shape already claimed it."""
    ids = sorted(snapped)
    for i in ids:
        for j in ids:
            if j <= i:
                continue
            a, b = snapped[i].buffer(0), snapped[j].buffer(0)
            if a.is_empty or b.is_empty:
                continue
            try:
                inter = a.intersection(b)
            except Exception:
                inter = a.buffer(0.02).intersection(b.buffer(0.02)).buffer(-0.02)
            if inter.is_empty or inter.area < 80:
                continue
            oa, ob = original[i].buffer(0), original[j].buffer(0)
            give_a = inter.intersection(oa)
            give_b = inter.intersection(ob).difference(give_a)
            leftover = inter.difference(unary_union([give_a, give_b]))
            if not leftover.is_empty:
                ca, cb = oa.centroid, ob.centroid
                if leftover.centroid.distance(ca) <= leftover.centroid.distance(cb):
                    give_a = give_a.union(leftover)
                else:
                    give_b = give_b.union(leftover)
            snapped[i] = a.difference(inter).union(give_a).buffer(0)
            snapped[j] = b.difference(inter).union(give_b).buffer(0)
    return snapped


def fill_gaps(snapped, original):
    envelope = unary_union(list(original.values())).buffer(55)
    covered = unary_union(list(snapped.values()))
    gaps = envelope.difference(covered)
    if gaps.is_empty:
        return snapped
    pieces = list(gaps.geoms) if gaps.geom_type == "MultiPolygon" else [gaps]
    for gap in pieces:
        if gap.area < 40 or gap.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        best = None
        best_len = -1.0
        for i, g in snapped.items():
            shared = gap.boundary.intersection(g.boundary)
            length = shared.length if not shared.is_empty else 0.0
            if length > best_len:
                best_len = length
                best = i
        if best is None or best_len < 8:
            best = min(snapped, key=lambda i: gap.centroid.distance(snapped[i]))
        snapped[best] = snapped[best].union(gap).buffer(0)
    return snapped


def drop_tiny_holes(geom):
    if geom.geom_type == "Polygon":
        holes = [h for h in geom.interiors if Polygon(h).area >= 2500]
        return Polygon(geom.exterior, holes)
    if geom.geom_type == "MultiPolygon":
        return unary_union([drop_tiny_holes(p) for p in geom.geoms])
    return geom


def close_seams(snapped, meters=8.0):
    """Grow each district a few meters into unclaimed slivers, never into another district."""
    claimed = unary_union(list(snapped.values()))
    for i in sorted(snapped):
        extra = snapped[i].buffer(meters).difference(claimed)
        if extra.is_empty:
            continue
        snapped[i] = snapped[i].union(extra).buffer(0)
        claimed = claimed.union(extra)
    return snapped


def main():
    print("loading OSM…", flush=True)
    G, _meta = load_osm()
    print(f"  graph {G.number_of_nodes()} nodes, {G.number_of_edges()} edges", flush=True)
    points = []
    geoms = []
    for nid, d in G.nodes(data=True):
        geoms.append(Point(d["x"], d["y"]))
        points.append({"id": nid, **d})
    tree = STRtree(geoms)

    src = json.loads(SRC_PATH.read_text())
    original = {}
    snapped = {}
    landmarks = {
        "Aviator / 8054 E 28th": (-104.8917, 39.7564),
        "The Cube": (-104.8905, 39.7858),
        "Jet Stream area": (-104.8880, 39.7635),
        "F-15 / Eastbridge": (-104.8665, 39.7565),
        "Greenway Park / Puddle Jumper": (-104.8895, 39.7510),
        "Splash Landing / North End": (-104.8720, 39.8050),
        "Beeler Park plaza": (-104.8810, 39.8030),
        "Central Park Station": (-104.8930, 39.7700),
    }

    for feat in src["features"]:
        ring = feat["geometry"]["coordinates"][0]
        did = feat["properties"]["id"]
        print(f"snapping D{did} {feat['properties']['name']} ({len(ring)} verts)…", flush=True)
        if did in (10, 11):
            # Beeler Park / North End: rebuilt after the generic snap.
            original[did] = as_poly(ring)
            snapped[did] = as_poly(ring)
            print("  -> skip generic snap (park-curve rebuild)", flush=True)
            continue
        new_ring = ring_follow(G, tree, points, ring)
        original[did] = as_poly(ring)
        snapped[did] = as_poly(new_ring)
        print(f"  -> {len(new_ring)} verts, {snapped[did].area/1e4:.1f} ha", flush=True)

    print("resolving overlaps…", flush=True)
    snapped = resolve_overlaps(snapped, original)
    snapped = close_seams(snapped, 8.0)

    for feat in src["features"]:
        did = feat["properties"]["id"]
        geom = drop_tiny_holes(snapped[did].buffer(0)).simplify(1.8, preserve_topology=True)
        gj = geom_to_lonlat(geom)
        if gj is None:
            raise RuntimeError(f"D{did} vanished after clip")
        feat["geometry"] = gj
        feat["properties"]["source"] = "osm-snapped-from-earth-trace"

    print("\nLandmarks:")
    for name, (lon, lat) in landmarks.items():
        hits = []
        for feat in src["features"]:
            g = feat["geometry"]
            rings = []
            if g["type"] == "Polygon":
                rings = [g["coordinates"][0]]
            else:
                rings = [p[0] for p in g["coordinates"]]
            if any(pip(lon, lat, ring) for ring in rings):
                hits.append(feat["properties"]["id"])
        print(f"  {name:32} -> {hits or 'NONE'}")

    print("\nOverlaps:")
    ids = sorted(snapped)
    for i in ids:
        for j in ids:
            if j <= i:
                continue
            inter = snapped[i].intersection(snapped[j])
            if not inter.is_empty and inter.area > 800:
                print(f"  D{i} ∩ D{j}: {inter.area/1e4:.2f} ha")

    OUT_PATH.write_text(json.dumps(src))
    print(f"\nwrote {OUT_PATH}")
    from rebuild_d10_d11 import rebuild
    print("rebuilding D10 / D11 on streets + Beeler Park curve…", flush=True)
    rebuild()


if __name__ == "__main__":
    main()
