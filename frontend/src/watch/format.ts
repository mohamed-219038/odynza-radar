/* Display helpers for the Watch section. */
import type { User } from "../types";
import type { Progress, Source, Tier } from "./types";

export const TIER_LABEL: Record<Tier, string> = {
  direct: "Direct",
  adjacent: "Adjacent",
  aspirational: "Aspirational",
  emerging: "Emerging",
};

export const TIER_HELP: Record<Tier, string> = {
  direct: "Same offer, same buyers. Pages checked daily.",
  adjacent: "Overlapping offer or buyers. Every 3½ days.",
  aspirational: "Bigger players you learn from. Weekly.",
  emerging: "New or small. Homepage and Instagram, weekly.",
};

export const SCORE_LABEL: Record<number, string> = {
  5: "Act this week",
  4: "Plan a response this month",
  3: "Worth knowing",
  2: "Note it",
  1: "Archive",
};

export const KIND_LABEL: Record<Source["kind"], string> = {
  page: "Website",
  instagram: "Instagram",
  facebook: "Facebook",
  linkedin: "LinkedIn",
  ads: "Meta ads",
  web: "Web & news",
};

/** Who may do what (mirrors the watch router's reader / watcher / staff rules). */
export function rights(role: User["role"]) {
  return { decide: ["admin", "member", "client"].includes(role), staff: ["admin", "member"].includes(role) };
}

export function when(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) || /^\d{4}-\d\d-\d\d$/.test(value) ? value : value + "Z");
  return Number.isNaN(d.valueOf()) ? null : d;
}

/** "2h ago", "3d ago"; future times read "in 4h". */
export function ago(value: string | null | undefined, now = Date.now()): string {
  const d = when(value);
  if (!d) return "never";
  const diff = Math.round((now - d.valueOf()) / 60000);
  const abs = Math.abs(diff);
  const text = abs < 1 ? "now" : abs < 60 ? `${abs}m` : abs < 1440 ? `${Math.round(abs / 60)}h` : `${Math.round(abs / 1440)}d`;
  if (text === "now") return "just now";
  return diff >= 0 ? `${text} ago` : `in ${text}`;
}

export function stamp(value: string | null | undefined): string {
  const d = when(value);
  return d ? d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
}

export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v.toFixed(v < 10 ? 2 : 1)}%`);
export const count = (v: number | null | undefined) => (v === null || v === undefined ? "—" : Number(v).toLocaleString());

export function shortUrl(url: string) {
  try {
    const u = new URL(url);
    return (u.hostname.replace(/^www\./, "") + u.pathname).replace(/\/$/, "");
  } catch {
    return url;
  }
}

/** A field change in words: "price:Business changed" → "Price · Business". */
export function fieldLabel(field: string) {
  const [head, ...rest] = field.split(":");
  const name = head.replace(/_/g, " ");
  return (name.charAt(0).toUpperCase() + name.slice(1)) + (rest.length ? ` · ${rest.join(":")}` : "");
}

/** CSV with quoted cells, so commas and quotes in captions stay in one cell. */
export function toCsv(rows: (string | number | null | undefined)[][]) {
  return rows.map((r) => r.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
}

export const splitList = (text: string) =>
  text
    .split(/[,\n]/)
    .map((x) => x.trim())
    .filter(Boolean);

/** Client logos as read from alt texts: drop "Logo for", people photos and the company's own badges. */
export function cleanLogos(list: string[], ownName = ""): string[] {
  const own = ownName.toLowerCase().trim();
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of list) {
    if (/^(photo|picture|image|headshot|portrait) of\b/i.test(raw.trim())) continue;
    const name = raw
      .replace(/^(the\s+)?(logo|icon)\s+(for|of)\s+/i, "")
      .replace(/\s+(brand\s+)?(logo|icon)\b.*$/i, "")
      .replace(/\s+/g, " ")
      .trim();
    const key = name.toLowerCase();
    if (!name || name.length > 40 || (own && key.includes(own)) || /^(home|logo|menu)$/i.test(name) || seen.has(key)) continue;
    seen.add(key);
    out.push(name);
  }
  return out;
}

/** A plan read without its name comes back as "price 2". */
export const planName = (name: string) => (/^price \d+$/i.test(name) ? "Unnamed plan" : name);

export type StepKey = "setup" | "competitors" | "collect" | "signals" | "brief";
export interface Step {
  key: StepKey;
  title: string;
  done: boolean;
  hint: string;
}

/** The five steps of Watch, in order. Each one opens when the one before it is done. */
export function watchSteps(hasClient: boolean, p?: Progress): Step[] {
  const q = p ?? { confirmed: 0, captures: 0, collections: 0, running: null, scoring: 0, changes: 0, signals: 0, briefs: 0, opportunities: 0 };
  return [
    { key: "setup", title: "Your profile", done: hasClient, hint: "Save your website and social accounts." },
    { key: "competitors", title: "Pick competitors", done: q.confirmed > 0, hint: "Find or add rivals, then confirm at least one." },
    { key: "collect", title: "First collection", done: q.captures > 0, hint: "Collect once. This first run records a starting point." },
    { key: "signals", title: "First changes", done: q.signals > 0, hint: "Collect again later. n8n scores what changed." },
    { key: "brief", title: "Weekly brief", done: q.briefs > 0, hint: "Make the first brief and its opportunities." },
  ];
}

export type TabKey = "overview" | "competitors" | "compare" | "ads" | "brief" | "opportunities" | "data" | "sources" | "setup";

/** Which step must be done before each tab opens (null: always open). */
export const TAB_NEEDS: Record<TabKey, StepKey | null> = {
  setup: null,
  competitors: "setup",
  sources: "competitors",
  overview: "collect",
  compare: "collect",
  ads: "collect",
  brief: "collect",
  opportunities: "brief",
  data: "collect",
};

export function tabOpen(tab: TabKey, steps: Step[]): boolean {
  const need = TAB_NEEDS[tab];
  return need === null || Boolean(steps.find((s) => s.key === need)?.done);
}
