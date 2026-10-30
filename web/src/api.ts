import { useEffect, useRef, useState } from "react";

export type Policy = "excel" | "lv1";
export type Category = "sample" | "iv" | "injection";
export type Outcome = "accepted" | "declined" | "lost" | "cancelled_before_decision";

export interface Meta {
  synthetic: boolean;
  dates: { date: string; weekday: string; orders: number }[];
  policies: { id: Policy; label: string }[];
  window: { start: number; end: number };
  settings: {
    auto_accept_lead_h: number;
    office_hours: string;
    quiet_hours: string;
    arrival_tolerance_min: number;
    excel_response_min: [number, number];
    manual_response_min: [number, number];
  };
  office: { lat: number; lon: number; name: string };
  labs: { id: string; name: string; lat: number; lon: number }[];
}

export interface Block {
  kind: "drive" | "visit" | "office" | "lab" | "standby";
  start: number;
  end: number;
  km: number;
  loc: [number, number];
  job_id: string | null;
  lab_id: string | null;
  job_ids: string[];
  note: string;
}

export interface PairDay {
  id: string;
  nurse: string;
  driver: string;
  car_id: string;
  iv_certified: boolean;
  shift_start: number;
  shift_end: number;
  km: number;
  visits: number;
  blocks: Block[];
}

export interface Job {
  service: string;
  category: Category;
  area: string;
  emirate: string;
  slot: number;
  published: number;
  lab_id: string | null;
  needs_kits: boolean;
  duration: number;
  patient: string;
}

export interface LogRow {
  order_id: string;
  published: number;
  decided: number;
  slot: number;
  mode: "auto" | "manual" | "excel";
  outcome: Outcome;
  reason: string;
  pair_id: string | null;
  final: "served" | "cancelled" | "late_cancellation" | "not_served";
}

export interface Kpis {
  offered: number;
  capturable: number;
  accepted: number;
  lost: number;
  declined: number;
  cancelled_before_decision: number;
  honored_cancellations: number;
  late_cancellations: number;
  visits: number;
  capture_rate: number;
  km: number;
  km_per_visit: number;
  visit_h: number;
  drive_h: number;
  idle_h: number;
}

export interface DayData {
  synthetic: boolean;
  date: string;
  weekday: string;
  policy: Policy;
  policy_label: string;
  window: { start: number; end: number };
  pairs: PairDay[];
  jobs: Record<string, Job>;
  log: LogRow[];
  kpis: Kpis;
  violations: number;
}

export interface Compare {
  kpis: Record<Policy, Kpis>;
}

export interface Overrides {
  auto_accept_lead_h?: number;
  office_hours?: string;
  quiet_hours?: string;
}

export function query(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") q.set(k, String(v));
  return q.toString();
}

export interface Fetched<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/** Fetches `url`; keeps the previous data on screen while the next request is in flight. */
export function useFetch<T>(url: string | null): Fetched<T> {
  const [state, setState] = useState<Fetched<T>>({ data: null, loading: url !== null, error: null });
  const latest = useRef(0);
  useEffect(() => {
    if (url === null) return;
    const id = ++latest.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    fetch(url)
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          const detail = Array.isArray(body.detail) ? body.detail.map((d: { message: string }) => d.message).join("; ") : body.detail;
          throw new Error(detail || `${r.status} ${r.statusText}`);
        }
        return r.json() as Promise<T>;
      })
      .then((data) => id === latest.current && setState({ data, loading: false, error: null }))
      .catch((e: Error) => id === latest.current && setState((s) => ({ data: s.data, loading: false, error: e.message })));
  }, [url]);
  return state;
}
