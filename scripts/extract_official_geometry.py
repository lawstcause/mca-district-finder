#!/usr/bin/env python3
"""Trace the official geometric district map into lat/lng polygons.

Source: public/maps/mca-delegates-geometry.png (same schematic as the
neighborhood basemap). Solid fills are districts; hatching is park / outside.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from rebuild_d10_d11 import OSM_PATH, OUT_PATH, from_xy, to_xy

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "public" / "maps" / "mca-delegates-geometry.png"

# Printed fill colors used on the Leaflet map.
COLORS = {
    1: "#5c7a32",
    2: "#54c43c",
    3: "#c44ad4",
    4: "#f0a020",
    5: "#50d0f0",
    6: "#f0e020",
    7: "#e03028",
    8: "#2040f0",
    9: "#d09018",
    10: "#28d8e0",
    11: "#f890f0",
}


def flood_mask(arr, seed, tol=28):
    h, w = arr.shape[:2]
    x, y = seed
    rgb = np.linalg.norm(arr.astype(np.int16) - arr[y, x].astype(np.int16), axis=2)
    close = rgb < tol
    ff = close.astype(np.uint8)
    mask = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(ff, mask, (int(x), int(y)), 2, flags=4)
    out = (ff == 2).astype(np.uint8)
    k = np.ones((7, 7), np.uint8)
    out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, k)
    out = cv2.morphologyEx(out, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return out


def largest_contour(mask):
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    # light approx to keep the clean printed edges, not JPEG jaggies
    eps = 0.0018 * cv2.arcLength(c, True)
    approx = cv2.approxPolyDP(c, eps, True)
    pts = approx.reshape(-1, 2).astype(float)
    return pts


def affine_from(src_pts, dst_pts):
    src = np.array(src_pts, dtype=np.float64)
    dst = np.array(dst_pts, dtype=np.float64)
    A = []
    b = []
    for (x, y), (X, Y) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0])
        A.append([0, 0, 0, x, y, 1])
        b.extend([X, Y])
    A = np.array(A)
    b = np.array(b)
    coef, *_ = np.linalg.lstsq(A, b, rcond=None)
    M = coef.reshape(2, 3)
    return M


def apply(M, pts):
    ones = np.ones((len(pts), 1))
    xy = np.hstack([pts, ones])
    return (M @ xy.T).T


def ring_of(pts_lonlat):
    coords = [[round(float(lon), 6), round(float(lat), 6)] for lon, lat in pts_lonlat]
    # drop dupes
    out = []
    for p in coords:
        if not out or out[-1] != p:
            out.append(p)
    if out[0] != out[-1]:
        out.append(out[0])
    poly = Polygon(out).buffer(0)
    if poly.is_empty:
        return out
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    poly = poly.simplify(0.00002, preserve_topology=True)
    coords = [[round(x, 6), round(y, 6)] for x, y in poly.exterior.coords]
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    if not Polygon(coords).exterior.is_ccw:
        coords = list(reversed(coords))
    return coords


def main():
    arr = np.array(Image.open(IMG).convert("RGB")) if False else None
    from PIL import Image as _Image

    arr = np.array(_Image.open(IMG).convert("RGB"))
    h, w = arr.shape[:2]
    print("image", w, h)

    # Seeds on the 1248x1929 geometric map (x, y) — sampled from solid fills.
    seeds = {
        11: (700, 250),
        10: (515, 250),
        9: (400, 560),
        8: (400, 800),
        7: (200, 1120),
        6: (400, 1280),
        1: (700, 1280),
        5: (700, 1480),
        3: (400, 1480),
        2: (100, 1560),
        4: (400, 1680),
    }

    # If a seed lands on white, search nearby for color.
    masks = {}
    contours = {}
    vis = arr.copy()
    for did, (x, y) in seeds.items():
        if tuple(arr[y, x]) == (255, 255, 255) or arr[y, x].min() > 240:
            found = None
            for rad in range(4, 40, 4):
                for dy in range(-rad, rad + 1, 4):
                    for dx in range(-rad, rad + 1, 4):
                        xx, yy = x + dx, y + dy
                        if 0 <= yy < h and 0 <= xx < w and arr[yy, xx].min() < 230:
                            sat = int(arr[yy, xx].max()) - int(arr[yy, xx].min())
                            if sat > 25:
                                found = (xx, yy)
                                break
                    if found:
                        break
                if found:
                    break
            if not found:
                print("NO SEED", did, "at", x, y, "pixel", arr[y, x])
                continue
            x, y = found
        print(f"D{did} seed {(x,y)} rgb {tuple(int(v) for v in arr[y,x])}")
        mask = flood_mask(arr, (x, y))
        area = int(mask.sum())
        print(f"  fill {area} px")
        pts = largest_contour(mask)
        if pts is None or area < 200:
            print("  skip")
            continue
        masks[did] = mask
        contours[did] = pts
        cv2.drawContours(vis, [pts.astype(np.int32)], -1, (0, 0, 0), 2)

    Path("/tmp/mca-districts").mkdir(exist_ok=True)
    _Image.fromarray(vis).save("/tmp/mca-districts/geom_traced.jpg", quality=90)

    def bbox(did):
        ys, xs = np.where(masks[did] > 0)
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())

    # --- GCPs: pixel -> (lon, lat). Three panels. ---
    # North inset: D10+D11
    nL, nT, nR, nB = None, None, None, None
    xs = []
    ys = []
    for did in (10, 11):
        x0, y0, x1, y1 = bbox(did)
        xs += [x0, x1]
        ys += [y0, y1]
    nL, nR = min(xs), max(xs)
    nT, nB = min(ys), max(ys)
    print("north box", nL, nT, nR, nB)

    # Middle: D8+D9
    xs, ys = [], []
    for did in (8, 9):
        x0, y0, x1, y1 = bbox(did)
        xs += [x0, x1]
        ys += [y0, y1]
    mL, mR = min(xs), max(xs)
    mT, mB = min(ys), max(ys)
    print("middle box", mL, mT, mR, mB)

    # South: D1–D7
    xs, ys = [], []
    for did in (1, 2, 3, 4, 5, 6, 7):
        if did not in masks:
            continue
        x0, y0, x1, y1 = bbox(did)
        xs += [x0, x1]
        ys += [y0, y1]
    sL, sR = min(xs), max(xs)
    sT, sB = min(ys), max(ys)
    print("south box", sL, sT, sR, sB)

    # Geographic corners (OSM).
    # North inset: CP Blvd / Havana / 56th / 64th
    M_north = affine_from(
        [(nL, nB), (nR, nB), (nR, nT), (nL, nT)],
        [
            (-104.88449, 39.79847),  # SW CP Blvd & 56th
            (-104.86599, 39.79842),  # SE Havana & 56th
            (-104.86609, 39.81299),  # NE Havana & 64th
            (-104.88442, 39.81297),  # NW park/64th
        ],
    )
    M_mid = affine_from(
        [(mL, mB), (mR, mB), (mR, mT), (mL, mT)],
        [
            (-104.9008, 39.7774),  # SW greenbelt / I-70
            (-104.8755, 39.7768),  # SE Dallas / I-70
            (-104.87547, 39.79831),  # NE Dallas & 56th
            (-104.89743, 39.79840),  # NW Spruce & 56th
        ],
    )

    # South: extra GCPs so the east finger and Quebec line land.
    # Use D7 top-right ≈ Havana & I-70, D7 top-left ≈ west I-70,
    # D4 bottom, D1 east tip, D2 west, MLK from D3/D6.
    d7 = bbox(7)
    d4 = bbox(4)
    d1 = bbox(1) if 1 in masks else bbox(5)
    d2 = bbox(2)
    d5 = bbox(5)
    d6 = bbox(6)
    src_s = [
        (d7[0], d7[1]),  # red NW
        (d7[2], d7[1]),  # red NE
        (d4[0], d4[3]),  # orange SW
        (d4[2], d4[3]),  # orange SE
        (d1[2], (d1[1] + d1[3]) / 2),  # D1 east mid (finger / Peoria)
        (d2[0], (d2[1] + d2[3]) / 2),  # D2 west (Quebec)
        (d6[0], d6[1]),  # yellow NW (35th / station)
        (d5[2], d5[3]),  # D5 SE along 26th
    ]
    dst_s = [
        (-104.9034, 39.7783),
        (-104.8659, 39.7757),
        (-104.89876, 39.74743),
        (-104.8764, 39.74738),
        (-104.84689, 39.75476),
        (-104.9034, 39.7570),
        (-104.9034, 39.7651),
        (-104.85405, 39.75311),
    ]
    M_south = affine_from(src_s, dst_s)

    panel_of = {
        10: M_north,
        11: M_north,
        8: M_mid,
        9: M_mid,
        1: M_south,
        2: M_south,
        3: M_south,
        4: M_south,
        5: M_south,
        6: M_south,
        7: M_south,
    }

    rings = {}
    for did, pts in contours.items():
        lonlat = apply(panel_of[did], pts)
        rings[did] = ring_of(lonlat)
        print(f"D{did} verts {len(rings[did])}")

    # Snap near-street vertices to OSM named ways (keep park curves).
    osm = json.loads(OSM_PATH.read_text())
    nodes = []
    for el in osm.get("elements", []):
        tags = el.get("tags") or {}
        if not tags.get("highway") and tags.get("leisure") not in {"park"}:
            continue
        for p in el.get("geometry") or []:
            nodes.append((p["lon"], p["lat"]))
    nodes = np.array(nodes)

    def snap_ring(ring, max_m=28):
        out = []
        for lon, lat in ring:
            x, y = to_xy(lon, lat)
            # brute near: convert a small bbox
            dlon = max_m / 85000.0
            dlat = max_m / 111320.0
            mask = (
                (nodes[:, 0] > lon - dlon)
                & (nodes[:, 0] < lon + dlon)
                & (nodes[:, 1] > lat - dlat)
                & (nodes[:, 1] < lat + dlat)
            )
            if not mask.any():
                out.append([lon, lat])
                continue
            cand = nodes[mask]
            d2 = (cand[:, 0] - lon) ** 2 + (cand[:, 1] - lat) ** 2
            j = int(d2.argmin())
            # meters
            cx, cy = to_xy(cand[j, 0], cand[j, 1])
            if math.hypot(cx - x, cy - y) <= max_m:
                out.append([round(float(cand[j, 0]), 6), round(float(cand[j, 1]), 6)])
            else:
                out.append([lon, lat])
        # reopen
        if out[0] != out[-1]:
            out.append(out[0])
        return ring_of(out)

    # Snap rectilinear south districts a bit harder; keep north curves softer.
    hard = {2, 3, 4, 5, 6, 7}
    for did in list(rings):
        rings[did] = snap_ring(rings[did], max_m=32 if did in hard else 18)

    fc = json.loads(OUT_PATH.read_text())
    for feat in fc["features"]:
        i = feat["properties"]["id"]
        if i in rings and len(rings[i]) >= 4:
            feat["geometry"] = {"type": "Polygon", "coordinates": [rings[i]]}
            feat["properties"]["color"] = COLORS[i]
            feat["properties"]["source"] = "official-geometry-map"
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
        ("Aviator", -104.89483, 39.75642, 2),
        ("Founders Green", -104.90053, 39.7577, 2),
        ("Puddle Jumper", -104.88568, 39.75162, 4),
        ("Westerly Creek", -104.88, 39.757, 3),
        ("Eastbridge", -104.873, 39.757, 5),
        ("CP West", -104.895, 39.763, 6),
        ("RTD", -104.8918, 39.7699, 7),
        ("Willow west", -104.896, 39.7945, 9),
        ("F-15", -104.86692, 39.7568, 5),
        ("Aurora 26th", -104.85596, 39.75469, 1),
        ("Jet Stream", -104.88166, 39.7666, 6),
        ("The Cube", -104.89087, 39.78577, 8),
        ("Maverick", -104.88598, 39.78912, 8),
        ("Beeler Plaza", -104.876, 39.8004, 11),
        ("Splash Landing", -104.8688, 39.8052, 11),
        ("Fred Thomas out", -104.9015, 39.7528, None),
    ]
    failed = 0
    for name, lon, lat, exp in checks:
        hits = [i for i, r in rings.items() if pip(lon, lat, r)]
        ok = (hits == [exp]) if exp else (hits == [])
        if not ok:
            failed += 1
        print(("OK  " if ok else "FAIL"), name, "->", hits, "expected", exp)
    print("failed", failed, "wrote", OUT_PATH)
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
