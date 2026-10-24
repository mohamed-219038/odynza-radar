/* M2 Content · new batch from a Radar plan: start date, weeks, posts a week per platform, reels, stories, media buying. */
import { useEffect, useState } from "react";
import { json, request } from "../../api";
import { CloseButton, Dialog } from "../../components/Dialog";
import { useToast } from "../../components/Toast";
import type { ContentRunSummary, Platform } from "../../types";
import { PlatformGlyph } from "../../watch/Visuals";
import type { RadarContentDefaults, RadarPlanSummary } from "./types";
import { money } from "./ui";

const PLATFORMS: Platform[] = ["LinkedIn", "Instagram", "Facebook"];

export function NewBatch({ open, planId, plans, onClose, onCreated }: { open: boolean; planId?: string; plans: RadarPlanSummary[]; onClose: () => void; onCreated: (r: ContentRunSummary) => void }) {
  const toast = useToast();
  const ready = plans.filter((p) => p.status === "completed");
  const [plan, setPlan] = useState(planId || "");
  const [d, setD] = useState<RadarContentDefaults | null>(null);
  const [f, setF] = useState({ start_date: "", weeks: 1, reels_per_month: 2, stories_per_week: 3, notes: "", media_buying: true });
  const [rhythm, setRhythm] = useState<Record<Platform, number>>({ LinkedIn: 3, Instagram: 4, Facebook: 3 });
  const [on, setOn] = useState<Platform[]>(PLATFORMS);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) setPlan(planId || ready[0]?.plan_id || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, planId]);
  useEffect(() => {
    if (!open || !plan) return;
    request<RadarContentDefaults>(`/content/plans/${plan}/defaults`)
      .then((x) => {
        setD(x);
        setF({ start_date: x.start_date, weeks: x.weeks, reels_per_month: x.reels_per_month, stories_per_week: x.stories_per_week, notes: "", media_buying: x.media_buying });
        setRhythm(x.rhythm);
      })
      .catch((e) => toast((e as Error).message));
  }, [open, plan, toast]);

  const posts = on.reduce((n, p) => n + (rhythm[p] || 0) * f.weeks, 0) + (on.includes("Instagram") ? f.stories_per_week * f.weeks : 0);
  async function submit() {
    setBusy(true);
    try {
      const run = await request<ContentRunSummary>("/content/runs", json({
        plan_id: plan, platforms: on, start_date: f.start_date, weeks: f.weeks, reels_per_month: f.reels_per_month,
        stories_per_week: on.includes("Instagram") ? f.stories_per_week : 0, rhythm, notes: f.notes, media_buying: f.media_buying,
        brand_look: d?.brand_look || "",
      }));
      toast("The content agents are writing in n8n.");
      onCreated(run);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog id="p2-batch-new" className="session-dialog p2-dialog" open={open} onClose={onClose} labelledBy="p2-batch-title">
      <div className="detail-header">
        <div>
          <span className="eyebrow">M2 CONTENT · NEW BATCH</span>
          <h2 id="p2-batch-title">Write posts and the ad plan</h2>
        </div>
        <CloseButton onClick={onClose} label="Close" />
      </div>
      <div className="p2 p2-form">
        {!ready.length ? <div className="alert">Finish a strategy plan first; content is written from a ready plan.</div> : null}
        <label>
          From the plan
          <select value={plan} onChange={(e) => setPlan(e.target.value)}>
            {ready.map((p) => <option key={p.plan_id} value={p.plan_id}>{p.goal} · {p.summary?.slice(0, 70) || p.company_name} ({p.period.start_date})</option>)}
          </select>
        </label>
        <div className="p2-grid4">
          <label>Starts on<input type="date" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} /></label>
          <label>Weeks<input type="number" min={1} max={4} value={f.weeks} onChange={(e) => setF({ ...f, weeks: Math.max(1, Math.min(4, Number(e.target.value))) })} /></label>
          <label>Reels a month<input type="number" min={0} max={4} value={f.reels_per_month} onChange={(e) => setF({ ...f, reels_per_month: Number(e.target.value) })} /></label>
          <label>Stories a week<input type="number" min={0} max={7} value={f.stories_per_week} onChange={(e) => setF({ ...f, stories_per_week: Number(e.target.value) })} /></label>
        </div>
        <div className="p2-rhythm">
          {PLATFORMS.map((p) => (
            <label key={p} className={"p2-input" + (on.includes(p) ? " on" : "")}>
              <input type="checkbox" checked={on.includes(p)} onChange={() => setOn(on.includes(p) ? on.filter((x) => x !== p) : [...on, p])} />
              <span>
                <b><PlatformGlyph kind={p.toLowerCase()} size={16} /> {p}</b>
                <small>{d?.voices?.[p]?.label} · {d?.voices?.[p]?.language}</small>
              </span>
              <input aria-label={`${p} posts a week`} type="number" min={1} max={7} value={rhythm[p]} disabled={!on.includes(p)}
                onChange={(e) => setRhythm({ ...rhythm, [p]: Math.max(1, Math.min(7, Number(e.target.value))) })} />
              <small>a week</small>
            </label>
          ))}
        </div>
        <label className="p2-check">
          <input type="checkbox" checked={f.media_buying} disabled={!d?.media_buying} onChange={(e) => setF({ ...f, media_buying: e.target.checked })} />
          Plan the paid ads too (Media buying agent){d && Object.keys(d.paid_budget).length ? `: ${Object.entries(d.paid_budget).map(([k, v]) => `${k} ${money(v, d.currency)}`).join(", ")}` : " (the plan has no ad budget)"}
        </label>
        <label>Notes for the writers (optional)<input value={f.notes} maxLength={600} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="Mention the free 2am test; no prices" /></label>
        <p className="p2-fine">About {posts} drafts. Nothing is posted or spent: you approve every draft and set up the ads yourself.</p>
      </div>
      <div className="detail-bottom">
        <button className="button secondary" onClick={onClose}>Cancel</button>
        <button className="button primary" disabled={busy || !plan || !on.length || !f.start_date} onClick={submit}>{busy ? "Starting…" : "Write the batch"}</button>
      </div>
    </Dialog>
  );
}
