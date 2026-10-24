/* M1 Strategy · one Radar plan in 11 tabs: Overview, Competitive brief, Positioning, Campaigns, Calendar, Content plan,
   Channels and budget, KPIs, Results, Creative ideas, Risks and next steps. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { json, request, send } from "../../api";
import { useToast } from "../../components/Toast";
import type { Platform } from "../../types";
import { Logo } from "../../watch/parts";
import { PlatformGlyph } from "../../watch/Visuals";
import type { Campaign, RadarEvent, RadarPlan, RadarPlanDetail } from "./types";
import { Results } from "./Results";
import { Bar, Card, fmtDate, KIND_LABEL, List, money, Tabs, Tile } from "./ui";

type Tab = "overview" | "brief" | "positioning" | "campaigns" | "calendar" | "content" | "budget" | "kpis" | "results" | "ideas" | "risks";
const TABS: [Tab, string][] = [
  ["overview", "Overview"], ["brief", "Competitive brief"], ["positioning", "Positioning"], ["campaigns", "Campaigns"],
  ["calendar", "Calendar"], ["content", "Content plan"], ["budget", "Channels and budget"], ["kpis", "KPIs"],
  ["results", "Results"], ["ideas", "Creative ideas"], ["risks", "Risks and next steps"],
];
const PLATFORMS: Platform[] = ["LinkedIn", "Instagram", "Facebook"];
const active = (s?: string) => s === "queued" || s === "running";

export function PlanView({ planId, canEdit, onBack, onMakeContent, onDeleted }: { planId: string; canEdit: boolean; onBack: () => void; onMakeContent: (id: string) => void; onDeleted: () => void }) {
  const toast = useToast();
  const [detail, setDetail] = useState<RadarPlanDetail | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("overview");
  const [printing, setPrinting] = useState(false);

  const load = useCallback(async () => {
    try {
      setDetail(await request<RadarPlanDetail>(`/strategy/radar/plans/${encodeURIComponent(planId)}`));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [planId]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (!active(detail?.status)) return;
    const t = window.setInterval(() => !document.hidden && load(), 5000);
    return () => window.clearInterval(t);
  }, [detail?.status, load]);
  useEffect(() => {
    if (!printing) return;
    const t = window.setTimeout(() => {
      window.print();
      setPrinting(false);
    }, 300);
    return () => window.clearTimeout(t);
  }, [printing]);

  async function remove() {
    if (!window.confirm("Delete this strategy plan and its typed results? This cannot be undone.")) return;
    try {
      await request(`/strategy/plans/${encodeURIComponent(planId)}`, { method: "DELETE" });
      toast("Plan deleted.");
      onDeleted();
    } catch (e) {
      toast((e as Error).message);
    }
  }

  if (error) return <div className="alert">{error}</div>;
  if (!detail) return <div className="loading-state">Opening the plan…</div>;
  const inp = detail.inputs;
  const voices = inp.voices;
  const p = detail.plan;
  return (
    <div className={"p2 p2-plan" + (printing ? " printing" : "")}>
      <button className="p2-back" onClick={onBack}>← All plans</button>
      <header className="p2-head p2-plan-head">
        <div>
          <span className="p2-kicker">
            M1 Strategy · {detail.status === "completed" ? "Plan ready" : active(detail.status) ? "Writing in n8n" : "Failed"} · {fmtDate(inp.start_date, { day: "numeric", month: "short", year: "numeric" })} to {fmtDate(inp.end_date, { day: "numeric", month: "short", year: "numeric" })}
          </span>
          <h2>{p?.overview.big_idea || detail.company_name}</h2>
          <div className="p2-meta">
            <span>Goal: {inp.goal}</span>
            <span>{inp.budget ? `${money(inp.budget as number, String(inp.currency))} a month` : "No budget given"}</span>
            {voices ? PLATFORMS.map((pl) => voices[pl] ? <span key={pl} className="p2-vchip"><PlatformGlyph kind={pl.toLowerCase()} size={14} /> {voices[pl].label}</span> : null) : null}
          </div>
        </div>
        <div className="p2-head-actions">
          {p ? <button className="button secondary" onClick={() => setPrinting(true)}>Print or save PDF</button> : null}
          {p && canEdit ? <button className="button primary" onClick={() => onMakeContent(planId)}>Make content from this plan</button> : null}
        </div>
      </header>

      {active(detail.status) ? (
        <div className="p2-wait">
          <span className="p2-pulse" aria-hidden="true" />
          <div>
            <b>Five agents are writing the plan in n8n</b>
            <p>Competitive brief → Positioning → Campaigns and creative → Calendar and content plan → Budget, KPIs and overview. This page refreshes by itself.</p>
          </div>
        </div>
      ) : detail.status === "failed" || !p ? (
        <div className="alert">
          {detail.error || "The plan could not be written."}
          {detail.validation_errors?.length ? <ul>{detail.validation_errors.map((x) => <li key={x}>{x}</li>)}</ul> : null}
          <p>Open the latest execution of “Odynza Radar Strategy” in n8n to see which node stopped, then start a new plan.</p>
        </div>
      ) : (
        <>
          <Tabs tabs={TABS} value={tab} onChange={setTab} label="Plan sections" />
          {(printing ? TABS.map((t) => t[0]) : [tab]).map((t) => (
            <div key={t} className="p2-pane" role="tabpanel">
              {printing ? <h2 className="p2-print-title">{TABS.find((x) => x[0] === t)?.[1]}</h2> : null}
              <Pane tab={t} plan={p} detail={detail} canEdit={canEdit} onVisual={load} onSaved={setDetail} />
            </div>
          ))}
          {p.notes?.length ? <p className="p2-fine p2-notes">Fixed by Radar before saving: {p.notes.join(" ")}</p> : null}
          {canEdit ? <button className="p2-delete" onClick={remove}>Delete plan</button> : null}
        </>
      )}
    </div>
  );
}

function Pane({ tab, plan, detail, canEdit, onVisual, onSaved }: { tab: Tab; plan: RadarPlan; detail: RadarPlanDetail; canEdit: boolean; onVisual: () => void; onSaved: (d: RadarPlanDetail) => void }) {
  switch (tab) {
    case "overview": return <Overview plan={plan} />;
    case "brief": return <Brief plan={plan} client={detail.company_name} logos={detail.logos} />;
    case "positioning": return <Positioning plan={plan} />;
    case "campaigns": return <Campaigns plan={plan} detail={detail} canEdit={canEdit} onVisual={onVisual} />;
    case "calendar": return <Calendar plan={plan} detail={detail} canEdit={canEdit} onSaved={onSaved} />;
    case "content": return <ContentPlan plan={plan} />;
    case "budget": return <Budget plan={plan} />;
    case "kpis": return <Kpis plan={plan} />;
    case "results": return <Results planId={detail.plan_id} plan={plan} canEdit={canEdit} />;
    case "ideas": return <Ideas plan={plan} />;
    case "risks": return <Risks plan={plan} />;
  }
}

function Overview({ plan }: { plan: RadarPlan }) {
  const o = plan.overview;
  const b = plan.competitive_brief;
  const ads = plan.budget.filter((l) => /ads/i.test(l.channel)).reduce((n, l) => n + (l.amount || 0), 0);
  return (
    <div className="p2-stack">
      <div className="p2-tiles">
        <Tile tone="accent" label="Main target" value={o.north_star_target || "—"} sub={o.north_star} />
        <Tile label="Total budget" value={money(plan.budget_total, plan.currency)} sub={ads ? `${money(ads, plan.currency)} on ads` : undefined} />
        <Tile label="Campaigns" value={plan.campaigns.length} sub={plan.campaigns.map((c) => c.name).join(" · ")} />
        <Tile label="SMART goal" value={<span className="p2-small">{o.smart_goal}</span>} />
      </div>
      <Card kicker="The plan in one paragraph"><p className="p2-lead">{o.summary}</p></Card>
      <div className="p2-two">
        <Card kicker="Biggest opening" className="good"><p>{b.biggest_opportunity}</p></Card>
        <Card kicker="Biggest threat" className="bad"><p>{b.biggest_threat}</p></Card>
      </div>
      <div className="p2-two">
        <Card kicker="Highlights"><List items={o.highlights} /></Card>
        <Card kicker="First steps"><List items={plan.next_steps.slice(0, 4).map((s) => <><b>{s.when}</b> {s.step} <small>({s.owner})</small></>)} /></Card>
      </div>
    </div>
  );
}

// Finds the saved logo for a company name the plan uses (names can be shortened by the agents).
function logoFor(logos: RadarPlanDetail["logos"], name: string): string | number | null {
  if (!logos) return null;
  const n = name.trim().toLowerCase();
  if (!n) return null;
  for (const [k, id] of Object.entries(logos)) {
    const l = k.trim().toLowerCase();
    if (l && (l === n || l.startsWith(n) || n.startsWith(l))) return id;
  }
  return null;
}

function CoLogo({ logos, name, size = 22 }: { logos: RadarPlanDetail["logos"]; name: string; size?: number }) {
  const id = logoFor(logos, name);
  return id == null ? null : <Logo id={id} name={name} size={size} />;
}

function Brief({ plan, client, logos }: { plan: RadarPlan; client: string; logos: RadarPlanDetail["logos"] }) {
  const b = plan.competitive_brief;
  const map = b.positioning_map;
  return (
    <div className="p2-stack">
      <Card kicker="The market"><p className="p2-lead">{b.landscape}</p></Card>
      <div className="p2-rivals">
        {b.rivals.map((r) => (
          <article key={r.name} className={"p2-rival t-" + (r.threat || "").toLowerCase()}>
            <header>
              {logoFor(logos, r.name) != null ? <Logo id={logoFor(logos, r.name)!} name={r.name} size={36} /> : <span className="p2-initial">{r.name.slice(0, 1)}</span>}
              <span><b>{r.name}</b><small>{r.tier} · threat {r.threat || "?"}</small></span>
            </header>
            <p>{r.positioning}</p>
            {r.tagline ? <p className="p2-quote">“{r.tagline}”</p> : null}
            <p><b>Strong:</b> {r.strengths.join("; ") || "—"}</p>
            <p><b>Weak:</b> {r.weaknesses.join("; ") || "—"}</p>
            {r.recent_moves.length ? <p><b>Latest moves:</b> {r.recent_moves.join("; ")}</p> : null}
          </article>
        ))}
      </div>
      {b.messaging_matrix.length ? (
        <Card title="Messaging matrix">
          <div className="p2-scroll">
            <table className="p2-table">
              <thead><tr><th>Dimension</th>{b.messaging_matrix.map((m) => <th key={m.company} className={m.you ? "you" : ""}><span className="p2-co"><CoLogo logos={logos} name={m.company} />{m.company}</span></th>)}</tr></thead>
              <tbody>
                {([["tagline", "Tagline"], ["target_buyer", "Buyer"], ["value_prop", "Promise"], ["differentiator", "Difference"], ["tone", "Tone"]] as const).map(([k, l]) => (
                  <tr key={k}><th>{l}</th>{b.messaging_matrix.map((m) => <td key={m.company} className={m.you ? "you" : ""} dir="auto">{m[k]}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
      <div className="p2-two">
        <Card title="Positioning map">
          <div className="p2-map" role="img" aria-label={`Positioning map: ${map.x_low} to ${map.x_high} across, ${map.y_low} to ${map.y_high} up`}>
            <span className="ax x0">{map.x_low}</span><span className="ax x1">{map.x_high}</span>
            <span className="ax y0">{map.y_low}</span><span className="ax y1">{map.y_high}</span>
            {map.points.map((pt) => (
              <span key={pt.company} className={"pt" + (pt.you || pt.company === client ? " you" : "")} style={{ left: `${pt.x}%`, bottom: `${pt.y}%` }}>
                {logoFor(logos, pt.company) != null ? <Logo id={logoFor(logos, pt.company)!} name={pt.company} size={20} /> : <i />}{pt.company}
              </span>
            ))}
          </div>
          {map.open_space ? <p className="p2-fine"><b>Open space:</b> {map.open_space}</p> : null}
        </Card>
        <Card title="Content gaps">
          <List items={b.content_gaps.map((g) => <><b>{g.topic}</b>{g.who ? <small> · {g.who}</small> : null}<br />{g.action}</>)} empty="No gaps found yet." />
        </Card>
      </div>
      <Card title={<span className="p2-co"><CoLogo logos={logos} name={b.battlecard.rival} size={24} />Battlecard · when a lead mentions {b.battlecard.rival}</span>}>
        <p><b>Their pitch:</b> {b.battlecard.their_pitch}</p>
        <p><b>Our edge:</b> {b.battlecard.our_edge.join(" · ")}</p>
        <table className="p2-table">
          <thead><tr><th>If they say</th><th>Answer with</th></tr></thead>
          <tbody>{b.battlecard.objections.map((o) => <tr key={o.they_say}><td>“{o.they_say}”</td><td>{o.we_say}</td></tr>)}</tbody>
        </table>
        {b.battlecard.landmines.length ? <><h4>Questions to ask</h4><List items={b.battlecard.landmines} /></> : null}
      </Card>
    </div>
  );
}

function Positioning({ plan }: { plan: RadarPlan }) {
  const p = plan.positioning;
  return (
    <div className="p2-stack">
      <Card kicker="Positioning statement" className="p2-statement">
        <p className="p2-lead">{p.statement}</p>
        {p.statement_ar ? <p className="p2-ar" dir="rtl" lang="ar">{p.statement_ar}</p> : null}
        {p.core_message ? <p className="p2-core">{p.core_message}</p> : null}
      </Card>
      <div className="p2-three">
        {p.pillars.map((x, i) => (
          <Card key={x.name} kicker={`Pillar ${i + 1}`} title={x.name}>
            <p>{x.message}</p>
            <p className="p2-proof">Proof: {x.proof}</p>
          </Card>
        ))}
      </div>
      <Card title="The message on each platform, in the voice you picked">
        <table className="p2-table">
          <thead><tr><th>Platform</th><th>Voice</th><th>Language</th><th>Main line</th></tr></thead>
          <tbody>
            {p.by_platform.map((r) => (
              <tr key={r.platform}>
                <th><PlatformGlyph kind={r.platform.toLowerCase()} size={16} /> {r.platform}</th>
                <td>{r.voice}</td><td>{r.language}</td>
                <td dir="auto" className="p2-line">{r.line}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function Visual({ planId, c, has, canEdit, onDone }: { planId: string; c: Campaign; has: boolean; canEdit: boolean; onDone: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [v, setV] = useState(0);
  const file = useRef<HTMLInputElement>(null);
  const src = `/strategy/plans/${planId}/visuals/${c.id}?v=${v}`;
  async function make() {
    setBusy(true);
    try {
      await request(`/strategy/plans/${planId}/visuals/${c.id}`, json({}));
      setV(Date.now());
      onDone();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function upload(f: File) {
    setBusy(true);
    try {
      const r = await send(`/strategy/plans/${planId}/visuals/${c.id}`, { method: "PUT", body: f, headers: { "Content-Type": f.type || "application/octet-stream" } });
      if (!r.ok) throw new Error("The picture was not accepted. Use PNG, JPEG or WebP under 15 MB.");
      setV(Date.now());
      onDone();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="p2-visual">
      {has || v ? <img src={src} alt={`Key visual for ${c.name}`} /> : <div className="p2-visual-empty"><span>Key visual · FLUX</span><small>{c.visual_prompt}</small></div>}
      {canEdit ? (
        <div className="p2-visual-actions">
          <button className="button secondary" disabled={busy} onClick={make}>{busy ? "Making…" : has || v ? "Make again" : "Make key visual"}</button>
          <button className="button secondary" disabled={busy} onClick={() => file.current?.click()}>Upload</button>
          <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        </div>
      ) : null}
    </div>
  );
}

function Campaigns({ plan, detail, canEdit, onVisual }: { plan: RadarPlan; detail: RadarPlanDetail; canEdit: boolean; onVisual: () => void }) {
  return (
    <div className="p2-campaigns">
      {plan.campaigns.map((c) => (
        <article key={c.id} className="p2-campaign">
          <Visual planId={detail.plan_id} c={c} has={detail.visuals.includes(c.id)} canEdit={canEdit} onDone={onVisual} />
          <div className="p2-campaign-body">
            <span className="p2-kicker">{c.id} · {fmtDate(c.start_date)} to {fmtDate(c.end_date)}{c.event ? ` · rides ${c.event}` : ""}</span>
            <h3>{c.name}</h3>
            <p>{c.idea}</p>
            <dl className="p2-dl">
              <dt>Goal</dt><dd>{c.goal}</dd>
              <dt>Budget</dt><dd>{money(c.amount, plan.currency)} <small>({c.budget_percent}%)</small></dd>
              <dt>Audience</dt><dd>{c.audience}</dd>
              <dt>Channels</dt><dd>{c.channels.join(", ")}</dd>
              {c.offer ? <><dt>Offer</dt><dd>{c.offer}</dd></> : null}
              {c.kpi ? <><dt>Judged by</dt><dd>{c.kpi}</dd></> : null}
            </dl>
            <p className="p2-hook"><b>Hook:</b> {c.hook}</p>
            {c.hook_ar ? <p className="p2-hook p2-ar" dir="rtl" lang="ar">{c.hook_ar}</p> : null}
          </div>
        </article>
      ))}
    </div>
  );
}

function months(plan: RadarPlan) {
  return plan.by_month.map((m) => {
    const first = m.month + "-01";
    const [y, mo] = m.month.split("-").map(Number);
    const last = new Date(y, mo, 0).toISOString().slice(0, 10);
    const items = plan.calendar.filter((e) => e.date.slice(0, 7) === m.month || (e.kind === "campaign" && e.date <= last && (e.end_date || e.date) >= first));
    return { ...m, items };
  });
}

const KINDS = ["campaign", "content", "milestone", "shopping", "tech", "holiday", "season"];
type Draft = { date: string; end_date: string; title: string; kind: string; note: string; campaign_id: string };
const blank = (plan: RadarPlan, inputs: RadarPlanDetail["inputs"]): Draft => ({
  date: inputs.start_date || plan.by_month[0]?.month + "-01", end_date: "", title: "", kind: "content", note: "", campaign_id: "",
});

function Calendar({ plan, detail, canEdit, onSaved }: { plan: RadarPlan; detail: RadarPlanDetail; canEdit: boolean; onSaved: (d: RadarPlanDetail) => void }) {
  const toast = useToast();
  const ms = useMemo(() => months(plan), [plan]);
  const kinds = Array.from(new Set(plan.calendar.map((e) => e.kind)));
  const [hide, setHide] = useState<string[]>([]);
  // editing: index into plan.calendar, -1 for a new date, null when the form is closed.
  const [editing, setEditing] = useState<number | null>(null);
  const [f, setF] = useState<Draft>(blank(plan, detail.inputs));
  const [busy, setBusy] = useState(false);

  async function save(entries: RadarEvent[], done: string) {
    setBusy(true);
    try {
      const d = await request<RadarPlanDetail>(`/strategy/radar/plans/${encodeURIComponent(detail.plan_id)}/calendar`, {
        method: "PUT",
        body: JSON.stringify({ entries: entries.map((e) => ({ ...e, end_date: e.end_date || null, note: e.note || "", campaign_id: e.campaign_id || "", channel: e.channel || "", source: e.source || "you" })) }),
      });
      onSaved(d);
      setEditing(null);
      toast(done);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const open = (i: number) => {
    const e = i >= 0 ? plan.calendar[i] : null;
    setF(e ? { date: e.date, end_date: e.end_date || "", title: e.title, kind: e.kind, note: e.note || "", campaign_id: e.campaign_id || "" } : blank(plan, detail.inputs));
    setEditing(i);
  };
  function submit() {
    const row: RadarEvent = { ...(editing !== null && editing >= 0 ? plan.calendar[editing] : { confirmed: true, source: "you" }), ...f, end_date: f.end_date || null };
    const list = editing !== null && editing >= 0 ? plan.calendar.map((e, i) => (i === editing ? row : e)) : [...plan.calendar, row];
    save(list, editing !== null && editing >= 0 ? "Date updated." : "Date added.");
  }
  function remove(i: number) {
    const e = plan.calendar[i];
    if (!window.confirm(`Remove "${e.title}" from the calendar?`)) return;
    save(plan.calendar.filter((_, j) => j !== i), "Date removed.");
  }
  const indexOf = (e: RadarEvent) => plan.calendar.indexOf(e);

  return (
    <div className="p2-stack">
      <div className="p2-legend" role="group" aria-label="Show event kinds">
        {kinds.map((k) => (
          <label key={k} className={"p2-ev k-" + k + (hide.includes(k) ? " off" : "")}>
            <input type="checkbox" checked={!hide.includes(k)} onChange={() => setHide(hide.includes(k) ? hide.filter((x) => x !== k) : [...hide, k])} />
            {KIND_LABEL[k] || k}
          </label>
        ))}
        <span className="p2-fine">* date to confirm</span>
        {canEdit ? <button className="button primary p2-cal-add" onClick={() => open(-1)}>+ Add a date</button> : null}
      </div>
      {editing !== null ? (
        <form className="p2-box p2-cal-form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <h3>{editing >= 0 ? "Change this date" : "Add a date"}</h3>
          <div className="p2-cal-grid">
            <label>Date<input type="date" required value={f.date} min={detail.inputs.start_date} max={detail.inputs.end_date} onChange={(e) => setF({ ...f, date: e.target.value })} /></label>
            <label>Ends (optional)<input type="date" value={f.end_date} min={f.date} max={detail.inputs.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} /></label>
            <label>Kind
              <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{KINDS.map((k) => <option key={k} value={k}>{KIND_LABEL[k] || k}</option>)}</select>
            </label>
            <label>Campaign
              <select value={f.campaign_id} onChange={(e) => setF({ ...f, campaign_id: e.target.value })}>
                <option value="">None</option>{plan.campaigns.map((c) => <option key={c.id} value={c.id}>{c.id} · {c.name}</option>)}
              </select>
            </label>
            <label className="wide">What happens<input required maxLength={200} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Webinar: the 2am Test live" /></label>
            <label className="wide">Note (optional)<input maxLength={400} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} placeholder="Book the room by 1 Dec" /></label>
          </div>
          <div className="p2-actions">
            <button type="button" className="button secondary" onClick={() => setEditing(null)}>Cancel</button>
            <button className="button primary" disabled={busy || !f.title.trim() || !f.date}>{busy ? "Saving…" : "Save"}</button>
          </div>
          <p className="p2-fine">Content batches made after this read the new calendar.</p>
        </form>
      ) : null}
      <div className="p2-months">
        {ms.map((m) => (
          <section key={m.month} className="p2-month">
            <h3>{m.label} <small>{money(m.amount, plan.currency)}</small></h3>
            <ul>
              {m.items.filter((e) => !hide.includes(e.kind)).map((e: RadarEvent, i) => (
                <li key={i} className={"k-" + e.kind}>
                  <b>{fmtDate(e.date)}{e.end_date && e.end_date !== e.date ? `–${fmtDate(e.end_date)}` : ""}{e.confirmed ? "" : " *"}</b>
                  <span>{e.title}{e.note && e.kind !== "campaign" ? <small>{e.note}</small> : null}</span>
                  <em>
                    {KIND_LABEL[e.kind] || e.kind}{e.source === "you" ? " · added by you" : ""}
                    {canEdit ? (
                      <span className="p2-cal-tools">
                        <button type="button" className="p2-link" onClick={() => open(indexOf(e))} aria-label={`Change ${e.title}`}>Change</button>
                        <button type="button" className="p2-link danger" onClick={() => remove(indexOf(e))} aria-label={`Remove ${e.title}`}>Remove</button>
                      </span>
                    ) : null}
                  </em>
                </li>
              ))}
              {!m.items.length ? <li className="p2-cal-empty">Nothing planned yet.</li> : null}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

function ContentPlan({ plan }: { plan: RadarPlan }) {
  const cp = plan.content_plan;
  return (
    <div className="p2-stack">
      <Card title="Content mix">
        <div className="p2-mix" role="img" aria-label={cp.mix.map((m) => `${m.label} ${m.percent}%`).join(", ")}>
          {cp.mix.map((m, i) => <span key={m.label} className={"m" + (i % 6)} style={{ flex: m.percent }}>{m.label} {m.percent}%</span>)}
        </div>
      </Card>
      <Card title="Weekly rhythm">
        <table className="p2-table">
          <thead><tr><th>Platform</th><th>Posts a week</th><th>Formats</th><th>Best times (Cairo)</th><th>Themes</th><th>Voice</th></tr></thead>
          <tbody>
            {cp.rhythm.map((r) => (
              <tr key={r.platform}>
                <th><PlatformGlyph kind={r.platform.toLowerCase()} size={16} /> {r.platform}</th>
                <td>{r.per_week}</td><td>{r.formats.join(", ")}</td><td>{r.best_slots.join(", ")}</td><td>{r.themes.join(", ")}</td>
                <td>{r.voice} <small>({r.language})</small></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <div className="p2-three">
        {(cp.gaps.length ? cp.gaps : plan.competitive_brief.content_gaps).slice(0, 6).map((g, i) => (
          <Card key={i} kicker={`Gap ${i + 1}`} title={g.topic}><p>{g.action}</p>{g.who ? <p className="p2-fine">{g.who}</p> : null}</Card>
        ))}
      </div>
    </div>
  );
}

function Budget({ plan }: { plan: RadarPlan }) {
  const max = Math.max(...plan.by_month.map((m) => m.amount || 0), 1);
  return (
    <div className="p2-stack">
      <Card title={`Where the ${money(plan.budget_total, plan.currency)} goes`}>
        <table className="p2-table">
          <thead><tr><th>Line</th><th>Role</th><th className="num">{plan.currency}</th><th>Share</th></tr></thead>
          <tbody>
            {plan.budget.map((b) => (
              <tr key={b.channel}><th>{b.channel}</th><td>{b.purpose}</td><td className="num">{money(b.amount)}</td><td><Bar value={b.percent} /> {b.percent}%</td></tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title="By month">
        <div className="p2-bymonth">
          {plan.by_month.map((m) => (
            <div key={m.month}>
              <b>{m.label}</b>
              <Bar value={m.amount || 0} max={max} />
              <span>{money(m.amount, plan.currency)}</span>
              <small>{m.campaigns.join(" · ") || "No campaign running"}</small>
            </div>
          ))}
        </div>
        <p className="p2-fine">Amounts are worked out by Radar from your monthly budget; the agents only chose the shares.</p>
      </Card>
    </div>
  );
}

function Kpis({ plan }: { plan: RadarPlan }) {
  const names = Object.fromEntries(plan.campaigns.map((c) => [c.id, c.name]));
  return (
    <Card title="How we will know it works">
      <table className="p2-table">
        <thead><tr><th>KPI</th><th>Stage</th><th>Today</th><th>Target</th><th>Where it is measured</th><th>Check</th></tr></thead>
        <tbody>
          {plan.kpis.map((k) => (
            <tr key={k.name}>
              <th>{k.name}{k.campaign_id ? <small> · {names[k.campaign_id]}</small> : null}</th>
              <td>{k.stage}</td><td>{k.baseline}</td><td><b>{k.target}</b></td><td>{k.how}</td><td>{k.cadence}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function Ideas({ plan }: { plan: RadarPlan }) {
  return (
    <div className="p2-ideas">
      {plan.creative_ideas.map((i) => (
        <article key={i.title} className="p2-idea">
          <span className="p2-kicker"><PlatformGlyph kind={i.platform.toLowerCase()} size={14} /> {i.platform} · {i.format}</span>
          <h3>{i.title}</h3>
          <p>{i.description}</p>
          {i.why ? <p className="p2-fine">Why: {i.why}</p> : null}
        </article>
      ))}
    </div>
  );
}

function Risks({ plan }: { plan: RadarPlan }) {
  return (
    <div className="p2-stack">
      <Card title="Risks">
        <table className="p2-table">
          <thead><tr><th>Risk</th><th>Likelihood</th><th>What we do</th></tr></thead>
          <tbody>{plan.risks.map((r) => <tr key={r.risk}><td>{r.risk}</td><td>{r.likelihood}</td><td>{r.mitigation}</td></tr>)}</tbody>
        </table>
      </Card>
      <Card title="Next steps">
        <ol className="p2-steps">{plan.next_steps.map((s) => <li key={s.step}><b>{s.when}</b><span>{s.step}</span><small>{s.owner}</small></li>)}</ol>
      </Card>
      {plan.assumptions.length ? <Card title="Assumptions"><List items={plan.assumptions} /></Card> : null}
    </div>
  );
}

