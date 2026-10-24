/* Pictures and visuals placed through the Watch tabs: platform glyphs, a strip of the latest posts and ads, a company
   cover made from its website picture, and the best post per company. All pictures are the copies saved on this
   computer; everything comes from one shared load of /watch/data. */
import { useEffect, useState } from "react";
import { request, watchClientId } from "../api";
import { safeUrl } from "../format";
import { count } from "./format";
import { imageUrl, Logo } from "./parts";
import type { Ad, CompanyData, Mention, Post } from "./types";
import { AdCard, FacebookPost, InstagramPost, LinkedInPost, SearchResult, type Who } from "./PlatformCard";
import "./visuals.css";

type Gallery = { client: string; companies: CompanyData[] };
const cache = new Map<string, Promise<Gallery>>();
const loadedAt = new Map<string, number>();

/** Every company's saved data, loaded once per client and shared by every visual on the page. */
export function useGallery(): CompanyData[] | null {
  const key = String(watchClientId() ?? "");
  const [data, setData] = useState<CompanyData[] | null>(null);
  useEffect(() => {
    let live = true;
    if (!cache.has(key) || Date.now() - (loadedAt.get(key) ?? 0) > 5 * 60000) {
      cache.set(key, request<Gallery>("/watch/data"));   // fresh pictures after a collection, at most every 5 minutes
      loadedAt.set(key, Date.now());
    }
    cache
      .get(key)!
      .then((g) => live && setData(g.companies))
      .catch(() => {
        cache.delete(key);
        if (live) setData([]);
      });
    return () => {
      live = false;
    };
  }, [key]);
  return data;
}

/** Forget the shared load, after a collection brings new pictures. */
export function refreshGallery() {
  cache.clear();
}

export type Platform = "instagram" | "facebook" | "linkedin" | "ads" | "page" | "web" | "news";

/** The platform's own mark in its colours, drawn small. */
export function PlatformGlyph({ kind, size = 18 }: { kind: Platform | string; size?: number }) {
  const s = { width: size, height: size };
  if (kind === "instagram")
    return (
      <svg viewBox="0 0 24 24" style={s} className="vz-glyph" aria-label="Instagram">
        <defs>
          <radialGradient id="vz-ig" cx="30%" cy="107%" r="150%">
            <stop offset="0" stopColor="#FDF497" />
            <stop offset=".1" stopColor="#FDF497" />
            <stop offset=".5" stopColor="#FD5949" />
            <stop offset=".68" stopColor="#D6249F" />
            <stop offset="1" stopColor="#285AEB" />
          </radialGradient>
        </defs>
        <rect width="24" height="24" rx="6" fill="url(#vz-ig)" />
        <rect x="5.5" y="5.5" width="13" height="13" rx="4" fill="none" stroke="#fff" strokeWidth="1.8" />
        <circle cx="12" cy="12" r="3.1" fill="none" stroke="#fff" strokeWidth="1.8" />
        <circle cx="16.1" cy="7.9" r="1" fill="#fff" />
      </svg>
    );
  if (kind === "facebook")
    return (
      <svg viewBox="0 0 24 24" style={s} className="vz-glyph" aria-label="Facebook">
        <circle cx="12" cy="12" r="12" fill="#0866FF" />
        <path d="M13.3 24v-8.4h2.8l.5-3.3h-3.3v-2.1c0-.9.4-1.8 1.9-1.8h1.5V5.6s-1.4-.2-2.7-.2c-2.7 0-4.5 1.6-4.5 4.6v2.3H6.6v3.3h2.9V24h3.8Z" fill="#fff" />
      </svg>
    );
  if (kind === "linkedin")
    return (
      <svg viewBox="0 0 24 24" style={s} className="vz-glyph" aria-label="LinkedIn">
        <rect width="24" height="24" rx="4" fill="#0A66C2" />
        <path d="M7.1 9.6v8.2H4.5V9.6h2.6ZM5.8 5.5a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3Zm3.6 4.1h2.5v1.1c.4-.7 1.3-1.3 2.6-1.3 2.7 0 3.2 1.8 3.2 4.1v4.3h-2.6v-3.8c0-.9 0-2.1-1.3-2.1s-1.5 1-1.5 2v3.9H9.4V9.6Z" fill="#fff" />
      </svg>
    );
  if (kind === "ads")
    return (
      <svg viewBox="0 0 24 24" style={s} className="vz-glyph" aria-label="Meta ad">
        <rect width="24" height="24" rx="6" fill="#1C2B33" />
        <path d="M5 15.5c0-3.6 1.6-7 3.6-7 1.6 0 2.6 1.6 3.4 3 .8-1.4 1.9-3 3.4-3 2 0 3.6 3.4 3.6 7 0 1.3-.6 2-1.5 2-1.6 0-2.8-2.6-5.5-7.2-2.7 4.6-3.9 7.2-5.5 7.2-.9 0-1.5-.7-1.5-2Z" fill="none" stroke="#0A7CFF" strokeWidth="1.7" strokeLinejoin="round" />
      </svg>
    );
  if (kind === "news")
    return (
      <svg viewBox="0 0 24 24" style={s} className="vz-glyph" aria-label="News">
        <rect width="24" height="24" rx="6" fill="#F1F3F4" />
        <path d="M6 7h9v10H7a1 1 0 0 1-1-1V7Zm9 3h3v6a1 1 0 0 1-1 1h-2M8 9.5h5M8 12h5M8 14.5h3" fill="none" stroke="#1A73E8" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  return (
    <svg viewBox="0 0 24 24" style={s} className="vz-glyph" aria-label="Website">
      <rect width="24" height="24" rx="6" fill="#E8EDF7" />
      <circle cx="12" cy="12" r="6.5" fill="none" stroke="#3B5BDB" strokeWidth="1.5" />
      <path d="M5.5 12h13M12 5.5c2 1.8 2 11.2 0 13M12 5.5c-2 1.8-2 11.2 0 13" fill="none" stroke="#3B5BDB" strokeWidth="1.3" />
    </svg>
  );
}

export interface Shot {
  key: string;
  company: CompanyData;
  kind: Platform;
  picture: string;
  text: string;
  date: string | null;
  link: string;
  score: number;
  live?: boolean;
  raw: Post | Ad;
}

const when = (v: string | null) => (v ? Date.parse(v.length === 10 ? v : v.replace(" ", "T")) || 0 : 0);
function age(v: string | null) {
  const t = when(v);
  if (!t) return "";
  const d = Math.round((Date.now() - t) / 86400000);
  return d < 1 ? "today" : d < 7 ? `${d}d ago` : d < 60 ? `${Math.round(d / 7)}w ago` : new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Every post and ad that has a picture, newest first. */
export function shotsOf(companies: CompanyData[]): Shot[] {
  const out: Shot[] = [];
  for (const c of companies) {
    for (const kind of ["instagram", "facebook", "linkedin"] as const) {
      for (const p of c.social[kind]?.posts ?? []) {
        const pic = (p.images ?? []).map((u) => safeUrl(u)).find(Boolean);
        if (pic) out.push({ key: `${c.key}-${kind}-${p.id}`, company: c, kind, picture: pic, text: p.caption, date: p.date, link: p.url, score: p.engagement_total ?? 0, raw: p });
      }
    }
    if (!c.ads?.unchecked)
      for (const a of c.ads?.items ?? []) {
        const pic = a.images.map((u) => safeUrl(u)).find(Boolean);
        if (pic) out.push({ key: `${c.key}-ad-${a.id}`, company: c, kind: "ads", picture: pic, text: a.headline || a.body, date: a.start, link: a.url, score: a.active ? 1000 : 0, live: a.active, raw: a });
      }
  }
  return out.sort((a, b) => when(b.date) - when(a.date));
}

/** One scraped post, ad or mention drawn in its own platform's look. */
export function PlatformItem({ kind, raw, who }: { kind: Platform | string; raw: Post | Ad | Mention; who: Who }) {
  if (kind === "instagram") return <InstagramPost post={raw as Post} who={who} />;
  if (kind === "facebook") return <FacebookPost post={raw as Post} who={who} />;
  if (kind === "linkedin") return <LinkedInPost post={raw as Post} who={who} />;
  if (kind === "ads") return <AdCard ad={raw as Ad} who={who} />;
  return <SearchResult m={raw as Mention} />;
}

/** One post or ad as it looked on its platform, with the company and age underneath. */
export function ShotCard({ s, big = false }: { s: Shot; big?: boolean }) {
  const who: Who = { name: s.company.you ? s.company.name : s.company.name, logo: s.company.key };
  return (
    <div className={"vz-pf" + (big ? " big" : "") + (s.live ? " live" : "")}>
      <PlatformItem kind={s.kind} raw={s.raw} who={who} />
      <span className="vz-pf-under">
        <PlatformGlyph kind={s.kind} size={14} />
        <b>{s.company.you ? "You" : s.company.name}</b>
        <small>{age(s.date)}</small>
        {s.kind !== "ads" && s.score ? <small className="vz-shot-score">♥ {count(s.score)}</small> : null}
      </span>
    </div>
  );
}

/** A sideways strip of the newest posts and ads with pictures. */
export function FieldStrip({ title, sub, filter = () => true, limit = 14, empty }: { title: string; sub?: string; filter?: (c: CompanyData) => boolean; limit?: number; empty?: string }) {
  const companies = useGallery();
  if (!companies) return null;
  const shots = shotsOf(companies.filter(filter)).slice(0, limit);
  if (!shots.length && !empty) return null;
  return (
    <section className="vz-strip" aria-label={title}>
      <div className="vz-strip-head">
        <span>
          <b>{title}</b>
          {sub ? <small>{sub}</small> : null}
        </span>
        <span className="vz-strip-marks">
          {(["instagram", "facebook", "linkedin", "ads"] as const)
            .filter((k) => shots.some((s) => s.kind === k))
            .map((k) => (
              <PlatformGlyph key={k} kind={k} size={16} />
            ))}
        </span>
      </div>
      {shots.length ? (
        <div className="vz-strip-row">
          {shots.map((s) => (
            <ShotCard key={s.key} s={s} />
          ))}
        </div>
      ) : (
        <p className="vz-empty">{empty}</p>
      )}
    </section>
  );
}

/** The best post of each company, side by side. */
export function BestPosts({ title = "Best post per company", sub }: { title?: string; sub?: string }) {
  const companies = useGallery();
  if (!companies) return null;
  const best = companies
    .map((c) => shotsOf([c]).filter((s) => s.kind !== "ads").sort((a, b) => b.score - a.score)[0])
    .filter(Boolean) as Shot[];
  if (!best.length) return null;
  return (
    <section className="vz-best" aria-label={title}>
      <div className="vz-strip-head">
        <span>
          <b>{title}</b>
          {sub ? <small>{sub}</small> : null}
        </span>
      </div>
      <div className="vz-best-row">
        {best.map((s) => (
          <ShotCard key={s.key} s={s} big />
        ))}
      </div>
    </section>
  );
}

/** A company's cover: its website picture as the banner, its browser-tab icon, name and audience. */
export function Cover({ companyKey, children }: { companyKey: string; children?: React.ReactNode }) {
  const companies = useGallery();
  const c = companies?.find((x) => x.key === companyKey);
  if (!c) return null;
  const home = c.pages.find((p) => p.page_kind === "homepage") ?? c.pages[0];
  const banner = (home?.images ?? c.images.filter((i) => i.source === "page" && !i.logo).map((i) => i.url)).map((u) => safeUrl(u)).find(Boolean);
  const followers = (["instagram", "facebook", "linkedin"] as const)
    .map((k) => [k, c.social[k]?.them?.followers] as const)
    .filter(([, n]) => n !== null && n !== undefined);
  const shots = shotsOf([c]).slice(0, 4);
  return (
    <section className={"vz-cover" + (banner ? " pic" : "")}>
      <span className="vz-cover-bg" style={banner ? { backgroundImage: `url("${imageUrl(banner)}")` } : undefined} />
      <div className="vz-cover-body">
        <Logo id={c.key} name={c.name} size={64} />
        <div className="vz-cover-text">
          <b>{c.name}</b>
          {home?.fields.headline ? <span dir="auto">{home.fields.headline}</span> : null}
          {followers.length ? (
            <span className="vz-cover-stats">
              {followers.map(([k, n]) => (
                <span key={k}>
                  <PlatformGlyph kind={k} size={16} /> {count(n)}
                </span>
              ))}
            </span>
          ) : null}
        </div>
        {children}
      </div>
      {shots.length ? (
        <div className="vz-cover-shots">
          {shots.map((s) => (
            <a key={s.key} href={safeUrl(s.link) ?? undefined} target="_blank" rel="noopener noreferrer nofollow" title={s.text.slice(0, 120)}>
              <img src={imageUrl(s.picture)} alt="" loading="lazy" onError={(e) => (e.currentTarget.style.visibility = "hidden")} />
              <PlatformGlyph kind={s.kind} size={14} />
            </a>
          ))}
        </div>
      ) : null}
    </section>
  );
}

/** Four small pictures of one company, for a card. */
export function Thumbs({ companyKey, limit = 4 }: { companyKey: string; limit?: number }) {
  const companies = useGallery();
  const c = companies?.find((x) => x.key === companyKey);
  if (!c) return null;
  const shots = shotsOf([c]).slice(0, limit);
  if (!shots.length) return null;
  return (
    <span className="vz-thumbs">
      {shots.map((s) => (
        <a key={s.key} href={safeUrl(s.link) ?? undefined} target="_blank" rel="noopener noreferrer nofollow" title={s.text.slice(0, 120)}>
          <img src={imageUrl(s.picture)} alt="" loading="lazy" onError={(e) => (e.currentTarget.style.visibility = "hidden")} />
          <PlatformGlyph kind={s.kind} size={13} />
        </a>
      ))}
    </span>
  );
}
