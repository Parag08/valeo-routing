import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useFetch } from "./api";
import type { Hub, HubsData, Kpis, Meta } from "./api";
import { Tooltip, token, useDark, useWidth } from "./components";
import { oneDecimal, pct } from "./format";

interface Props {
  qs: string; // the scenario query string, without the date
  date: string;
  meta: Meta;
  applied: number;
  apply: (k: number) => void;
}

const hubsLabel = (k: number) => (k === 0 ? "Office only" : `${k} hub${k === 1 ? "" : "s"}`);

export function Hubs({ qs, date, meta, applied, apply }: Props) {
  const r = useFetch<HubsData>(`/api/hubs?date=${date}&${qs}`);
  const [preview, setPreview] = useState(applied);
  useEffect(() => setPreview(applied), [applied]);
  const data = r.data;
  const siting = data?.sitings[preview];

  return (
    <>
      <div className={`card${r.loading ? " loading" : ""}`}>
        <div className="card-head">
          <div>
            <h2>Where idle pairs wait between visits</h2>
            <p className="hint">
              Hubs are sited by K-median on the last {meta.settings.hub_history_days} days of synthetic orders
              {data ? ` (${data.window.from} to ${data.window.to}, ${data.window.orders} orders)` : ""}: each candidate is a
              public neighbourhood centre, and the hubs chosen are the ones that put demand nearest a place to wait. The office
              stays open as a standby spot, so a pair waits at whichever of them adds the least driving.
            </p>
          </div>
          <div className="hub-actions">
            <div className="seg" role="group" aria-label="Number of hubs">
              {Array.from({ length: meta.settings.hub_max_count + 1 }, (_, k) => (
                <button key={k} aria-pressed={preview === k} onClick={() => setPreview(k)}>{k === 0 ? "Office only" : k}</button>
              ))}
            </div>
            <button className="primary-btn" disabled={preview === applied} onClick={() => apply(preview)}>
              {preview === applied ? `${hubsLabel(applied)} in use` : `Use ${hubsLabel(preview).toLowerCase()} in the day view`}
            </button>
          </div>
        </div>
        {r.error && <p className="error">{r.error}</p>}
        {data && siting && (
          <div className="hub-grid">
            <HubMap data={data} hubs={siting.hubs} meta={meta} />
            <HubList siting={siting} data={data} applied={applied} />
          </div>
        )}
        {!data && r.loading && <p className="hint">Siting hubs and replaying the day for each count…</p>}
      </div>
      {data && <HubCurves data={data} preview={preview} setPreview={setPreview} />}
    </>
  );
}

function HubMap({ data, hubs, meta }: { data: HubsData; hubs: Hub[]; meta: Meta }) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);
  const [ready, setReady] = useState(false);
  const dark = useDark();

  useEffect(() => {
    if (!box.current) return;
    const m = new maplibregl.Map({
      container: box.current,
      style: {
        version: 8,
        sources: {
          tiles: { type: "raster", tiles: [meta.map.tile_url], tileSize: 256, attribution: meta.map.attribution, maxzoom: 19 },
        },
        layers: [{ id: "tiles", type: "raster", source: "tiles" }],
      },
      bounds: bounds(data.orders),
      fitBoundsOptions: { padding: 32 },
      attributionControl: { compact: true },
      cooperativeGestures: true,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("load", () => {
      m.addSource("orders", { type: "geojson", data: points(data.orders) });
      m.addLayer({ id: "orders", type: "circle", source: "orders",
                   paint: { "circle-radius": 2.5, "circle-opacity": 0.55, "circle-color": token("--accent") } });
      setReady(true);
    });
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
      setReady(false);
    };
  }, [meta.map.tile_url, meta.map.attribution]); // eslint-disable-line react-hooks/exhaustive-deps

  // Orders change only with the data; hubs with the preview; the tiles and dots follow the theme.
  useEffect(() => {
    const src = map.current?.getSource("orders") as maplibregl.GeoJSONSource | undefined;
    if (ready && src) src.setData(points(data.orders));
  }, [ready, data.orders]);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    m.setPaintProperty("tiles", "raster-saturation", dark ? -0.9 : -0.6);
    m.setPaintProperty("tiles", "raster-brightness-min", dark ? 0.85 : 0);
    m.setPaintProperty("tiles", "raster-brightness-max", dark ? 0.05 : 1);
    m.setPaintProperty("tiles", "raster-opacity", dark ? 0.9 : 0.85);
    m.setPaintProperty("orders", "circle-color", token("--accent"));
  }, [ready, dark]);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    markers.current.forEach((x) => x.remove());
    const pin = (cls: string, label: string, title: string) => {
      const el = document.createElement("div");
      el.className = `map-pin ${cls}`;
      el.title = title;
      el.innerHTML = `<span class="map-pin-dot"></span><span class="map-pin-label"></span>`;
      (el.querySelector(".map-pin-label") as HTMLElement).textContent = label;
      return el;
    };
    markers.current = [
      new maplibregl.Marker({ element: pin("office", "Office", data.office.name), anchor: "left", offset: [-7, 0] })
        .setLngLat([data.office.lon, data.office.lat]).addTo(m),
      ...hubs.map((h) =>
        new maplibregl.Marker({ element: pin("hub", `${h.id} ${h.name}`, `${h.id}: ${h.name}, ${h.emirate}`), anchor: "left", offset: [-7, 0] })
          .setLngLat([h.lon, h.lat]).addTo(m),
      ),
    ];
  }, [hubs, data.office]);

  return (
    <div className="map-wrap">
      <div ref={box} className="map" role="img"
           aria-label={`Map of ${data.orders.length} synthetic orders with the office and ${hubs.length} hubs. The hubs are listed beside the map.`} />
      <div className="legend map-legend">
        <span><i style={{ background: "var(--accent)", borderRadius: 6, width: 8, height: 8 }} />An order (synthetic, last {data.window.days} days)</span>
        <span><i className="legend-pin hub" />Hub</span>
        <span><i className="legend-pin office" />Office</span>
      </div>
    </div>
  );
}

function bounds(orders: [number, number][]): [[number, number], [number, number]] {
  const lats = orders.map((o) => o[0]);
  const lons = orders.map((o) => o[1]);
  return [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]];
}

function points(orders: [number, number][]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: orders.map(([lat, lon]) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [lon, lat] } })),
  };
}

function HubList({ siting, data, applied }: { siting: HubsData["sitings"][number]; data: HubsData; applied: number }) {
  const total = data.window.orders;
  return (
    <div className="hub-list">
      <div className="hub-list-head">
        <b>{hubsLabel(siting.k)}</b>
        {siting.k === applied && <span className="tag">in the day view</span>}
      </div>
      <p className="hint" style={{ margin: "2px 0 10px" }}>
        On average an order is <b className="ink">{oneDecimal(siting.km_to_spot)} km</b> by road from its nearest place to wait.
      </p>
      <table>
        <thead>
          <tr><th>Spot</th><th className="num">Orders nearest</th></tr>
        </thead>
        <tbody>
          {siting.hubs.map((h) => (
            <tr key={h.id}>
              <td><span className="chip"><i className="legend-pin hub" />{h.id} {h.name}</span><div className="sub-cell">{h.emirate}</div></td>
              <td className="num">{h.orders} <span className="sub-cell">{pct(h.orders / total)}</span></td>
            </tr>
          ))}
          <tr>
            <td><span className="chip"><i className="legend-pin office" />Office</span><div className="sub-cell">{data.office.name}</div></td>
            <td className="num">{siting.office_orders} <span className="sub-cell">{pct(siting.office_orders / total)}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

type Row = { k: number; label: string; value: number; kpis?: Kpis };

function HubCurves({ data, preview, setPreview }: { data: HubsData; preview: number; setPreview: (k: number) => void }) {
  const day: Row[] = data.sitings.map((s) => ({ k: s.k, label: hubsLabel(s.k), value: s.day.km_per_visit, kpis: s.day }));
  const proxy: Row[] = data.sitings.map((s) => ({ k: s.k, label: hubsLabel(s.k), value: s.km_to_spot }));
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>km per order against the number of hubs</h2>
      <p className="hint">
        Left: what the planner actually drives on {data.date} under Logistics Valeo v1, way home included, under the same acceptance
        rules: only where idle pairs wait changes (which can also shift a few later orders between pairs). Right: the siting's own measure over
        the {data.window.days} days, how far an order sits from its nearest place to wait. The gain flattens once demand is
        near a hub. Synthetic data.
      </p>
      <div className="curve-grid">
        <BarCurve title="km per visit, this day" rows={day} preview={preview} setPreview={setPreview} unit="km per visit" />
        <BarCurve title={`km to the nearest place to wait, ${data.window.days} days`} rows={proxy} preview={preview}
                  setPreview={setPreview} unit="km to nearest spot" />
      </div>
      <details className="table-view">
        <summary>Table view</summary>
        <div className="table-scroll" style={{ maxHeight: "none" }}>
          <table>
            <thead>
              <tr><th>Standby</th><th>Hubs</th><th className="num">km to nearest spot</th><th className="num">Visits</th>
                <th className="num">Captured</th><th className="num">km</th><th className="num">km per visit</th><th className="num">Idle pair-hours</th></tr>
            </thead>
            <tbody>
              {data.sitings.map((s) => (
                <tr key={s.k}>
                  <td>{hubsLabel(s.k)}</td>
                  <td style={{ whiteSpace: "normal" }}>{s.hubs.map((h) => h.name).join(", ") || "–"}</td>
                  <td className="num">{oneDecimal(s.km_to_spot)}</td>
                  <td className="num">{s.day.visits}</td>
                  <td className="num">{pct(s.day.capture_rate)}</td>
                  <td className="num">{Math.round(s.day.km)}</td>
                  <td className="num">{oneDecimal(s.day.km_per_visit)}</td>
                  <td className="num">{Math.round(s.day.idle_h)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

const C = { left: 36, right: 8, top: 22, bottom: 28, height: 220 };

function BarCurve({ title, rows, preview, setPreview, unit }: {
  title: string; rows: Row[]; preview: number; setPreview: (k: number) => void; unit: string;
}) {
  const [ref, width] = useWidth(420);
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null);
  const W = Math.max(260, width);
  const plotW = W - C.left - C.right;
  const plotH = C.height - C.top - C.bottom;
  const max = Math.max(...rows.map((r) => r.value), 1);
  const step = max > 40 ? 20 : max > 20 ? 10 : 5;
  const top = Math.ceil(max / step) * step;
  const ticks = Array.from({ length: top / step + 1 }, (_, i) => i * step);
  const band = plotW / rows.length;
  const barW = Math.min(44, band * 0.56);
  const y = (v: number) => C.top + plotH - (v / top) * plotH;
  const base = C.top + plotH;
  const bar = (i: number, v: number) => {
    const bx = C.left + i * band + (band - barW) / 2;
    const by = y(v);
    const r = Math.min(4, (base - by) / 2);
    return `M${bx},${base} V${by + r} Q${bx},${by} ${bx + r},${by} H${bx + barW - r} Q${bx + barW},${by} ${bx + barW},${by + r} V${base} Z`;
  };
  return (
    <div>
      <div className="curve-title">{title}</div>
      <div className="timeline-wrap" ref={ref} onPointerLeave={() => setHover(null)}>
        <svg width={W} height={C.height} className="timeline" role="img" aria-label={`${title}, by number of hubs. The same numbers are in the table view.`}>
          {ticks.map((t) => (
            <g key={t}>
              <line className="gridline" x1={C.left} x2={W - C.right} y1={y(t)} y2={y(t)} />
              <text className="axis-label" x={C.left - 6} y={y(t) + 4} textAnchor="end">{t}</text>
            </g>
          ))}
          {rows.map((r, i) => (
            <g key={r.k}>
              {hover?.i === i && <rect fill="var(--hover)" x={C.left + i * band} y={C.top} width={band} height={plotH} />}
              <path d={bar(i, r.value)} fill={r.k === preview ? "var(--accent)" : "var(--neutral-mid)"} />
              <text className="bar-value" x={C.left + i * band + band / 2} y={y(r.value) - 6} textAnchor="middle">{oneDecimal(r.value)}</text>
              <text className="axis-label" x={C.left + i * band + band / 2} y={C.height - 9} textAnchor="middle">{r.k === 0 ? "Office" : r.k}</text>
              <rect x={C.left + i * band} y={C.top} width={band} height={plotH} fill="transparent" style={{ cursor: "pointer" }}
                    onClick={() => setPreview(r.k)}
                    onPointerMove={(e) => {
                      const b = ref.current!.getBoundingClientRect();
                      setHover({ i, x: Math.min(e.clientX - b.left + 14, W - 230), y: e.clientY - b.top + 14 });
                    }} />
            </g>
          ))}
        </svg>
        {hover && (
          <Tooltip x={hover.x} y={hover.y}>
            <div className="t-title">{rows[hover.i].label}</div>
            <div className="t-line"><b>{oneDecimal(rows[hover.i].value)}</b> {unit}</div>
            {rows[hover.i].kpis && (
              <div className="t-line">{rows[hover.i].kpis!.visits} visits · {Math.round(rows[hover.i].kpis!.km)} km · {pct(rows[hover.i].kpis!.capture_rate)} captured</div>
            )}
            <div className="t-line">Click to show it on the map</div>
          </Tooltip>
        )}
      </div>
    </div>
  );
}
