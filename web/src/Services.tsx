import { useState } from "react";
import { useFetch } from "./api";
import type { Category, ServiceEdit, ServiceRow, ServicesData } from "./api";
import { CATEGORY_LABEL, pct } from "./format";

interface Props {
  qs: string;
  setEdit: (id: string, edit: ServiceEdit | null) => void;
  resetAll: () => void;
}

export function Services({ qs, setEdit, resetAll }: Props) {
  const r = useFetch<ServicesData>(`/api/services?${qs}`);
  const [problem, setProblem] = useState<string | null>(null);
  const data = r.data;
  if (!data) return <div className="card">{r.error ? <p className="error">{r.error}</p> : <p className="hint">Loading the catalog…</p>}</div>;

  const edited = data.services.filter((s) => s.edited).length;
  const commit = (s: ServiceRow, next: { lo?: number; hi?: number; limit?: number | null }) => {
    const lo = next.lo ?? s.duration_lo;
    const hi = next.hi ?? s.duration_hi;
    const limit = next.limit !== undefined ? next.limit : s.sample_max_min;
    if (lo < 1 || hi < lo || hi > data.limits.max_duration_min) {
      setProblem(`${s.name}: minutes on site must run from at least 1 up to ${data.limits.max_duration_min}, and the maximum can't be below the minimum.`);
      return;
    }
    if (limit !== null && (limit < 15 || limit > data.limits.max_sample_limit_min)) {
      setProblem(`${s.name}: the time to reach the lab must be between 15 and ${data.limits.max_sample_limit_min} minutes.`);
      return;
    }
    setProblem(null);
    const same = lo === s.default_lo && hi === s.default_hi && limit === s.default_sample_max_min;
    setEdit(s.id, same ? null : { lo, hi, limit });
  };

  const groups = (["sample", "iv", "injection"] as Category[]).map((c) => ({ c, rows: data.services.filter((s) => s.category === c) }));
  return (
    <div className={`card${r.loading ? " loading" : ""}`}>
      <div className="card-head">
        <div>
          <h2>Services</h2>
          <p className="hint">
            How long each kind of appointment takes on site. The plan reserves {pct(data.plan_duration_position)} of the way from the minimum to the
            maximum, plus a few minutes to reach the door. Change a time and the day view, the roster's demand estimate and the lab deadlines all follow.
          </p>
        </div>
        <button className="icon-btn" disabled={edited === 0} onClick={() => { setProblem(null); resetAll(); }}>Reset to defaults</button>
      </div>
      {(problem || r.error) && <p className="error">{problem ?? r.error}</p>}
      <div className="table-scroll" style={{ maxHeight: "none" }}>
        <table>
          <thead>
            <tr>
              <th>Service</th><th className="num">Minimum (min)</th><th className="num">Maximum (min)</th><th className="num">Planned (min)</th>
              <th className="num">Lab within (min)</th><th>IV kit stop</th><th>IV nurse only</th><th className="num">Share of orders</th>
            </tr>
          </thead>
          <tbody>
            {groups.map(({ c, rows }) => (
              <GroupRows key={c} category={c} rows={rows} commit={commit} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint" style={{ marginTop: 12, marginBottom: 0 }}>
        The kit stop and nurse certification are fixed by the catalog. Lab services show how long a sample may wait before it reaches a lab.
      </p>
    </div>
  );
}

function GroupRows({ category, rows, commit }: {
  category: Category; rows: ServiceRow[]; commit: (s: ServiceRow, n: { lo?: number; hi?: number; limit?: number | null }) => void;
}) {
  return (
    <>
      <tr className="group"><td colSpan={8}>{CATEGORY_LABEL[category]} · {pct(rows.reduce((a, s) => a + s.mix_share, 0))} of orders</td></tr>
      {rows.map((s) => (
        <tr key={s.id} className={s.edited ? "edited" : ""}>
          <td>{s.name}{s.edited && <span className="tag">edited</span>}</td>
          <td className="num"><NumInput label={`${s.name} minimum`} value={s.duration_lo} onCommit={(v) => commit(s, { lo: v })} /></td>
          <td className="num"><NumInput label={`${s.name} maximum`} value={s.duration_hi} onCommit={(v) => commit(s, { hi: v })} /></td>
          <td className="num">{s.planned_min}</td>
          <td className="num">
            {s.needs_lab && s.sample_max_min !== null
              ? <NumInput label={`${s.name} time to reach the lab`} value={s.sample_max_min} onCommit={(v) => commit(s, { limit: v })} />
              : <span style={{ color: "var(--muted)" }}>no lab</span>}
          </td>
          <td>{s.needs_office_supplies ? "From the office unless prepared" : "None"}</td>
          <td>{s.iv_certified_only ? "Yes" : "No"}</td>
          <td className="num">{pct(s.mix_share)}</td>
        </tr>
      ))}
    </>
  );
}

function NumInput({ value, label, onCommit }: { value: number; label: string; onCommit: (v: number) => void }) {
  const [draft, setDraft] = useState(String(value));
  const [focused, setFocused] = useState(false);
  if (!focused && draft !== String(value)) setDraft(String(value));
  const commit = () => {
    const n = Number(draft);
    if (Number.isInteger(n) && n !== value) onCommit(n);
    else if (!Number.isInteger(n)) setDraft(String(value));
  };
  return (
    <input className="num-input" type="text" inputMode="numeric" aria-label={label} value={draft}
           onFocus={() => setFocused(true)} onChange={(e) => setDraft(e.target.value)}
           onBlur={() => { setFocused(false); commit(); }} onKeyDown={(e) => e.key === "Enter" && commit()} />
  );
}
