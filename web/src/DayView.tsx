import type { DayData } from "./api";
import { OrderDetail } from "./OrderDetail";
import { Timeline } from "./Timeline";

function Key({ children, shape }: { children: string; shape: React.ReactNode }) {
  return <span>{shape}{children}</span>;
}

const box = (fill: string, extra: React.CSSProperties = {}) => (
  <i style={{ background: fill, ...extra }} />
);

export function DayView({ day, tolerance, selected, onSelect, onShowInLog, loading }: {
  day: DayData; tolerance: number; selected: string | null; onSelect: (id: string) => void;
  onShowInLog: () => void; loading: boolean;
}) {
  return (
    <>
      <div className={`card${loading ? " loading" : ""}`}>
        <h2>{day.weekday} {day.date} · {day.policy_label} · {day.roster_label} roster</h2>
        <p className="hint">
          One row per nurse and driver pair. Shaded bars are the shift; hover anything for details, click a visit to inspect the order.
        </p>
        <div className="legend" aria-label="Legend">
          <Key shape={box("var(--sample)")}>Sample collection</Key>
          <Key shape={box("var(--iv)")}>IV therapy</Key>
          <Key shape={box("var(--injection)")}>Injection</Key>
          <Key shape={box("var(--muted)", { height: 6, opacity: 0.55, borderRadius: 3, marginTop: 3 })}>Driving</Key>
          <Key shape={box("transparent", { border: "1px solid var(--axis)", height: 10, marginTop: 1 })}>Waiting</Key>
          <Key shape={box("var(--neutral-mid)")}>Collecting IV kits</Key>
          <Key shape={box("var(--neutral-strong)")}>Lab drop-off</Key>
          <Key shape={box("var(--critical)", { borderRadius: 6 })}>Lost to a competitor</Key>
          <Key shape={box("var(--serious)", { transform: "rotate(45deg) scale(0.8)", borderRadius: 2 })}>Declined</Key>
        </div>
        <Timeline day={day} tolerance={tolerance} selected={selected} onSelect={onSelect} />
        {day.violations > 0 && (
          <p className="error">The independent validator found {day.violations} rule violation(s) in this plan.</p>
        )}
      </div>
      {selected && (
        <OrderDetail day={day} orderId={selected} tolerance={tolerance}
          action={{ label: "Show in the decision log", run: onShowInLog }} />
      )}
    </>
  );
}
