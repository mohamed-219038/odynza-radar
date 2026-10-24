/* What changed since you last looked: at most five scored changes, the engagement scorecard and watch health. */
import { useState } from "react";
import { json, request } from "../api";
import { useToast } from "../components/Toast";
import { ago, count, pct } from "./format";
import { Bars, Loading, Problem, SignalCard, useLoad } from "./parts";
import type { Overview, SocialKind } from "./types";
import type { WatchTab } from "./WatchSection";
import { BriefTeaser, SnapshotTiles, Takeaways } from "./WeekView";
import { Select } from "../components/Select";
import { FieldStrip } from "./Visuals";

export function OverviewPage({ canDecide, canRun, go }: { canDecide: boolean; canRun: boolean; go: (tab: WatchTab) => void }) {
  const toast = useToast();
  const { data, error, reload } = useLoad<Overview>("/watch/overview", 30000);
  const [platform, setPlatform] = useState<SocialKind>("instagram");
  const [busy, setBusy] = useState("");

  async function act(kind: "run" | "seen" | "rescore") {
    setBusy(kind);
    try {
      if (kind === "run") {
        const out = await request<{ message: string }>("/watch/run", json({ everything: true }));
        toast(out.message);
      } else if (kind === "seen") {
        await request("/watch/overview/seen", { method: "POST" });
        toast("Marked as seen. New changes will collect here from now.");
      } else {
        const out = await request<{ started: boolean; message?: string; signals?: number }>("/watch/rescore", { method: "POST" });
        toast(out.started ? `Rescoring ${out.signals} signals in n8n. Nothing is collected again.` : out.message || "Nothing to rescore.");
      }
      reload();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  if (!data) return error ? <Problem text={error} /> : <Loading text="Opening the watch…" />;
  const rates = data.scorecard
    .filter((r) => r.platforms[platform])
    .map((r) => ({ name: r.you ? `You (${r.name})` : r.name, value: r.platforms[platform]?.engagement_rate ?? null, you: r.you }))
    .sort((a, b) => (b.value ?? -1) - (a.value ?? -1));

  return (
    <div className="w-grid">
      <section className="w-main">
        <div className="w-heading">
          <div>
            <h2>What changed since you last looked</h2>
            <p>
              Since {ago(data.since)} · {data.watched} competitors watched · next check {data.next_check ? ago(data.next_check) : "not scheduled"}
            </p>
          </div>
          <div className="w-actions">
            {canRun ? (
              <button className="button primary" disabled={Boolean(busy)} onClick={() => act("run")}>
                {busy === "run" ? "Starting…" : "Run check now"}
              </button>
            ) : null}
            <button className="button secondary" disabled={Boolean(busy)} onClick={() => act("seen")}>
              Mark as seen
            </button>
          </div>
        </div>
        <Problem text={error} />
        {data.brief ? <BriefTeaser brief={data.brief} onOpen={() => go("brief")} /> : null}
        {data.snapshot ? <SnapshotTiles snap={data.snapshot} /> : null}
        <FieldStrip title="Fresh from your rivals" sub="Their newest posts and ads. Click one to open it where it was posted." filter={(c) => !c.you} />
        {data.quiet ? (
          <>
            <p className="w-quiet-line">
              <span>☾</span> No new change scored 2 or more since you last looked. Here is what the market looks like now.
            </p>
            {data.snapshot ? <Takeaways snap={data.snapshot} /> : null}
          </>
        ) : (
          <>
            <div className="w-cap">
              Top changes · {data.items.length} of {data.item_cap} maximum
            </div>
            {data.items.map((s) => (
              <SignalCard key={s.id} signal={s} canCorrect={canDecide} onChanged={reload} />
            ))}
          </>
        )}
        {data.alerts.length ? (
          <div className="w-panel">
            <h3 className="w-sub">Movement alerts</h3>
            <ul className="w-alerts">
              {data.alerts.map((a, i) => (
                <li key={i}>
                  <span className="badge warn">{a.rule}</span> {a.message} <small>{ago(a.at)}</small>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>
      <aside className="w-rail">
        <section className="rail-card">
          <div className="section-heading">
            <h2>Engagement rate</h2>
            <Select aria-label="Platform" value={platform} onChange={(e) => setPlatform(e.target.value as SocialKind)} className="w-mini-select">
              <option value="instagram">Instagram</option>
              <option value="facebook">Facebook</option>
              <option value="linkedin">LinkedIn</option>
            </Select>
          </div>
          {rates.length ? <Bars rows={rates} format={pct} /> : <p className="muted w-pad">No {platform} captures yet.</p>}
          <div className="rail-foot">Engagement rate leads, not followers. Last 30 days.</div>
        </section>
        <section className="rail-card w-status">
          <h2>Watch status</h2>
          <dl>
            <div>
              <dt>Sources healthy</dt>
              <dd>
                {data.sources.healthy} of {data.sources.total}
              </dd>
            </div>
            <div>
              <dt>New entrants to review</dt>
              <dd>{count(data.new_entrants)}</dd>
            </div>
            <div>
              <dt>Reviews due (90 days)</dt>
              <dd>{count(data.review_due)}</dd>
            </div>
            <div>
              <dt>Apify credit used</dt>
              <dd className={data.budget.paused ? "w-bad" : ""}>
                ${data.budget.spent_usd.toFixed(2)} of ${data.budget.limit_usd.toFixed(0)}
                {data.budget.paused ? " · paused" : ""}
              </dd>
            </div>
          </dl>
          <button className="text-link" onClick={() => go("sources")}>
            Open source health →
          </button>
          {data.new_entrants ? (
            <button className="text-link" onClick={() => go("competitors")}>
              Review {data.new_entrants} proposed competitors →
            </button>
          ) : null}
          {data.new_opportunities ? (
            <button className="text-link" onClick={() => go("opportunities")}>
              {data.new_opportunities} new opportunities →
            </button>
          ) : null}
          {canRun ? (
            <button className="text-link" disabled={Boolean(busy)} onClick={() => act("rescore")} title="Send the last 30 days of signals back to the impact step with the current profile and corrections.">
              Rescore last 30 days
            </button>
          ) : null}
        </section>
      </aside>
    </div>
  );
}
