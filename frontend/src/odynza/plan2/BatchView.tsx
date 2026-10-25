/* M2 Content · one batch from a Radar plan in 7 tabs: Overview, LinkedIn, Instagram, Facebook, Media buying,
   Posting calendar and Performance. Drafts are shown the way they will look once posted. */
import { useCallback, useEffect, useMemo, useState } from "react";
import { download, request } from "../../api";
import { ItemCard, runActive } from "../../components/ItemCard";
import { useToast } from "../../components/Toast";
import { safePath, saveFile } from "../../format";
import type { ContentItem, ItemStatus, Platform } from "../../types";
import { DraftCard, PlannedAd, type Who } from "../../watch/PlatformCard";
import { PlatformGlyph } from "../../watch/Visuals";
import { Results } from "./Results";
import type { MediaBuying, RadarPlanDetail, RadarRunDetail } from "./types";
import { Card, fmtDate, List, money, Tabs, Tile } from "./ui";

type Tab = "overview" | Platform | "buying" | "calendar" | "performance";
const PLATFORMS: Platform[] = ["LinkedIn", "Instagram", "Facebook"];
const FORMAT: Record<string, string> = { post: "Post", carousel: "Carousel", document: "Document", reel: "Reel", story: "Story" };
const STATUS: Record<ItemStatus, string> = { draft: "To review", approved: "Approved", rejected: "Rejected", posted: "Posted" };

export function BatchView({ runId, canEdit, onBack, onDeleted, onAgain }: { runId: string; canEdit: boolean; onBack: () => void; onDeleted: () => void; onAgain?: () => void }) {
  const toast = useToast();
  const [run, setRun] = useState<RadarRunDetail | null>(null);
  const [plan, setPlan] = useState<RadarPlanDetail | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("overview");
  const load = useCallback(async () => {
    try {
      const r = await request<RadarRunDetail>(`/content/runs/${encodeURIComponent(runId)}`);
      setRun(r);
      setError("");
      if (!plan || plan.plan_id !== r.plan_id) setPlan(await request<RadarPlanDetail>(`/strategy/radar/plans/${r.plan_id}`).catch(() => null));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [runId, plan]);
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);
  const waiting = Boolean(run && (runActive(run.status) || run.items.some((i) => i.image_status === "pending")));
  useEffect(() => {
    if (!waiting) return;
    const t = window.setInterval(() => !document.hidden && load(), 5000);
    return () => window.clearInterval(t);
  }, [waiting, load]);

  const replace = (item: ContentItem) => setRun((r) => (r ? { ...r, items: r.items.map((i) => (i.id === item.id ? item : i)) } : r));
  async function zip(approved: boolean) {
    try {
      const { blob, name } = await download(`/content/runs/${runId}/download?approved_only=${approved}`, "The download failed.");
      saveFile(blob, name || "radar-content.zip");
    } catch (e) {
      toast((e as Error).message);
    }
  }
  async function remove() {
    if (!window.confirm("Delete this content batch with its images and videos? This cannot be undone.")) return;
    try {
      await request(`/content/runs/${runId}`, { method: "DELETE" });
      onDeleted();
    } catch (e) {
      toast((e as Error).message);
    }
  }

  if (error) return <div className="alert">{error}</div>;
  if (!run) return <div className="loading-state">Opening the batch…</div>;
  const who: Who = { name: run.company_name, logo: "client" };
  const tabs: [Tab, string][] = [
    ["overview", "Overview"],
    ...PLATFORMS.filter((p) => run.platforms.includes(p)).map((p) => [p, `${p} (${run.items.filter((i) => i.platform === p).length})`] as [Tab, string]),
    ["buying", "Media buying"], ["calendar", "Posting calendar"], ["performance", "Performance"],
  ];
  return (
    <div className="p2 p2-batch">
      <button className="p2-back" onClick={onBack}>← All batches</button>
      <header className="p2-head p2-plan-head">
        <div>
          <span className="p2-kicker">M2 Content · {fmtDate(run.start_date, { day: "numeric", month: "short" })} to {fmtDate(run.end_date, { day: "numeric", month: "short", year: "numeric" })}</span>
          <h2>{plan?.plan?.overview.big_idea || run.company_name}</h2>
          <div className="p2-meta">
            <span>{run.total} drafts</span>
            <span>{run.counts.approved} approved · {run.counts.draft} to review</span>
            {run.voices ? PLATFORMS.filter((p) => run.voices?.[p]).map((p) => <span key={p} className="p2-vchip"><PlatformGlyph kind={p.toLowerCase()} size={14} /> {run.voices?.[p].label}</span>) : null}
          </div>
        </div>
        <div className="p2-head-actions">
          {canEdit && onAgain ? <button className="button secondary" disabled={runActive(run.status)} onClick={onAgain}>Run again</button> : null}
          <button className="button secondary" disabled={!run.items.length} onClick={() => zip(false)}>All drafts ↓</button>
          <button className="button primary" disabled={!run.counts.approved} onClick={() => zip(true)}>Approved ({run.counts.approved}) ↓</button>
        </div>
      </header>
      {runActive(run.status) ? (
        <div className="p2-wait">
          <span className="p2-pulse" aria-hidden="true" />
          <div><b>The content agents are writing in n8n</b><p>LinkedIn → Instagram → Facebook → Media buying. This page refreshes by itself.</p></div>
        </div>
      ) : run.status === "failed" ? (
        <div className="alert">{run.error || "The drafts could not be written."} Open the latest execution of “Odynza Radar Content” in n8n to see which agent stopped.</div>
      ) : (
        <>
          <Tabs tabs={tabs} value={tab} onChange={setTab} label="Batch sections" />
          <div className="p2-pane" role="tabpanel">
            {tab === "overview" ? <Overview run={run} buying={run.media_buying} who={who} onTab={setTab} />
              : tab === "buying" ? <Buying m={run.media_buying} run={run} who={who} />
              : tab === "calendar" ? <PostingCalendar run={run} />
              : tab === "performance" ? (plan?.plan ? <Results planId={run.plan_id} plan={plan.plan} canEdit={canEdit} /> : <p className="p2-fine">The plan of this batch is missing.</p>)
              : <Drafts items={run.items.filter((i) => i.platform === tab)} who={who} canEdit={canEdit} onChange={replace} />}
          </div>
          {run.missing_slots.length ? <p className="p2-fine">The agents skipped {run.missing_slots.length} slot(s): {run.missing_slots.join(", ")}.</p> : null}
          {canEdit ? <button className="p2-delete" onClick={remove}>Delete batch</button> : null}
        </>
      )}
    </div>
  );
}

const when = (i: ContentItem) => `${fmtDate(i.date, { weekday: "short", day: "numeric", month: "short" })}${(i.content as { time?: string }).time ? " · " + (i.content as { time?: string }).time : ""}`;

function Preview({ item, who }: { item: ContentItem; who: Who }) {
  const c = item.content;
  return <DraftCard who={who} d={{ platform: item.platform, format: item.format, text: c.text, hashtags: c.hashtags, slides: c.slides, slideImages: (item.slide_urls ?? []).map((u) => safePath(u) || null), image: item.image_url, onImage: c.on_image_text, when: when(item) }} />;
}

function Drafts({ items, who, canEdit, onChange }: { items: ContentItem[]; who: Who; canEdit: boolean; onChange: (i: ContentItem) => void }) {
  const toast = useToast();
  async function status(item: ContentItem, s: ItemStatus) {
    try {
      onChange(await request<ContentItem>(`/content/items/${item.id}`, { method: "PATCH", body: JSON.stringify({ status: s }) }));
    } catch (e) {
      toast((e as Error).message);
    }
  }
  if (!items.length) return <p className="p2-fine">No drafts for this platform in this batch.</p>;
  return (
    <div className="p2-drafts">
      {items.map((item) => (
        <article key={item.id} className={"p2-draft s-" + item.status}>
          <div className="p2-draft-look"><Preview item={item} who={who} /></div>
          <div className="p2-draft-side">
            <span className="p2-kicker">{when(item)} · {FORMAT[item.format]}{item.content.campaign_name ? ` · ${item.content.campaign_name}` : ""}</span>
            <span className={"p2-status s-" + item.status}>{STATUS[item.status]}</span>
            {item.content.why ? <p className="p2-fine">Why: {item.content.why}</p> : null}
            {item.content.checks?.length ? <List items={item.content.checks} /> : null}
            {canEdit ? (
              <div className="p2-draft-actions">
                <button className="button primary" disabled={item.status === "approved"} onClick={() => status(item, "approved")}>Approve</button>
                <button className="button secondary" disabled={item.status === "rejected"} onClick={() => status(item, "rejected")}>Reject</button>
                {item.status === "approved" ? <button className="button secondary" onClick={() => status(item, "posted")}>Mark posted</button> : null}
              </div>
            ) : null}
            <details className="p2-edit">
              <summary>Edit text, picture and prompts</summary>
              <ItemCard item={item} canEdit={canEdit} onChange={onChange} />
            </details>
          </div>
        </article>
      ))}
    </div>
  );
}

function Overview({ run, buying, who, onTab }: { run: RadarRunDetail; buying?: MediaBuying | null; who: Who; onTab: (t: Tab) => void }) {
  const next = [...run.items].filter((i) => i.status !== "rejected").sort((a, b) => a.date.localeCompare(b.date)).slice(0, 3);
  const paid = buying ? Object.values(buying.budget).reduce((a, b) => a + b, 0) : 0;
  return (
    <div className="p2-stack">
      <div className="p2-tiles">
        {PLATFORMS.filter((p) => run.platforms.includes(p)).map((p) => {
          const mine = run.items.filter((i) => i.platform === p);
          return <Tile key={p} label={p} value={mine.length} sub={`${mine.filter((i) => i.status === "approved").length} approved · ${mine.filter((i) => i.format === "reel").length} reels${p === "Instagram" ? ` · ${mine.filter((i) => i.format === "story").length} stories` : ""}`} />;
        })}
        <Tile tone="accent" label="Paid plan" value={buying ? money(paid, buying.currency) : "—"} sub={buying ? `${buying.campaigns.length} campaigns · ${buying.campaigns.reduce((n, c) => n + c.ad_sets.length, 0)} ad sets` : "No media buying in this batch"} />
      </div>
      {buying?.summary ? <Card kicker="Paid plan in one line"><p className="p2-lead">{buying.summary}</p></Card> : null}
      <Card title="Coming up first">
        <div className="p2-feed">{next.map((i) => <button key={i.id} className="p2-feed-item" onClick={() => onTab(i.platform)}><Preview item={i} who={who} /></button>)}</div>
      </Card>
    </div>
  );
}

function Buying({ m, run, who }: { m?: MediaBuying | null; run: RadarRunDetail; who: Who }) {
  const bySlot = useMemo(() => Object.fromEntries(run.items.map((i) => [i.slot_id, i])), [run.items]);
  if (!m) return <p className="p2-fine">This batch has no media buying plan. Start a new batch with “Plan the paid ads too” ticked (the plan needs a Meta or LinkedIn ads budget).</p>;
  const cur = m.currency;
  return (
    <div className="p2-stack">
      <div className="p2-tiles">
        {Object.entries(m.budget).map(([k, v]) => <Tile key={k} label={k} value={money(v, cur)} sub={`${m.campaigns.filter((c) => c.platform === k).length} campaigns`} />)}
        <Tile label="A/B tests" value={m.ab_tests.length} />
      </div>
      {m.campaigns.map((c, ci) => (
        <Card key={ci} kicker={`${c.platform} · ${c.objective} · ${fmtDate(c.start_date)} to ${fmtDate(c.end_date)}`} title={c.name}>
          <p className="p2-fine">{money(c.amount, cur)} in total · {money(c.daily, cur)} a day{c.bidding ? ` · ${c.bidding}` : ""}</p>
          <div className="p2-scroll">
            <table className="p2-table">
              <thead><tr><th>Ad set</th><th>Who</th><th>Where</th><th>Ages</th><th>{/linkedin/i.test(c.platform) ? "Job titles" : "Interests"}</th><th>Placements</th><th className="num">A day</th></tr></thead>
              <tbody>
                {c.ad_sets.map((a) => (
                  <tr key={a.name}>
                    <th>{a.name}<small> · {a.optimization}</small></th><td>{a.audience}</td><td>{a.locations.join(", ")}</td><td>{a.ages}{a.gender ? ` · ${a.gender}` : ""}</td>
                    <td>{(/linkedin/i.test(c.platform) ? a.job_titles : a.interests).join(", ")}</td><td>{a.placements.join(", ")}</td>
                    <td className="num">{money(a.daily, cur)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="p2-ads">
            {c.ad_sets.flatMap((a) => a.ads.map((ad, i) => (
              <figure key={a.name + i}>
                <PlannedAd who={who} platform={c.platform} text={ad.primary_text} headline={ad.headline} cta={ad.cta} image={ad.draft_slot_id ? bySlot[ad.draft_slot_id]?.image_url : null} />
                <figcaption>{a.name} · {ad.name} · {ad.format}{ad.draft_slot_id ? " · uses a draft from this batch" : ""}</figcaption>
              </figure>
            )))}
          </div>
        </Card>
      ))}
      <div className="p2-two">
        <Card title="A/B tests">
          <table className="p2-table">
            <thead><tr><th>Test</th><th>A</th><th>B</th><th>Judge by</th></tr></thead>
            <tbody>{m.ab_tests.map((t) => <tr key={t.name}><th>{t.name}<small> · {t.variable}, {t.duration}</small></th><td dir="auto">{t.a}</td><td dir="auto">{t.b}</td><td>{t.metric}</td></tr>)}</tbody>
          </table>
        </Card>
        <Card title="Usual ranges">
          <table className="p2-table">
            <tbody>{m.benchmarks.map((b) => <tr key={b.platform + b.metric}><th>{b.platform}</th><td>{b.metric}</td><td><b>{b.range}</b></td><td className="p2-fine">{b.note}</td></tr>)}</tbody>
          </table>
        </Card>
      </div>
      <Card title="Before you launch">
        <ul className="p2-checklist">{m.checklist.map((x) => <li key={x}><label><input type="checkbox" /> {x}</label></li>)}</ul>
        {m.tracking.length ? <><h4>Tracking</h4><List items={m.tracking} /></> : null}
      </Card>
    </div>
  );
}

function PostingCalendar({ run }: { run: RadarRunDetail }) {
  const days = useMemo(() => {
    const out: string[] = [];
    if (!run.start_date) return out;
    const d = new Date(run.start_date + "T00:00:00");
    const end = run.end_date || run.start_date;
    while (d.toISOString().slice(0, 10) <= end) {
      out.push(d.toISOString().slice(0, 10));
      d.setDate(d.getDate() + 1);
    }
    return out;
  }, [run.start_date, run.end_date]);
  return (
    <div className="p2-week">
      {days.map((day) => {
        const items = run.items.filter((i) => i.date === day).sort((a, b) => String((a.content as { time?: string }).time).localeCompare(String((b.content as { time?: string }).time)));
        return (
          <section key={day} className="p2-day">
            <h4>{fmtDate(day, { weekday: "short", day: "numeric", month: "short" })}</h4>
            {items.length ? items.map((i) => (
              <div key={i.id} className={"p2-slot s-" + i.status}>
                <PlatformGlyph kind={i.platform.toLowerCase()} size={14} />
                <b>{(i.content as { time?: string }).time || ""}</b>
                <span>{FORMAT[i.format]}</span>
                <small dir="auto">{i.content.hook || i.content.text.slice(0, 60)}</small>
              </div>
            )) : <small className="p2-fine">Nothing planned</small>}
          </section>
        );
      })}
    </div>
  );
}
