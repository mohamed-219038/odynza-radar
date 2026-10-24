/* Every item collected for one competitor: source switch, search, one card per item with the full saved
   text and all saved fields. */
import { useMemo, useState } from "react";
import { request } from "../api";
import { saveFile } from "../format";
import { count, fieldLabel, KIND_LABEL, pct, stamp, toCsv } from "./format";
import { Empty, ExtLink } from "./parts";
import type { CompetitorDetail, SocialKind } from "./types";
import { FeedGrid, LayoutSwitch, useLayout, type Profile } from "./FeedGrid";
import { Select } from "../components/Select";
import { AdCard, FacebookPost, InstagramPost, JobsBoard, LinkedInPost, SearchResult, WebPage, type Who } from "./PlatformCard";

export type ItemSource = "page" | "instagram" | "facebook" | "linkedin" | "ads" | "web" | "jobs";

const SOURCE_LABEL: Record<ItemSource, string> = { ...KIND_LABEL, jobs: "Jobs" };
const ORDER: ItemSource[] = ["page", "instagram", "facebook", "linkedin", "ads", "web", "jobs"];

export interface Item {
  key: string;
  source: ItemSource;
  label: string;
  title: string;
  stats: string;
  date: string | null;
  url: string;
  text: string;
  images: string[];
  rank: number;
  live?: boolean;
  snapshotId?: number;
  raw: unknown;
  who?: Who;
}

/** Flattens pages, posts, ads, mentions and jobs into one list of cards. */
export function itemsOf(data: Pick<CompetitorDetail, "pages" | "social" | "ads" | "mentions" | "jobs">, who?: Who): Item[] {
  const out: Item[] = [];
  for (const p of data.pages) {
    const f = p.fields;
    const lines = [
      f.headline ? `Headline: ${f.headline}` : "",
      f.prices && Object.keys(f.prices).length ? "Prices: " + Object.entries(f.prices).map(([k, v]) => `${k} ${v}`).join(" · ") : "",
      f.services?.length ? `Services: ${f.services.join(" · ")}` : "",
      f.headings?.length ? `Headings: ${f.headings.join(" · ")}` : "",
      f.buttons?.length ? `Buttons: ${f.buttons.join(" · ")}` : "",
      f.clients?.length ? `Clients: ${f.clients.join(" · ")}` : "",
    ].filter(Boolean);
    out.push({
      key: `page-${p.source_id}`,
      source: "page",
      label: `Website · ${p.page_kind || "page"}`,
      title: f.headline || p.url,
      stats: `${count(p.words)} words · ${p.snapshots} capture${p.snapshots === 1 ? "" : "s"}`,
      date: p.captured_at,
      url: p.url,
      text: lines.join("\n"),
      images: [...(p.screenshot ? [p.screenshot] : []), ...(p.images ?? [])],
      rank: p.words,
      snapshotId: p.snapshot_id,
      raw: p,
    });
  }
  for (const kind of ["instagram", "facebook", "linkedin"] as const) {
    for (const post of data.social[kind]?.posts ?? []) {
      const bits = [`${count(post.likes)} likes`, `${count(post.comments)} comments`];
      if (kind !== "instagram" && post.shares !== null) bits.push(`${count(post.shares)} shares`);
      if (post.views) bits.push(`${count(post.views)} views`);
      if (post.engagement_rate !== undefined && post.engagement_rate !== null) bits.push(`${pct(post.engagement_rate)} engagement`);
      out.push({
        key: `${kind}-${post.id}`,
        source: kind,
        label: `${KIND_LABEL[kind]} · ${post.format || "post"}`,
        title: `${KIND_LABEL[kind]} post · ${stamp(post.date)}`,
        stats: bits.join(" · "),
        date: post.date,
        url: post.url,
        text: post.caption,
        images: post.images ?? [],
        rank: post.engagement_total ?? 0,
        raw: post,
      });
    }
  }
  for (const ad of data.ads?.items ?? []) {
    out.push({
      key: `ad-${ad.id}`,
      source: "ads",
      label: `Meta ad · ${ad.active ? "Live" : "Ended"}${ad.format ? " · " + ad.format.toLowerCase() : ""}`,
      title: ad.headline || ad.page_name || "Ad without a headline",
      stats: [`${ad.start ?? "?"} → ${ad.end ?? (ad.active ? "running" : "?")}`, ad.platforms.join(", "), ad.cta ? `Button: ${ad.cta}` : ""].filter(Boolean).join(" · "),
      date: ad.start,
      url: ad.url,
      text: ad.body + (ad.landing ? `\n\nLanding page: ${ad.landing}` : ""),
      images: ad.images,
      rank: ad.active ? 1 : 0,
      live: ad.active,
      raw: ad,
    });
  }
  for (const m of data.mentions?.items ?? []) {
    out.push({
      key: `web-${m.id}`,
      source: "web",
      label: m.kind === "news" ? "News" : "Web page",
      title: m.title || m.url,
      stats: [m.site, m.date].filter(Boolean).join(" · "),
      date: data.mentions?.captured_at ?? null,
      url: m.url,
      text: m.summary || m.snippet,
      images: m.images ?? [],
      rank: m.kind === "news" ? 1 : 0,
      raw: m,
    });
  }
  const careers = data.pages.find((p) => p.page_kind === "careers");
  const jobs = data.jobs ?? [];
  if (jobs.length)
    out.push({
      key: "jobs",
      source: "jobs",
      label: "Jobs",
      title: `${jobs.length} open role${jobs.length === 1 ? "" : "s"}`,
      stats: "From the careers page",
      date: careers?.captured_at ?? null,
      url: careers?.url ?? "",
      text: jobs.map((j) => `• ${j}`).join("\n"),
      images: [],
      rank: jobs.length,
      raw: { roles: jobs },
    });
  return who ? out.map((i) => ({ ...i, who })) : out;
}

/** The account header of a platform grid, from the latest capture of that account. */
export function profileFrom(
  social: CompetitorDetail["social"],
  socials: Partial<Record<string, string>> | undefined,
  who: { name: string; logo: string | number },
  kind: string,
): Profile {
  const m = social[kind as SocialKind]?.them;
  return { name: who.name, logo: who.logo, url: socials?.[kind], followers: m?.followers, engagement_rate: m?.engagement_rate, posts_per_week: m?.posts_per_week, bio: m?.bio };
}

const time = (v: string | null) => (v ? Date.parse(v.length === 10 ? v : v.replace(" ", "T")) || 0 : 0);

export function ScrapedData({ data, start = "all", liveOnlyAtStart = false }: { data: CompetitorDetail; start?: ItemSource | "all"; liveOnlyAtStart?: boolean }) {
  const items = useMemo(() => itemsOf(data, { name: data.competitor.name, logo: data.competitor.id }), [data]);
  const [source, setSource] = useState<ItemSource | "all">(start);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"source" | "newest" | "top">("source");
  const [liveOnly, setLiveOnly] = useState(liveOnlyAtStart);
  const [layout, setLayout] = useLayout();
  const profileOf = useMemo(() => (i: Item) => profileFrom(data.social, data.competitor.socials, i.who ?? { name: data.competitor.name, logo: data.competitor.id }, i.source), [data]);
  const counts = ORDER.map((k) => [k, items.filter((i) => i.source === k).length] as const).filter(([, n]) => n);
  const q = query.trim().toLowerCase();
  const shown = items
    .filter((i) => source === "all" || i.source === source)
    .filter((i) => !liveOnly || i.source !== "ads" || i.live)
    .filter((i) => !q || `${i.title}\n${i.text}\n${i.stats}\n${i.url}`.toLowerCase().includes(q))
    .sort((a, b) =>
      sort === "top" ? b.rank - a.rank : sort === "newest" ? time(b.date) - time(a.date) : ORDER.indexOf(a.source) - ORDER.indexOf(b.source) || time(b.date) - time(a.date),
    );
  const name = data.competitor.name;
  const file = name.replace(/[^\w-]+/g, "-");

  function downloadJson() {
    const body = { competitor: data.competitor, pages: data.pages, social: data.social, ads: data.ads, mentions: data.mentions, jobs: data.jobs };
    saveFile(new Blob([JSON.stringify(body, null, 2)], { type: "application/json" }), `${file}-scraped-data.json`);
  }
  function downloadCsv() {
    const rows = [["source", "label", "title", "date", "stats", "url", "text"], ...shown.map((i) => [SOURCE_LABEL[i.source], i.label, i.title, i.date, i.stats, i.url, i.text])];
    saveFile(new Blob(["﻿" + toCsv(rows)], { type: "text/csv;charset=utf-8" }), `${file}-scraped-data.csv`);
  }

  return (
    <section className="w-data" aria-label="Scraped data">
      <div className="w-data-head">
        <div>
          <span className="eyebrow">SCRAPED DATA</span>
          <h3>All scraped data for {name}</h3>
          <p className="muted">
            {items.length} items{counts.length ? " · " + counts.map(([k, n]) => (k === "jobs" ? `${data.jobs?.length ?? 0} jobs` : `${n} ${SOURCE_LABEL[k]}`)).join(" · ") : ""}. Everything from the latest capture of each source, including items n8n did not score.
          </p>
        </div>
        {items.length ? (
          <div className="w-actions">
            <button className="button secondary small-button" onClick={downloadCsv}>
              CSV ↓
            </button>
            <button className="button secondary small-button" onClick={downloadJson}>
              JSON ↓
            </button>
          </div>
        ) : null}
      </div>
      {data.ads?.unchecked ? (
        <p className="w-notice">
          The ads saved last time were not checked against {name}'s page, and some belonged to other pages, so they are hidden. Press <b>Check now</b> to collect this page's own ads.
        </p>
      ) : null}
      {items.length ? (
        <>
          <div className="w-switch" role="group" aria-label="Source">
            <button className={source === "all" ? "selected" : ""} aria-pressed={source === "all"} onClick={() => setSource("all")}>
              All <span>{items.length}</span>
            </button>
            {counts.map(([k, n]) => (
              <button key={k} className={source === k ? "selected" : ""} aria-pressed={source === k} onClick={() => setSource(k)}>
                {SOURCE_LABEL[k]} <span>{n}</span>
              </button>
            ))}
          </div>
          <div className="w-data-tools">
            <LayoutSwitch value={layout} onChange={setLayout} />
            <input type="search" placeholder="Search saved content…" aria-label="Search saved content" value={query} onChange={(e) => setQuery(e.target.value)} />
            <Select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value as "source" | "newest" | "top")}>
              <option value="source">By source</option>
              <option value="newest">Newest first</option>
              <option value="top">Most engagement first</option>
            </Select>
            {source === "ads" || source === "all" ? (
              <label className="checkbox">
                <input type="checkbox" checked={liveOnly} onChange={(e) => setLiveOnly(e.target.checked)} /> Live ads only
              </label>
            ) : null}
          </div>
          <p className="muted" role="status">
            {shown.length} of {items.length} saved items shown
          </p>
          {shown.length ? (
            layout === "grid" ? (
              <FeedGrid items={shown} profileOf={profileOf} renderCard={(i) => <ItemCard item={i} />} />
            ) : (
              <div className="w-evidence-grid">
                {shown.map((i) => (
                  <ItemCard key={i.key} item={i} />
                ))}
              </div>
            )
          ) : (
            <p className="w-filter-empty">No saved items match these filters.</p>
          )}
        </>
      ) : (
        <Empty icon="◫" title="Nothing collected yet.">
          {data.competitor.status === "confirmed" ? "Press Check now, or wait for the next scheduled check." : "Confirm this competitor first. Nothing is collected before that."}
        </Empty>
      )}
    </section>
  );
}

/** One saved item in its platform's own look, with the original link, the full saved text and every saved field. */
export function ItemCard({ item }: { item: Item }) {
  const [full, setFull] = useState<string | null>(null);
  async function loadFull(open: boolean) {
    if (!open || full !== null || !item.snapshotId) return;
    try {
      const snap = await request<{ text: string }>(`/watch/snapshots/${item.snapshotId}`);
      setFull(snap.text || "(no text was saved)");
    } catch (e) {
      setFull((e as Error).message);
    }
  }
  const who: Who = item.who ?? { name: item.title, logo: "client" };
  const raw = item.raw as never;
  const body =
    item.source === "instagram" ? (
      <InstagramPost post={raw} who={who} />
    ) : item.source === "facebook" ? (
      <FacebookPost post={raw} who={who} />
    ) : item.source === "linkedin" ? (
      <LinkedInPost post={raw} who={who} />
    ) : item.source === "ads" ? (
      <AdCard ad={raw} who={who} />
    ) : item.source === "page" ? (
      <WebPage page={raw} who={who} />
    ) : item.source === "web" ? (
      <SearchResult m={raw} />
    ) : (
      <JobsBoard roles={(item.raw as { roles: string[] }).roles} who={who} />
    );
  return (
    <div className={"pf-item" + (item.live ? " live" : "")} data-source={item.source}>
      {body}
      <div className="pf-under">
        <span className="pf-under-label">{item.label}</span>
        {item.url ? <ExtLink href={item.url}>Open original</ExtLink> : null}
        {item.snapshotId ? (
          <details onToggle={(e) => loadFull((e.target as HTMLDetailsElement).open)}>
            <summary>Full saved text</summary>
            <pre dir="auto">{full ?? "Loading…"}</pre>
          </details>
        ) : null}
        <details>
          <summary>All saved fields</summary>
          <dl className="w-facts">
            {Object.entries(item.raw as Record<string, unknown>)
              .filter(([, v]) => v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && !v.length))
              .map(([k, v]) => (
                <div key={k}>
                  <dt>{fieldLabel(k)}</dt>
                  <dd dir="auto">{typeof v === "object" ? <pre>{JSON.stringify(v, null, 2)}</pre> : String(v)}</dd>
                </div>
              ))}
          </dl>
        </details>
      </div>
    </div>
  );
}
