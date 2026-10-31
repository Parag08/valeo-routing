import { useState } from "react";
import { useFetch } from "./api";
import type { MetricsData, MetricsDay, MetricsTotals } from "./api";
import { Tooltip, useWidth } from "./components";
import { pct } from "./format";

interface Props {
  qs: string; // the scenario query string, without the date
  date: string;
  setDate: (d: string) => void;
}

const num = (x: number) => Math.round(x).toLocaleString("en-US");
const ratio = (x: number) => `${x.toFixed(2)}×`;

export function Metrics({ qs, date, setDate }: Props) {
  const r = useFetch<MetricsData>(`/api/metrics?date=${date}&${qs}`);
  const m = r.data;
  return (
    <>
      <div className={`card${r.loading ? " loading" : ""}`}>
        <h2>Predicted against actual</h2>
        <p className="hint">
          The planner predicts each drive as straight-line distance × a road factor{m ? ` of ${m.road_factor}` : ""}. Here the
          "actual" comes from a synthetic vehicle tracker, recorded per drive, which sometimes drops out or jumps. Days with bad
          tracker data are left out of every total, and the reason is shown. Synthetic data.
        </p>
        {r.error && <p className="error">{r.error}</p>}
        {!m && r.loading && <p className="hint">Replaying the month under both policies…</p>}
        {m && (
          <div className="levels">
            <div className="tile">
              <div className="label">Recorded ÷ predicted km</div>
              <div className="value">{ratio(m.summary.km_ratio)}</div>
              <div className="note">from totals, {m.summary.clean_days} of {m.summary.days} days clean</div>
            </div>
            <div className="tile">
              <div className="label">Typical error, one pair's day</div>
              <div className="value">{m.summary.median_error === null ? "–" : `±${pct(m.summary.median_error)}`}</div>
              <div className="note">median, km recorded against predicted</div>
            </div>
            <div className="tile">
              <div className="label">Driving time, recorded ÷ predicted</div>
              <div className="value">{ratio(m.summary.time_ratio)}</div>
              <div className="note">traffic the speed model misses</div>
            </div>
            <div className="tile">
              <div className="label">Road factor to recalibrate to</div>
              <div className="value">{m.road_factor} → {m.summary.suggested_road_factor}</div>
              <div className="note">so predictions match the tracker on average</div>
            </div>
          </div>
        )}
      </div>
      {m && <DayChart m={m} date={date} setDate={setDate} />}
      {m && <SavingCard m={m} />}
      {m && <PairTable m={m} />}
    </>
  );
}

const M = { left: 48, right: 12, top: 16, bottom: 34, height: 260 };

function DayChart({ m, date, setDate }: { m: MetricsData; date: string; setDate: (d: string) => void }) {
  const [ref, width] = useWidth(1000);
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null);
  const days = m.days;
  const W = Math.max(640, width);
  const plotW = W - M.left - M.right;
  const plotH = M.height - M.top - M.bottom;
  const most = Math.max(...days.map((d) => Math.max(d.actual_km, d.predicted_km)), 1);
  const step = most > 2000 ? 500 : 250;
  const top = Math.ceil(most / step) * step;
  const ticks = Array.from({ length: top / step + 1 }, (_, k) => k * step);
  const band = plotW / days.length;
  const barW = Math.min(18, band * 0.62);
  const y = (v: number) => M.top + plotH - (v / top) * plotH;
  const base = M.top + plotH;
  const x = (i: number) => M.left + i * band + band / 2;
  const bar = (i: number, v: number) => {
    const bx = x(i) - barW / 2;
    const by = y(v);
    const r = Math.min(4, (base - by) / 2, barW / 2);
    return `M${bx},${base} V${by + r} Q${bx},${by} ${bx + r},${by} H${bx + barW - r} Q${bx + barW},${by} ${bx + barW},${by + r} V${base} Z`;
  };
  const d: MetricsDay | null = hover ? days[hover.i] : null;

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>Day by day: km recorded against km predicted</h2>
      <p className="hint">
        Under {m.tool_label}. Excluded days are outlined, not filled: their totals are wrong, so nothing is measured on them.
        Click a day to open it in the other tabs.
      </p>
      <div className="legend">
        <span><i style={{ background: "var(--accent)" }} />Recorded km, clean day</span>
        <span><i style={{ background: "transparent", border: "1.5px dashed var(--muted)" }} />Recorded km, day excluded</span>
        <span><i style={{ background: "var(--text-2)", height: 2, marginTop: 5 }} />Predicted km</span>
      </div>
      <div className="timeline-wrap" ref={ref} onPointerLeave={() => setHover(null)}>
        <svg width={W} height={M.height} className="timeline" role="img"
             aria-label="Recorded against predicted km for each day; excluded days are outlined. The same numbers are in the table view.">
          {ticks.map((t) => (
            <g key={t}>
              <line className="gridline" x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} />
              <text className="axis-label" x={M.left - 6} y={y(t) + 4} textAnchor="end">{num(t)}</text>
            </g>
          ))}
          {days.map((day, i) => (
            <g key={day.date}>
              {(hover?.i === i || day.date === date) && (
                <rect fill="var(--hover)" x={M.left + i * band} y={M.top} width={band} height={plotH} />
              )}
              <path d={bar(i, day.actual_km)} fill={day.excluded ? "transparent" : "var(--accent)"}
                    stroke={day.excluded ? "var(--muted)" : "none"} strokeWidth={1.5} strokeDasharray={day.excluded ? "3 2" : undefined} />
              <line x1={x(i) - barW / 2 - 2} x2={x(i) + barW / 2 + 2} y1={y(day.predicted_km)} y2={y(day.predicted_km)}
                    stroke="var(--text-2)" strokeWidth={2} />
              {(band > 26 || i % 7 === 0) && (
                <text className="axis-label" x={x(i)} y={M.height - 18} textAnchor="middle">{day.date.slice(8)}</text>
              )}
              {(band > 26 || i % 7 === 0) && (
                <text className="axis-label" x={x(i)} y={M.height - 5} textAnchor="middle">{day.weekday.slice(0, 2)}</text>
              )}
            </g>
          ))}
          {days.map((day, i) => (
            <rect key={day.date} x={M.left + i * band} y={M.top} width={band} height={plotH} fill="transparent" style={{ cursor: "pointer" }}
                  onClick={() => setDate(day.date)}
                  onPointerMove={(e) => {
                    const b = ref.current!.getBoundingClientRect();
                    setHover({ i, x: Math.min(e.clientX - b.left + ref.current!.scrollLeft + 14, W - 280), y: e.clientY - b.top + 14 });
                  }} />
          ))}
          <text className="axis-label" x={M.left} y={10}>km</text>
        </svg>
        {d && hover && (
          <Tooltip x={hover.x} y={hover.y}>
            <div className="t-title">{d.weekday} {d.date}</div>
            <div className="t-line"><b>{num(d.actual_km)}</b> km recorded · <b>{num(d.predicted_km)}</b> predicted</div>
            <div className="t-line">driving {num(d.actual_min)} min recorded · {num(d.predicted_min)} predicted</div>
            <div className="t-line">{d.visits} visits</div>
            {d.excluded && <div className="t-line"><b>Excluded:</b> {d.excluded}</div>}
          </Tooltip>
        )}
      </div>
      <details className="table-view">
        <summary>Table view</summary>
        <div className="table-scroll" style={{ maxHeight: 360 }}>
          <table>
            <thead>
              <tr><th>Day</th><th className="num">Visits</th><th className="num">km predicted</th><th className="num">km recorded</th>
                <th className="num">Drive min predicted</th><th className="num">Drive min recorded</th><th>Excluded because</th></tr>
            </thead>
            <tbody>
              {days.map((day) => (
                <tr key={day.date}>
                  <td>{day.weekday} {day.date}</td><td className="num">{day.visits}</td>
                  <td className="num">{num(day.predicted_km)}</td><td className="num">{num(day.actual_km)}</td>
                  <td className="num">{num(day.predicted_min)}</td><td className="num">{num(day.actual_min)}</td>
                  <td className="why">{day.excluded || "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

function SavingCard({ m }: { m: MetricsData }) {
  const s = m.saving;
  const c = m.rates.currency;
  const excluded = m.days.filter((d) => d.excluded);
  const row = (label: string, t: MetricsTotals) => (
    <tr>
      <td>{label}</td><td className="num">{t.days}</td><td className="num">{num(t.visits)}</td><td className="num">{num(t.km)}</td>
      <td className="num"><b>{t.km_per_visit.toFixed(1)}</b></td><td className="num">{t.mean_of_daily.toFixed(1)}</td>
    </tr>
  );
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>Measuring the saving</h2>
      <p className="hint">
        The method the real project was measured by, run on the synthetic month: the Excel era against {m.tool_label} on
        the same clean days and the same demand, using recorded km.
      </p>
      <ol className="method">
        <li>
          <b>Leave out bad days.</b> {excluded.length} of {m.days.length} days had a tracker fault: coverage under{" "}
          {pct(m.rules.min_coverage)} of a shift, or a pair recording more than {m.rules.max_pair_ratio}× its prediction.
          {excluded.length > 0 && (
            <ul>{excluded.map((d) => <li key={d.date}>{d.weekday} {d.date}: {d.excluded}</li>)}</ul>
          )}
        </li>
        <li>
          <b>km per visit from totals</b>: total km ÷ total visits, not the average of each day's ratio, which gives
          small days the same weight as big ones.
          <div className="table-scroll" style={{ marginTop: 8 }}>
            <table>
              <thead><tr><th>Policy</th><th className="num">Days</th><th className="num">Visits</th><th className="num">km</th>
                <th className="num">km per visit</th><th className="num">Average of daily ratios</th></tr></thead>
              <tbody>{row("Excel era", s.baseline)}{row(m.tool_label, s.tool)}</tbody>
            </table>
          </div>
        </li>
        <li>
          <b>km saved</b> = ({s.baseline.km_per_visit.toFixed(1)} − {s.tool.km_per_visit.toFixed(1)}) km × {num(s.tool.visits)} visits ={" "}
          <b>{num(s.km_saved)} km</b> over {s.tool.days} days.
        </li>
        <li>
          <b>Valued at the marginal rate</b>, {c} {m.rates.marginal.toFixed(2)} per km (fuel, tolls, parking):{" "}
          <b>{c} {num(s.marginal)}</b>. Salaries and car rental don't fall when cars drive less, so the all-in{" "}
          {c} {m.rates.all_in.toFixed(2)} per km would claim {c} {num(s.all_in)}, {(s.all_in / Math.max(1, s.marginal)).toFixed(1)}× too much.
        </li>
      </ol>
      <p className="hint" style={{ margin: 0 }}>Rates are assumptions for the demo. Synthetic data, not Valeo's figures.</p>
    </div>
  );
}

function PairTable({ m }: { m: MetricsData }) {
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>Per pair on {m.date}</h2>
      <p className="hint">
        {m.day_excluded ? `This day is excluded: ${m.day_excluded}.` : "A clean day: every tracker covered its shift."} Under {m.tool_label}.
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>Pair</th><th className="num">Visits</th><th className="num">km predicted</th><th className="num">km recorded</th>
              <th className="num">Error</th><th className="num">Drive min predicted</th><th className="num">Drive min recorded</th>
              <th className="num">Tracker coverage</th></tr>
          </thead>
          <tbody>
            {m.pairs.map((p) => {
              const err = p.predicted_km ? p.actual_km / p.predicted_km - 1 : 0;
              return (
                <tr key={p.id}>
                  <td>{p.id}{p.fault && <span className="pill warn">{p.fault === "gap" ? "tracker dropped out" : "GPS jump"}</span>}</td>
                  <td className="num">{p.visits}</td><td className="num">{p.predicted_km.toFixed(1)}</td>
                  <td className="num">{p.actual_km.toFixed(1)}</td>
                  <td className="num">{p.predicted_km ? `${err >= 0 ? "+" : "−"}${Math.abs(Math.round(err * 100))}%` : "–"}</td>
                  <td className="num">{p.predicted_min}</td><td className="num">{p.actual_min}</td>
                  <td className="num">{pct(p.coverage)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
