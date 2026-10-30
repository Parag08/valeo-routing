import { useState } from "react";
import { useFetch } from "./api";
import type { CapacityData, CapacityDay } from "./api";
import { Tooltip, useWidth } from "./components";
import { pct } from "./format";

interface Props {
  qs: string; // the scenario query string, without the date
  date: string;
  setDate: (d: string) => void;
}

export function Capacity({ qs, date, setDate }: Props) {
  const r = useFetch<CapacityData>(`/api/capacity?${qs}`);
  const data = r.data;
  return (
    <>
      <div className={`card${r.loading ? " loading" : ""}`}>
        <h2>How many pairs each day's demand needs</h2>
        <p className="hint">
          For every day of the synthetic month, the planner is given all of the day's orders upfront and the fewest pairs that
          serve {data ? pct(data.serve_share) : "the target share"} of what {data ? data.max_pairs : "the largest fleet of"} pairs
          could serve are found by simulation. The concurrency floor
          is the most visits that overlap at one moment: no roster can do with fewer. A service level reads across days: the
          pairs needed at p75 are enough on at least three days in four.
        </p>
        {r.error && <p className="error">{r.error}</p>}
        {!data && r.loading && <p className="hint">Simulating the month, a few plans per day. The first time takes about half a minute…</p>}
        {data && (
          <div className="levels">
            {data.levels.map((l) => (
              <div className="tile" key={l.p}>
                <div className="label">Pairs needed at p{l.p}</div>
                <div className="value">{l.pairs}</div>
                <div className="note">enough on {l.p}% of days or more</div>
              </div>
            ))}
            <div className="tile">
              <div className="label">Pairs rostered</div>
              <div className="value">{data.rostered.min}–{data.rostered.max}</div>
              <div className="note">by the auto roster, from the staff available</div>
            </div>
          </div>
        )}
      </div>
      {data && <NeedChart data={data} date={date} setDate={setDate} />}
    </>
  );
}

const M = { left: 36, right: 12, top: 16, bottom: 34, height: 280 };

function NeedChart({ data, date, setDate }: { data: CapacityData; date: string; setDate: (d: string) => void }) {
  const [ref, width] = useWidth(1000);
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null);
  const days = data.days;
  const W = Math.max(640, width);
  const plotW = W - M.left - M.right;
  const plotH = M.height - M.top - M.bottom;
  const top = Math.ceil(Math.max(...days.map((d) => Math.max(d.needed, d.rostered)), 1) / 2) * 2 + 2;
  const ticks = Array.from({ length: top / 2 + 1 }, (_, k) => k * 2);
  const band = plotW / days.length;
  const barW = Math.min(18, band * 0.62);
  const y = (v: number) => M.top + plotH - (v / top) * plotH;
  const base = M.top + plotH;
  const x = (i: number) => M.left + i * band + band / 2;
  const short = (d: CapacityDay) => d.needed > d.rostered;
  const bar = (i: number, v: number) => {
    const bx = x(i) - barW / 2;
    const by = y(v);
    const r = Math.min(4, (base - by) / 2, barW / 2);
    return `M${bx},${base} V${by + r} Q${bx},${by} ${bx + r},${by} H${bx + barW - r} Q${bx + barW},${by} ${bx + barW},${by + r} V${base} Z`;
  };
  const shortDays = days.filter(short).length;
  const d = hover ? days[hover.i] : null;

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>Day by day: pairs needed against pairs rostered</h2>
      <p className="hint">
        {shortDays === 0
          ? "The auto roster put at least the simulated need on duty every day."
          : `On ${shortDays} of ${days.length} days the simulation needs more pairs than the roster had: days to expect declined orders.`}{" "}
        Click a day to open it in the other tabs. Synthetic data.
      </p>
      <div className="legend">
        <span><i style={{ background: "var(--neutral-mid)" }} />Pairs needed, rostered enough</span>
        <span><i style={{ background: "var(--serious)" }} />Pairs needed, more than rostered</span>
        <span><i style={{ background: "var(--accent)", borderRadius: 6 }} />Pairs rostered</span>
        <span><i style={{ background: "var(--text-2)", height: 2, marginTop: 5 }} />Concurrency floor</span>
      </div>
      <div className="timeline-wrap" ref={ref} onPointerLeave={() => setHover(null)}>
        <svg width={W} height={M.height} className="timeline" role="img"
             aria-label="Pairs needed each day against pairs rostered and the concurrency floor. The same numbers are in the table view.">
          {ticks.map((t) => (
            <g key={t}>
              <line className="gridline" x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} />
              <text className="axis-label" x={M.left - 6} y={y(t) + 4} textAnchor="end">{t}</text>
            </g>
          ))}
          {days.map((day, i) => (
            <g key={day.date}>
              {(hover?.i === i || day.date === date) && (
                <rect fill="var(--hover)" x={M.left + i * band} y={M.top} width={band} height={plotH} />
              )}
              <path d={bar(i, day.needed)} fill={short(day) ? "var(--serious)" : "var(--neutral-mid)"} />
              <line x1={x(i) - barW / 2 - 2} x2={x(i) + barW / 2 + 2} y1={y(day.floor)} y2={y(day.floor)} stroke="var(--text-2)" strokeWidth={2} />
              <circle cx={x(i)} cy={y(day.rostered)} r={4} fill="var(--accent)" stroke="var(--surface)" strokeWidth={2} />
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
                    setHover({ i, x: Math.min(e.clientX - b.left + ref.current!.scrollLeft + 14, W - 260), y: e.clientY - b.top + 14 });
                  }} />
          ))}
          <text className="axis-label" x={M.left} y={10}>pairs</text>
        </svg>
        {d && hover && (
          <Tooltip x={hover.x} y={hover.y}>
            <div className="t-title">{d.weekday} {d.date}</div>
            <div className="t-line"><b>{d.needed}</b> pairs needed · <b>{d.rostered}</b> rostered · floor <b>{d.floor}</b></div>
            <div className="t-line">{d.orders} orders; {d.served} served with {d.needed} pairs</div>
            {d.unservable > 0 && <div className="t-line">{d.unservable} that no fleet of up to {data.max_pairs} pairs could fit</div>}
          </Tooltip>
        )}
      </div>
      <details className="table-view">
        <summary>Table view</summary>
        <div className="table-scroll" style={{ maxHeight: 360 }}>
          <table>
            <thead>
              <tr><th>Day</th><th className="num">Orders</th><th className="num">Floor</th><th className="num">Pairs needed</th>
                <th className="num">Served with them</th><th className="num">Unservable</th><th className="num">Rostered</th></tr>
            </thead>
            <tbody>
              {days.map((day) => (
                <tr key={day.date}>
                  <td>{day.weekday} {day.date}</td><td className="num">{day.orders}</td><td className="num">{day.floor}</td>
                  <td className="num">{day.needed}</td><td className="num">{day.served}</td><td className="num">{day.unservable}</td>
                  <td className="num">{day.rostered}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
