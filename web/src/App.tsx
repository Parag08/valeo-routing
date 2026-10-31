import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { query, serviceTokens, useFetch } from "./api";
import type { Compare, DayData, Meta, Overrides, Policy, RosterMode, ServiceEdit } from "./api";
import { About } from "./About";
import { Acceptance } from "./Acceptance";
import { Capacity } from "./Capacity";
import { DayView } from "./DayView";
import { Kpis } from "./Kpis";
import { Metrics } from "./Metrics";
import { Roster } from "./Roster";
import { Services } from "./Services";

// The map library is large, so the Hub siting tab loads on first use.
const Hubs = lazy(() => import("./Hubs").then((m) => ({ default: m.Hubs })));

type Tab = "day" | "roster" | "services" | "acceptance" | "hubs" | "capacity" | "metrics";
const TABS: { id: Tab; label: string }[] = [
  { id: "day", label: "Day view" },
  { id: "roster", label: "Roster" },
  { id: "services", label: "Services" },
  { id: "acceptance", label: "Acceptance engine" },
  { id: "hubs", label: "Hub siting" },
  { id: "capacity", label: "Capacity" },
  { id: "metrics", label: "Metrics" },
];
type Theme = "light" | "dark" | null;

function initial(): { date: string | null; policy: Policy; tab: Tab; roster: RosterMode } {
  const q = new URLSearchParams(window.location.search);
  const tab = q.get("tab");
  return {
    date: q.get("date"),
    policy: q.get("policy") === "excel" ? "excel" : q.get("policy") === "lv2" ? "lv2" : "lv1",
    tab: TABS.some((t) => t.id === tab) ? (tab as Tab) : "day",
    roster: q.get("roster") === "simple" ? "simple" : "auto",
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
  const [roster, setRoster] = useState<RosterMode>(start.roster);
  const [tab, setTab] = useState<Tab>(start.tab);
  const [overrides, setOverrides] = useState<Overrides>({});
  const [unavailable, setUnavailable] = useState<string[]>([]);
  const [edits, setEdits] = useState<Record<string, ServiceEdit>>({});
  const [hubCount, setHubCount] = useState<number | null>(null); // null: the configured default
  const [selected, setSelected] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [about, setAbout] = useState(false);

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
    if (current) window.history.replaceState(null, "", `?${query({ date: current, policy, roster, tab })}`);
  }, [current, policy, roster, tab]);

  // Everything that changes a plan travels in the query string; the API keeps no state.
  const defaultHubs = meta.data?.settings.hub_count ?? 0;
  const hubs = hubCount ?? defaultHubs;
  const scenario = {
    roster,
    hubs: hubCount ?? undefined,
    unavailable: [...unavailable].sort().join(","),
    services: serviceTokens(edits),
    ...overrides,
  };
  const qs = query({ ...scenario, policy });
  const q = query({ date: current ?? undefined, ...scenario });
  const day = useFetch<DayData>(current ? `/api/day?${q}&policy=${policy}` : null);
  const compare = useFetch<Compare>(current ? `/api/compare?${q}` : null);

  const index = dates.findIndex((d) => d.date === current);
  const move = (by: number) => {
    const next = dates[index + by];
    if (next) {
      setDate(next.date);
      setSelected(null);
      setUnavailable([]); // sick marks belong to one day
    }
  };
  const toggleSick = (id: string) => setUnavailable((u) => (u.includes(id) ? u.filter((x) => x !== id) : [...u, id]));
  const setEdit = (id: string, edit: ServiceEdit | null) =>
    setEdits((e) => {
      const next = { ...e };
      if (edit) next[id] = edit;
      else delete next[id];
      return next;
    });

  const changes = [
    unavailable.length ? `${unavailable.length} marked sick` : "",
    Object.keys(edits).length ? `${Object.keys(edits).length} service${Object.keys(edits).length === 1 ? "" : "s"} edited` : "",
    Object.keys(overrides).length ? "acceptance rules changed" : "",
    hubCount !== null && hubCount !== defaultHubs ? (hubCount === 0 ? "no hubs" : `${hubCount} hub${hubCount === 1 ? "" : "s"}`) : "",
  ].filter(Boolean);

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
        <div className="header-actions">
          <button className="icon-btn" onClick={() => setAbout(true)}>About the real project</button>
          <button className="icon-btn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                  aria-label="Switch between light and dark">
            {theme === "dark" ? "Light" : "Dark"}
          </button>
        </div>
      </header>

      {meta.error && <p className="error">Could not reach the API: {meta.error}</p>}
      {m && current && (
        <>
          <div className="controls">
            <div className="field">
              <button className="step" onClick={() => move(-1)} disabled={index <= 0} aria-label="Previous day">‹</button>
              <label htmlFor="date" className="sr" style={{ position: "absolute", left: -9999 }}>Day</label>
              <select id="date" value={current} onChange={(e) => { setDate(e.target.value); setSelected(null); setUnavailable([]); }}>
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
            {changes.length > 0 && (
              <span className="scenario">
                Scenario: {changes.join(" · ")}{" "}
                <button className="link-btn" onClick={() => { setUnavailable([]); setEdits({}); setOverrides({}); setHubCount(null); }}>Clear all</button>
              </span>
            )}
          </div>

          {day.data && <Kpis day={day.data} compare={compare.data} loading={day.loading || compare.loading} />}

          <div className="tabs" role="tablist">
            {TABS.map((t) => (
              <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>{t.label}</button>
            ))}
          </div>

          {day.error && tab === "day" && <p className="error">{day.error}</p>}
          {day.data && tab === "day" && (
            <DayView day={day.data} tolerance={m.settings.arrival_tolerance_min} selected={selected}
                     onSelect={setSelected} onShowInLog={() => setTab("acceptance")} loading={day.loading} />
          )}
          {tab === "roster" && (
            <Roster qs={qs} date={current} mode={roster} setMode={setRoster} unavailable={unavailable} toggleSick={toggleSick} />
          )}
          {tab === "services" && (
            <Services qs={qs} setEdit={setEdit} resetAll={() => setEdits({})} />
          )}
          {tab === "hubs" && (
            <Suspense fallback={<p className="hint">Loading the map…</p>}>
              <Hubs qs={qs} date={current} meta={m} applied={hubs}
                    apply={(k) => { setHubCount(k === defaultHubs ? null : k); setPolicy("lv1"); setTab("day"); }} />
            </Suspense>
          )}
          {tab === "capacity" && (
            <Capacity qs={qs} date={current} setDate={(d) => { setDate(d); setSelected(null); setUnavailable([]); }} />
          )}
          {tab === "metrics" && (
            <Metrics qs={qs} date={current} setDate={(d) => { setDate(d); setSelected(null); setUnavailable([]); }} />
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
        The figures are not Valeo's: the real project's measured results are in{" "}
        <button className="link-btn" onClick={() => setAbout(true)}>About the real project</button>.
      </p>
      <About open={about} onClose={() => setAbout(false)} />
    </div>
  );
}
