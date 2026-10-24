/* Last tab: everything collected for you and every watched rival, in one place.
   Pictures in a gallery (each one downloadable, or all of them in one zip), and every item as a card. */
import { useMemo, useState } from "react";
import { download } from "../api";
import { saveFile } from "../format";
import { useToast } from "../components/Toast";
import { ago, KIND_LABEL, TIER_LABEL } from "./format";
import { Empty, ExtLink, imageUrl, Loading, Logo, Problem, useLoad } from "./parts";
import { ItemCard, itemsOf, profileFrom, type Item } from "./ScrapedData";
import { FeedGrid, LayoutSwitch, useLayout } from "./FeedGrid";
import type { CompanyData, SavedImage } from "./types";

type View = "pictures" | "items";
const PIC_SOURCE: Record<string, string> = { ...KIND_LABEL, page: "Website", logos: "Logos", jobs: "Jobs" };

interface Pic extends SavedImage {
  company: CompanyData;
}

export function DataPage() {
  const toast = useToast();
  const { data, error } = useLoad<{ client: string; companies: CompanyData[] }>("/watch/data");
  const [who, setWho] = useState<string>("all");
  const [view, setView] = useState<View>("items");
  const [source, setSource] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [layout, setLayout] = useLayout();

  const companies = useMemo(() => data?.companies ?? [], [data]);
  const items = useMemo(
    () =>
      companies.flatMap((c) =>
        itemsOf(c, { name: c.you ? data?.client ?? c.name : c.name, logo: c.key }).map((i): Item & { company: CompanyData } => ({ ...i, key: `${c.key}-${i.key}`, label: `${c.you ? "You" : c.name} · ${i.label}`, company: c })),
      ),
    [companies],
  );
  const pics = useMemo(() => companies.flatMap((c) => c.images.map((i): Pic => ({ ...i, company: c }))), [companies]);

  async function zip(key?: string) {
    setBusy(true);
    toast("Packing the data and pictures. Big sets take a minute.");
    try {
      const { blob, name } = await download(`/watch/data.zip${key ? `?company=${encodeURIComponent(key)}` : ""}`, "The zip could not be made.");
      saveFile(blob, name || "radar-data.zip");
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!data) return error ? <Problem text={error} /> : <Loading text="Gathering all scraped data…" />;
  const inCompany = <T extends { company: CompanyData }>(x: T) => who === "all" || x.company.key === who;
  const q = query.trim().toLowerCase();
  const picSource = (p: Pic) => (p.logo ? "logos" : p.source);
  const shownPics = pics
    .filter(inCompany)
    .filter((p) => source === "all" || picSource(p) === source)
    .filter((p) => !q || `${p.company.name} ${p.label} ${p.link}`.toLowerCase().includes(q));
  const shownItems = items
    .filter(inCompany)
    .filter((i) => source === "all" || i.source === source)
    .filter((i) => !q || `${i.label}\n${i.title}\n${i.text}\n${i.url}`.toLowerCase().includes(q));
  const pool = view === "pictures" ? pics.filter(inCompany).map(picSource) : items.filter(inCompany).map((i) => i.source as string);
  const sources = [...new Set(pool)].map((k) => [k, pool.filter((x) => x === k).length] as const);
  const picked = companies.find((c) => c.key === who);

  return (
    <div className="w-main">
      <div className="w-heading">
        <div>
          <h2>All scraped data</h2>
          <p>
            Everything collected for you and your watched competitors, from the latest capture of each source: {items.length} items and {pics.length} pictures. Download one picture, or everything in a zip with a CSV per company.
          </p>
        </div>
        <div className="w-actions">
          {picked ? (
            <button className="button secondary" disabled={busy} onClick={() => zip(picked.key)}>
              {picked.you ? "Your data" : picked.name} (.zip) ↓
            </button>
          ) : null}
          <button className="button primary" disabled={busy || !companies.length} onClick={() => zip()}>
            {busy ? "Packing…" : "Download everything (.zip)"}
          </button>
        </div>
      </div>

      <div className="w-company-strip" role="group" aria-label="Company">
        <button className={"w-company-card" + (who === "all" ? " selected" : "")} aria-pressed={who === "all"} onClick={() => setWho("all")}>
          <span className="w-logo w-logo-all" aria-hidden="true">
            ✦
          </span>
          <span>
            <b>Everyone</b>
            <small>
              {companies.length} companies · {pics.length} pictures
            </small>
          </span>
        </button>
        {companies.map((c) => (
          <button key={c.key} className={"w-company-card" + (who === c.key ? " selected" : "")} aria-pressed={who === c.key} onClick={() => setWho(c.key)}>
            <Logo id={c.key} name={c.name} size={36} />
            <span>
              <b>{c.you ? `You · ${c.name}` : c.name}</b>
              <small>
                {c.you ? "Your own accounts" : TIER_LABEL[c.tier as keyof typeof TIER_LABEL]} · {items.filter((i) => i.company.key === c.key).length} items · {c.images.length} pictures
                {c.captured_at ? ` · ${ago(c.captured_at)}` : ""}
              </small>
            </span>
          </button>
        ))}
      </div>

      <div className="w-data-tools">
        <div className="w-dviews" role="tablist" aria-label="Show">
          <button role="tab" aria-selected={view === "pictures"} className={view === "pictures" ? "selected" : ""} onClick={() => { setView("pictures"); setSource("all"); }}>
            Pictures <span>{pics.filter(inCompany).length}</span>
          </button>
          <button role="tab" aria-selected={view === "items"} className={view === "items" ? "selected" : ""} onClick={() => { setView("items"); setSource("all"); }}>
            Posts, pages, ads & news <span>{items.filter(inCompany).length}</span>
          </button>
        </div>
        {view === "items" ? <LayoutSwitch value={layout} onChange={setLayout} /> : null}
        <input type="search" placeholder="Search…" aria-label="Search scraped data" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      {sources.length > 1 ? (
        <div className="w-switch" role="group" aria-label="Source">
          <button className={source === "all" ? "selected" : ""} aria-pressed={source === "all"} onClick={() => setSource("all")}>
            All <span>{pool.length}</span>
          </button>
          {sources.map(([k, n]) => (
            <button key={k} className={source === k ? "selected" : ""} aria-pressed={source === k} onClick={() => setSource(k)}>
              {PIC_SOURCE[k] ?? k} <span>{n}</span>
            </button>
          ))}
        </div>
      ) : null}

      {view === "pictures" ? (
        shownPics.length ? (
          <div className="w-gallery">
            {shownPics.map((p) => (
              <figure key={p.url} className={"w-shot" + (p.logo ? " logo" : "")}>
                <a href={imageUrl(p.url)} target="_blank" rel="noopener noreferrer" className="w-shot-img">
                  <img src={imageUrl(p.url)} alt={p.label || `${p.company.name} picture`} loading="lazy" onError={(e) => e.currentTarget.closest("figure")?.classList.add("broken")} />
                  <span className="w-shot-broken">The link expired. Collect again to refresh it.</span>
                </a>
                <figcaption>
                  <div className="w-shot-who">
                    <Logo id={p.company.key} name={p.company.name} size={22} />
                    <b>{p.company.you ? "You" : p.company.name}</b>
                    <span className="badge neutral">{p.logo ? "Logo" : PIC_SOURCE[p.source] ?? p.source}</span>
                  </div>
                  {p.label && !p.logo ? <p dir="auto">{p.label}</p> : null}
                  <div className="w-shot-actions">
                    <a className="button secondary small-button" href={imageUrl(p.url, true)} download>
                      Download ↓
                    </a>
                    {p.link ? <ExtLink href={p.link}>Original</ExtLink> : null}
                  </div>
                </figcaption>
              </figure>
            ))}
          </div>
        ) : (
          <Empty icon="▣" title={pics.length ? "No pictures match these filters." : "No pictures saved yet."}>
            {pics.length ? null : "Pictures of posts, ads, site pages and logos are kept from the next collection on. Press Collect again now on the Collect tab."}
          </Empty>
        )
      ) : shownItems.length && layout === "grid" ? (
        <FeedGrid
          items={shownItems}
          profileOf={(i) => {
            const c = (i as Item & { company: CompanyData }).company;
            return profileFrom(c.social, c.socials, i.who ?? { name: c.name, logo: c.key }, i.source);
          }}
          renderCard={(i) => <ItemCard item={i} />}
        />
      ) : shownItems.length ? (
        <div className="w-evidence-grid">
          {shownItems.map((i) => (
            <ItemCard key={i.key} item={i} />
          ))}
        </div>
      ) : (
        <Empty icon="◫" title="No saved items match these filters." />
      )}
    </div>
  );
}
