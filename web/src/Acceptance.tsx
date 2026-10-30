import { useMemo, useState } from "react";
import type { Compare, DayData, Meta, Outcome, Overrides, Policy } from "./api";
import { OutcomeChip } from "./components";
import { FINAL_LABEL, MODE_LABEL, pct, shortService, when } from "./format";
import { OrderDetail } from "./OrderDetail";

const LABEL: Record<Policy, string> = { excel: "Excel era", lv1: "Logistics Valeo v1" };

interface Props {
  day: DayData;
  compare: Compare | null;
  meta: Meta;
  overrides: Overrides;
  setOverrides: (o: Overrides) => void;
  error: string | null;
  selected: string | null;
  onSelect: (id: string) => void;
  onShowOnDay: () => void;
  loading: boolean;
}

export function Acceptance(p: Props) {
  const { day, compare, meta } = p;
  const lead = p.overrides.auto_accept_lead_h ?? meta.settings.auto_accept_lead_h;
  const changed = Object.keys(p.overrides).length > 0;
  return (
    <>
      <div className="card">
        <h2>Acceptance rules</h2>
        <p className="hint">Change a rule and every figure on this page is replayed.</p>
        <div className="rules-grid">
          <div className="setting">
            <label htmlFor="lead">Accept by itself from {lead} h of notice</label>
            <input id="lead" className="range" type="range" min={0} max={48} step={1} value={lead}
                   onChange={(e) => p.setOverrides({ ...p.overrides, auto_accept_lead_h: Number(e.target.value) })} />
            <p className="hint">Notice not counting quiet hours. Shorter notice goes to ops with the open slots shown. Applies to {LABEL.lv1}.</p>
          </div>
          <TextSetting id="quiet" label="Quiet hours" value={p.overrides.quiet_hours ?? meta.settings.quiet_hours}
                       hint="Overnight hours that don't count as time for ops to react. May run past midnight."
                       onCommit={(v) => p.setOverrides({ ...p.overrides, quiet_hours: v })} />
          <TextSetting id="office" label="Office hours" value={p.overrides.office_hours ?? meta.settings.office_hours}
                       hint="When ops are at their desks. Orders published outside them wait for the morning."
                       onCommit={(v) => p.setOverrides({ ...p.overrides, office_hours: v })} />
        </div>
        {p.error && <p className="error">{p.error}</p>}
        <div className="rules-foot">
          <span className="hint" style={{ margin: 0 }}>
            Ops take {meta.settings.excel_response_min[0]}–{meta.settings.excel_response_min[1]} min to decide in the Excel era and{" "}
            {meta.settings.manual_response_min[0]}–{meta.settings.manual_response_min[1]} min with the tool. Arrival must be within ±{" "}
            {meta.settings.arrival_tolerance_min} min of the requested time.
          </span>
          <button className="icon-btn" disabled={!changed} onClick={() => p.setOverrides({})}>Reset to defaults</button>
        </div>
      </div>

      <div className={`card${p.loading ? " loading" : ""}`} style={{ marginTop: 16 }}>
        <h2>What happened to the day's orders</h2>
        <p className="hint">{day.weekday} {day.date} · {day.kpis.offered} orders published for this day.</p>
        {compare && (["excel", "lv1"] as Policy[]).map((id) => <OutcomeBar key={id} policy={id} compare={compare} />)}
        <div className="legend" style={{ marginTop: 4, marginBottom: 0 }}>
          {(["accepted", "lost", "declined", "cancelled_before_decision"] as Outcome[]).map((o) => <OutcomeChip key={o} outcome={o} />)}
        </div>
      </div>

      {p.selected && (
        <OrderDetail day={day} orderId={p.selected} tolerance={meta.settings.arrival_tolerance_min}
          action={{ label: "Show on the day view", run: p.onShowOnDay }} />
      )}

      <DecisionLog day={day} selected={p.selected} onSelect={p.onSelect} loading={p.loading} />
    </>
  );
}

function TextSetting({ id, label, value, hint, onCommit }: {
  id: string; label: string; value: string; hint: string; onCommit: (v: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  if (draft !== value && document.activeElement?.id !== id) setDraft(value);
  const commit = () => draft !== value && onCommit(draft.trim());
  return (
    <div className="setting">
      <label htmlFor={id}>{label}</label>
      <input id={id} type="text" value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={commit}
             onKeyDown={(e) => e.key === "Enter" && commit()} inputMode="text" spellCheck={false} />
      <p className="hint">{hint}</p>
    </div>
  );
}

function OutcomeBar({ policy, compare }: { policy: Policy; compare: Compare }) {
  const k = compare.kpis[policy];
  const parts: { cls: string; n: number; label: string }[] = [
    { cls: "seg-accepted", n: k.accepted, label: "accepted" },
    { cls: "seg-lost", n: k.lost, label: "lost to a competitor" },
    { cls: "seg-declined", n: k.declined, label: "declined" },
    { cls: "seg-cancelled", n: k.cancelled_before_decision, label: "cancelled before anyone decided" },
  ];
  return (
    <div style={{ marginBottom: 14 }}>
      <div className="stack-title"><span>{LABEL[policy]}</span><span>{pct(k.capture_rate)} captured</span></div>
      <div className="stack" role="img" aria-label={`${LABEL[policy]}: ${parts.map((x) => `${x.n} ${x.label}`).join(", ")}`}>
        {parts.filter((x) => x.n > 0).map((x) => (
          <div key={x.cls} className={x.cls} style={{ flex: x.n }} title={`${x.n} ${x.label}`}>
            {x.n / k.offered >= 0.07 ? x.n : ""}
          </div>
        ))}
      </div>
    </div>
  );
}

function DecisionLog({ day, selected, onSelect, loading }: {
  day: DayData; selected: string | null; onSelect: (id: string) => void; loading: boolean;
}) {
  const [outcome, setOutcome] = useState<"all" | Outcome>("all");
  const [text, setText] = useState("");
  const rows = useMemo(() => {
    const needle = text.trim().toLowerCase();
    return day.log.filter((r) => {
      if (outcome !== "all" && r.outcome !== outcome) return false;
      if (!needle) return true;
      const job = day.jobs[r.order_id];
      return [r.order_id, r.reason, job.service, job.area, job.emirate].some((s) => s.toLowerCase().includes(needle));
    });
  }, [day, outcome, text]);

  return (
    <div className={`card${loading ? " loading" : ""}`} style={{ marginTop: 16 }}>
      <h2>Decision log</h2>
      <p className="hint">One row per order, in the order it was decided. This is also the table view of the day.</p>
      <div className="table-tools">
        <div className="field">
          <label htmlFor="outcome">Outcome</label>
          <select id="outcome" value={outcome} onChange={(e) => setOutcome(e.target.value as "all" | Outcome)}>
            <option value="all">All ({day.log.length})</option>
            <option value="accepted">Accepted</option>
            <option value="lost">Lost to a competitor</option>
            <option value="declined">Declined</option>
            <option value="cancelled_before_decision">Cancelled first</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="find">Find</label>
          <input id="find" type="text" placeholder="order, service, area, reason" value={text} onChange={(e) => setText(e.target.value)} />
        </div>
        <span className="hint" style={{ margin: 0 }}>{rows.length} shown</span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Order</th><th>Service</th><th>Area</th>
              <th className="num">Published</th><th className="num">Decided</th><th className="num">Requested</th>
              <th>Decided by</th><th>Outcome</th><th>Pair</th><th>Result</th><th>Why</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const job = day.jobs[r.order_id];
              return (
                <tr key={r.order_id} className={`row${selected === r.order_id ? " selected" : ""}`} tabIndex={0}
                    onClick={() => onSelect(r.order_id)} onKeyDown={(e) => e.key === "Enter" && onSelect(r.order_id)}
                    aria-selected={selected === r.order_id}>
                  <td>{r.order_id}</td>
                  <td>{shortService(job)}</td>
                  <td>{job.area}</td>
                  <td className="num">{when(r.published)}</td>
                  <td className="num">{when(r.decided)}</td>
                  <td className="num">{when(r.slot)}</td>
                  <td>{MODE_LABEL[r.mode]}</td>
                  <td><OutcomeChip outcome={r.outcome} /></td>
                  <td>{r.pair_id ?? "–"}</td>
                  <td>{FINAL_LABEL[r.final]}</td>
                  <td className="why">{r.reason}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && <div className="empty">No orders match.</div>}
      </div>
    </div>
  );
}
