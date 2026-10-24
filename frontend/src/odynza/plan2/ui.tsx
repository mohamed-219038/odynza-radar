/* Small pieces shared by the Radar plan and batch pages. */
import type { ReactNode } from "react";
import type { RadarEvent } from "./types";

export function money(v: number | null | undefined, currency = "") {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${Math.round(v).toLocaleString()}${currency ? " " + currency : ""}`;
}

export function fmtDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" }) {
  if (!iso) return "";
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  return Number.isNaN(d.valueOf()) ? iso : d.toLocaleDateString(undefined, opts);
}

export const pct = (v: number | null | undefined, digits = 0) => (v === null || v === undefined ? "—" : `${v.toFixed(digits)}%`);

export const KIND_LABEL: Record<string, string> = {
  campaign: "Our campaign", content: "Content", milestone: "Milestone", shopping: "Shopping", tech: "Tech event",
  holiday: "Holiday", season: "Season",
};

export function EventChip({ e }: { e: RadarEvent }) {
  return (
    <span className={"p2-ev k-" + e.kind} title={e.confirmed ? undefined : "Date to confirm"}>
      <b>{fmtDate(e.date)}{e.end_date && e.end_date !== e.date ? `–${fmtDate(e.end_date)}` : ""}</b> {e.title}
      {e.confirmed ? null : <em aria-label="date to confirm">*</em>}
    </span>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: [T, string][]; value: T; onChange: (t: T) => void; label: string }) {
  return (
    <div className="p2-tabs" role="tablist" aria-label={label}>
      {tabs.map(([key, name]) => (
        <button key={key} role="tab" aria-selected={value === key} className={"p2-tab" + (value === key ? " on" : "")} onClick={() => onChange(key)}>
          {name}
        </button>
      ))}
    </div>
  );
}

export function Tile({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "good" | "bad" | "accent" }) {
  return (
    <div className={"p2-tile" + (tone ? " " + tone : "")}>
      <small>{label}</small>
      <b>{value}</b>
      {sub ? <span>{sub}</span> : null}
    </div>
  );
}

export function Card({ title, kicker, children, className = "" }: { title?: ReactNode; kicker?: string; children: ReactNode; className?: string }) {
  return (
    <section className={"p2-card " + className}>
      {kicker ? <span className="p2-kicker">{kicker}</span> : null}
      {title ? <h3>{title}</h3> : null}
      {children}
    </section>
  );
}

export function List({ items, empty = "None" }: { items: ReactNode[]; empty?: string }) {
  const rows = items.filter(Boolean);
  if (!rows.length) return <p className="p2-fine">{empty}</p>;
  return <ul className="p2-list">{rows.map((x, i) => <li key={i}>{x}</li>)}</ul>;
}

export function Bar({ value, max = 100, tone }: { value: number; max?: number; tone?: string }) {
  return (
    <span className={"p2-bar" + (tone ? " " + tone : "")} aria-hidden="true">
      <i style={{ width: `${Math.max(0, Math.min(100, (value / (max || 1)) * 100))}%` }} />
    </span>
  );
}
