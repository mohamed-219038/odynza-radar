/* The week in numbers: tiles, takeaways, you against the rivals, best posts, news and live ads.
   Built from the captures alone, so the brief and Overview always have something real to show. */
import { count, pct, TIER_LABEL } from "./format";
import { CountUp, Logo } from "./parts";
import type { Ad, Brief, CompanyData, Mention, Post, WeekSnapshot } from "./types";
import { PlatformItem, useGallery } from "./Visuals";

const PLATFORM = { instagram: "Instagram", facebook: "Facebook", linkedin: "LinkedIn" } as const;

export function SnapshotTiles({ snap }: { snap: WeekSnapshot }) {
  const n = snap.numbers;
  const tiles: [string, string, string][] = [
    ["Rivals watched", count(n.rivals), "confirmed competitors"],
    ["Rival posts", count(n.posts_7d), "in the last 7 days"],
    ["Live ads", n.live_ads === null ? "—" : count(n.live_ads), n.live_ads === null ? "not checked yet" : "running in Egypt now"],
    ["News & web", count(n.news), "mentions in the last month"],
  ];
  return (
    <div className="w-tiles">
      {tiles.map(([label, value, note]) => (
        <article key={label}>
          <span>{label}</span>
          <strong>
            <CountUp value={value} />
          </strong>
          <small>{note}</small>
        </article>
      ))}
    </div>
  );
}

export function Takeaways({ snap }: { snap: WeekSnapshot }) {
  if (!snap.takeaways.length) return null;
  return (
    <section className="w-takeaways">
      <h3 className="w-sub">Key takeaways</h3>
      <ul>
        {snap.takeaways.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    </section>
  );
}

/** Everything below the tiles and takeaways. */
type Snap = WeekSnapshot;
export const keyOf = (g: CompanyData[] | null, name: string) => g?.find((c) => c.name === name)?.key ?? name;

/** The saved post behind a brief's "best post", so it can be drawn with its pictures; built from the brief if not found. */
export function findPost(g: CompanyData[] | null, p: Snap["posts"][number]): Post {
  const saved = g?.find((c) => c.key === p.key)?.social[p.platform]?.posts?.find((x) => x.url === p.url);
  return saved ?? { id: p.url ?? p.caption.slice(0, 20), url: p.url ?? "", date: p.date, format: "", caption: p.caption, likes: p.likes, comments: p.comments, shares: null, views: null, engagement_total: p.engagement };
}

export function findAd(g: CompanyData[] | null, a: Snap["ads"][number]): Ad {
  const saved = g?.find((c) => c.name === a.company)?.ads?.items?.find((x) => x.url === a.url);
  return saved ?? { id: a.url ?? "", active: true, start: a.start, end: null, platforms: [], headline: a.headline, body: a.body, cta: "", landing: "", format: "", images: [], url: a.url ?? "" };
}

export function findMention(g: CompanyData[] | null, n: Snap["news"][number]): Mention {
  const saved = g?.find((c) => c.name === n.company)?.mentions?.items?.find((x) => x.url === n.url);
  return saved ?? { id: n.url ?? "", url: n.url ?? "", kind: n.kind === "news" ? "news" : "web", title: n.title ?? "", snippet: "", site: n.site ?? "", date: n.date ?? "" };
}

export function SnapshotDetails({ snap }: { snap: WeekSnapshot }) {
  const gallery = useGallery();
  return (
    <>
      {snap.standing.length ? (
        <section className="w-panel">
          <h3 className="w-sub">You against the rivals</h3>
          <div className="w-table-wrap"><table className="plan-table">
            <thead>
              <tr>
                <th>Platform</th>
                <th>Your engagement</th>
                <th>Rivals' average</th>
                <th>Leader</th>
                <th>Your posts (7 days)</th>
              </tr>
            </thead>
            <tbody>
              {snap.standing.map((s) => {
                const ahead = s.you !== null && s.rivals_avg !== null ? s.you >= s.rivals_avg : null;
                return (
                  <tr key={s.platform}>
                    <td>{PLATFORM[s.platform]}</td>
                    <td className={ahead === null ? "" : ahead ? "w-good" : "w-bad"}>{pct(s.you)}</td>
                    <td>{pct(s.rivals_avg)}</td>
                    <td>{s.leader ? `${s.leader} (${pct(s.leader_rate)})` : "—"}</td>
                    <td>{count(s.you_posts_7d)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table></div>
        </section>
      ) : null}
      {snap.rivals.length ? (
        <section className="w-panel">
          <h3 className="w-sub">Rivals at a glance</h3>
          <div className="w-table-wrap"><table className="plan-table">
            <thead>
              <tr>
                <th>Rival</th>
                <th>Biggest audience</th>
                <th>Engagement</th>
                <th>Posts (7 days)</th>
                <th>Live ads</th>
                <th>News</th>
                <th>Open jobs</th>
              </tr>
            </thead>
            <tbody>
              {snap.rivals.map((r) => (
                <tr key={r.name}>
                  <td>
                    <span className="w-who">
                      <Logo id={r.key} name={r.name} size={24} />
                      <span>
                        <b>{r.name}</b> <small className="muted">{TIER_LABEL[r.tier]}</small>
                      </span>
                    </span>
                  </td>
                  <td>{r.followers ? `${count(r.followers)} on ${PLATFORM[r.platform!]}` : "—"}</td>
                  <td>{pct(r.engagement_rate)}</td>
                  <td>{r.posts_7d}</td>
                  <td>{r.live_ads === null ? "—" : r.live_ads}</td>
                  <td>{r.news}</td>
                  <td>{r.jobs === null ? "—" : r.jobs}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </section>
      ) : null}
      {snap.posts.length ? (
        <section>
          <h3 className="w-sub">Rivals' best posts this month</h3>
          <div className="w-week-feed">
            {snap.posts.map((p, i) => (
              <div key={i} className="w-week-feed-item">
                <PlatformItem kind={p.platform} raw={findPost(gallery, p)} who={{ name: p.company, logo: p.key }} />
                {p.this_week ? <span className="badge">This week</span> : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}
      {snap.news.length ? (
        <section className="w-panel">
          <h3 className="w-sub">In the web and news</h3>
          <div className="w-week-feed">
            {snap.news.map((n, i) => (
              <div key={i} className="w-week-feed-item">
                <PlatformItem kind="web" raw={findMention(gallery, n)} who={{ name: n.company, logo: n.company }} />
                <small className="muted">{n.company}</small>
              </div>
            ))}
          </div>
        </section>
      ) : null}
      {snap.ads.length ? (
        <section className="w-panel">
          <h3 className="w-sub">Live ads</h3>
          <div className="w-week-feed">
            {snap.ads.map((a, i) => (
              <div key={i} className="w-week-feed-item">
                <PlatformItem kind="ads" raw={findAd(gallery, a)} who={{ name: a.company, logo: keyOf(gallery, a.company) }} />
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
}

/** A short card for the latest ready brief, for Overview. */
export function BriefTeaser({ brief, onOpen }: { brief: Brief; onOpen: () => void }) {
  return (
    <section className="w-brief-teaser">
      <div className="w-brief-teaser-head">
        <div>
          <span className="eyebrow">WEEKLY BRIEF · WEEK OF {brief.week_start}</span>
          <h3>{brief.headline || (brief.quiet ? "A quiet week: no big moves" : "This week's brief")}</h3>
        </div>
        <button className="button primary small-button" onClick={onOpen}>
          Read the brief →
        </button>
      </div>
      {brief.items.length ? (
        <ol>
          {brief.items.slice(0, 3).map((it) => (
            <li key={it.signal_id}>
              <b>{it.competitor}:</b> {it.title}
              {it.move ? <span className="w-teaser-move">Your move: {it.move}</span> : null}
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted">No rival change scored 3 or more. The brief shows what the market did instead.</p>
      )}
    </section>
  );
}
