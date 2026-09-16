import { useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer,
  TileLayer,
  GeoJSON,
  Marker,
  Popup,
  useMap,
  useMapEvents,
} from "react-leaflet";
import L from "leaflet";
import { MAP_CENTER, MAP_ZOOM, MCA } from "./data.js";
import { centroidOf, findDistrict, geocodeAddress } from "./geo.js";

function FitDistricts({ geo }) {
  const map = useMap();
  const done = useRef(false);
  useEffect(() => {
    if (done.current || !geo?.features?.length) return;
    const layer = L.geoJSON(geo);
    const bounds = layer.getBounds();
    if (!bounds.isValid()) return;
    done.current = true;
    map.fitBounds(bounds, { padding: [28, 28], maxZoom: 15 });
  }, [geo, map]);
  return null;
}

function FlyTo({ target }) {
  const map = useMap();
  useEffect(() => {
    if (!target) return;
    const lat = Number(target.lat);
    const lng = Number(target.lng);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
    map.setView([lat, lng], target.zoom ?? 16, { animate: true });
  }, [map, target]);
  return null;
}

function MapClick({ onPick }) {
  useMapEvents({
    click(e) {
      const t = e.originalEvent?.target;
      if (t?.closest?.(".district-label, .leaflet-marker-icon, .leaflet-popup")) {
        return;
      }
      onPick({ lat: e.latlng.lat, lng: e.latlng.lng, label: "Dropped pin" });
    },
  });
  return null;
}

function pinIcon() {
  return L.divIcon({
    className: "search-pin",
    html: `<span class="search-pin-dot"></span>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

function inkOn(color) {
  const hex = (color || "#000000").replace("#", "");
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  return 0.299 * r + 0.587 * g + 0.114 * b > 165 ? "#142017" : "#fff";
}

function districtLabelIcon(d) {
  const fg = inkOn(d.color);
  return L.divIcon({
    className: "",
    html: `<div class="district-label" style="background:${d.color};color:${fg}">${d.id}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

export default function App() {
  const [districtsFc, setDistrictsFc] = useState(null);
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const [pin, setPin] = useState(null);
  const [fly, setFly] = useState(null);
  const [activeId, setActiveId] = useState(null);
  const [basemap, setBasemap] = useState("streets");
  const debounceRef = useRef(null);

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data/districts.geojson`)
      .then((r) => r.json())
      .then(setDistrictsFc)
      .catch(() => setError("Could not load district shapes."));
  }, []);

  const districts = useMemo(
    () =>
      (districtsFc?.features || [])
        .map((f) => ({ ...f.properties, geometry: f.geometry }))
        .sort((a, b) => a.id - b.id),
    [districtsFc]
  );

  const match = pin && districts.length ? findDistrict(pin.lng, pin.lat, districts) : null;
  const active = activeId ? districts.find((d) => d.id === activeId) : match;

  function applyPin(next) {
    setPin(next);
    setFly({ lat: next.lat, lng: next.lng, zoom: 16 });
    const d = districts.length ? findDistrict(next.lng, next.lat, districts) : null;
    setActiveId(d ? d.id : null);
    setSuggestions([]);
    setError("");
  }

  async function runSearch(text) {
    const q = text.trim();
    if (q.length < 3) {
      setSuggestions([]);
      return;
    }
    setSearching(true);
    setError("");
    try {
      const results = await geocodeAddress(
        /denver|aurora|80238|80010|co\b/i.test(q) ? q : `${q}, Denver CO`
      );
      const local = results.filter(
        (r) => r.lat > 39.74 && r.lat < 39.82 && r.lng > -104.91 && r.lng < -104.84
      );
      setSuggestions(local.length ? local : results.slice(0, 5));
    } catch {
      setError("Could not look up that address.");
    } finally {
      setSearching(false);
    }
  }

  function onQueryChange(value) {
    setQuery(value);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => runSearch(value), 280);
  }

  function submitSearch(e) {
    e.preventDefault();
    if (suggestions[0]) applyPin({ ...suggestions[0] });
    else runSearch(query);
  }

  function selectDistrict(d) {
    setActiveId(d.id);
    const [lat, lng] = centroidOf(d.geometry);
    setFly({ lat, lng, zoom: 15 });
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <img
            className="brand-logo"
            src={`${import.meta.env.BASE_URL}mca-logo.png?v=2`}
            alt="MCA Central Park"
          />
          <p className="tagline">Find your delegate district</p>
        </div>
      </header>

      <div className="workspace">
        <aside className="sidebar sidebar-search">
          <form className="search" onSubmit={submitSearch}>
            <label htmlFor="addr">Your address</label>
            <div className="search-row">
              <input
                id="addr"
                value={query}
                onChange={(e) => onQueryChange(e.target.value)}
                placeholder="e.g. 8054 E 28th Ave"
                autoComplete="street-address"
              />
              <button type="submit" className="primary">
                {searching ? "…" : "Find"}
              </button>
            </div>
            <div className="search-actions">
              <button
                type="button"
                className="ghost"
                onClick={() => {
                  if (!navigator.geolocation) {
                    setError("Location is not available.");
                    return;
                  }
                  navigator.geolocation.getCurrentPosition(
                    (pos) =>
                      applyPin({
                        lat: pos.coords.latitude,
                        lng: pos.coords.longitude,
                        label: "Your location",
                      }),
                    () => setError("Could not read your location.")
                  );
                }}
              >
                Use my location
              </button>
              <span className="hint">or tap the map</span>
            </div>
            {suggestions.length > 0 && (
              <ul className="suggest">
                {suggestions.map((s) => (
                  <li key={`${s.lat}-${s.lng}`}>
                    <button
                      type="button"
                      onClick={() => {
                        setQuery(s.label);
                        applyPin(s);
                      }}
                    >
                      {s.label}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {error && <p className="error">{error}</p>}
          </form>

          {pin && (
            <section className={`result ${match ? "in" : "out"}`}>
              {match ? (
                <>
                  <p className="eyebrow">You are in</p>
                  <h2>
                    <span
                      className="num"
                      style={{ background: match.color, color: inkOn(match.color) }}
                    >
                      {match.id}
                    </span>
                    {match.name}
                  </h2>
                  <p className="blurb">{match.blurb}</p>
                  <dl>
                    <div>
                      <dt>Delegate</dt>
                      <dd>
                        {match.open ? <strong>Open seat</strong> : match.delegate}
                      </dd>
                    </div>
                    <div>
                      <dt>Neighborhoods</dt>
                      <dd>{match.neighborhoods.join(" · ")}</dd>
                    </div>
                  </dl>
                  <p className="contact">
                    Questions? <a href={`mailto:${MCA.email}`}>{MCA.email}</a>
                    {" · "}
                    <a href={MCA.delegatesUrl} target="_blank" rel="noreferrer">
                      Current delegates
                    </a>
                  </p>
                </>
              ) : (
                <>
                  <p className="eyebrow">Outside MCA districts</p>
                  <h2>Not in a drawn district</h2>
                  <p className="blurb">
                    This pin is outside the 11 district shapes from the official MCA map. Parks and hatched open space are not assigned.
                  </p>
                </>
              )}
              <p className="pin-label">{pin.label}</p>
            </section>
          )}
        </aside>

        <div className="map-wrap">
          <div className="layer-toggles">
            <label>
              <input
                type="radio"
                name="basemap"
                checked={basemap === "streets"}
                onChange={() => setBasemap("streets")}
              />
              Streets
            </label>
            <label>
              <input
                type="radio"
                name="basemap"
                checked={basemap === "satellite"}
                onChange={() => setBasemap("satellite")}
              />
              Satellite
            </label>
          </div>
          <MapContainer center={MAP_CENTER} zoom={MAP_ZOOM} minZoom={12} maxZoom={19} className="map">
            {basemap === "streets" ? (
              <TileLayer
                attribution="Tiles &copy; Esri"
                url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
                updateWhenZooming={false}
                keepBuffer={2}
              />
            ) : (
              <TileLayer
                attribution="Tiles &copy; Esri"
                url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                updateWhenZooming={false}
                keepBuffer={2}
              />
            )}
            {districtsFc && (
              <GeoJSON
                key={`${active?.id || "all"}-${basemap}`}
                data={districtsFc}
                style={(feat) => {
                  const id = feat.properties.id;
                  const on = active?.id === id;
                  const dim = active && !on;
                  return {
                    color: feat.properties.color,
                    weight: on ? 3 : 2,
                    fillColor: feat.properties.color,
                    fillOpacity: dim ? 0.28 : on ? 0.72 : 0.62,
                  };
                }}
                onEachFeature={(feat, layer) => {
                  const d = districts.find((x) => x.id === feat.properties.id);
                  layer.bindTooltip(`District ${d.id} · ${d.name}`, { sticky: true });
                  layer.on("click", (e) => {
                    L.DomEvent.stopPropagation(e);
                    selectDistrict(d);
                  });
                }}
              />
            )}
            {districts.map((d) => {
              const [lat, lng] =
                d.labelLat != null && d.labelLng != null
                  ? [d.labelLat, d.labelLng]
                  : centroidOf(d.geometry);
              return (
                <Marker
                  key={d.id}
                  position={[lat, lng]}
                  icon={districtLabelIcon(d)}
                  bubblingMouseEvents={false}
                  eventHandlers={{ click: () => selectDistrict(d) }}
                >
                  <Popup>
                    <strong>
                      District {d.id}: {d.name}
                    </strong>
                    <br />
                    {d.open ? "Open seat" : d.delegate}
                  </Popup>
                </Marker>
              );
            })}
            {pin && (
              <Marker position={[pin.lat, pin.lng]} icon={pinIcon()}>
                <Popup>{pin.label}</Popup>
              </Marker>
            )}
            <MapClick onPick={applyPin} />
            <FlyTo target={fly} />
            {districtsFc && <FitDistricts geo={districtsFc} />}
          </MapContainer>
          <p className="map-credit">
            District borders are the official KMZ polygons, loaded as drawn.
            {" "}
            <a href={MCA.mapsUrl} target="_blank" rel="noreferrer">
              Open in Google Earth
            </a>
          </p>
        </div>

        <aside className="sidebar sidebar-list">
          <section className="source-map">
            <h3>Official district map</h3>
            <img
              src={`${import.meta.env.BASE_URL}maps/mca-district-key.jpg?v=4`}
              alt="MCA Central Park neighborhood map with 11 delegate districts"
            />
          </section>
          <section className="district-list">
            <h3>11 delegate districts</h3>
            <ul>
              {districts.map((d) => (
                <li key={d.id}>
                  <button
                    type="button"
                    className={active?.id === d.id ? "active" : ""}
                    onClick={() => selectDistrict(d)}
                  >
                    <span
                      className="swatch"
                      style={{ background: d.color, color: inkOn(d.color) }}
                    >
                      {d.id}
                    </span>
                    <span>
                      <strong>{d.name}</strong>
                      <em>{d.open ? "Open seat" : d.delegate}</em>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>

      <footer className="foot">
        <span>{MCA.short}</span>
        <a href={MCA.web} target="_blank" rel="noreferrer">
          mca80238.com
        </a>
        <a href="tel:3033880724">{MCA.phone}</a>
      </footer>
    </div>
  );
}
