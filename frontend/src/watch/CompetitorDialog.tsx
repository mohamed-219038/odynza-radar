/* One competitor in full: a summary against you, every scraped item, its changes and its sources. */
import { useState } from "react";
import { json, request } from "../api";
import { CloseButton, Dialog } from "../components/Dialog";
import { useToast } from "../components/Toast";
import { ago, cleanLogos, count, KIND_LABEL, pct, planName, stamp, TIER_HELP, TIER_LABEL } from "./format";
import { Empty, ExtLink, Loading, Logo, Problem, SignalCard, useLoad, CountUp } from "./parts";
import { itemsOf, ScrapedData } from "./ScrapedData";
import { Cover } from "./Visuals";
import type { CompetitorDetail, SocialKind } from "./types";

type View = "summary" | "data" | "changes" | "sources";
const SOCIAL: SocialKind[] = ["instagram", "facebook", "linkedin"];

export function CompetitorDialog(props: { id: number | null; liveAds?: boolean; canDecide: boolean; canRun: boolean; onClose: () => void; onChanged: () => void }) {
  return (
    <Dialog id="watch-competitor" className="session-dialog w-dialog" open={props.id !== null} onClose={props.onClose} labelledBy="w-comp-title">
      {props.id !== null ? <Body key={`${props.id}-${Boolean(props.liveAds)}`} {...props} id={props.id} /> : null}
    </Dialog>
  );
}

function Body({ id, liveAds, canDecide, canRun, onClose, onChanged }: { id: number; liveAds?: boolean; canDecide: boolean; canRun: boolean; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const { data, error, reload } = useLoad<CompetitorDetail>(`/watch/competitors/${id}`);
  const [view, setView] = useState<View>(liveAds ? "data" : "summary");
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    try {
      const out = await request<{ message: string }>("/watch/run", json({ competitor_id: id }));
      toast(out.message + " Reopen this page in a few minutes to see the new data.");
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function reviewed() {
    try {
      await request(`/watch/competitors/${id}/reviewed`, { method: "POST" });
      toast("Marked as reviewed. Next review in 90 days.");
      reload();
      onChanged();
    } catch (e) {
      toast((e as Error).message);
    }
  }

  if (!data)
    return (
      <div className="w-dialog-pad">
        <div className="dialog-top">
          <span className="eyebrow">COMPETITOR</span>
          <CloseButton onClick={onClose} />
        </div>
        {error ? <Problem text={error} /> : <Loading />}
      </div>
    );

  const c = data.competitor;
  const items = itemsOf(data).length;
  const ok = data.sources.filter((s) => s.enabled && s.healthy && s.last_success_at).length;
  const failing = data.sources.filter((s) => s.enabled && !s.healthy && s.last_run_at);
  const last = data.sources.map((s) => s.last_success_at).filter(Boolean).sort().pop() ?? null;
  const next = data.sources.map((s) => s.next_run_at).filter(Boolean).sort()[0] ?? null;
  const socials = (Object.entries(c.socials || {}) as [string, string][]).filter(([, url]) => url);

  const VIEWS: [View, string, number | null][] = [
    ["summary", "Summary", null],
    ["data", "Scraped data", items],
    ["changes", "Changes", data.timeline.length],
    ["sources", "Sources & log", data.sources.length],
  ];

  return (
    <>
      <div className="w-dhead">
        <div className="w-dhead-main">
          <Logo id={c.id} name={c.name} size={56} />
          <div>
            <div className="w-dhead-badges">
              <span className="badge neutral" title={TIER_HELP[c.tier]}>
                {TIER_LABEL[c.tier]}
              </span>
              <span className={"badge" + (c.status === "confirmed" ? "" : c.status === "rejected" ? " warn" : " neutral")}>{c.status === "confirmed" ? "Watched" : c.status}</span>
              {c.review_due ? <span className="badge warn">Review due</span> : null}
            </div>
            <h2 id="w-comp-title">{c.name}</h2>
            <div className="w-links">
              <ExtLink href={c.website} />
              {socials.map(([k, url]) => (
                <ExtLink key={k} href={url}>
                  {KIND_LABEL[k as SocialKind] ?? k}
                </ExtLink>
              ))}
            </div>
            {c.why ? <p className="muted w-why">{c.why}</p> : null}
          </div>
        </div>
        <div className="w-actions">
          {canRun && c.status === "confirmed" ? (
            <button className="button small-button" disabled={busy} onClick={run}>
              {busy ? "Starting…" : "Check now"}
            </button>
          ) : null}
          {canDecide && c.review_due ? (
            <button className="button secondary small-button" onClick={reviewed}>
              Mark reviewed
            </button>
          ) : null}
          <CloseButton onClick={onClose} />
        </div>
      </div>
      <div className="w-fresh">
        {c.status !== "confirmed" ? (
          <span>Not watched yet. Confirm it in the Competitors tab and its data is collected.</span>
        ) : (
          <>
            <span>
              Last collected <b>{ago(last)}</b>
            </span>
            <span>
              {ok} of {data.sources.length} sources OK
            </span>
            {failing.length ? (
              <button className="text-link w-bad" onClick={() => setView("sources")}>
                {failing.length} failing
              </button>
            ) : null}
            <span>Next check {next ? ago(next) : "not planned"}</span>
          </>
        )}
      </div>
      <nav className="w-dviews" aria-label="Competitor sections">
        {VIEWS.map(([k, label, n]) => (
          <button key={k} className={view === k ? "selected" : ""} aria-current={view === k ? "page" : undefined} onClick={() => setView(k)}>
            {label}
            {n !== null ? <span>{n}</span> : null}
          </button>
        ))}
      </nav>
      <div className="w-dialog-body">
        {view === "summary" ? (
          <>
            <Cover companyKey={String(c.id)} />
            <Summary data={data} go={setView} />
          </>
        ) : null}
        {view === "data" ? <ScrapedData data={data} start={liveAds ? "ads" : "all"} liveOnlyAtStart={Boolean(liveAds)} /> : null}
        {view === "changes" ? (
          <section>
            {data.alerts.length ? (
              <ul className="w-alerts">
                {data.alerts.map((a, i) => (
                  <li key={i}>
                    <span className="badge warn">{a.rule}</span> {a.message} <small>{ago(a.at)}</small>
                  </li>
                ))}
              </ul>
            ) : null}
            {data.timeline.length ? (
              data.timeline.map((s) => <SignalCard key={s.id} signal={s} canCorrect={canDecide} onChanged={reload} showCompany={false} />)
            ) : (
              <Empty icon="↻" title="No changes yet.">
                The first collection of each source only records a starting point. Changes show from the next collection, after n8n scores them.
              </Empty>
            )}
          </section>
        ) : null}
        {view === "sources" ? <Sources data={data} /> : null}
      </div>
    </>
  );
}

function Summary({ data, go }: { data: CompetitorDetail; go: (v: View) => void }) {
  const c = data.competitor;
  const home = data.pages.find((p) => p.page_kind === "homepage") ?? data.pages[0];
  const pricing = data.pages.find((p) => p.fields.prices && Object.keys(p.fields.prices).length);
  const services = [...new Set(data.pages.filter((p) => p.page_kind === "services" || p.page_kind === "homepage").flatMap((p) => p.fields.services ?? []))];
  const logos = cleanLogos(
    data.pages.flatMap((p) => p.fields.clients ?? []),
    c.name,
  );
  const platforms = SOCIAL.map((k) => ({ k, s: data.social[k] })).filter((x) => x.s);
  const bio = platforms.map(({ s }) => s!.them.bio).find(Boolean);
  const live = data.ads && !data.ads.unchecked ? (data.ads.metrics.live_ads ?? 0) : null;
  const news = data.mentions?.items ?? [];

  if (!data.pages.length && !platforms.length && !data.ads && !data.mentions)
    return (
      <Empty icon="◎" title="No data yet.">
        {c.status === "confirmed" ? "Press Check now, or wait for the next scheduled check." : "Confirm this competitor first. Nothing is collected before that."}
      </Empty>
    );

  return (
    <>
      <div className="w-kpis">
        {platforms.map(({ k, s }) => {
          const them = s!.them.engagement_rate;
          const you = s!.you?.engagement_rate;
          const days = s!.them.days_since_last_post;
          const lead = them === null || them === undefined || you === null || you === undefined ? null : them > you ? "they" : "you";
          return (
            <article key={k}>
              <span>{KIND_LABEL[k]}</span>
              <strong>
                <CountUp value={count(s!.them.followers)} />
              </strong>
              <small>followers · {pct(them)} engagement</small>
              <small>
                {s!.them.posts_per_week ?? "—"} posts/week · last post {days === null || days === undefined ? "—" : days === 0 ? "today" : `${days} days ago`}
              </small>
              {lead ? <em className={lead === "they" ? "w-bad" : "w-good"}>{lead === "they" ? `They lead you (you ${pct(you)})` : `You lead (you ${pct(you)})`}</em> : <em className="muted">You are not watched here</em>}
            </article>
          );
        })}
        <article className={live ? "w-warn" : ""}>
          <span>Meta ads</span>
          <strong>{live === null ? "—" : live}</strong>
          <small>{data.ads?.unchecked ? "Waiting for a fresh check" : data.ads ? `live now · ${data.ads.metrics.ads_seen ?? 0} seen in the Ad Library` : "Needs a Facebook page"}</small>
          {data.ads && !data.ads.unchecked && data.ads.items.length ? (
            <button className="text-link" onClick={() => go("data")}>
              See the ads →
            </button>
          ) : null}
        </article>
        <article>
          <span>Web & news</span>
          <strong>{news.length}</strong>
          <small>{news.filter((n) => n.kind === "news").length} news · last month</small>
          {news.length ? (
            <button className="text-link" onClick={() => go("data")}>
              Read them →
            </button>
          ) : null}
        </article>
        <article>
          <span>Changes</span>
          <strong>{data.timeline.length}</strong>
          <small>{data.timeline.filter((s) => (s.score ?? 0) >= 4).length} scored 4 or 5</small>
          {data.timeline.length ? (
            <button className="text-link" onClick={() => go("changes")}>
              Open the timeline →
            </button>
          ) : null}
        </article>
      </div>

      <section className="w-cols">
        <div className="w-panel">
          <span className="w-cap">What they sell</span>
          <h3 className="w-big" dir="auto">
            {home?.fields.headline || "No headline found"}
          </h3>
          {bio ? (
            <p className="w-bio" dir="auto">
              {bio.slice(0, 260)}
            </p>
          ) : null}
          <h4 className="w-mini">Prices</h4>
          {pricing ? (
            <table className="w-prices">
              <tbody>
                {Object.entries(pricing.fields.prices!).map(([plan, price]) => {
                  const was = pricing.previous_fields?.prices?.[plan];
                  return (
                    <tr key={plan}>
                      <td>{planName(plan)}</td>
                      <td dir="auto">
                        <b>{price}</b>
                        {was && was !== price ? <span className="w-was"> was {was}</span> : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <p className="muted">No prices published on the watched pages.</p>
          )}
          <h4 className="w-mini">Services and topics ({services.length})</h4>
          <Chips list={services} empty="None found on the watched pages." />
        </div>
        <div className="w-panel">
          <span className="w-cap">Who they work with</span>
          <h4 className="w-mini">Client and partner logos ({logos.length})</h4>
          <Chips list={logos} empty="No client logos found." />
          <h4 className="w-mini">Hiring</h4>
          {data.jobs?.length ? (
            <>
              <p className="w-small">
                <b>{data.jobs.length} open roles</b>
              </p>
              <Chips list={data.jobs} limit={6} />
            </>
          ) : (
            <p className="muted">{data.pages.some((p) => p.page_kind === "careers") ? "No open roles listed." : "No careers page is watched."}</p>
          )}
          <h4 className="w-mini">Claims they make</h4>
          {data.claims.length ? <Chips list={data.claims} /> : <p className="muted">None yet. Claims are filled in by the weekly brief.</p>}
        </div>
      </section>

      {news.length ? (
        <section className="w-panel">
          <div className="section-heading">
            <span className="w-cap">Latest in the web and news</span>
            <button className="text-link" onClick={() => go("data")}>
              All {news.length} →
            </button>
          </div>
          <ul className="w-mentions">
            {news.slice(0, 4).map((m) => (
              <li key={m.id}>
                <span className={"badge" + (m.kind === "news" ? " running" : " neutral")}>{m.kind === "news" ? "News" : "Web"}</span> <ExtLink href={m.url}>{m.title || m.url}</ExtLink>
                <small>{[m.site, m.date].filter(Boolean).join(" · ")}</small>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {data.timeline.length ? (
        <section>
          <span className="w-cap">Latest changes</span>
          {data.timeline.slice(0, 3).map((s) => (
            <SignalCard key={s.id} signal={s} canCorrect={false} showCompany={false} />
          ))}
        </section>
      ) : null}
    </>
  );
}

function Chips({ list, empty, limit = 14 }: { list: string[]; empty?: string; limit?: number }) {
  const [all, setAll] = useState(false);
  if (!list.length) return <p className="muted">{empty}</p>;
  const shown = all ? list : list.slice(0, limit);
  return (
    <div className="w-chips">
      {shown.map((x) => (
        <span key={x} className="w-chip" dir="auto">
          {x}
        </span>
      ))}
      {list.length > limit ? (
        <button className="text-link" onClick={() => setAll(!all)}>
          {all ? "Show less" : `+${list.length - limit} more`}
        </button>
      ) : null}
    </div>
  );
}

function Sources({ data }: { data: CompetitorDetail }) {
  return (
    <>
      <section className="w-panel">
        <span className="w-cap">Sources</span>
        <div className="w-table-wrap">
          <table className="plan-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Status</th>
                <th>Last success</th>
                <th>Next check</th>
                <th>Collected by</th>
              </tr>
            </thead>
            <tbody>
              {data.sources.map((s) => (
                <tr key={s.id} className={s.enabled ? "" : "w-off"}>
                  <td>
                    <b>{s.kind === "page" ? `Website · ${s.page_kind || "page"}` : KIND_LABEL[s.kind]}</b>
                    <small>
                      <ExtLink href={s.url} />
                    </small>
                  </td>
                  <td className={!s.last_run_at ? "" : s.healthy ? "w-good" : "w-bad"}>
                    {!s.enabled ? "Off" : !s.last_run_at ? "Not run yet" : s.healthy ? "OK" : "Failing"}
                    {s.last_error ? <small>{s.last_error}</small> : null}
                  </td>
                  <td>{ago(s.last_success_at)}</td>
                  <td>{s.next_run_at ? ago(s.next_run_at) : "—"}</td>
                  <td>{s.via}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="w-panel">
        <span className="w-cap">Collection log</span>
        {data.log.length ? (
          <div className="w-table-wrap">
            <table className="plan-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Source</th>
                  <th>Result</th>
                  <th>Cost</th>
                </tr>
              </thead>
              <tbody>
                {data.log.map((l, i) => (
                  <tr key={i}>
                    <td>{stamp(l.at)}</td>
                    <td>
                      {KIND_LABEL[l.kind as keyof typeof KIND_LABEL] ?? l.kind} · <ExtLink href={l.url} />
                    </td>
                    <td className={l.error ? "w-bad" : ""}>{l.error ? l.error : l.changes ? `${l.changes} new changes` : "Saved, no changes"}</td>
                    <td>{l.cost ? `$${l.cost.toFixed(3)}` : "free"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">Not collected yet.</p>
        )}
      </section>
    </>
  );
}
