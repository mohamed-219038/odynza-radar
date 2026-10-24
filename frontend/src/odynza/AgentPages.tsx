/* M1 Strategy and M2 Social content: plan list and plan pages, content batches and batch pages. */
import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "../api";
import { runActive } from "../components/ItemCard";
import { RunList } from "../components/RunList";
import type { ContentRunSummary, User } from "../types";
import { AgentMark } from "./Mark";
import { BatchView } from "./plan2/BatchView";
import { NewBatch } from "./plan2/NewBatch";
import { NewPlan } from "./plan2/NewPlan";
import { PlanView } from "./plan2/PlanView";
import type { RadarPlanSummary } from "./plan2/types";
import { fmtDate } from "./plan2/ui";

export type AgentMode = "strategy" | "content";
const planActive = (p: { status: string }) => ["queued", "running"].includes(p.status);

export function AgentPages({ user, mode, onMode, onOpportunities }: { user: User; mode: AgentMode; onMode: (m: AgentMode) => void; onOpportunities: () => void }) {
  const canEdit = user.role === "admin" || user.role === "member";
  const [plansError, setPlansError] = useState("");
  const [runs, setRuns] = useState<ContentRunSummary[] | null>(null);
  const [runsError, setRunsError] = useState("");
  // Plans and their batches open as full pages.
  const [radar, setRadar] = useState<RadarPlanSummary[] | null>(null);
  const [radarNew, setRadarNew] = useState(false);
  const [radarId, setRadarId] = useState<string | null>(null);
  const [batchNew, setBatchNew] = useState<{ open: boolean; planId?: string }>({ open: false });
  const [batchId, setBatchId] = useState<string | null>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;

  const loadRadar = useCallback(async () => {
    try {
      setRadar(await request<RadarPlanSummary[]>("/strategy/radar/plans"));
    } catch (e) {
      setPlansError((e as Error).message);
    }
  }, []);
  const loadRuns = useCallback(async () => {
    try {
      setRuns(await request<ContentRunSummary[]>("/content/runs"));
      setRunsError("");
    } catch (e) {
      setRunsError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    loadRadar();
    loadRuns();
  }, [loadRadar, loadRuns, mode]);

  // Plans and batches being written in n8n refresh every 5 s while their page is open.
  const planning = Boolean(radar?.some(planActive));
  const writing = Boolean(runs?.some((r) => runActive(r.status)));
  useEffect(() => {
    if (!planning && !writing) return;
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      if (planning && modeRef.current === "strategy") loadRadar();
      if (writing && modeRef.current === "content") loadRuns();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [planning, writing, loadRadar, loadRuns]);

  const ready = radar?.filter((p) => p.status === "completed").length ?? 0;
  const deleteRun = async (r: ContentRunSummary) => {
    if (!window.confirm(`Delete the batch from ${r.start_date} (${r.total} drafts) with its pictures and videos? This cannot be undone.`)) return;
    try {
      await request(`/content/runs/${encodeURIComponent(r.run_id)}`, { method: "DELETE" });
      await loadRuns();
    } catch (e) {
      setRunsError((e as Error).message);
    }
  };
  const runAgain = async (id: string) => {
    try {
      const run = await request<ContentRunSummary>(`/content/runs/${encodeURIComponent(id)}/again`, { method: "POST" });
      await loadRuns();
      setBatchId(run.run_id);
    } catch (e) {
      setRunsError((e as Error).message);
    }
  };
  const openRun = (id: string) => setBatchId(id);
  const startPlan = () => {
    setRadarId(null);
    setRadarNew(true);
  };
  const toReview = runs?.reduce((n, r) => n + (r.counts.draft || 0), 0) ?? 0;

  return (
    <div className="odz-agent-page">
      <div className="odz-flow" role="list" aria-label="How the agents hand work on">
        <button role="listitem" className="odz-flow-step" onClick={onOpportunities}>
          <AgentMark code="M0" />
          <span>
            <b>Opportunities</b>
            <small>Spotted in rivals' moves</small>
          </span>
        </button>
        <i aria-hidden="true" />
        <button role="listitem" className={"odz-flow-step" + (mode === "strategy" ? " here" : "")} onClick={() => onMode("strategy")}>
          <AgentMark code="M1" />
          <span>
            <b>Strategy plans</b>
            <small>{radar ? `${ready} ready${planning ? " · planning now" : ""}` : "…"}</small>
          </span>
        </button>
        <i aria-hidden="true" />
        <button role="listitem" className={"odz-flow-step" + (mode === "content" ? " here" : "")} onClick={() => onMode("content")}>
          <AgentMark code="M2" />
          <span>
            <b>Social content</b>
            <small>{runs ? `${toReview} drafts to review${writing ? " · writing now" : ""}` : "…"}</small>
          </span>
        </button>
      </div>

      {mode === "strategy" && radarNew ? (
        <NewPlan
          onCancel={() => setRadarNew(false)}
          onCreated={async (p) => {
            setRadarNew(false);
            await loadRadar();
            setRadarId(p.plan_id);
          }}
        />
      ) : mode === "strategy" && radarId ? (
        <PlanView
          planId={radarId}
          canEdit={canEdit}
          onBack={() => {
            setRadarId(null);
            loadRadar();
          }}
          onMakeContent={(id) => setBatchNew({ open: true, planId: id })}
          onDeleted={() => {
            setRadarId(null);
            loadRadar();
          }}
        />
      ) : mode === "strategy" ? (
        <section className="library strategy-view odz-library" aria-labelledby="odz-plans-title">
          <div className="section-heading">
            <div>
              <h2 id="odz-plans-title">
                Strategy plans <span className="count">{radar?.length ?? 0}</span>
              </h2>
              <p>Five agents in n8n read what Radar has collected (rivals' moves, claims, ads, posts and opportunities) and write the competitive brief, positioning, campaigns, calendar, budget and KPIs.</p>
            </div>
            {canEdit ? (
              <button className="button primary" onClick={startPlan}>
                <span>＋</span> New plan
              </button>
            ) : null}
          </div>
          {plansError ? <div className="alert">{plansError}</div> : null}
          {!radar ? (
            <div className="loading-state">Reading the plans…</div>
          ) : radar.length ? (
            <div className="p2 p2-cards">
              {radar.map((p) => (
                <button key={p.plan_id} className="p2-item" onClick={() => setRadarId(p.plan_id)}>
                  <span className="p2-kicker">{p.goal || "Plan"} · {fmtDate(p.period.start_date)} to {fmtDate(p.period.end_date, { day: "numeric", month: "short", year: "numeric" })}</span>
                  <h3>{p.company_name}</h3>
                  <p>{p.status === "completed" ? p.summary || p.objective : p.status === "failed" ? p.error || "The agents could not finish this plan." : "The agents are writing this plan in n8n."}</p>
                  <footer>
                    <span className={"p2-status s-" + p.status}>{p.status === "completed" ? "Ready" : p.status === "failed" ? "Failed" : "Planning"}</span>
                    <span>{fmtDate(p.created_at)}</span>
                  </footer>
                </button>
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <p>No plans yet. {canEdit ? "Press New plan; Radar fills in the budget, dates and voices for you." : ""}</p>
            </div>
          )}
        </section>
      ) : batchId ? (
        <BatchView
          runId={batchId}
          canEdit={canEdit}
          onAgain={() => runAgain(batchId)}
          onBack={() => {
            setBatchId(null);
            loadRuns();
          }}
          onDeleted={() => {
            setBatchId(null);
            loadRuns();
          }}
        />
      ) : (
        <section className="library content-view odz-library" aria-labelledby="odz-runs-title">
          <div className="section-heading">
            <div>
              <h2 id="odz-runs-title">
                Content batches <span className="count">{runs?.length ?? 0}</span>
              </h2>
              <p>One agent per platform in n8n writes drafts from a ready plan, in that platform's voice and language, and a Media buying agent plans the paid ads. You approve and post everything yourself.</p>
            </div>
            {canEdit ? (
              <button className="button primary" onClick={() => setBatchNew({ open: true })}>
                <span>＋</span> New batch
              </button>
            ) : null}
          </div>
          <RunList runs={runs} error={runsError} onOpen={openRun} onNew={canEdit ? () => setBatchNew({ open: true }) : undefined} onDelete={canEdit ? deleteRun : undefined} onAgain={canEdit ? (r) => runAgain(r.run_id) : undefined} />
        </section>
      )}

      <NewBatch
        open={batchNew.open}
        planId={batchNew.planId}
        plans={radar ?? []}
        onClose={() => setBatchNew({ open: false })}
        onCreated={async (run) => {
          setBatchNew({ open: false });
          setRadarId(null);
          onMode("content");
          await loadRuns();
          setBatchId(run.run_id);
        }}
      />
    </div>
  );
}
