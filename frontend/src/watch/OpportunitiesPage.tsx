/* Ranked marketing opportunities from the weekly brief. Act opens a prefilled strategy plan. */
import { useState } from "react";
import { json, request } from "../api";
import { useToast } from "../components/Toast";
import { Empty, Loading, Logo, Problem, useLoad } from "./parts";
import { useGallery } from "./Visuals";
import type { Opportunity } from "./types";

type Filter = "open" | "acted" | "closed" | "all";
const FILTERS: [Filter, string][] = [
  ["open", "To decide"],
  ["acted", "Acted on"],
  ["closed", "Rejected or expired"],
  ["all", "All"],
];

function matches(o: Opportunity, f: Filter) {
  if (f === "open") return o.status === "new" || o.status === "accepted";
  if (f === "acted") return o.status === "acted";
  if (f === "closed") return o.status === "rejected" || o.status === "expired";
  return true;
}

function evidenceLabel(ref: string) {
  if (ref.startsWith("claim:")) return `Claim map #${ref.slice(6)}`;
  if (ref.startsWith("gap:")) return `Content gap #${ref.slice(4)}`;
  return `Signal #${ref}`;
}

export function OpportunitiesPage({ canDecide, canStaff, onOpenPlans }: { canDecide: boolean; canStaff: boolean; onOpenPlans?: () => void }) {
  const toast = useToast();
  const { data, error, reload } = useLoad<Opportunity[]>("/watch/opportunities", 15000);
  const [filter, setFilter] = useState<Filter>("open");
  const [busy, setBusy] = useState(0);

  async function decide(o: Opportunity, status: "accepted" | "rejected" | "new") {
    setBusy(o.id);
    try {
      await request(`/watch/opportunities/${o.id}`, { method: "PATCH", body: JSON.stringify({ status }) });
      reload();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(0);
    }
  }

  async function act(o: Opportunity) {
    setBusy(o.id);
    try {
      await request(`/watch/opportunities/${o.id}/act`, json({}));
      toast("A strategy plan is being written from this opportunity. Find it under Strategy plans.");
      reload();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(0);
    }
  }

  if (!data) return error ? <Problem text={error} /> : <Loading text="Opening opportunities…" />;
  const shown = data.filter((o) => matches(o, filter));
  return (
    <div className="w-main">
      <div className="w-heading">
        <div>
          <h2>Marketing opportunities</h2>
          <p>Each one has all ten fields and evidence that exists in Radar, or it is refused. Ranked by the weekly brief.</p>
        </div>
      </div>
      <div className="filter-row">
        <div className="tabs">
          {FILTERS.map(([k, label]) => (
            <button key={k} className={"tab" + (filter === k ? " active" : "")} onClick={() => setFilter(k)}>
              {label} <span className="count">{data.filter((o) => matches(o, k)).length}</span>
            </button>
          ))}
        </div>
      </div>
      <Problem text={error} />
      {!shown.length ? (
        <Empty icon="↗" title={data.length ? "Nothing here." : "No opportunities yet."}>
          {data.length ? "Try another filter." : "They are written with the weekly brief, from signals scoring 3 or more, the claim map and the content gaps."}
        </Empty>
      ) : (
        shown.map((o) => (
          <article key={o.id} className="w-panel w-opp" data-opportunity={o.id}>
            <div className="w-opp-top">
              <span className="w-rank">#{o.rank}</span>
              <div>
                <h3>{o.angle}</h3>
                <small>
                  Week of {o.week_start} · confidence <b>{o.confidence}</b> · expires {o.expires_on}
                </small>
              </div>
              <span className={"badge " + ({ new: "running", accepted: "", acted: "", rejected: "neutral", expired: "neutral" } as Record<string, string>)[o.status]}>{o.status}</span>
            </div>
            <dl className="w-opp-grid">
              <div>
                <dt>Trigger</dt>
                <dd>{o.trigger}</dd>
              </div>
              <div>
                <dt>Claim to own</dt>
                <dd>{o.claim}</dd>
              </div>
              <div>
                <dt>Audience</dt>
                <dd>{o.audience}</dd>
              </div>
              <div>
                <dt>Why now</dt>
                <dd>{o.why_now}</dd>
              </div>
              <div>
                <dt>What rivals are saying</dt>
                <dd>
                  <RivalFaces text={o.competitors_saying} />
                  {o.competitors_saying}
                </dd>
              </div>
              <div>
                <dt>What would make this wrong</dt>
                <dd>{o.wrong_if}</dd>
              </div>
            </dl>
            <div className="w-chips">
              <small>Evidence:</small>
              {o.evidence.map((r) => (
                <span key={r} className="badge neutral">
                  {evidenceLabel(r)}
                </span>
              ))}
            </div>
            {o.outcome ? <p className="w-reason">{o.outcome}</p> : null}
            <div className="w-actions">
              {canDecide && o.status === "new" ? (
                <>
                  <button className="button secondary small-button" disabled={busy === o.id} onClick={() => decide(o, "accepted")}>
                    Accept
                  </button>
                  <button className="button secondary small-button" disabled={busy === o.id} onClick={() => decide(o, "rejected")}>
                    Reject
                  </button>
                </>
              ) : null}
              {canDecide && (o.status === "accepted" || o.status === "rejected") ? (
                <button className="button secondary small-button" disabled={busy === o.id} onClick={() => decide(o, "new")}>
                  Undo
                </button>
              ) : null}
              {canStaff && (o.status === "new" || o.status === "accepted" || (o.status === "acted" && o.plan_status === "failed")) ? (
                <button className="button primary small-button" disabled={busy === o.id} onClick={() => act(o)} title="Opens a new strategy plan prefilled from this opportunity">
                  {busy === o.id ? "Starting…" : o.plan_status === "failed" ? "Try the plan again" : "Act: make a plan"}
                </button>
              ) : null}
              {o.plan_id && onOpenPlans ? (
                <button className="text-link" onClick={onOpenPlans}>
                  Plan {o.plan_status === "completed" ? "ready" : o.plan_status || "started"} · open Strategy plans →
                </button>
              ) : null}
            </div>
          </article>
        ))
      )}
    </div>
  );
}

/** Logos of the watched rivals named in a sentence, so the reader sees who is saying it. */
function RivalFaces({ text }: { text: string }) {
  const companies = useGallery();
  const named = (companies ?? []).filter((c) => !c.you && text.toLowerCase().includes(c.name.toLowerCase().split(/\s+/)[0]));
  if (!named.length) return null;
  return (
    <span className="w-faces">
      {named.map((c) => (
        <span key={c.key} title={c.name}>
          <Logo id={c.key} name={c.name} size={26} />
        </span>
      ))}
    </span>
  );
}
