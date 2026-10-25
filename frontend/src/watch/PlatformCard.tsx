/* Each scraped item drawn the way it looked where it was posted: an Instagram post, a Facebook post, a LinkedIn
   post, a Meta Ad Library card, the website in a browser window, or a search result for news and web mentions.
   Pictures come from the copies saved on this computer (imageUrl), never from the platform's own link. */
import { useState, type ReactNode } from "react";
import { safeUrl } from "../format";
import { count } from "./format";
import { imageUrl, Logo } from "./parts";
import type { Ad, Mention, PageCapture, Post, SitePicture } from "./types";
import "./platform.css";

export interface Who {
  name: string;
  logo: string | number;
}

const when = (v: string | null | undefined) => {
  if (!v) return null;
  const d = new Date(v.length === 10 ? v + "T00:00:00" : v.replace(" ", "T"));
  return Number.isNaN(d.valueOf()) ? null : d;
};
/** "3d", "5h" or "Oct 12", the way feeds show the age of a post. */
function age(v: string | null | undefined) {
  const d = when(v);
  if (!d) return "";
  const mins = Math.round((Date.now() - d.valueOf()) / 60000);
  if (mins < 60) return `${Math.max(mins, 1)}m`;
  if (mins < 1440) return `${Math.round(mins / 60)}h`;
  if (mins < 7 * 1440) return `${Math.round(mins / 1440)}d`;
  if (mins < 30 * 1440) return `${Math.round(mins / (7 * 1440))}w`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric" });
}
const longDate = (v: string | null | undefined) =>
  when(v)?.toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" }) ?? "";
const plural = (n: number | null, one: string, many: string) => `${count(n)} ${n === 1 ? one : many}`;
const handle = (name: string) => name.toLowerCase().replace(/[^a-z0-9._]+/g, "") || "account";
const host = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
};

/** Long text cut like the feeds do, with "more" to open it. */
function Caption({ text, limit, more = "more", lead }: { text: string; limit: number; more?: string; lead?: ReactNode }) {
  const [open, setOpen] = useState(false);
  if (!text && !lead) return null;
  const cut = !open && text.length > limit;
  return (
    <p className="pf-text" dir="auto">
      {lead}
      {cut ? text.slice(0, limit).trimEnd() + "… " : text}
      {cut ? (
        <button type="button" className="pf-more" onClick={() => setOpen(true)}>
          {more}
        </button>
      ) : null}
    </p>
  );
}

/** Pictures made or uploaded in this app (/content/..., /strategy/...) are shown from their own address. */
export const own = (u: string) => /^\/(content|strategy)\/[\w/?=.&-]+$/.test(u);

/** Links to a platform's own pages (a Facebook photo or reel page) are not pictures; older captures kept some. */
const PAGE_HOSTS = /^(www\.|web\.|m\.)?(facebook\.com|fb\.com|fb\.me|instagram\.com|linkedin\.com)$/i;
/** A full-page screenshot saved by the collector ("shot:<site>/<page>/<date>.jpg"), shown through imageUrl. */
export const isShot = (u: string) => /^shot:[a-z0-9-]+\/[a-z0-9-]+\/[\d_-]+\.jpg$/.test(u);
export function picturesOf(images: string[]) {
  return images
    .map((u) => (own(u) || isShot(u) ? u : safeUrl(u)))
    .filter((u): u is string => {
      if (!u) return false;
      if (isShot(u)) return true;
      try {
        return own(u) || !PAGE_HOSTS.test(new URL(u).hostname);
      } catch {
        return false;
      }
    });
}

/** Several pictures laid out the way Facebook and LinkedIn show them in the feed: one large, two side by side, one
    wide over two, or four with "+N" on the last. One picture keeps its own shape. */
function Grid({ images, reel }: { images: string[]; reel?: boolean }) {
  const [gone, setGone] = useState<Record<string, boolean>>({});
  const pics = picturesOf(images).filter((u) => !gone[u]);
  if (!pics.length) return null;
  const shown = pics.slice(0, 4);
  const more = pics.length - shown.length;
  return (
    <div className={"pf-grid" + (shown.length === 1 ? " one" : "")}>
      {shown.map((u, n) => (
        <div key={u} className={"pf-tile" + (shown.length === 3 && n === 0 ? " wide" : "")}>
          <a href={own(u) ? u : imageUrl(u)} target="_blank" rel="noopener noreferrer">
            <img src={own(u) ? u : imageUrl(u)} alt="" loading="lazy" onError={() => setGone((g) => ({ ...g, [u]: true }))} />
          </a>
          {reel && n === 0 ? <span className="pf-reel" aria-label="Video">{I.play}</span> : null}
          {more > 0 && n === shown.length - 1 ? <span className="pf-plus">+{more}</span> : null}
        </div>
      ))}
    </div>
  );
}

function Media({ images, ratio, reel }: { images: string[]; ratio: string; reel?: boolean }) {
  const pics = picturesOf(images);
  const [i, setI] = useState(0);
  const [broken, setBroken] = useState<Record<string, boolean>>({});
  if (!pics.length) return null;
  const u = pics[Math.min(i, pics.length - 1)];
  return (
    <div className="pf-media" style={{ aspectRatio: ratio }}>
      {broken[u] ? (
        <span className="pf-media-gone">Picture no longer available</span>
      ) : (
        <a href={own(u) ? u : imageUrl(u)} target="_blank" rel="noopener noreferrer">
          <img src={own(u) ? u : imageUrl(u)} alt="" loading="lazy" onError={() => setBroken({ ...broken, [u]: true })} />
        </a>
      )}
      {reel ? <span className="pf-reel" aria-label="Video">{I.play}</span> : null}
      {pics.length > 1 ? (
        <>
          <span className="pf-count">
            {Math.min(i, pics.length - 1) + 1}/{pics.length}
          </span>
          <button type="button" className="pf-nav prev" aria-label="Previous picture" disabled={i === 0} onClick={() => setI(i - 1)}>
            ‹
          </button>
          <button type="button" className="pf-nav next" aria-label="Next picture" disabled={i >= pics.length - 1} onClick={() => setI(i + 1)}>
            ›
          </button>
          <span className="pf-dots">
            {pics.slice(0, 8).map((p, n) => (
              <i key={p} className={n === i ? "on" : ""} />
            ))}
          </span>
        </>
      ) : null}
    </div>
  );
}

const svg = (d: ReactNode, fill = false) => (
  <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill={fill ? "currentColor" : "none"} stroke={fill ? "none" : "currentColor"} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
    {d}
  </svg>
);
const I = {
  heart: svg(<path d="M12 20.5s-7.5-4.6-9.2-9.2C1.6 8 3.6 4.5 7 4.5c2 0 3.3 1 5 3 1.7-2 3-3 5-3 3.4 0 5.4 3.5 4.2 6.8-1.7 4.6-9.2 9.2-9.2 9.2Z" />),
  comment: svg(<path d="M20.5 11.6a8.5 8.5 0 0 1-12.4 7.6L3.5 20.5l1.3-4.4A8.5 8.5 0 1 1 20.5 11.6Z" />),
  send: svg(<path d="M21.5 3 10 13.6M21.5 3 15 21l-5-7.4L2.5 9.5 21.5 3Z" />),
  save: svg(<path d="M18.5 21 12 15.8 5.5 21V4.5a1.5 1.5 0 0 1 1.5-1.5h10a1.5 1.5 0 0 1 1.5 1.5V21Z" />),
  dots: svg(<><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></>, true),
  globe: svg(<><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.6 3 2.6 15 0 18M12 3c-2.6 3-2.6 15 0 18" /></>),
  like: svg(<path d="M7 21H4a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1h3m0 10V11m0 10h9.6a2 2 0 0 0 2-1.6l1.3-6.6A2 2 0 0 0 18 10.4h-4.6l.7-4a2 2 0 0 0-2-2.4L7 11" />),
  share: svg(<path d="M14 5l7 7-7 7M21 12H9a6 6 0 0 0-6 6v1" />),
  repost: svg(<path d="M17 3l3 3-3 3M20 6H8a4 4 0 0 0-4 4v1M7 21l-3-3 3-3M4 18h12a4 4 0 0 0 4-4v-1" />),
  play: svg(<path d="M8 5.5v13l11-6.5-11-6.5Z" />, true),
  lock: svg(<><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>),
  check: svg(<path d="M12 2.5l2.4 1.8 3-.2.9 2.9 2.5 1.7-1 2.8 1 2.9-2.5 1.7-.9 2.9-3-.2L12 21.5l-2.4-1.8-3 .2-.9-2.9-2.5-1.7 1-2.9-1-2.8 2.5-1.7.9-2.9 3 .2L12 2.5Zm-3.2 9.7 2.2 2.2 4.4-4.6" />, false),
};

function Avatar({ who, size, shape = "round" }: { who: Who; size: number; shape?: "round" | "square" }) {
  return (
    <span className={"pf-avatar " + shape} style={{ width: size, height: size }}>
      <Logo id={who.logo} name={who.name} size={size} />
    </span>
  );
}

export function InstagramPost({ post, who }: { post: Post; who: Who }) {
  const h = handle(who.name);
  const reel = /reel|video/i.test(post.format);
  return (
    <article className="pf-card pf-ig">
      <header>
        <span className="pf-ring">
          <Avatar who={who} size={32} />
        </span>
        <b>{h}</b>
        <span className="pf-dim">• {age(post.date)}</span>
        <span className="pf-end">{I.dots}</span>
      </header>
      <Media images={post.images ?? []} ratio={reel ? "4 / 5" : "1 / 1"} reel={reel} />
      <div className="pf-ig-actions">
        {I.heart}
        {I.comment}
        {I.send}
        <span className="pf-end">{I.save}</span>
      </div>
      <div className="pf-ig-body">
        {post.likes !== null ? <b className="pf-likes">{plural(post.likes, "like", "likes")}</b> : null}
        {post.views ? <span className="pf-dim"> · {count(post.views)} views</span> : null}
        <Caption text={post.caption} limit={125} lead={<b>{h} </b>} />
        {post.comments ? <span className="pf-dim pf-line">{post.comments === 1 ? "View 1 comment" : `View all ${count(post.comments)} comments`}</span> : null}
        <span className="pf-date">{longDate(post.date)}</span>
      </div>
    </article>
  );
}

export function FacebookPost({ post, who }: { post: Post; who: Who }) {
  return (
    <article className="pf-card pf-fb">
      <header>
        <Avatar who={who} size={40} />
        <span className="pf-who">
          <b>{who.name}</b>
          <span className="pf-dim">
            {age(post.date)} · <span className="pf-ico">{I.globe}</span>
          </span>
        </span>
        <span className="pf-end">{I.dots}</span>
      </header>
      <Caption text={post.caption} limit={240} more="See more" />
      <Grid images={post.images ?? []} reel={/reel|video/i.test(post.format)} />
      <div className="pf-fb-stats">
        <span className="pf-reacts">
          <i className="like">{I.like}</i>
          <i className="love">{I.heart}</i>
          {count(post.likes ?? 0)}
        </span>
        <span className="pf-dim">
          {post.comments ? plural(post.comments, "comment", "comments") : ""}
          {post.comments && post.shares ? " · " : ""}
          {post.shares ? plural(post.shares, "share", "shares") : ""}
        </span>
      </div>
      <div className="pf-bar">
        <span>{I.like} Like</span>
        <span>{I.comment} Comment</span>
        <span>{I.share} Share</span>
      </div>
    </article>
  );
}

export function LinkedInPost({ post, who }: { post: Post; who: Who }) {
  return (
    <article className="pf-card pf-li">
      <header>
        <Avatar who={who} size={48} shape="square" />
        <span className="pf-who">
          <b>{who.name}</b>
          <span className="pf-dim">Company page</span>
          <span className="pf-dim">
            {age(post.date)} • <span className="pf-ico">{I.globe}</span>
          </span>
        </span>
        <span className="pf-end pf-follow">+ Follow</span>
      </header>
      <Caption text={post.caption} limit={210} more="…see more" />
      <Grid images={post.images ?? []} reel={/video/i.test(post.format)} />
      <div className="pf-li-stats">
        <span className="pf-reacts">
          <i className="like">{I.like}</i>
          <i className="clap">✦</i>
          <i className="love">{I.heart}</i>
          {count(post.likes ?? 0)}
        </span>
        <span className="pf-dim">
          {post.comments ? plural(post.comments, "comment", "comments") : ""}
          {post.comments && post.shares ? " • " : ""}
          {post.shares ? plural(post.shares, "repost", "reposts") : ""}
        </span>
      </div>
      <div className="pf-bar">
        <span>{I.like} Like</span>
        <span>{I.comment} Comment</span>
        <span>{I.repost} Repost</span>
        <span>{I.send} Send</span>
      </div>
    </article>
  );
}

export function AdCard({ ad, who }: { ad: Ad; who: Who }) {
  const name = ad.page_name || who.name;
  // An ad with several versions (Meta's "This ad has multiple versions") keeps each as a card with its own picture.
  const versions = (ad.cards ?? []).filter((c) => c.image || c.title || c.body);
  const [v, setV] = useState(0);
  const card = versions.length > 1 ? versions[Math.min(v, versions.length - 1)] : null;
  const pics = card ? (card.image ? [card.image] : []) : ad.images;
  const body = (card?.body && card.body !== "{{product.description}}" ? card.body : "") || ad.body;
  const headline = (card?.title && !card.title.startsWith("{{") ? card.title : "") || ad.headline;
  return (
    <article className="pf-card pf-ad">
      <div className="pf-ad-meta">
        <span className={"pf-status " + (ad.active ? "on" : "")}>{ad.active ? "Active" : "Inactive"}</span>
        <span className="pf-dim">Library ID: {ad.id}</span>
        <span>
          {ad.active ? "Started running on " : "Ran "}
          {longDate(ad.start)}
          {!ad.active && ad.end ? ` to ${longDate(ad.end)}` : ""}
        </span>
        {ad.platforms.length ? (
          <span className="pf-plats">
            Platforms
            {ad.platforms.map((p) => (
              <i key={p} title={p}>
                {p.slice(0, 1).toUpperCase()}
              </i>
            ))}
          </span>
        ) : null}
      </div>
      <div className="pf-ad-post">
        <header>
          <Avatar who={{ ...who, name }} size={36} />
          <span className="pf-who">
            <b>{name}</b>
            <span className="pf-dim">Sponsored</span>
          </span>
        </header>
        <Caption text={body} limit={200} more="See more" />
        {card ? <Grid images={pics} /> : <Media images={pics} ratio="1 / 1" reel={/video/i.test(ad.format)} />}
        {headline || ad.cta || ad.landing ? (
          <div className="pf-ad-cta">
            <span>
              {ad.landing ? <small>{host(ad.landing).toUpperCase()}</small> : null}
              {headline ? <b dir="auto">{headline}</b> : null}
            </span>
            {ad.cta ? <span className="pf-btn">{card?.cta || ad.cta}</span> : null}
          </div>
        ) : null}
        {versions.length > 1 ? (
          <div className="pf-versions">
            <small>This ad has {versions.length} versions</small>
            <span>
              {versions.map((c, n) =>
                c.image && safeUrl(c.image) ? (
                  <button key={n} type="button" className={n === v ? "on" : ""} aria-label={`Version ${n + 1}`} onClick={() => setV(n)}>
                    <img src={imageUrl(c.image)} alt="" loading="lazy" />
                  </button>
                ) : (
                  <button key={n} type="button" className={n === v ? "on" : ""} aria-label={`Version ${n + 1}`} onClick={() => setV(n)}>
                    {n + 1}
                  </button>
                ),
              )}
            </span>
          </div>
        ) : null}
      </div>
    </article>
  );
}

export function WebPage({ page, who }: { page: PageCapture; who: Who }) {
  const f = page.fields;
  const hero = (page.images ?? []).map((u) => safeUrl(u)).filter(Boolean)[0] as string | undefined;
  let path = page.url;
  try {
    const u = new URL(page.url);
    path = u.hostname.replace(/^www\./, "") + (u.pathname === "/" ? "" : u.pathname);
  } catch {
    /* keep the raw link */
  }
  const prices = Object.entries(f.prices ?? {});
  const shot = page.screenshot && isShot(page.screenshot) ? page.screenshot : null;
  const [view, setView] = useState<"look" | "read">(shot ? "look" : "read");
  const [tall, setTall] = useState(false);
  const [shotGone, setShotGone] = useState(false);
  const showShot = shot && !shotGone && view === "look";
  return (
    <article className="pf-card pf-web">
      <div className="pf-chrome">
        <span className="pf-lights">
          <i />
          <i />
          <i />
        </span>
        <span className="pf-url">
          <span className="pf-ico">{I.lock}</span>
          {path}
        </span>
      </div>
      {shot && !shotGone ? (
        <div className="pf-views" role="group" aria-label="Show the page">
          <button type="button" aria-pressed={view === "look"} className={view === "look" ? "on" : ""} onClick={() => setView("look")}>
            As it looked{page.captured_at ? ` · ${age(page.captured_at)} ago` : ""}
          </button>
          <button type="button" aria-pressed={view === "read"} className={view === "read" ? "on" : ""} onClick={() => setView("read")}>
            What we read
          </button>
        </div>
      ) : null}
      {showShot ? (
        <div className={"pf-shot" + (tall ? " tall" : "")}>
          <img src={imageUrl(shot)} alt={`Screenshot of ${path}`} loading="lazy" onError={() => setShotGone(true)} />
          <span className="pf-shot-tools">
            <button type="button" onClick={() => setTall(!tall)}>
              {tall ? "Show less ↑" : "Show the whole page ↓"}
            </button>
            <a href={imageUrl(shot, true)} download>
              Download ↓
            </a>
          </span>
        </div>
      ) : null}
      <div className="pf-site" hidden={!!showShot}>
        <nav>
          <Avatar who={who} size={22} shape="square" />
          <b>{who.name}</b>
          <span className="pf-navlinks">
            {(f.headings ?? []).slice(0, 3).map((h) => (
              <span key={h} dir="auto">
                {h.length > 18 ? h.slice(0, 18) + "…" : h}
              </span>
            ))}
          </span>
        </nav>
        {hero ? <img className="pf-cover" src={imageUrl(hero)} alt="" loading="lazy" onError={(e) => (e.currentTarget.style.display = "none")} /> : null}
        <div className="pf-hero">
          <span className="pf-kind">{page.page_kind || "page"}</span>
          <h4 dir="auto">{f.headline || who.name}</h4>
          {f.buttons?.length ? (
            <span className="pf-site-btns">
              {f.buttons.slice(0, 2).map((b, n) => (
                <span key={b} className={n ? "ghost" : ""} dir="auto">
                  {b}
                </span>
              ))}
            </span>
          ) : null}
        </div>
        {prices.length ? (
          <div className="pf-prices">
            {prices.slice(0, 3).map(([plan, price]) => (
              <span key={plan}>
                <small dir="auto">{plan}</small>
                <b dir="auto">{price}</b>
              </span>
            ))}
          </div>
        ) : null}
        {f.services?.length ? (
          <div className="pf-chips">
            {f.services.slice(0, 6).map((s) => (
              <span key={s} dir="auto">
                {s}
              </span>
            ))}
          </div>
        ) : null}
        {f.clients?.length ? (
          <div className="pf-clients">
            <small>Trusted by</small>
            {f.clients.slice(0, 6).map((c) => (
              <b key={c} dir="auto">
                {c}
              </b>
            ))}
          </div>
        ) : null}
        <SitePictures page={page} />
      </div>
    </article>
  );
}

const PIC_ORDER: SitePicture["kind"][] = ["client_logo", "partner_logo", "product", "team", "banner", "brand_logo", "logo", "other"];
const PIC_PLURAL: Record<SitePicture["kind"], string> = {
  client_logo: "Client logos", partner_logo: "Partner logos", product: "Product shots", team: "Team photos",
  banner: "Banners", brand_logo: "Brand logo", logo: "Other logos", other: "Other pictures",
};
const isLogo = (k: SitePicture["kind"]) => k.endsWith("logo");

/** The page's sections in order, each with its words and the pictures under it, labelled from page clues. */
function SitePictures({ page }: { page: PageCapture }) {
  const [kind, setKind] = useState<SitePicture["kind"] | "all">("all");
  const [all, setAll] = useState(false);
  const pics = (page.pictures ?? []).filter((p) => safeUrl(p.url));
  if (!pics.length && !(page.sections ?? []).length) return null;
  const byUrl = new Map(pics.map((p) => [p.url, p]));
  const shown = (p: SitePicture) => kind === "all" || p.kind === kind;
  const used = new Set<string>();
  const secs = (page.sections ?? [])
    .map((s) => {
      const list = s.pictures.map((u) => byUrl.get(u)).filter((p): p is SitePicture => !!p);
      list.forEach((p) => used.add(p.url));
      return { ...s, list: list.filter(shown) };
    })
    .filter((s) => (kind === "all" ? s.text || s.list.length : s.list.length));
  const rest = pics.filter((p) => !used.has(p.url) && shown(p) && p.kind !== "banner");
  if (rest.length) secs.push({ heading: "More pictures on this page", text: "", pictures: [], list: rest });
  const counts = PIC_ORDER.map((k) => [k, pics.filter((p) => p.kind === k).length] as const).filter(([, n]) => n);
  const visible = all ? secs : secs.slice(0, 4);
  return (
    <div className="pf-secs">
      {counts.length > 1 ? (
        <div className="pf-pick" role="group" aria-label="Show pictures">
          <button type="button" className={kind === "all" ? "on" : ""} onClick={() => setKind("all")}>
            All · {pics.length}
          </button>
          {counts.map(([k, n]) => (
            <button key={k} type="button" className={kind === k ? "on" : ""} onClick={() => setKind(k)}>
              {PIC_PLURAL[k]} · {n}
            </button>
          ))}
        </div>
      ) : null}
      {visible.map((s, n) => (
        <section key={n} className="pf-sec">
          <h5 dir="auto">{s.heading}</h5>
          {s.text ? <p dir="auto">{s.text}</p> : null}
          {s.list.length ? (
            <div className="pf-pics">
              {s.list.map((p) => (
                <figure key={p.url} className={"pf-pic" + (isLogo(p.kind) ? "" : " photo")}>
                  <a href={imageUrl(p.url)} target="_blank" rel="noopener noreferrer" title={p.near || p.name}>
                    <img src={imageUrl(p.url)} alt={p.name} loading="lazy" />
                  </a>
                  <figcaption>
                    <b className={p.kind}>{p.label}</b>
                    <span dir="auto">{p.name.replace(/^[^:]+:\s*/, "") || p.label}</span>
                  </figcaption>
                </figure>
              ))}
            </div>
          ) : null}
        </section>
      ))}
      {secs.length > 4 ? (
        <button type="button" className="pf-secmore" onClick={() => setAll(!all)}>
          {all ? "Show fewer sections" : `Show all ${secs.length} sections`}
        </button>
      ) : null}
    </div>
  );
}

export function SearchResult({ m }: { m: Mention }) {
  const url = safeUrl(m.url);
  const site = m.site_name || m.site || host(m.url);
  const pic = picturesOf(m.images ?? [])[0];
  const [picGone, setPicGone] = useState(false);
  let crumbs = m.url;
  try {
    const u = new URL(m.url);
    crumbs = [u.hostname.replace(/^www\./, ""), ...u.pathname.split("/").filter(Boolean).slice(0, 2)].join(" › ");
  } catch {
    /* raw link */
  }
  return (
    <article className="pf-card pf-search">
      <span className="pf-tab">{m.kind === "news" ? "News" : "All"}</span>
      <header>
        <span className="pf-fav">{site.slice(0, 1).toUpperCase()}</span>
        <span className="pf-who">
          <b>{site}</b>
          <span className="pf-dim">{crumbs}</span>
        </span>
      </header>
      {url ? (
        <a className="pf-title" href={url} target="_blank" rel="noopener noreferrer nofollow" dir="auto">
          {m.title || m.url}
        </a>
      ) : (
        <span className="pf-title" dir="auto">
          {m.title || m.url}
        </span>
      )}
      <div className="pf-search-body">
        <p className="pf-text" dir="auto">
          {m.date ? <span className="pf-dim">{m.date} — </span> : null}
          {m.summary || m.snippet}
        </p>
        {pic && !picGone ? <img className="pf-search-pic" src={imageUrl(pic)} alt="" loading="lazy" onError={() => setPicGone(true)} /> : null}
      </div>
    </article>
  );
}

export function JobsBoard({ roles, who }: { roles: string[]; who: Who }) {
  return (
    <article className="pf-card pf-jobs">
      <header>
        <Avatar who={who} size={40} shape="square" />
        <span className="pf-who">
          <b>{who.name} is hiring</b>
          <span className="pf-dim">{roles.length} open roles on the careers page</span>
        </span>
      </header>
      <ul>
        {roles.slice(0, 8).map((r) => (
          <li key={r} dir="auto">
            <b>{r}</b>
            <span className="pf-btn">View</span>
          </li>
        ))}
      </ul>
      {roles.length > 8 ? <p className="pf-dim">and {roles.length - 8} more</p> : null}
    </article>
  );
}

/* ---- Drafts written by the M2 agents, shown the way they will look once posted ---------------------------- */

export interface DraftLook {
  platform: "LinkedIn" | "Instagram" | "Facebook";
  format: string;
  text: string;
  hashtags: string[];
  slides?: { headline: string; body: string }[];
  slideImages?: (string | null)[];
  image?: string | null;
  onImage?: string;
  when?: string;
}

function Slides({ slides, label, images = [] }: { slides: { headline: string; body: string }[]; label: string; images?: (string | null)[] }) {
  if (!slides.length) return null;
  return (
    <ol className="pf-slides" aria-label={label}>
      {slides.map((s, n) =>
        images[n] ? (
          <li key={n} className="pf-slide-pic">
            <img src={images[n] as string} alt={`Slide ${n + 1}: ${s.headline}`} loading="lazy" />
            <small>{n + 1}/{slides.length}</small>
          </li>
        ) : (
          <li key={n}>
            <small>{n + 1}/{slides.length}</small>
            <b dir="auto">{s.headline}</b>
            {s.body ? <span dir="auto">{s.body}</span> : null}
          </li>
        ),
      )}
    </ol>
  );
}

function DraftPicture({ d, ratio }: { d: DraftLook; ratio: string }) {
  const reel = d.format === "reel";
  if (d.image) return <Media images={[d.image]} ratio={ratio} reel={reel} />;
  return (
    <div className="pf-media pf-blank" style={{ aspectRatio: ratio }}>
      <span dir="auto">{d.onImage || "Picture comes here"}</span>
      {reel ? <span className="pf-reel" aria-label="Video">{I.play}</span> : null}
    </div>
  );
}

/** One draft in its platform's look. Stories are drawn as a phone screen with their frames. */
export function DraftCard({ d, who }: { d: DraftLook; who: Who }) {
  const text = d.text + (d.hashtags.length ? "\n\n" + d.hashtags.join(" ") : "");
  const slides = d.slides ?? [];
  if (d.format === "story") {
    return (
      <article className="pf-card pf-story">
        <div className="pf-story-bars">{(slides.length ? slides : [{ headline: "", body: "" }]).map((_, n) => <i key={n} className={n === 0 ? "on" : ""} />)}</div>
        <header>
          <Avatar who={who} size={28} />
          <b>{handle(who.name)}</b>
          <span className="pf-dim">{d.when || ""}</span>
        </header>
        <DraftPicture d={{ ...d, format: "post", onImage: "" }} ratio="9 / 16" />
        <div className="pf-story-frames">
          {slides.map((s, n) => (
            <p key={n} dir="auto">
              <b>{s.headline}</b>
              {s.body ? <span>{s.body}</span> : null}
            </p>
          ))}
        </div>
      </article>
    );
  }
  if (d.platform === "Instagram") {
    const ratio = d.format === "reel" ? "4 / 5" : d.format === "carousel" ? "4 / 5" : "4 / 5";
    return (
      <article className="pf-card pf-ig">
        <header>
          <span className="pf-ring"><Avatar who={who} size={32} /></span>
          <b>{handle(who.name)}</b>
          <span className="pf-dim">• {d.when || "Draft"}</span>
          <span className="pf-end">{I.dots}</span>
        </header>
        <DraftPicture d={d} ratio={ratio} />
        <div className="pf-ig-actions">{I.heart}{I.comment}{I.send}<span className="pf-end">{I.save}</span></div>
        <div className="pf-ig-body">
          <Caption text={text} limit={125} lead={<b>{handle(who.name)} </b>} />
          <Slides slides={slides} images={d.slideImages} label="Carousel slides" />
        </div>
      </article>
    );
  }
  if (d.platform === "Facebook") {
    return (
      <article className="pf-card pf-fb">
        <header>
          <Avatar who={who} size={40} />
          <span className="pf-who"><b>{who.name}</b><span className="pf-dim">{d.when || "Draft"} · <span className="pf-ico">{I.globe}</span></span></span>
          <span className="pf-end">{I.dots}</span>
        </header>
        <Caption text={text} limit={240} more="See more" />
        <DraftPicture d={d} ratio="1.2 / 1" />
        <Slides slides={slides} images={d.slideImages} label="Carousel cards" />
        <div className="pf-bar"><span>{I.like} Like</span><span>{I.comment} Comment</span><span>{I.share} Share</span></div>
      </article>
    );
  }
  return (
    <article className="pf-card pf-li">
      <header>
        <Avatar who={who} size={48} shape="square" />
        <span className="pf-who"><b>{who.name}</b><span className="pf-dim">Company page</span><span className="pf-dim">{d.when || "Draft"} • <span className="pf-ico">{I.globe}</span></span></span>
        <span className="pf-end pf-follow">+ Follow</span>
      </header>
      <Caption text={text} limit={210} more="…see more" />
      <DraftPicture d={d} ratio="1.25 / 1" />
      <Slides slides={slides} images={d.slideImages} label="Document pages" />
      <div className="pf-bar"><span>{I.like} Like</span><span>{I.comment} Comment</span><span>{I.repost} Repost</span><span>{I.send} Send</span></div>
    </article>
  );
}

/** A planned paid ad (Meta or LinkedIn), as it will look in the feed with its button. */
export function PlannedAd({ who, platform, text, headline, cta, image, link }: { who: Who; platform: string; text: string; headline: string; cta: string; image?: string | null; link?: string }) {
  return (
    <article className={"pf-card pf-ad " + (/linkedin/i.test(platform) ? "pf-li" : "pf-fb")}>
      <div className="pf-ad-post">
        <header>
          <Avatar who={who} size={36} shape={/linkedin/i.test(platform) ? "square" : "round"} />
          <span className="pf-who"><b>{who.name}</b><span className="pf-dim">{/linkedin/i.test(platform) ? "Promoted" : "Sponsored"}</span></span>
        </header>
        <Caption text={text} limit={180} more="See more" />
        <DraftPicture d={{ platform: "Facebook", format: "post", text: "", hashtags: [], image, onImage: headline }} ratio="1 / 1" />
        <div className="pf-ad-cta">
          <span>
            {link ? <small>{host(link).toUpperCase()}</small> : null}
            <b dir="auto">{headline}</b>
          </span>
          {cta ? <span className="pf-btn">{cta}</span> : null}
        </div>
      </div>
    </article>
  );
}
