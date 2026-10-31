import type { Compare, DayData, Policy } from "./api";
import { oneDecimal, pct } from "./format";

// Each policy is compared with the one before it: v1 with the Excel era, v2 with v1.
const OTHER: Record<Policy, Policy> = { excel: "lv1", lv1: "excel", lv2: "lv1" };
const NAME: Record<Policy, string> = { excel: "Excel era", lv1: "Logistics Valeo v1", lv2: "v2" };

export function Kpis({ day, compare, loading }: { day: DayData; compare: Compare | null; loading: boolean }) {
  const k = day.kpis;
  const other = compare ? compare.kpis[OTHER[day.policy]] : null;
  const gap = other ? Math.round((k.capture_rate - other.capture_rate) * 100) : null;
  return (
    <section className={`kpis${loading ? " loading" : ""}`} aria-label="Key figures for this day, synthetic data">
      <div className="tile hero">
        <div className="label">Orders captured</div>
        <div className="value">{pct(k.capture_rate)}</div>
        <div className="note">
          {k.accepted} of {k.capturable} orders the fleet could win
          {gap !== null && gap !== 0 && (
            <>
              {" · "}
              <span className={`delta ${gap > 0 ? "up" : "down"}`}>
                {gap > 0 ? "+" : "−"}
                {Math.abs(gap)} pts
              </span>{" "}
              vs {NAME[OTHER[day.policy]]}
            </>
          )}
        </div>
      </div>
      <Tile label="Lost to a competitor" value={String(k.lost)} note={other ? `${NAME[OTHER[day.policy]]}: ${other.lost}` : ""} />
      <Tile label="Declined, no room" value={String(k.declined)} note={other ? `${NAME[OTHER[day.policy]]}: ${other.declined}` : ""} />
      <Tile label="Visits made" value={String(k.visits)}
            note={day.policy === "lv2" ? `${k.moved} moved, ${k.bumped} swapped out to make room` : `${k.late_cancellations} late cancellations`} />
      <Tile label="km per visit" value={oneDecimal(k.km_per_visit)} note={`${Math.round(k.km)} km in total`} />
      <Tile label="Idle pair-hours" value={String(Math.round(k.idle_h))} note={`${oneDecimal(k.visit_h)} h with patients`} />
    </section>
  );
}

function Tile({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      <div className="note">{note || " "}</div>
    </div>
  );
}
