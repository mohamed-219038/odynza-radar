/* Scraped posts laid out the way each platform shows a profile: a header with the account's numbers, then a grid
   of tiles (Instagram's 4:5 grid, Facebook's and LinkedIn's square photo grid, the Ad Library's ad tiles, a browser
   thumbnail for site pages). Hover shows the counts, a click opens the post in its real look with arrows to move on. */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Dialog } from "../components/Dialog";
import { count, KIND_LABEL, pct } from "./format";
import { imageUrl, Logo } from "./parts";
import { isShot, own, picturesOf } from "./PlatformCard";
import { PlatformGlyph } from "./Visuals";
import type { Ad, Post } from "./types";
import type { Item } from "./ScrapedData";
import "./feedgrid.css";

export interface Profile {
  name: string;
  logo: string | number;
  url?: string;
  followers?: number | null;
  engagement_rate?: number | null;
  posts_per_week?: number | null;
  bio?: string | null;
}

const SOCIAL = new Set(["instagram", "facebook", "linkedin"]);
const SOURCE_NAME: Record<string, string> = { ...KIND_LABEL, page: "Website", ads: "Meta ads", web: "News & web", jobs: "Jobs" };
const src = (u: string) => (own(u) ? u : imageUrl(u));
const host = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
};
const handleOf = (p: Profile) => {
  const path = p.url ? (() => { try { return new URL(p.url).pathname.split("/").filter(Boolean).pop() ?? ""; } catch { return ""; } })() : "";
  return (path && !/^profile\.php$/i.test(path) ? path : p.name.toLowerCase().replace(/[^a-z0-9._]+/g, "")) || "account";
};
const shortDate = (v: string | null) => {
  if (!v) return "";
  const d = new Date(v.length === 10 ? v + "T00:00:00" : v.replace(" ", "T"));
  return Number.isNaN(d.valueOf()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

/** What a tile says on hover: likes and comments for posts, run dates for ads, the site for pages. */
function numbers(i: Item): { icon: string; value: string; label: string }[] {
  if (SOCIAL.has(i.source)) {
    const p = i.raw as Post;
    return [
      { icon: "♥", value: count(p.likes), label: "likes" },
      { icon: "💬", value: count(p.comments), label: "comments" },
      ...(p.shares ? [{ icon: "↗", value: count(p.shares), label: "shares" }] : []),
      ...(p.views ? [{ icon: "▶", value: count(p.views), label: "views" }] : []),
    ];
  }
  if (i.source === "ads") {
    const a = i.raw as Ad;
    return [{ icon: a.active ? "●" : "○", value: a.active ? "Live" : "Ended", label: a.start ? `since ${shortDate(a.start)}` : "" }];
  }
  return [{ icon: "⌁", value: host(i.url) || SOURCE_NAME[i.source], label: "" }];
}

function isVideo(i: Item) {
  const f = SOCIAL.has(i.source) ? (i.raw as Post).format : i.source === "ads" ? (i.raw as Ad).format ?? "" : "";
  return /reel|video/i.test(f || "");
}

/** One tile: the first picture, or the words of the post on the platform's colour when it has no picture. */
function Tile({ item, top, share, onOpen }: { item: Item; top: boolean; share: number; onOpen: () => void }) {
  const pics = picturesOf(item.images);
  const [broken, setBroken] = useState(false);
  const pic = !broken ? pics[0] : undefined;
  const words = (item.source === "ads" ? (item.raw as Ad).body || item.title : item.text || item.title).trim();
  return (
    <button type="button" className={`fg-tile fg-${item.source}${pic ? "" : " words"}${item.live ? " live" : ""}`} onClick={onOpen} aria-label={`Open ${SOURCE_NAME[item.source]} item: ${item.title}`}>
      {pic ? (
        <img src={src(pic)} alt="" loading="lazy" className={isShot(pic) ? "shot" : undefined} onError={() => setBroken(true)} />
      ) : (
        <span className="fg-words" dir="auto">
          {words.slice(0, 180)}
          {words.length > 180 ? "…" : ""}
        </span>
      )}
      {item.source === "page" ? <span className="fg-chrome" aria-hidden="true"><i /><i /><i /><b>{host(item.url)}</b></span> : null}
      <span className="fg-corner" aria-hidden="true">
        {isVideo(item) ? <span title="Video">▶</span> : null}
        {pics.length > 1 ? <span title={`${pics.length} pictures`}>❐ {pics.length}</span> : null}
        {item.source === "ads" ? <span className="fg-sponsored">{item.live ? "Live ad" : "Ad"}</span> : null}
      </span>
      {top ? <span className="fg-top">★ Top</span> : null}
      <span className="fg-hover" aria-hidden="true">
        {numbers(item).map((n) => (
          <span key={n.icon + n.label}>
            <b>
              {n.icon} {n.value}
            </b>
            {n.label ? <small>{n.label}</small> : null}
          </span>
        ))}
        <em>{shortDate(item.date)}</em>
      </span>
      {share > 0 ? <span className="fg-heat" style={{ width: `${Math.max(6, share * 100)}%` }} aria-hidden="true" /> : null}
    </button>
  );
}

/** The account header above a platform grid, the way the platform shows it on a profile page. */
function ProfileHead({ p, kind, shown, avg }: { p: Profile; kind: string; shown: number; avg: number }) {
  return (
    <header className={`fg-profile fg-${kind}`}>
      <span className="fg-ring">
        <Logo id={p.logo} name={p.name} size={kind === "instagram" ? 76 : 60} />
      </span>
      <div className="fg-profile-main">
        <div className="fg-profile-name">
          <b>{kind === "instagram" ? handleOf(p) : p.name}</b>
          <PlatformGlyph kind={kind} size={18} />
          {p.url ? (
            <a className="fg-follow" href={p.url} target="_blank" rel="noopener noreferrer">
              Open on {KIND_LABEL[kind as keyof typeof KIND_LABEL] ?? kind} ↗
            </a>
          ) : null}
        </div>
        <ul className="fg-profile-stats">
          <li>
            <b>{shown}</b> saved posts
          </li>
          {p.followers ? (
            <li>
              <b>{count(p.followers)}</b> followers
            </li>
          ) : null}
          {p.engagement_rate ? (
            <li>
              <b>{pct(p.engagement_rate)}</b> engagement
            </li>
          ) : null}
          {avg ? (
            <li>
              <b>{count(Math.round(avg))}</b> reactions a post
            </li>
          ) : null}
          {p.posts_per_week ? (
            <li>
              <b>{Math.round(p.posts_per_week * 10) / 10}</b> posts a week
            </li>
          ) : null}
        </ul>
        {kind === "instagram" ? <span className="fg-profile-real">{p.name}</span> : null}
        {p.bio ? (
          <p className="fg-bio" dir="auto">
            {p.bio}
          </p>
        ) : null}
      </div>
    </header>
  );
}

interface Group {
  key: string;
  kind: string;
  profile: Profile | null;
  items: Item[];
}

/** The grid itself. Social posts are grouped per account with a profile header; other items share one grid. */
export function FeedGrid({ items, profileOf, renderCard }: { items: Item[]; profileOf?: (i: Item) => Profile | null; renderCard: (i: Item) => ReactNode }) {
  const [open, setOpen] = useState<number | null>(null);
  const groups = useMemo(() => {
    const out: Group[] = [];
    const byKey = new Map<string, Group>();
    for (const i of items) {
      const social = SOCIAL.has(i.source);
      const key = social ? `${i.who?.name ?? ""}|${i.source}` : "rest";
      let g = byKey.get(key);
      if (!g) {
        g = { key, kind: social ? i.source : "rest", profile: social && profileOf ? profileOf(i) : null, items: [] };
        byKey.set(key, g);
        out.push(g);
      }
      g.items.push(i);
    }
    return out.sort((a, b) => Number(a.kind === "rest") - Number(b.kind === "rest"));
  }, [items, profileOf]);
  // The viewer walks the tiles in the order they are drawn.
  const order = useMemo(() => groups.flatMap((g) => g.items), [groups]);
  const current = open === null ? null : order[open];

  // Each account's usual engagement, so the viewer can say whether a post did better or worse than usual.
  const usual = useMemo(() => {
    const m = new Map<string, number>();
    for (const g of groups) {
      const r = g.items.map((i) => i.rank).filter((n) => n > 0);
      m.set(g.key, r.length ? r.reduce((a, b) => a + b, 0) / r.length : 0);
    }
    return m;
  }, [groups]);
  const groupOf = (i: Item) => groups.find((g) => g.items.includes(i))!;

  const best = [...order].filter((i) => SOCIAL.has(i.source) && i.rank > 0).sort((a, b) => b.rank - a.rank)[0];
  const days = order.map((i) => (i.date && SOCIAL.has(i.source) ? new Date(i.date.length === 10 ? i.date + "T00:00:00" : i.date.replace(" ", "T")).getDay() : -1)).filter((d) => d >= 0);
  const busiest = days.length ? [0, 1, 2, 3, 4, 5, 6].sort((a, b) => days.filter((d) => d === b).length - days.filter((d) => d === a).length)[0] : -1;

  return (
    <div className="fg">
      {best || busiest >= 0 ? (
        <div className="fg-ribbon" aria-label="At a glance">
          <div className="fg-chips">
            {busiest >= 0 ? (
              <span className="fg-chip">
                📅 Most posts on <b>{new Date(2026, 0, 4 + busiest).toLocaleDateString(undefined, { weekday: "long" })}</b>
              </span>
            ) : null}
          </div>
          {best ? (
            <button type="button" className="fg-best" onClick={() => setOpen(order.indexOf(best))}>
              {picturesOf(best.images)[0] ? <img src={src(picturesOf(best.images)[0])} alt="" /> : <span className="fg-best-dot">★</span>}
              <span>
                <small>Best post here</small>
                <b>
                  {best.who?.name} · {count(best.rank)} reactions
                </b>
              </span>
              <em>Open ›</em>
            </button>
          ) : null}
        </div>
      ) : null}
      {groups.map((g) => {
        const max = Math.max(0, ...g.items.map((i) => i.rank));
        const tops = new Set(
          g.kind === "rest" || g.items.length < 4
            ? []
            : [...g.items].sort((a, b) => b.rank - a.rank).slice(0, Math.max(1, Math.round(g.items.length / 9))).filter((i) => i.rank > 0).map((i) => i.key),
        );
        return (
          <section key={g.key} className={`fg-group fg-${g.kind}`} aria-label={g.profile ? `${g.profile.name} on ${KIND_LABEL[g.kind as keyof typeof KIND_LABEL]}` : "Pages, ads and news"}>
            {g.profile ? <ProfileHead p={g.profile} kind={g.kind} shown={g.items.length} avg={usual.get(g.key) ?? 0} /> : null}
            {g.profile ? (
              <div className="fg-tabs" aria-hidden="true">
                <span className="on">▦ Posts</span>
                {g.items.some(isVideo) ? <span>▶ Reels</span> : null}
              </div>
            ) : null}
            <div className="fg-grid">
              {g.items.map((i) => (
                <Tile key={i.key} item={i} top={tops.has(i.key)} share={max && SOCIAL.has(i.source) ? i.rank / max : 0} onOpen={() => setOpen(order.indexOf(i))} />
              ))}
            </div>
          </section>
        );
      })}
      <Viewer
        item={current}
        at={open ?? 0}
        total={order.length}
        usual={current ? usual.get(groupOf(current).key) ?? 0 : 0}
        onMove={(n) => setOpen((o) => (o === null ? o : Math.min(order.length - 1, Math.max(0, o + n))))}
        onClose={() => setOpen(null)}
        renderCard={renderCard}
      />
    </div>
  );
}

/** The post in its real platform look, with the numbers beside it, the arrows to move on and its pictures to save. */
function Viewer({ item, at, total, usual, onMove, onClose, renderCard }: { item: Item | null; at: number; total: number; usual: number; onMove: (n: number) => void; onClose: () => void; renderCard: (i: Item) => ReactNode }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!item) return;
    setCopied(false);
    const key = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (e.key === "ArrowRight") onMove(1);
      if (e.key === "ArrowLeft") onMove(-1);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [item, onMove]);
  const pics = item ? picturesOf(item.images) : [];
  const times = item && usual > 0 && item.rank > 0 && SOCIAL.has(item.source) ? item.rank / usual : 0;
  async function copy() {
    if (!item) return;
    try {
      await navigator.clipboard.writeText(item.source === "ads" ? (item.raw as Ad).body : item.text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  return (
    <Dialog id="fg-viewer" className="fg-viewer" open={!!item} onClose={onClose} labelledBy="fg-viewer-title">
      {item ? (
        <div className="fg-view">
          <button type="button" className="fg-arrow prev" aria-label="Previous item" disabled={at === 0} onClick={() => onMove(-1)}>
            ‹
          </button>
          <div className="fg-view-card">{renderCard(item)}</div>
          <aside className="fg-side">
            <div className="fg-side-top">
              <span className="fg-side-who">
                {item.who ? <Logo id={item.who.logo} name={item.who.name} size={34} /> : null}
                <span>
                  <b id="fg-viewer-title">{item.who?.name ?? item.title}</b>
                  <small>
                    <PlatformGlyph kind={item.source === "web" ? "news" : item.source} size={14} /> {SOURCE_NAME[item.source]} · {shortDate(item.date) || "no date"}
                  </small>
                </span>
              </span>
              <button type="button" className="fg-close" aria-label="Close" onClick={onClose}>
                ×
              </button>
            </div>
            <ul className="fg-side-stats">
              {numbers(item).map((n) => (
                <li key={n.icon + n.label}>
                  <b>{n.value}</b>
                  <small>{n.label || n.icon}</small>
                </li>
              ))}
            </ul>
            {times ? (
              <p className={"fg-vs " + (times >= 1.1 ? "up" : times <= 0.9 ? "down" : "even")}>
                {times >= 1.1 ? `${Math.round(times * 10) / 10}× their usual engagement` : times <= 0.9 ? `${Math.round((1 - times) * 100)}% below their usual engagement` : "About their usual engagement"}
                <span className="fg-vs-bar">
                  <i style={{ width: `${Math.min(100, times * 50)}%` }} />
                </span>
              </p>
            ) : null}
            {pics.length ? (
              <div className="fg-side-pics">
                <small>
                  {pics.length} picture{pics.length === 1 ? "" : "s"} saved on your computer
                </small>
                <div>
                  {pics.slice(0, 8).map((u, n) => (
                    <a key={u} href={own(u) ? u : imageUrl(u, true)} download title={`Download picture ${n + 1}`}>
                      <img src={src(u)} alt="" loading="lazy" />
                      <span>↓</span>
                    </a>
                  ))}
                </div>
              </div>
            ) : null}
            <div className="fg-side-actions">
              {item.url ? (
                <a className="button primary small-button" href={item.url} target="_blank" rel="noopener noreferrer">
                  Open original ↗
                </a>
              ) : null}
              {item.text || item.source === "ads" ? (
                <button type="button" className="button secondary small-button" onClick={copy}>
                  {copied ? "Copied ✓" : "Copy text"}
                </button>
              ) : null}
            </div>
            <p className="fg-side-foot">
              {at + 1} of {total} · use ← → to move
            </p>
          </aside>
          <button type="button" className="fg-arrow next" aria-label="Next item" disabled={at >= total - 1} onClick={() => onMove(1)}>
            ›
          </button>
        </div>
      ) : null}
    </Dialog>
  );
}

/** Grid or the full cards, remembered in this browser. */
export function useLayout(): ["grid" | "feed", (v: "grid" | "feed") => void] {
  const [v, setV] = useState<"grid" | "feed">(() => {
    try {
      return localStorage.getItem("watch-layout") === "feed" ? "feed" : "grid";
    } catch {
      return "grid";
    }
  });
  return [
    v,
    (n) => {
      setV(n);
      try {
        localStorage.setItem("watch-layout", n);
      } catch {
        /* private window: the choice lasts for this visit */
      }
    },
  ];
}

export function LayoutSwitch({ value, onChange }: { value: "grid" | "feed"; onChange: (v: "grid" | "feed") => void }) {
  return (
    <div className="fg-switch" role="group" aria-label="Layout">
      <button type="button" aria-pressed={value === "grid"} className={value === "grid" ? "on" : ""} onClick={() => onChange("grid")}>
        ▦ Grid
      </button>
      <button type="button" aria-pressed={value === "feed"} className={value === "feed" ? "on" : ""} onClick={() => onChange("feed")}>
        ☰ Feed
      </button>
    </div>
  );
}
