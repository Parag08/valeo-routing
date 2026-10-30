import { useEffect, useMemo, useState } from "react";
import { query, useFetch } from "./api";
import type { Compare, DayData, Meta, Overrides, Policy } from "./api";
import { Acceptance } from "./Acceptance";
import { DayView } from "./DayView";
import { Kpis } from "./Kpis";

type Tab = "day" | "acceptance";
type Theme = "light" | "dark" | null;

function initial(): { date: string | null; policy: Policy; tab: Tab } {
  const q = new URLSearchParams(window.location.search);
  return {
    date: q.get("date"),
    policy: q.get("policy") === "excel" ? "excel" : "lv1",
    tab: q.get("tab") === "acceptance" ? "acceptance" : "day",
  };
}

function readTheme(): Theme {
  try {
    const t = window.localStorage.getItem("theme");
    return t === "light" || t === "dark" ? t : null;
  } catch {
    return null;
  }
}

export default function App() {
  const start = useMemo(initial, []);
  const meta = useFetch<Meta>("/api/meta");
  const [date, setDate] = useState<string | null>(start.date);
  const [policy, setPolicy] = useState<Policy>(start.policy);
  const [tab, setTab] = useState<Tab>(start.tab);
  const [overrides, setOverrides] = useState<Overrides>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    try {
      if (theme) window.localStorage.setItem("theme", theme);
    } catch {
      /* storage can be blocked; the theme still applies for this visit */
    }
  }, [theme]);

  const dates = meta.data?.dates ?? [];
  const current = date && dates.some((d) => d.date === date) ? date : dates[0]?.date ?? null;
  useEffect(() => {
    if (current) window.history.replaceState(null, "", `?${query({ date: current, policy, tab })}`);
  }, [current, policy, tab]);

  const q = query({ date: current ?? undefined, ...overrides });
  const day = useFetch<DayData>(current ? `/api/day?${q}&policy=${policy}` : null);
  const compare = useFetch<Compare>(current ? `/api/compare?${q}` : null);

  const index = dates.findIndex((d) => d.date === current);
  const move = (by: number) => {
    const next = dates[index + by];
    if (next) {
      setDate(next.date);
      setSelected(null);
    }
  };

  const m = meta.data;
  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <h1>Logistics Valeo</h1>
          <span className="sub">a rebuild of a field-visit dispatch tool</span>
          <span className="badge" title="Every number on these screens comes from a seeded synthetic month, not from real operations.">
            Synthetic data
          </span>
        </div>
        <button className="icon-btn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                aria-label="Switch between light and dark">
          {theme === "dark" ? "Light" : "Dark"}
        </button>
      </header>

      {meta.error && <p className="error">Could not reach the API: {meta.error}</p>}
      {m && current && (
        <>
          <div className="controls">
            <div className="field">
              <button className="step" onClick={() => move(-1)} disabled={index <= 0} aria-label="Previous day">‹</button>
              <label htmlFor="date" className="sr" style={{ position: "absolute", left: -9999 }}>Day</label>
              <select id="date" value={current} onChange={(e) => { setDate(e.target.value); setSelected(null); }}>
                {dates.map((d) => (
                  <option key={d.date} value={d.date}>{d.weekday} {d.date} · {d.orders} orders</option>
                ))}
              </select>
              <button className="step" onClick={() => move(1)} disabled={index >= dates.length - 1} aria-label="Next day">›</button>
            </div>
            <div className="seg" role="group" aria-label="Acceptance policy">
              {m.policies.map((p) => (
                <button key={p.id} aria-pressed={policy === p.id} onClick={() => setPolicy(p.id)}>{p.label}</button>
              ))}
            </div>
          </div>

          {day.data && <Kpis day={day.data} compare={compare.data} loading={day.loading || compare.loading} />}

          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={tab === "day"} onClick={() => setTab("day")}>Day view</button>
            <button role="tab" aria-selected={tab === "acceptance"} onClick={() => setTab("acceptance")}>Acceptance engine</button>
            <span className="soon">Roster · Services · Metrics · Hubs · Capacity: coming</span>
          </div>

          {day.error && tab === "day" && <p className="error">{day.error}</p>}
          {day.data && tab === "day" && (
            <DayView day={day.data} tolerance={m.settings.arrival_tolerance_min} selected={selected}
                     onSelect={setSelected} onShowInLog={() => setTab("acceptance")} loading={day.loading} />
          )}
          {day.data && tab === "acceptance" && (
            <Acceptance day={day.data} compare={compare.data} meta={m} overrides={overrides} setOverrides={setOverrides}
                        error={day.error} selected={selected} onSelect={setSelected}
                        onShowOnDay={() => setTab("day")} loading={day.loading || compare.loading} />
          )}
          {!day.data && day.loading && <p className="hint">Planning the day…</p>}
        </>
      )}

      <p className="footer">
        Everything here runs on a seeded synthetic month of orders, staff and cars across Dubai and the northern emirates.
        The figures are not Valeo's: the real project's measured results are described in the case study.
      </p>
    </div>
  );
}
