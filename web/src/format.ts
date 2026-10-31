import type { Category, Job } from "./api";

const DAY = 24 * 60;

/** Minutes after midnight of the service day as HH:MM (wrapping past midnight). */
export function clock(minutes: number): string {
  const tod = ((minutes % DAY) + DAY) % DAY;
  return `${String(Math.floor(tod / 60)).padStart(2, "0")}:${String(tod % 60).padStart(2, "0")}`;
}

/** Like clock(), with a day offset for other days: "09:49 −2d". */
export function when(minutes: number): string {
  const d = Math.floor(minutes / DAY);
  return d === 0 ? clock(minutes) : `${clock(minutes)} ${d < 0 ? "−" : "+"}${Math.abs(d)}d`;
}

export const CATEGORY_LABEL: Record<Category, string> = { sample: "Sample collection", iv: "IV therapy", injection: "Injection" };

/** "Blood draw - routine panel (CBC)" -> "routine panel (CBC)"; "IV - hydration drip" -> "hydration drip". */
export function shortService(job: Job): string {
  const i = job.service.indexOf(" - ");
  return i >= 0 ? job.service.slice(i + 3) : job.service;
}

export const pct = (x: number): string => `${Math.round(x * 100)}%`;
export const oneDecimal = (x: number): string => x.toFixed(1);

export const MODE_LABEL: Record<string, string> = {
  auto: "Tool, automatic",
  manual: "Ops, with slots shown",
  excel: "Ops, by hand",
};

export const FINAL_LABEL: Record<string, string> = {
  served: "Served",
  cancelled: "Cancelled, plan freed",
  late_cancellation: "Late cancellation, visit made",
  not_served: "Not served",
  bumped: "Released to make room",
};
