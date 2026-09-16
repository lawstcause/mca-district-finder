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

const MCA_BBOX = {
  minLng: -104.915,
  minLat: 39.735,
  maxLng: -104.835,
  maxLat: 39.82,
};

const DENVER_ADDR =
  "https://services1.arcgis.com/zdB7qR0BtYrg0Xpl/arcgis/rest/services/ODC_CITY_LOC_ADDRESSPUBLIC_P/FeatureServer/31/query";
const DENVER_PARCEL =
  "https://services1.arcgis.com/zdB7qR0BtYrg0Xpl/arcgis/rest/services/ODC_PROP_PARCELS_A/FeatureServer/245/query";

const STREET_TYPES =
  "street|st|avenue|ave|boulevard|blvd|drive|dr|court|ct|way|lane|ln|place|pl|circle|cir|parkway|pkwy|terrace|ter|trail|trl|road|rd|highway|hwy|row|pass|loop";
const DIRS = "north|south|east|west|northeast|northwest|southeast|southwest|n|s|e|w|ne|nw|se|sw";

function inMcaBbox(lat, lng) {
  return lat > MCA_BBOX.minLat && lat < MCA_BBOX.maxLat && lng > MCA_BBOX.minLng && lng < MCA_BBOX.maxLng;
}

function ordinalStreet(token) {
  if (!/^\d+$/.test(token)) return token;
  const n = Number(token);
  const mod100 = n % 100;
  const mod10 = n % 10;
  const suf =
    mod100 >= 11 && mod100 <= 13 ? "th" : mod10 === 1 ? "st" : mod10 === 2 ? "nd" : mod10 === 3 ? "rd" : "th";
  return `${token}${suf}`;
}

function sqlString(value) {
  return String(value).replace(/'/g, "''");
}

export function parseAddress(raw) {
  let q = String(raw || "").trim();
  q = q.replace(/[.,#]/g, " ");
  q = q.replace(/\b(denver|aurora|colorado|usa|united states)\b/gi, " ");
  q = q.replace(/\bCO\b/gi, " ");
  q = q.replace(/\b80\d{3}(?:-\d{4})?\b/g, " ");
  q = q.replace(/\s+/g, " ").trim();

  let unit = "";
  const unitMatch = q.match(/\b(?:unit|apt|apartment|ste|suite)\s+([a-z0-9-]+)\b/i);
  if (unitMatch) {
    unit = unitMatch[1];
    q = q.replace(unitMatch[0], " ").replace(/\s+/g, " ").trim();
  }

  const re = new RegExp(
    `^(\\d+)\\s+(?:(${DIRS})\\s+)?(.+?)(?:\\s+(${STREET_TYPES}))?$`,
    "i"
  );
  const m = q.match(re);
  if (!m) return { raw: q, number: null, street: q, unit };
  const street = m[3]
    .trim()
    .split(/\s+/)
    .map((part) => ordinalStreet(part))
    .join(" ");
  return {
    raw: q,
    number: m[1],
    dir: m[2] || "",
    street,
    posttype: m[4] || "",
    unit,
  };
}

async function fetchJson(url, timeoutMs = 8000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      headers: { Accept: "application/json" },
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(t);
  }
}

function uniqueHits(hits) {
  const ranked = [...hits].sort((a, b) => {
    const extra = (s) => /\b(unit|apt|ste|bldg|building)\b/i.test(s.label);
    return Number(extra(a)) - Number(extra(b)) || a.label.length - b.label.length;
  });
  const seen = new Set();
  const out = [];
  for (const h of ranked) {
    const key = `${h.lat.toFixed(5)}|${h.lng.toFixed(5)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(h);
  }
  return out;
}

async function queryDenverAddresses(parsed) {
  if (!parsed.number || !parsed.street) return [];
  const street = sqlString(parsed.street.toUpperCase());
  if (street.length < 2) return [];
  const where = [
    `ADDRESS_NUMBER=${Number(parsed.number)}`,
    `UPPER(STREET_NAME) LIKE '${street}%'`,
  ];
  if (parsed.unit) where.push(`UPPER(UNIT_IDENTIFIER)='${sqlString(parsed.unit.toUpperCase())}'`);
  const params = new URLSearchParams({
    f: "json",
    where: where.join(" AND "),
    geometry: `${MCA_BBOX.minLng},${MCA_BBOX.minLat},${MCA_BBOX.maxLng},${MCA_BBOX.maxLat}`,
    geometryType: "esriGeometryEnvelope",
    inSR: "4326",
    spatialRel: "esriSpatialRelIntersects",
    outFields: "FULL_ADDRESS,ADDRESS_NUMBER,STREET_NAME,POSTTYPE,PREDIRECTIONAL,LATITUDE,LONGITUDE,UNIT_IDENTIFIER,ADDRESS_TYPE",
    returnGeometry: "false",
    resultRecordCount: "20",
    orderByFields: "UNIT_IDENTIFIER",
  });
  const data = await fetchJson(`${DENVER_ADDR}?${params}`);
  const features = Array.isArray(data.features) ? data.features : [];
  const hits = features
    .map((f) => {
      const a = f.attributes || {};
      const lat = Number(a.LATITUDE);
      const lng = Number(a.LONGITUDE);
      const unit = String(a.UNIT_IDENTIFIER || "").trim();
      return {
        lat,
        lng,
        label: a.FULL_ADDRESS || parsed.raw,
        city: "Denver",
        zip: "80238",
        state: "CO",
        source: "denver-address",
        unit,
        streetName: a.STREET_NAME || "",
      };
    })
    .filter((r) => Number.isFinite(r.lat) && Number.isFinite(r.lng) && inMcaBbox(r.lat, r.lng));
  const parents = hits.filter((h) => !h.unit);
  return uniqueHits(parents.length ? parents : hits);
}

function ringCentroid(geom) {
  const ring = geom?.rings?.[0];
  if (!ring?.length) return null;
  let x = 0;
  let y = 0;
  for (const [lng, lat] of ring) {
    x += lng;
    y += lat;
  }
  return { lng: x / ring.length, lat: y / ring.length };
}

async function queryDenverParcels(parsed) {
  if (!parsed.number || !parsed.street) return [];
  const street = sqlString(parsed.street.toUpperCase());
  if (street.length < 2) return [];
  const params = new URLSearchParams({
    f: "json",
    where: `SITUS_ADDR_NBR='${sqlString(parsed.number)}' AND UPPER(SITUS_STR_NAME) LIKE '${street}%'`,
    geometry: `${MCA_BBOX.minLng},${MCA_BBOX.minLat},${MCA_BBOX.maxLng},${MCA_BBOX.maxLat}`,
    geometryType: "esriGeometryEnvelope",
    inSR: "4326",
    spatialRel: "esriSpatialRelIntersects",
    outFields: "SITUS_ADDRESS_LINE1,SITUS_ZIP,SITUS_STR_NAME,SITUS_CITY",
    returnGeometry: "true",
    outSR: "4326",
    resultRecordCount: "8",
  });
  const data = await fetchJson(`${DENVER_PARCEL}?${params}`);
  const features = Array.isArray(data.features) ? data.features : [];
  return uniqueHits(
    features
      .map((f) => {
        const a = f.attributes || {};
        const c = ringCentroid(f.geometry);
        if (!c) return null;
        const zip = a.SITUS_ZIP ? String(a.SITUS_ZIP) : "80238";
        const line = a.SITUS_ADDRESS_LINE1 || parsed.raw;
        return {
          lat: c.lat,
          lng: c.lng,
          label: `${line.replace(/\s+/g, " ").trim()}, Denver CO ${zip}`,
          city: a.SITUS_CITY || "Denver",
          zip,
          state: "CO",
          source: "denver-parcel",
        };
      })
      .filter((r) => r && Number.isFinite(r.lat) && Number.isFinite(r.lng) && inMcaBbox(r.lat, r.lng))
  );
}

async function queryPhotonHouse(query, parsed) {
  const photonUrl = new URL("https://photon.komoot.io/api/");
  photonUrl.searchParams.set("q", query);
  photonUrl.searchParams.set("lat", "39.778");
  photonUrl.searchParams.set("lon", "-104.878");
  photonUrl.searchParams.set("limit", "6");
  photonUrl.searchParams.set("lang", "en");
  const data = await fetchJson(photonUrl.toString());
  const features = Array.isArray(data.features) ? data.features : [];
  const wantNum = parsed.number;
  return uniqueHits(
    features
      .map((f) => {
        const [lng, lat] = f.geometry.coordinates;
        const p = f.properties || {};
        if (wantNum && String(p.housenumber || "") !== String(wantNum)) return null;
        if (!inMcaBbox(lat, lng)) return null;
        const parts = [
          [p.housenumber, p.street].filter(Boolean).join(" "),
          p.city || p.locality,
          p.postcode,
        ].filter(Boolean);
        return {
          lat,
          lng,
          label: parts.join(", ") || query,
          city: p.city || p.locality || "",
          zip: p.postcode || "",
          state: p.state || "",
          source: "photon",
        };
      })
      .filter(Boolean)
  );
}

export async function geocodeAddress(query) {
  const q = query.trim();
  if (!q) return [];
  const parsed = parseAddress(q);
  if (!parsed.number || parsed.street.length < 2) return [];

  try {
    const addresses = await queryDenverAddresses(parsed);
    if (addresses.length) return addresses.slice(0, 8);
  } catch {
    /* parcel / photon fallback */
  }

  try {
    const parcels = await queryDenverParcels(parsed);
    if (parcels.length) return parcels.slice(0, 6);
  } catch {
    /* photon fallback for Aurora edge only, and only with a house number */
  }

  try {
    return (await queryPhotonHouse(q, parsed)).slice(0, 5);
  } catch {
    return [];
  }
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
