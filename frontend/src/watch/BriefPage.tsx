/* Weekly competitor brief: 3 to 7 items, never padded, in the app, as a PDF and by email on Monday. */
import { useEffect, useState, type ReactNode } from "react";
import { download, request, watchClientId } from "../api";
import { saveFile } from "../format";
import { useToast } from "../components/Toast";
import { ago, stamp } from "./format";
import { Empty, ExtLink, Loading, Problem, ScoreBadge, useLoad } from "./parts";
import type { Brief, WeekSnapshot } from "./types";
import { SnapshotDetails, SnapshotTiles, Takeaways } from "./WeekView";

interface BriefList {
  briefs: Brief[];
  email_ready: boolean;
  recipients: string[];
  snapshot?: WeekSnapshot;
}

export function BriefPage({
  canStaff,
  onChanged,
  body,
}: {
  canStaff: boolean;
  onChanged?: () => void;
  /** Draws a ready brief in the host's own look (the Odynza site's mission debrief) instead of the default. */
  body?: (brief: Brief, snapshot?: WeekSnapshot) => ReactNode;
}) {
  const toast = useToast();
  const [poll, setPoll] = useState(0);
  const { data, error, reload: load } = useLoad<BriefList>("/watch/briefs", poll);
  const reload = () => {
    load();
    onChanged?.();
  };
  const [busy, setBusy] = useState("");
  const [shown, setShown] = useState<number | null>(null);
  const running = Boolean(data?.briefs.some((b) => b.status === "running"));
  useEffect(() => setPoll(running ? 5000 : 0), [running]);

  async function make() {
    setBusy("make");
    try {
      await request("/watch/briefs/make", { method: "POST" });
      toast("The brief is being written in n8n. This page updates when it is ready.");
      reload();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function pdf(b: Brief) {
    setBusy(`pdf${b.id}`);
    try {
      const { blob, name } = await download(`/watch/briefs/${b.id}/pdf`, "The PDF could not be made.");
      saveFile(blob, name || `competitor-brief-${b.week_start}.pdf`);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function email(b: Brief) {
    setBusy(`mail${b.id}`);
    try {
      await request(`/watch/briefs/${b.id}/email`, { method: "POST" });
      toast(`Brief emailed to ${data?.recipients.join(", ")}.`);
      reload();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  if (!data) return error ? <Problem text={error} /> : <Loading text="Opening briefs…" />;
  const open = data.briefs.find((b) => b.id === shown) ?? data.briefs.find((b) => b.status === "ready") ?? data.briefs[0];
  return (
    <div className="w-main">
      <div className="w-heading">
        <div>
          <h2>Weekly competitor brief</h2>
          <p>
            Written every Sunday at 22:00 Cairo time and emailed Monday 08:00{" "}
            {data.email_ready ? `to ${data.recipients.join(", ") || "nobody yet (add recipients in Setup)"}` : "once email is set up in .env (SMTP_USER and SMTP_PASSWORD)"}.
          </p>
        </div>
        {canStaff ? (
          <button className="button primary" disabled={Boolean(busy) || running} onClick={make}>
            {running ? "Writing in n8n…" : busy === "make" ? "Starting…" : "Make this week's brief now"}
          </button>
        ) : null}
      </div>
      <Problem text={error} />
      {!data.briefs.length ? (
        <Empty icon="▤" title="No brief yet.">
          The first one is written on Sunday night, or now with the button above.
        </Empty>
      ) : (
        <div className="w-grid">
          <section className="w-main">
            {open ? (
              <article className={"w-panel w-brief" + (body ? " w-brief-custom" : "")}>
                <div className="section-heading">
                  <div>
                    {body && open.status === "ready" ? null : <span className="eyebrow">WEEK OF {open.week_start}</span>}
                    {body && open.status === "ready" ? null : <h3 className="w-brief-head">{open.status === "running" ? "Being written…" : open.headline || (open.quiet ? "A quiet week: no big moves" : "Brief")}</h3>}
                  </div>
                  {open.status === "ready" ? (
                    <div className="w-actions">
                      <a className="button secondary small-button" href={`/watch/briefs/${open.id}/view${watchClientId() ? `?client=${watchClientId()}` : ""}`} target="_blank" rel="noopener noreferrer">
                        Open page ↗
                      </a>
                      <button className="button secondary small-button" disabled={Boolean(busy)} onClick={() => pdf(open)}>
                        {busy === `pdf${open.id}` ? "Making PDF…" : "PDF ↓"}
                      </button>
                      {canStaff ? (
                        <button className="button secondary small-button" disabled={Boolean(busy) || !data.email_ready} title={data.email_ready ? "" : "Email is not set up in .env"} onClick={() => email(open)}>
                          {busy === `mail${open.id}` ? "Sending…" : "Email now"}
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                {open.status === "failed" ? <Problem text={open.error || "The brief failed in n8n."} /> : null}
                {open.status === "ready" && open.error ? <p className="w-reason">{open.error}</p> : null}
                {open.email_error ? <p className="report-error">Email failed: {open.email_error}</p> : null}
                {open.emailed_at ? <p className="muted">Emailed {stamp(open.emailed_at)}</p> : null}
                {body && open.status === "ready" ? body(open, data.snapshot) : null}
                {!body && open.status === "ready" && data.snapshot ? <SnapshotTiles snap={data.snapshot} /> : null}
                {body && open.status === "ready" ? null : open.quiet && open.status === "ready" ? (
                  <p className="w-quiet-line">
                    <span>☾</span> No rival change scored 3 or more this week. Here is what the market did instead.
                  </p>
                ) : open.items.length ? (
                  <h3 className="w-sub w-brief-moves">Moves to act on</h3>
                ) : null}
                {!body && open.status === "ready" && data.snapshot ? <Takeaways snap={data.snapshot} /> : null}
                {(body && open.status === "ready" ? [] : open.items).map((it, i) => (
                  <div key={it.signal_id} className="w-signal">
                    <ScoreBadge score={it.score} />
                    <div className="w-signal-body">
                      <div className="w-signal-top">
                        <b>
                          {i + 1}. {it.competitor}
                        </b>
                        <span className="badge neutral">{it.type}</span>
                        <small>{ago(it.captured_at)}</small>
                      </div>
                      <h3>{it.title}</h3>
                      <p className="w-meaning">
                        <b>What it means for you:</b> {it.meaning}
                      </p>
                      {it.move ? (
                        <p className="w-move">
                          <b>Your move:</b> {it.move}
                        </p>
                      ) : null}
                      <ExtLink href={it.source_url} />
                    </div>
                  </div>
                ))}
              </article>
            ) : null}
            {!body && open?.status === "ready" && data.snapshot ? <SnapshotDetails snap={data.snapshot} /> : null}
          </section>
          <aside className="w-rail">
            <section className="rail-card">
              <h2>All briefs</h2>
              <ul className="w-brief-list">
                {data.briefs.map((b) => (
                  <li key={b.id}>
                    <button className={"w-brief-pick" + (open?.id === b.id ? " active" : "")} onClick={() => setShown(b.id)}>
                      <b>Week of {b.week_start}</b>
                      <small>
                        {b.status === "ready" ? (b.quiet ? "Quiet week" : `${b.items.length} items`) : b.status === "running" ? "Writing…" : "Failed"}
                        {b.emailed_at ? " · emailed" : ""}
                      </small>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          </aside>
        </div>
      )}
    </div>
  );
}
