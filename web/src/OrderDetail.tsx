import type { DayData } from "./api";
import { OutcomeChip } from "./components";
import { CATEGORY_LABEL, FINAL_LABEL, MODE_LABEL, clock, when } from "./format";

export function OrderDetail({ day, orderId, tolerance, action }: {
  day: DayData; orderId: string; tolerance: number; action?: { label: string; run: () => void };
}) {
  const job = day.jobs[orderId];
  const row = day.log.find((r) => r.order_id === orderId);
  if (!job || !row) return null;
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>{job.service}</h2>
      <p className="hint" style={{ margin: 0 }}>
        {orderId} · {CATEGORY_LABEL[job.category]}
        {action && <> · <button className="link-btn" onClick={action.run}>{action.label}</button></>}
      </p>
      <dl className="detail">
        <div><dt>Where</dt><dd>{job.area}, {job.emirate}</dd></div>
        <div><dt>Requested</dt><dd>{clock(job.slot)} ± {tolerance} min</dd></div>
        <div><dt>Published</dt><dd>{when(row.published)}</dd></div>
        <div><dt>Decided</dt><dd>{when(row.decided)} · {MODE_LABEL[row.mode]}</dd></div>
        <div><dt>Outcome</dt><dd><OutcomeChip outcome={row.outcome} /></dd></div>
        <div><dt>Result</dt><dd>{FINAL_LABEL[row.final]}{row.pair_id ? ` · ${row.pair_id}` : ""}</dd></div>
        <div><dt>Lab</dt><dd>{job.lab_id ?? "Not needed"}</dd></div>
        <div><dt>IV kits</dt><dd>{job.needs_kits ? "Collected from the office after publishing" : "Not needed, or prepared in advance"}</dd></div>
        <div className="why"><dt>Why</dt><dd>{row.reason}</dd></div>
      </dl>
    </div>
  );
}
