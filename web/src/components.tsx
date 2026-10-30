import type React from "react";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Outcome } from "./api";

/** Status marks always pair an icon with a label, so colour never carries the meaning alone. */
export function OutcomeChip({ outcome }: { outcome: Outcome }) {
  const spec = {
    accepted: { label: "Accepted", color: "var(--good)", glyph: <path d="M3 8.5l3.2 3L13 4.5" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /> },
    lost: { label: "Lost to competitor", color: "var(--critical)", glyph: <path d="M4 4l8 8M12 4l-8 8" fill="none" strokeWidth="2" strokeLinecap="round" /> },
    declined: { label: "Declined", color: "var(--serious)", glyph: <path d="M8 3.5v5.5M8 12.2v.3" fill="none" strokeWidth="2" strokeLinecap="round" /> },
    cancelled_before_decision: { label: "Cancelled first", color: "var(--muted)", glyph: <path d="M3.5 8h9" fill="none" strokeWidth="2" strokeLinecap="round" /> },
  }[outcome];
  return (
    <span className="chip">
      <svg width="14" height="14" viewBox="0 0 16 16" stroke={spec.color} aria-hidden="true">{spec.glyph}</svg>
      {spec.label}
    </span>
  );
}

export function LegendSwatch({ color, children }: { color: string; children: ReactNode }) {
  return (
    <span>
      <i style={{ background: color }} />
      {children}
    </span>
  );
}

export function Tooltip({ x, y, children }: { x: number; y: number; children: ReactNode }) {
  return (
    <div className="tooltip" role="tooltip" style={{ left: x, top: y }}>
      {children}
    </div>
  );
}

/** The width of a container, kept current as it resizes. */
export function useWidth(fallback: number): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    setWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

/** Whether the page is in dark mode, from the toggle or, when it is unset, the OS. */
export function useDark(): boolean {
  const read = () =>
    document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const [dark, setDark] = useState(read);
  useEffect(() => {
    const update = () => setDark(read());
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", update);
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      media.removeEventListener("change", update);
      observer.disconnect();
    };
  }, []);
  return dark;
}

/** A CSS custom property's current value, e.g. token("--accent"). */
export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
