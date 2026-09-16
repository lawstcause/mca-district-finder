/** Point-in-polygon and geocoding helpers. */

function ringContains(lng, lat, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const intersect =
      yi > lat !== yj > lat && lng < ((xj - xi) * (lat - yi)) / (yj - yi + 0.0) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

function polygonContains(lng, lat, polygon) {
  if (!polygon.length) return false;
  if (!ringContains(lng, lat, polygon[0])) return false;
  for (let h = 1; h < polygon.length; h++) {
    if (ringContains(lng, lat, polygon[h])) return false;
  }
  return true;
}

export function geometryContains(lng, lat, geometry) {
  if (!geometry) return false;
  if (geometry.type === "Polygon") return polygonContains(lng, lat, geometry.coordinates);
  if (geometry.type === "MultiPolygon") {
    return geometry.coordinates.some((poly) => polygonContains(lng, lat, poly));
  }
  return false;
}

export function findDistrict(lng, lat, districts) {
  return districts.find((d) => geometryContains(lng, lat, d.geometry)) ?? null;
}

export function findZipFeature(lng, lat, zipGeo) {
  if (!zipGeo?.features) return null;
  return zipGeo.features.find((f) => geometryContains(lng, lat, f.geometry)) ?? null;
}

export function centroidOf(geometry) {
  const rings = [];
  if (geometry.type === "Polygon") rings.push(geometry.coordinates[0]);
  else if (geometry.type === "MultiPolygon") {
    for (const p of geometry.coordinates) rings.push(p[0]);
  }
  // Pick the largest ring and use its bounding-box center, then walk toward
  // the first vertex until the point is inside that ring.
  let best = rings[0] || [];
  let bestA = 0;
  for (const ring of rings) {
    let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
    for (const [x, y] of ring) {
      if (x < minx) minx = x;
      if (y < miny) miny = y;
      if (x > maxx) maxx = x;
      if (y > maxy) maxy = y;
    }
    const a = (maxx - minx) * (maxy - miny);
    if (a > bestA) {
      bestA = a;
      best = ring;
    }
  }
  if (!best.length) return [0, 0];
  let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
  for (const [x, y] of best) {
    if (x < minx) minx = x;
    if (y < miny) miny = y;
    if (x > maxx) maxx = x;
    if (y > maxy) maxy = y;
  }
  let lng = (minx + maxx) / 2;
  let lat = (miny + maxy) / 2;
  const geom = { type: "Polygon", coordinates: [best] };
  if (geometryContains(lng, lat, geom)) return [lat, lng];
  for (let t = 0.4; t <= 0.9; t += 0.1) {
    for (const [x, y] of best) {
      const cx = lng + (x - lng) * t * 0.35;
      const cy = lat + (y - lat) * t * 0.35;
      if (geometryContains(cx, cy, geom)) return [cy, cx];
    }
  }
  return [best[0][1], best[0][0]];
}

const DENVER_BIAS = { lat: 39.778, lon: -104.878 };

export async function geocodeAddress(query) {
  const q = query.trim();
  if (!q) return [];

  const photonUrl = new URL("https://photon.komoot.io/api/");
  photonUrl.searchParams.set("q", q);
  photonUrl.searchParams.set("lat", String(DENVER_BIAS.lat));
  photonUrl.searchParams.set("lon", String(DENVER_BIAS.lon));
  photonUrl.searchParams.set("limit", "6");
  photonUrl.searchParams.set("lang", "en");

  const res = await fetch(photonUrl.toString(), {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`Geocoder failed (${res.status})`);
  const data = await res.json();
  const features = Array.isArray(data.features) ? data.features : [];

  return features
    .map((f) => {
      const [lng, lat] = f.geometry.coordinates;
      const p = f.properties || {};
      const parts = [
        [p.housenumber, p.street].filter(Boolean).join(" "),
        p.name,
        p.city || p.locality,
        p.postcode,
        p.state,
      ].filter(Boolean);
      const label = parts.filter((v, i, a) => a.indexOf(v) === i).join(", ");
      return {
        lat,
        lng,
        label: label || q,
        city: p.city || p.locality || "",
        zip: p.postcode || "",
        state: p.state || "",
      };
    })
    .filter((r) => Number.isFinite(r.lat) && Number.isFinite(r.lng));
}

export function haversineMiles(lat1, lng1, lat2, lng2) {
  const R = 3958.8;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
