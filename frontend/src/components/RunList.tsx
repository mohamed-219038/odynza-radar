/* The list of content batches on the Social content page. */
import { date, initials } from "../format";
import type { ContentRunSummary } from "../types";
import { runActive } from "./ItemCard";

export function RunList(props: { runs: ContentRunSummary[] | null; error: string; onOpen: (id: string) => void; onNew?: () => void; onDelete?: (r: ContentRunSummary) => void; onAgain?: (r: ContentRunSummary) => void }) {
  if (props.error && !props.runs) return <div className="alert">{props.error}</div>;
  if (!props.runs) return <div className="loading-state">Gathering your content…</div>;
  if (!props.runs.length)
    return (
      <div className="empty-state">
        <span>✎</span>
        <h3>No content yet.</h3>
        <p>Pick a finished strategy plan and the LinkedIn, Instagram and Facebook agents write the drafts, with images and a reel kit.</p>
        {props.onNew ? (
          <button className="button primary" data-new-content onClick={props.onNew}>
            New batch ↗
          </button>
        ) : null}
      </div>
    );
  return (
    <>
      {props.error ? <div className="alert">{props.error}</div> : null}
      {props.runs.map((r) => {
        const [label, style] = runActive(r.status)
          ? ["Writing in n8n", "running"]
          : r.status === "failed"
            ? ["Needs attention", "warn"]
            : r.counts.draft
              ? [`${r.counts.draft} to review`, "running"]
              : ["All reviewed", ""];
        const row = (
          <button key={r.run_id} className="session-row" data-run={r.run_id} aria-label={`Open content for ${r.company_name}`} onClick={() => props.onOpen(r.run_id)}>
            <span className="company-icon">{initials(r.company_name)}</span>
            <span className="session-info">
              <h3>{r.company_name}</h3>
              <small>
                {r.platforms.join(", ")} <span>·</span> {r.start_date}{r.end_date ? ` → ${r.end_date}` : ""} <span>·</span> {r.total} drafts, {r.counts.approved} approved, {r.counts.posted} posted
              </small>
            </span>
            <span className="session-end">
              <span>
                <span className={`badge ${style}`}>{label}</span>
                <small>{date(r.created_at)}</small>
              </span>
              <span className="arrow">↗</span>
            </span>
          </button>
        );
        if (!props.onDelete && !props.onAgain) return row;
        const { onDelete: del, onAgain: again } = props;
        return (
          <div key={r.run_id} className="run-row">
            {row}
            {again ? (
              <button className="run-again" disabled={runActive(r.status)} aria-label={`Run the batch for ${r.company_name} from ${r.start_date} again`} onClick={() => again(r)}>
                Run again
              </button>
            ) : null}
            {del ? (
              <button className="run-delete" disabled={runActive(r.status)} title={runActive(r.status) ? "Wait until the agents finish" : undefined}
                aria-label={`Delete the batch for ${r.company_name} from ${r.start_date}`} onClick={() => del(r)}>
                Delete
              </button>
            ) : null}
          </div>
        );
      })}
    </>
  );
}
