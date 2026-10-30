import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useFetch } from "./api";
import type { Kpis, RosterData, RosterMode, StaffRow, StaffStatus } from "./api";
import { Tooltip } from "./components";
import { clock, oneDecimal, pct } from "./format";

const LABEL: Record<RosterMode, string> = { auto: "Auto-allocated", simple: "Simple pairing" };

interface Props {
  qs: string; // the scenario query string, without the date
  date: string;
  mode: RosterMode;
  setMode: (m: RosterMode) => void;
  unavailable: string[];
  toggleSick: (id: string) => void;
}

export function Roster({ qs, date, mode, setMode, unavailable, toggleSick }: Props) {
  const r = useFetch<RosterData>(`/api/roster?date=${date}&${qs}`);
  const data = r.data;
  return (
    <>
      <div className={`card${r.loading ? " loading" : ""}`}>
        <div className="card-head">
          <div>
            <h2>{data ? `${data.weekday} ${data.date}` : date}: who works, and when</h2>
            <p className="hint">
              Every available nurse and driver is paired; the roster picks each pair's shift start so that the pairs on duty
              cover the demand expected for this weekday, estimated from the other days of the month.
            </p>
          </div>
          <div className="seg" role="group" aria-label="Roster mode">
            {(Object.keys(LABEL) as RosterMode[]).map((m) => (
              <button key={m} aria-pressed={mode === m} onClick={() => setMode(m)}>{LABEL[m]}</button>
            ))}
          </div>
        </div>
        {r.error && <p className="error">{r.error}</p>}
        {data && <DemandChart data={data} mode={mode} />}
      </div>

      {data && (
        <>
          <Comparison data={data} />
          <StaffTable data={data} unavailable={unavailable} toggleSick={toggleSick} />
        </>
      )}
    </>
  );
}

function niceMax(v: number): number {
  const steps = [2, 4, 6, 8, 10, 12, 14, 16];
  return steps.find((s) => s >= v) ?? Math.ceil(v / 2) * 2;
}

const M = { left: 40, right: 16, top: 14, bottom: 30, height: 260 };

function DemandChart({ data, mode }: { data: RosterData; mode: RosterMode }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    setWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);

  const { hours, required_pairs: need, on_duty, expected_orders: orders } = data.curve;
  const other: RosterMode = mode === "auto" ? "simple" : "auto";
  const mine = on_duty[mode];
  const W = Math.max(520, width);
  const plotW = W - M.left - M.right;
  const plotH = M.height - M.top - M.bottom;
  const top = niceMax(Math.max(...need, ...mine, ...on_duty[other], 1));
  const band = plotW / hours.length;
  const barW = Math.min(24, band * 0.6);
  const x0 = (i: number) => M.left + i * band;
  const y = (v: number) => M.top + plotH - (v / top) * plotH;
  const ticks = Array.from({ length: top / 2 + 1 }, (_, k) => k * 2);

  const step = (values: number[]) =>
    values.map((v, i) => `${i === 0 ? "M" : "L"}${x0(i)},${y(v)} L${x0(i + 1)},${y(v)}`).join(" ");
  const barPath = (i: number, v: number) => {
    const bx = x0(i) + (band - barW) / 2;
    const by = y(v);
    const r = Math.min(4, (M.top + plotH - by) / 2, barW / 2);
    return `M${bx},${M.top + plotH} V${by + r} Q${bx},${by} ${bx + r},${by} H${bx + barW - r} Q${bx + barW},${by} ${bx + barW},${by + r} V${M.top + plotH} Z`;
  };

  const short = (i: number) => need[i] > mine[i] + 0.05;
  const tip = hover && (
    <Tooltip x={hover.x} y={hover.y}>
      <div className="t-title">{clock(hours[hover.i] * 60)}–{clock(hours[hover.i] * 60 + 60)}</div>
      <div className="t-line"><b>{oneDecimal(need[hover.i])} pairs</b> needed · about {oneDecimal(orders[hover.i])} orders expected</div>
      <div className="t-line"><b>{oneDecimal(mine[hover.i])}</b> on duty ({LABEL[mode].toLowerCase()})</div>
      <div className="t-line"><b>{oneDecimal(on_duty[other][hover.i])}</b> on duty ({LABEL[other].toLowerCase()})</div>
      {short(hover.i) && <div className="t-line">Short by {oneDecimal(need[hover.i] - mine[hover.i])} pairs</div>}
    </Tooltip>
  );

  return (
    <>
      <div className="legend">
        <span><i style={{ background: "var(--neutral-mid)" }} />Pairs needed, covered</span>
        <span><i style={{ background: "var(--serious)" }} />Pairs needed, not covered</span>
        <span><i style={{ background: "var(--accent)", height: 3, marginTop: 4 }} />On duty, {LABEL[mode].toLowerCase()}</span>
        <span><i style={{ background: "var(--muted)", height: 3, marginTop: 4 }} />On duty, {LABEL[other].toLowerCase()}</span>
      </div>
      <div className="timeline-wrap" ref={wrapRef} onPointerLeave={() => setHover(null)}>
        <svg width={W} height={M.height} role="img" className="timeline"
             aria-label={`Pairs needed each hour against pairs on duty, ${LABEL[mode]}. The same numbers are in the table below.`}>
          {ticks.map((t) => (
            <g key={t}>
              <line className="gridline" x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} />
              <text className="axis-label" x={M.left - 8} y={y(t) + 4} textAnchor="end">{t}</text>
            </g>
          ))}
          {hours.map((h, i) => (
            <g key={h}>
              {hover?.i === i && <rect fill="var(--hover)" x={x0(i)} y={M.top} width={band} height={plotH} />}
              <path d={barPath(i, need[i])} fill={short(i) ? "var(--serious)" : "var(--neutral-mid)"} />
              <text className="axis-label" x={x0(i) + band / 2} y={M.height - 10} textAnchor="middle">
                {band > 40 ? clock(h * 60) : String(h).padStart(2, "0")}
              </text>
            </g>
          ))}
          <path d={step(on_duty[other])} fill="none" stroke="var(--muted)" strokeWidth={2} strokeLinejoin="round" />
          <path d={step(mine)} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" />
          {hover && (
            <circle cx={x0(hover.i) + band / 2} cy={y(mine[hover.i])} r={5} fill="var(--accent)" stroke="var(--surface)" strokeWidth={2} />
          )}
          {hours.map((h, i) => (
            <rect key={h} x={x0(i)} y={M.top} width={band} height={plotH} fill="transparent"
                  onPointerMove={(e) => {
                    const box = wrapRef.current!.getBoundingClientRect();
                    setHover({ i, x: Math.min(e.clientX - box.left + wrapRef.current!.scrollLeft + 14, W - 300), y: e.clientY - box.top + 14 });
                  }} />
          ))}
          <text className="axis-label" x={M.left} y={10}>pairs</text>
        </svg>
        {tip}
      </div>
      <details className="table-view">
        <summary>Table view</summary>
        <div className="table-scroll" style={{ maxHeight: 320 }}>
          <table>
            <thead>
              <tr><th>Hour</th><th className="num">Orders expected</th><th className="num">Pairs needed</th>
                <th className="num">On duty, {LABEL[mode].toLowerCase()}</th><th className="num">On duty, {LABEL[other].toLowerCase()}</th></tr>
            </thead>
            <tbody>
              {hours.map((h, i) => (
                <tr key={h}>
                  <td>{clock(h * 60)}</td><td className="num">{oneDecimal(orders[i])}</td><td className="num">{oneDecimal(need[i])}</td>
                  <td className="num">{oneDecimal(mine[i])}</td><td className="num">{oneDecimal(on_duty[other][i])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

function Comparison({ data }: { data: RosterData }) {
  const rows = (Object.keys(LABEL) as RosterMode[]).map((m) => ({ m, k: data.compare[m], gap: data.curve.shortfall[m] }));
  const better = (get: (k: Kpis) => number, lower = false) => {
    const [a, b] = [get(rows[0].k), get(rows[1].k)];
    return (m: RosterMode) => (a === b ? "" : (m === "auto" ? a : b) === (lower ? Math.min(a, b) : Math.max(a, b)) ? " best" : "");
  };
  const capture = better((k) => k.capture_rate);
  const idle = better((k) => k.idle_h, true);
  const km = better((k) => k.km_per_visit, true);
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>Same day, same acceptance policy, different roster</h2>
      <p className="hint">
        Both rosters use the same people; only how they are paired and when their shifts start differs. The green bar marks the better value.
        km per visit falls when fewer far-away orders are served, so read it with the captured share.
      </p>
      <div className="table-scroll" style={{ maxHeight: "none" }}>
        <table>
          <thead>
            <tr><th>Roster</th><th className="num">Pairs</th><th className="num">Captured</th><th className="num">Visits</th><th className="num">Declined</th>
              <th className="num">km per visit</th><th className="num">Idle pair-hours</th><th className="num">Demand left uncovered</th></tr>
          </thead>
          <tbody>
            {rows.map(({ m, k, gap }) => (
              <tr key={m}>
                <td>{LABEL[m]}{data.roster === m ? " (shown)" : ""}</td>
                <td className="num">{data.pairs.length}</td>
                <td className={`num${capture(m)}`}>{pct(k.capture_rate)}</td>
                <td className="num">{k.visits}</td>
                <td className="num">{k.declined}</td>
                <td className={`num${km(m)}`}>{oneDecimal(k.km_per_visit)}</td>
                <td className={`num${idle(m)}`}>{Math.round(k.idle_h)}</td>
                <td className="num">{oneDecimal(gap)} pair-h</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const STATUS: Record<StaffStatus, { label: string; color: string; glyph: ReactNode }> = {
  available: { label: "Available", color: "var(--good)", glyph: <path d="M3 8.5l3.2 3L13 4.5" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /> },
  rest: { label: "Rest day", color: "var(--muted)", glyph: <path d="M3.5 8h9" fill="none" strokeWidth="2" strokeLinecap="round" /> },
  leave: { label: "On leave", color: "var(--muted)", glyph: <path d="M3.5 8h9" fill="none" strokeWidth="2" strokeLinecap="round" /> },
  sick: { label: "Sick", color: "var(--serious)", glyph: <path d="M8 3.5v5.5M8 12.2v.3" fill="none" strokeWidth="2" strokeLinecap="round" /> },
  marked_sick: { label: "Marked sick", color: "var(--serious)", glyph: <path d="M8 3.5v5.5M8 12.2v.3" fill="none" strokeWidth="2" strokeLinecap="round" /> },
};

function StatusChip({ status }: { status: StaffStatus }) {
  const s = STATUS[status];
  return (
    <span className="chip">
      <svg width="14" height="14" viewBox="0 0 16 16" stroke={s.color} aria-hidden="true">{s.glyph}</svg>
      {s.label}
    </span>
  );
}

function StaffTable({ data, unavailable, toggleSick }: { data: RosterData; unavailable: string[]; toggleSick: (id: string) => void }) {
  const pairs = new Map(data.pairs.map((p) => [p.id, p]));
  const where = (p: StaffRow) =>
    p.pair_id ? `${p.pair_id} · ${clock(p.shift_start!)}–${clock(p.shift_end!)}` : p.status === "available" ? "Reserve" : "–";
  const partner = (p: StaffRow) => {
    const pair = p.pair_id ? pairs.get(p.pair_id) : undefined;
    return pair ? (p.role === "nurse" ? pair.driver : pair.nurse) : "–";
  };
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>Staff for the day</h2>
      <p className="hint">
        Mark someone sick and the roster, the plan and every figure are redone without them. Rest days, sick calls and leave
        come from the data. {unavailable.length > 0 && `${unavailable.length} marked sick here.`}
      </p>
      <div className="table-scroll" style={{ maxHeight: 520 }}>
        <table>
          <thead>
            <tr><th>Name</th><th>Role</th><th>Status</th><th>Pair and shift</th><th>Paired with</th><th /></tr>
          </thead>
          <tbody>
            {data.staff.map((p) => {
              const can = p.status === "available" || p.status === "marked_sick";
              return (
                <tr key={p.id}>
                  <td>{p.name} <span style={{ color: "var(--muted)" }}>{p.id}</span></td>
                  <td>{p.role === "nurse" ? (p.iv_certified ? "Nurse, IV certified" : "Nurse") : "Driver"}</td>
                  <td><StatusChip status={p.status} /></td>
                  <td>{where(p)}</td>
                  <td>{partner(p)}</td>
                  <td>
                    {can && (
                      <button className="icon-btn" onClick={() => toggleSick(p.id)}>
                        {p.status === "marked_sick" ? "Restore" : "Mark sick"}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
