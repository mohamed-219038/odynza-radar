/* Strategy · Results: the ad numbers typed by hand each week, and the rule-based report (wins, misses, next moves). */
import { useCallback, useEffect, useState } from "react";
import { json, request } from "../../api";
import { Select } from "../../components/Select";
import { useToast } from "../../components/Toast";
import type { RadarPlan, ResultsReport } from "./types";
import { Card, fmtDate, List, money, pct, Tile } from "./ui";

const PLATFORMS = ["Meta ads", "LinkedIn ads", "Instagram", "Facebook", "LinkedIn"];
const monday = () => {
  const d = new Date();
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
};

export function Results({ planId, plan, canEdit, compact = false }: { planId: string; plan: RadarPlan; canEdit: boolean; compact?: boolean }) {
  const toast = useToast();
  const [rep, setRep] = useState<ResultsReport | null>(null);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ week_start: monday(), platform: "Meta ads", campaign_id: "", spend: "", impressions: "", clicks: "", leads: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      setRep(await request<ResultsReport>(`/strategy/plans/${planId}/results`));
    } catch (e) {
      toast((e as Error).message);
    }
  }, [planId, toast]);
  useEffect(() => {
    load();
  }, [load]);

  async function save() {
    setBusy(true);
    try {
      const n = (v: string) => Number(v.replace(/,/g, "")) || 0;
      setRep(await request<ResultsReport>(`/strategy/plans/${planId}/results`, json({
        ...f, spend: n(f.spend), impressions: n(f.impressions), clicks: n(f.clicks), leads: n(f.leads),
      })));
      setF({ ...f, spend: "", impressions: "", clicks: "", leads: "", notes: "" });
      setOpen(false);
      toast("Saved. The report below is updated.");
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function remove(id: number) {
    try {
      setRep(await request<ResultsReport>(`/strategy/plans/${planId}/results/${id}`, { method: "DELETE" }));
    } catch (e) {
      toast((e as Error).message);
    }
  }

  if (!rep) return <div className="loading-state">Reading the results…</div>;
  const t = rep.totals;
  const cur = rep.currency;
  const names = Object.fromEntries(plan.campaigns.map((c) => [c.id, c.name]));
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="p2-stack">
      <div className="p2-results-head">
        <p className="p2-fine">{rep.entries.length ? `From ${rep.entries.length} weekly entries you typed in, compared with the plan's KPIs and usual B2B ranges in MENA.` : "Type each week's numbers from Meta Ads Manager and LinkedIn Campaign Manager. The report fills in by itself."}</p>
        {canEdit ? <button className="button primary" onClick={() => setOpen(!open)}>{open ? "Close" : "+ Type this week's ad numbers"}</button> : null}
      </div>
      {open ? (
        <form className="p2-box p2-result-form" onSubmit={(e) => { e.preventDefault(); save(); }}>
          <label>Week starting<input type="date" value={f.week_start} onChange={set("week_start")} /></label>
          <label>Platform<Select value={f.platform} onChange={set("platform")} aria-label="Platform">{PLATFORMS.map((p) => <option key={p} value={p}>{p}</option>)}</Select></label>
          <label>Campaign<Select value={f.campaign_id} onChange={set("campaign_id")} aria-label="Campaign"><option value="">Not linked</option>{plan.campaigns.map((c) => <option key={c.id} value={c.id}>{c.id} · {c.name}</option>)}</Select></label>
          <label>Spend ({cur})<input inputMode="numeric" value={f.spend} onChange={set("spend")} /></label>
          <label>Impressions<input inputMode="numeric" value={f.impressions} onChange={set("impressions")} /></label>
          <label>Clicks<input inputMode="numeric" value={f.clicks} onChange={set("clicks")} /></label>
          <label>Leads<input inputMode="numeric" value={f.leads} onChange={set("leads")} /></label>
          <label className="wide">Note (optional)<input value={f.notes} onChange={set("notes")} maxLength={400} placeholder="New hook B started Tuesday" /></label>
          <button className="button primary" disabled={busy}>{busy ? "Saving…" : "Save week"}</button>
        </form>
      ) : null}
      <div className="p2-tiles">
        <Tile label="Leads so far" value={t.leads.toLocaleString()} tone="accent" sub={rep.kpis.find((k) => /lead/i.test(k.name) && k.actual === t.leads)?.state ?? undefined} />
        <Tile label="Cost per lead" value={money(t.cpl, cur)} />
        <Tile label="Click rate" value={pct(t.ctr, 2)} />
        <Tile label="Spent" value={money(t.spend, cur)} sub={plan.budget_total ? `${Math.round((t.spend * 100) / plan.budget_total)}% of the budget` : undefined} />
      </div>
      {!compact ? (
        <>
          <div className="p2-three">
            <Card kicker="Wins" className="good"><List items={rep.wins} empty="None yet." /></Card>
            <Card kicker="Misses" className="bad"><List items={rep.misses} empty="None yet." /></Card>
            <Card kicker="Next moves"><List items={rep.next_moves} /></Card>
          </div>
          {Object.keys(rep.by_platform).length ? (
            <Card title="By platform">
              <table className="p2-table">
                <thead><tr><th>Platform</th><th className="num">Spend</th><th className="num">Impressions</th><th className="num">Clicks</th><th className="num">CTR</th><th className="num">Leads</th><th className="num">Cost per lead</th></tr></thead>
                <tbody>
                  {Object.entries(rep.by_platform).map(([p, r]) => (
                    <tr key={p}><th>{p}</th><td className="num">{money(r.spend)}</td><td className="num">{r.impressions.toLocaleString()}</td><td className="num">{r.clicks.toLocaleString()}</td><td className="num">{pct(r.ctr, 2)}</td><td className="num">{r.leads}</td><td className="num">{money(r.cpl)}</td></tr>
                  ))}
                </tbody>
              </table>
            </Card>
          ) : null}
          {rep.kpis.length ? (
            <Card title="KPIs">
              <table className="p2-table">
                <thead><tr><th>KPI</th><th>Target</th><th>Now</th><th>State</th></tr></thead>
                <tbody>{rep.kpis.map((k) => <tr key={k.name}><th>{k.name}</th><td>{k.target}</td><td>{k.actual === null ? "Not tracked here" : k.actual.toLocaleString()}</td><td className={k.state === "behind" ? "bad" : k.state ? "good" : ""}>{k.state || "—"}</td></tr>)}</tbody>
              </table>
            </Card>
          ) : null}
          {rep.entries.length ? (
            <Card title="What you typed">
              <table className="p2-table">
                <thead><tr><th>Week</th><th>Platform</th><th>Campaign</th><th className="num">Spend</th><th className="num">Impr.</th><th className="num">Clicks</th><th className="num">Leads</th><th></th></tr></thead>
                <tbody>
                  {rep.entries.map((e) => (
                    <tr key={e.id}>
                      <td>{fmtDate(e.week_start)}</td><td>{e.platform}</td><td>{names[e.campaign_id] || "—"}</td>
                      <td className="num">{money(e.spend)}</td><td className="num">{e.impressions.toLocaleString()}</td><td className="num">{e.clicks.toLocaleString()}</td><td className="num">{e.leads}</td>
                      <td>{canEdit ? <button className="p2-link" onClick={() => remove(e.id)} aria-label={`Delete the ${e.platform} numbers for ${e.week_start}`}>Delete</button> : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
