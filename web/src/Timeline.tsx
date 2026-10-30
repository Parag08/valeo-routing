import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Block, DayData, LogRow, PairDay } from "./api";
import { Tooltip } from "./components";
import { MODE_LABEL, clock, oneDecimal, shortService, when } from "./format";

const LABEL_W = 184;
const ROW_H = 56;
const AXIS_H = 30;
const NOT_SERVED_H = 44;
const PAD_R = 16;
const MIN_PLOT_W = 560;
const CHAR_W = 6.3; // approximate width of one 11.5px character, used to check that a label fits

interface Tip {
  x: number;
  y: number;
  content: ReactNode;
}

interface Props {
  day: DayData;
  tolerance: number;
  selected: string | null;
  onSelect: (orderId: string) => void;
}

/** First candidate that fits in `width` px with comfortable padding; labels are never clipped. */
function fit(candidates: string[], width: number): string {
  return candidates.find((c) => c.length * CHAR_W + 12 <= width) ?? "";
}

export function Timeline({ day, tolerance, selected, onSelect }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(1100);
  const [tip, setTip] = useState<Tip | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    setWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);

  const { start, end } = day.window;
  const plotW = Math.max(MIN_PLOT_W, width - LABEL_W - PAD_R);
  const svgW = LABEL_W + plotW + PAD_R;
  const x = (minutes: number) => LABEL_W + ((minutes - start) / (end - start)) * plotW;
  const notServed = useMemo(() => day.log.filter((r) => r.outcome === "lost" || r.outcome === "declined"), [day.log]);
  const logById = useMemo(() => new Map(day.log.map((r) => [r.order_id, r])), [day.log]);
  const height = AXIS_H + NOT_SERVED_H + day.pairs.length * ROW_H + 8;
  const hours: number[] = [];
  for (let m = start; m <= end; m += 60) hours.push(m);

  const showTip = (event: { clientX: number; clientY: number }, content: ReactNode) => {
    const box = wrapRef.current!.getBoundingClientRect();
    const left = event.clientX - box.left + wrapRef.current!.scrollLeft + 14;
    const maxLeft = wrapRef.current!.scrollLeft + box.width - 310;
    setTip({ x: Math.max(8, Math.min(left, maxLeft)), y: event.clientY - box.top + 16, content });
  };
  const focusTip = (target: SVGElement, content: ReactNode) => {
    const r = target.getBoundingClientRect();
    showTip({ clientX: r.left + r.width / 2, clientY: r.bottom }, content);
  };

  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const box = svgRef.current!.getBoundingClientRect();
    const minutes = start + ((event.clientX - box.left - LABEL_W) / plotW) * (end - start);
    setCursor(minutes >= start && minutes <= end ? Math.round(minutes) : null);
  };

  return (
    <div className="timeline-wrap" ref={wrapRef} onPointerLeave={() => { setTip(null); setCursor(null); }}>
      <svg ref={svgRef} className="timeline" width={svgW} height={height} role="img"
           aria-label={`Timeline of ${day.pairs.length} nurse and driver pairs on ${day.date}, ${day.policy_label}. The same data is in the Acceptance tab as a table.`}
           onPointerMove={onMove}>
        {hours.map((m) => (
          <g key={m}>
            <line className="gridline" x1={x(m)} x2={x(m)} y1={AXIS_H - 4} y2={height - 4} />
            <text className="axis-label" x={x(m)} y={AXIS_H - 12} textAnchor="middle">
              {plotW / hours.length > 44 ? clock(m) : clock(m).slice(0, 2)}
            </text>
          </g>
        ))}

        <g>
          <text className="row-label" x={8} y={AXIS_H + 19}>Not captured</text>
          <text className="row-sub" x={8} y={AXIS_H + 34}>by requested time</text>
          {notServed.map((r) => (
            <NotServedMarker key={r.order_id} row={r} cx={x(r.slot)} cy={AXIS_H + NOT_SERVED_H / 2}
              selected={selected === r.order_id} job={day.jobs[r.order_id]}
              onSelect={onSelect} showTip={showTip} focusTip={focusTip} hide={() => setTip(null)} />
          ))}
        </g>

        {day.pairs.map((pair, i) => (
          <PairRow key={pair.id} pair={pair} y={AXIS_H + NOT_SERVED_H + i * ROW_H} x={x} day={day}
            tolerance={tolerance} logById={logById} selected={selected} onSelect={onSelect}
            showTip={showTip} focusTip={focusTip} hide={() => setTip(null)} />
        ))}

        {cursor !== null && (
          <g pointerEvents="none">
            <line className="crosshair" x1={x(cursor)} x2={x(cursor)} y1={AXIS_H - 2} y2={height - 4} />
            <rect className="cross-label-bg" x={x(cursor) - 24} y={2} width={48} height={18} rx={4} />
            <text className="cross-label" x={x(cursor)} y={15} textAnchor="middle">{clock(cursor)}</text>
          </g>
        )}
      </svg>
      {tip && <Tooltip x={tip.x} y={tip.y}>{tip.content}</Tooltip>}
    </div>
  );
}

interface Common {
  showTip: (event: { clientX: number; clientY: number }, content: ReactNode) => void;
  focusTip: (target: SVGElement, content: ReactNode) => void;
  hide: () => void;
  onSelect: (orderId: string) => void;
}

function NotServedMarker({ row, cx, cy, selected, job, onSelect, showTip, focusTip, hide }: Common & {
  row: LogRow; cx: number; cy: number; selected: boolean; job: DayData["jobs"][string];
}) {
  const lost = row.outcome === "lost";
  const content = (
    <>
      <div className="t-title">{job.service}</div>
      <div className="t-line"><b>{lost ? "Lost to a competitor" : "Declined"}</b> · requested {clock(row.slot)}</div>
      <div className="t-line">{job.area}, {job.emirate}</div>
      <div className="t-line">{row.reason}</div>
    </>
  );
  return (
    <g className="marker" tabIndex={0} role="button" aria-label={`${lost ? "Lost" : "Declined"} order ${row.order_id}, requested ${clock(row.slot)}`}
       onClick={() => onSelect(row.order_id)} onKeyDown={(e) => e.key === "Enter" && onSelect(row.order_id)}
       onPointerMove={(e) => { e.stopPropagation(); showTip(e, content); }} onPointerLeave={hide}
       onFocus={(e) => focusTip(e.currentTarget, content)} onBlur={hide}>
      <circle cx={cx} cy={cy} r={14} fill="transparent" />
      {lost ? (
        <circle className="marker-lost" cx={cx} cy={cy} r={6} stroke="var(--surface)" strokeWidth={2} />
      ) : (
        <rect className="marker-declined" x={cx - 6} y={cy - 6} width={12} height={12} rx={2}
              transform={`rotate(45 ${cx} ${cy})`} stroke="var(--surface)" strokeWidth={2} />
      )}
      {selected && <circle cx={cx} cy={cy} r={11} fill="none" stroke="var(--text)" strokeWidth={2} />}
    </g>
  );
}

function PairRow({ pair, y, x, day, tolerance, logById, selected, onSelect, showTip, focusTip, hide }: Common & {
  pair: PairDay; y: number; x: (m: number) => number; day: DayData; tolerance: number;
  logById: Map<string, LogRow>; selected: string | null;
}) {
  const cy = y + ROW_H / 2;
  const shiftX = x(pair.shift_start);
  const shiftW = x(pair.shift_end) - shiftX;
  const order: Record<Block["kind"], number> = { standby: 0, drive: 1, visit: 2, office: 2, lab: 2 };
  const blocks = [...pair.blocks].sort((a, b) => order[a.kind] - order[b.kind] || a.start - b.start);

  return (
    <g>
      <text className="row-label" x={8} y={y + 20}>{pair.id}{pair.iv_certified ? " · IV nurse" : ""}</text>
      <text className="row-sub" x={8} y={y + 35}>{pair.nurse} · {pair.driver}</text>
      <text className="row-sub" x={8} y={y + 49}>{pair.visits} visit{pair.visits === 1 ? "" : "s"} · {Math.round(pair.km)} km</text>
      <rect className="shift" x={shiftX} y={y + 6} width={shiftW} height={ROW_H - 12} rx={6}>
        <title>{`Shift ${clock(pair.shift_start)}–${clock(pair.shift_end)}`}</title>
      </rect>
      {blocks.map((b, i) => {
        const bx = x(b.start);
        const bw = Math.max(2, x(b.end) - bx);
        const mins = b.end - b.start;
        const job = b.job_id ? day.jobs[b.job_id] : undefined;
        const row = b.job_id ? logById.get(b.job_id) : undefined;
        const common = {
          onPointerMove: (e: React.PointerEvent) => { e.stopPropagation(); showTip(e, blockTip(b, mins, pair, day, tolerance, row)); },
          onPointerLeave: hide,
        };
        const hit = <rect x={bx - 1} y={cy - 16} width={Math.max(bw, 10) + 2} height={32} fill="transparent" />;

        if (b.kind === "drive") {
          return (
            <g key={i} {...common}>
              <rect className="blk-drive" x={bx} y={cy - 3} width={bw} height={6} rx={3} />
              {bw >= 36 && <text className="drive-km" x={bx + bw / 2} y={cy - 8} textAnchor="middle">{Math.round(b.km)} km</text>}
              {hit}
            </g>
          );
        }
        if (b.kind === "standby") {
          const label = fit([b.note, b.note.split(" ")[0]], bw);
          return (
            <g key={i} {...common}>
              <rect className="blk-standby" x={bx + 0.5} y={cy - 7} width={Math.max(1, bw - 1)} height={14} rx={3} />
              {label && <text className="blk-note" x={bx + bw / 2} y={cy + 4} textAnchor="middle">{label}</text>}
              {hit}
            </g>
          );
        }
        const isVisit = b.kind === "visit" && job !== undefined;
        const cls = isVisit ? `blk-${job!.category}` : b.kind === "lab" ? "blk-lab" : "blk-office";
        const textCls = b.kind === "lab" ? "blk-text on-lab" : b.kind === "office" ? "blk-text on-office" : "blk-text";
        const label = isVisit
          ? fit([`${shortService(job!)} · ${clock(b.start)}`, shortService(job!), clock(b.start)], bw)
          : fit([b.kind === "lab" ? `lab ${b.lab_id ?? ""}`.trim() : "kits", b.kind === "lab" ? "lab" : "kits"], bw);
        const isSelected = isVisit && selected === b.job_id;
        const aria = isVisit ? `${job!.service}, ${clock(b.start)} to ${clock(b.end)}, order ${b.job_id}` : undefined;
        return (
          <g key={i} className="blk" {...common}
             {...(isVisit ? {
               tabIndex: 0, role: "button", "aria-label": aria,
               onClick: () => onSelect(b.job_id!),
               onKeyDown: (e: React.KeyboardEvent) => e.key === "Enter" && onSelect(b.job_id!),
               onFocus: (e: React.FocusEvent<SVGGElement>) => focusTip(e.currentTarget, blockTip(b, mins, pair, day, tolerance, row)),
               onBlur: hide,
             } : {})}>
            <rect className={cls} x={bx} y={cy - 14} width={bw} height={28} rx={4} />
            {label && <text className={textCls} x={bx + 6} y={cy + 4}>{label}</text>}
            <rect className={`blk-ring${isSelected ? " selected" : ""}`} x={bx - 2} y={cy - 16} width={bw + 4} height={32} rx={6} />
            {hit}
          </g>
        );
      })}
    </g>
  );
}

function blockTip(b: Block, mins: number, pair: PairDay, day: DayData, tolerance: number, row?: LogRow): ReactNode {
  const range = `${clock(b.start)}–${clock(b.end)}`;
  const who = `${pair.id} · ${pair.nurse}, ${pair.driver}`;
  if (b.kind === "visit" && b.job_id) {
    const job = day.jobs[b.job_id];
    return (
      <>
        <div className="t-title">{job.service}</div>
        <div className="t-line"><b>{range}</b> · {mins} min including access</div>
        <div className="t-line">Requested {clock(job.slot)} ± {tolerance} min · {job.area}, {job.emirate}</div>
        <div className="t-line">{who}</div>
        {row && <div className="t-line">{MODE_LABEL[row.mode]}, decided {when(row.decided)}</div>}
        <div className="t-line">{b.job_id}</div>
      </>
    );
  }
  if (b.kind === "drive") {
    return (
      <>
        <div className="t-title">Driving</div>
        <div className="t-line"><b>{oneDecimal(b.km)} km</b> · {mins} min</div>
        <div className="t-line">{range} · {who}</div>
      </>
    );
  }
  if (b.kind === "standby") {
    return (
      <>
        <div className="t-title">Waiting ({b.note})</div>
        <div className="t-line"><b>{mins} min</b> · {range}</div>
        <div className="t-line">{who}</div>
      </>
    );
  }
  if (b.kind === "office") {
    return (
      <>
        <div className="t-title">Collecting IV kits at the office</div>
        <div className="t-line"><b>{mins} min</b> · {range}</div>
        <div className="t-line">{who}</div>
      </>
    );
  }
  return (
    <>
      <div className="t-title">Lab drop-off · {b.lab_id}</div>
      <div className="t-line"><b>{b.job_ids.length} sample{b.job_ids.length === 1 ? "" : "s"}</b> · {range}</div>
      <div className="t-line">{who}</div>
    </>
  );
}
