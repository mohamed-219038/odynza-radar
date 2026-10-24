/* Source health: every watched page and social account, its last run, errors, Apify spend and recent visits. */
import { useState, type FormEvent } from "react";
import { json, request } from "../api";
import { useToast } from "../components/Toast";
import { ago, KIND_LABEL, stamp } from "./format";
import { Empty, ExtLink, Loading, Logo, Problem, useLoad } from "./parts";
import type { Competitor, Source, SourcesInfo } from "./types";
import { Select } from "../components/Select";
import { PlatformGlyph } from "./Visuals";

const PAGE_KINDS = [
  "homepage",
  "pricing",
  "services",
  "clients",
  "about",
  "careers",
  "news",
];

export function SourcesPage({
  canDecide,
  canStaff,
  onChanged,
}: {
  canDecide: boolean;
  canStaff: boolean;
  onChanged?: () => void;
}) {
  const toast = useToast();
  const {
    data,
    error,
    reload: load,
  } = useLoad<SourcesInfo>("/watch/sources", 15000);
  const reload = () => {
    load();
    onChanged?.();
  };
  const comps = useLoad<Competitor[]>("/watch/competitors?status=confirmed");
  const [busy, setBusy] = useState("");
  const [onlyBad, setOnlyBad] = useState(false);
  const [company, setCompany] = useState("all");
  const [picked, setPicked] = useState<Set<number>>(new Set());

  async function toggle(s: Source) {
    setBusy(`s${s.id}`);
    try {
      await request(`/watch/sources/${s.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !s.enabled }),
      });
      reload();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function run(ids: number[] | "all") {
    setBusy("run");
    try {
      const out = await request<{ message: string }>(
        "/watch/run",
        json(ids === "all" ? { everything: true } : { source_ids: ids }),
      );
      toast(out.message);
      if (ids !== "all") setPicked(new Set());
      reload();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function resend(id: number) {
    setBusy(`v${id}`);
    try {
      await request(`/watch/visits/${id}/resend`, { method: "POST" });
      toast("Sent to n8n again for scoring.");
      reload();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  if (!data)
    return error ? (
      <Problem text={error} />
    ) : (
      <Loading text="Checking sources…" />
    );
  const b = data.budget;
  const companies = [...new Set(data.sources.map((s) => s.company))];
  const shown = data.sources.filter(
    (s) =>
      (!onlyBad || (s.enabled && !s.healthy)) &&
      (company === "all" || s.company === company),
  );
  // One group per company, in the order the server lists them, so each company gets one checkbox for all its sources.
  const groups = companies
    .map((c) => ({ company: c, rows: shown.filter((s) => s.company === c) }))
    .filter((g) => g.rows.length);
  const runnable = (rows: Source[]) => rows.filter((s) => s.enabled).map((s) => s.id);
  const chosen = data.sources.filter((s) => picked.has(s.id) && s.enabled).map((s) => s.id);
  const allIds = runnable(shown);
  const setMany = (ids: number[], on: boolean) => {
    const next = new Set(picked);
    ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
    setPicked(next);
  };
  const state = (ids: number[]) => {
    const n = ids.filter((id) => picked.has(id)).length;
    return { checked: Boolean(ids.length) && n === ids.length, mixed: n > 0 && n < ids.length };
  };
  return (
    <div className="w-main">
      <div className="w-heading">
        <div>
          <h2>Source health</h2>
          <p>
            {data.healthy} of {data.enabled} sources healthy. A source that
            fails 3 times in a row stays visible here until it works again.
          </p>
        </div>
        {canStaff ? (
          <div className="w-actions">
            <button
              className="button primary"
              disabled={Boolean(busy)}
              onClick={() => run("all")}
            >
              {busy === "run" ? "Starting…" : "Collect everything now"}
            </button>
          </div>
        ) : null}
      </div>
      <Problem text={error} />
      <div className="w-kpis">
        <article>
          <span>Healthy sources</span>
          <strong>
            {data.healthy}/{data.enabled}
          </strong>
          <small>{data.sources.length - data.enabled} turned off</small>
        </article>
        <article className={b.paused ? "w-warn" : ""}>
          <span>Apify credit ({b.month})</span>
          <strong>${b.spent_usd.toFixed(2)}</strong>
          <small>
            of ${b.limit_usd.toFixed(0)} ·{" "}
            {b.paused
              ? "paused at 90%: Apify sources wait for next month"
              : `max $${b.per_run_usd} per run`}
          </small>
          <div className="channel-track">
            <div
              className="channel-fill"
              style={{
                width: `${Math.min(100, Math.round((b.spent_usd / (b.limit_usd || 1)) * 100))}%`,
              }}
            ></div>
          </div>
        </article>
        <article>
          <span>Last visit</span>
          <strong>
            {data.visits[0] ? ago(data.visits[0].started_at) : "—"}
          </strong>
          <small>
            {data.visits[0]
              ? `${data.visits[0].status} · ${data.visits[0].changes} changes`
              : "Nothing collected yet"}
          </small>
        </article>
      </div>

      <section className="w-panel">
        <div className="section-heading">
          <h3 className="w-sub">Sources</h3>
          <div className="w-actions">
            <Select
              aria-label="Company"
              className="w-mini-select"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
            >
              <option value="all">All companies ({data.sources.length})</option>
              {companies.map((c) => (
                <option key={c} value={c}>
                  {c} ({data.sources.filter((s) => s.company === c).length})
                </option>
              ))}
            </Select>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={onlyBad}
                onChange={(e) => setOnlyBad(e.target.checked)}
              />{" "}
              Only problems
            </label>
          </div>
        </div>
        {canStaff && allIds.length ? (
          <div className={"w-pickbar" + (chosen.length ? " on" : "")}>
            <label className="checkbox">
              <Tick ids={allIds} state={state(allIds)} onChange={(on) => setMany(allIds, on)} label="Select every source shown" />
              {chosen.length ? `${chosen.length} source${chosen.length === 1 ? "" : "s"} selected` : "Tick a company to collect all its sources, or tick single sources"}
            </label>
            {chosen.length ? (
              <span className="w-actions">
                <button className="text-link" onClick={() => setPicked(new Set())}>
                  Clear
                </button>
                <button className="button primary small-button" disabled={Boolean(busy)} onClick={() => run(chosen)}>
                  {busy === "run" ? "Starting…" : `Collect selected (${chosen.length})`}
                </button>
              </span>
            ) : null}
          </div>
        ) : null}
        {shown.length ? (
          <div className="w-table-wrap">
            <table className="plan-table w-sources">
              <thead>
                <tr>
                  {canStaff ? <th aria-label="Select"></th> : null}
                  <th>Checked</th>
                  <th>Health</th>
                  <th>Source</th>
                  <th>Via</th>
                  <th>Last success</th>
                  <th>Next run</th>
                  <th></th>
                </tr>
              </thead>
              {groups.map((g) => {
                const ids = runnable(g.rows);
                const first = g.rows[0];
                return (
                <tbody key={g.company}>
                  <tr className="w-group-row">
                    {canStaff ? (
                      <td>
                        <Tick ids={ids} state={state(ids)} onChange={(on) => setMany(ids, on)} label={`Select all of ${g.company}'s sources`} />
                      </td>
                    ) : null}
                    <td>
                      <Done rows={g.rows.filter((s) => s.enabled)} />
                    </td>
                    <td colSpan={6}>
                      <span className="w-who">
                        <Logo id={first.competitor_id ?? "client"} name={g.company === "You" ? "You" : g.company} size={26} />
                        <b>{g.company}</b>
                        <small className="muted">
                          {g.rows.length} source{g.rows.length === 1 ? "" : "s"}
                          {g.rows.some((s) => s.enabled && !s.healthy) ? " · some failing" : ""}
                        </small>
                      </span>
                    </td>
                  </tr>
                {g.rows.map((s) => (
                  <tr key={s.id} className={(s.enabled ? "" : "w-off") + (picked.has(s.id) ? " w-picked" : "")}>
                    {canStaff ? (
                      <td>
                        {s.enabled ? <Tick ids={[s.id]} state={state([s.id])} onChange={(on) => setMany([s.id], on)} label={`Select ${s.company} ${KIND_LABEL[s.kind]}`} /> : null}
                      </td>
                    ) : null}
                    <td>{s.enabled ? <Done rows={[s]} /> : null}</td>
                    <td>
                      <span
                        className={
                          "badge " +
                          (!s.enabled ? "neutral" : s.healthy ? "" : "warn")
                        }
                      >
                        {!s.enabled
                          ? "Off"
                          : s.healthy
                            ? "OK"
                            : `Failing ×${s.fail_count}`}
                      </span>
                    </td>
                    <td>
                      <span className="w-source-kind">
                        <PlatformGlyph kind={s.kind === "web" ? "news" : s.kind} size={20} />
                        {KIND_LABEL[s.kind]}
                        {s.page_kind ? ` · ${s.page_kind}` : ""}
                      </span>
                      <small>
                        <ExtLink href={s.url} />
                      </small>
                      {s.last_error ? (
                        <small className="w-bad">{s.last_error}</small>
                      ) : null}
                    </td>
                    <td>{s.via}</td>
                    <td>
                      {s.last_success_at ? stamp(s.last_success_at) : "never"}
                    </td>
                    <td>
                      {s.enabled
                        ? s.next_run_at
                          ? ago(s.next_run_at)
                          : "—"
                        : "—"}
                    </td>
                    <td className="w-row-actions">
                      {canStaff && s.enabled ? (
                        <button
                          className="text-link"
                          disabled={Boolean(busy)}
                          onClick={() => run([s.id])}
                        >
                          Run
                        </button>
                      ) : null}
                      {canDecide ? (
                        <button
                          className="text-link"
                          disabled={busy === `s${s.id}`}
                          onClick={() => toggle(s)}
                        >
                          {s.enabled ? "Turn off" : "Turn on"}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
                </tbody>
                );
              })}
            </table>
          </div>
        ) : (
          <Empty icon="↻" title={onlyBad ? "No problems." : "No sources yet."}>
            {onlyBad
              ? "Every source worked on its last run."
              : "Sources are set up when you save the profile and confirm competitors."}
          </Empty>
        )}
      </section>

      {canDecide ? (
        <AddSource competitors={comps.data ?? []} onAdded={reload} />
      ) : null}

      <section className="w-panel">
        <h3 className="w-sub">Recent visits</h3>
        {data.visits.length ? (
          <div className="w-table-wrap">
            <table className="plan-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Started</th>
                  <th>Trigger</th>
                  <th>Status</th>
                  <th>Changes</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.visits.map((v) => (
                  <tr key={v.id}>
                    <td>{v.id}</td>
                    <td>{stamp(v.started_at)}</td>
                    <td>{v.trigger.replace("_", " ")}</td>
                    <td>
                      <span
                        className={
                          "badge " +
                          (v.status === "failed"
                            ? "warn"
                            : v.status === "done"
                              ? ""
                              : "running")
                        }
                      >
                        {v.status}
                      </span>
                      {v.error ? (
                        <small className="w-bad">{v.error}</small>
                      ) : null}
                    </td>
                    <td>{v.changes}</td>
                    <td>
                      {canStaff &&
                      (v.status === "failed" || v.status === "scoring") ? (
                        <button
                          className="text-link"
                          disabled={busy === `v${v.id}`}
                          onClick={() => resend(v.id)}
                        >
                          Send to n8n again
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No visits yet.</p>
        )}
      </section>
    </div>
  );
}

function AddSource({
  competitors,
  onAdded,
}: {
  competitors: Competitor[];
  onAdded: () => void;
}) {
  const toast = useToast();
  const [f, setF] = useState({
    competitor: "",
    kind: "page",
    page_kind: "pricing",
    url: "",
  });
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) =>
    setF({ ...f, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await request(
        "/watch/sources",
        json({
          competitor_id: f.competitor ? Number(f.competitor) : null,
          kind: f.kind,
          url: f.url,
          page_kind: f.kind === "page" ? f.page_kind : null,
        }),
      );
      toast("Source added. It is collected on the next check.");
      setF({ ...f, url: "" });
      onAdded();
    } catch (err) {
      toast((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="w-panel w-form" onSubmit={submit}>
      <h3 className="w-sub">Add a page or account by hand</h3>
      <fieldset disabled={busy} className="w-add-source">
        <label>
          Company
          <Select value={f.competitor} onChange={set("competitor")}>
            <option value="">You (the client)</option>
            {competitors.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </label>
        <label>
          Kind
          <Select value={f.kind} onChange={set("kind")}>
            {Object.entries(KIND_LABEL).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </Select>
        </label>
        {f.kind === "page" ? (
          <label>
            Page type
            <Select value={f.page_kind} onChange={set("page_kind")}>
              {PAGE_KINDS.map((k) => (
                <option key={k}>{k}</option>
              ))}
            </Select>
          </label>
        ) : null}
        <label className="w-grow">
          Link{" "}
          {f.kind === "ads" ? (
            <span className="optional">the Facebook page</span>
          ) : null}
          <input
            required
            value={f.url}
            onChange={set("url")}
            placeholder="https://…"
          />
        </label>
        <button className="button secondary">{busy ? "Adding…" : "Add"}</button>
      </fieldset>
    </form>
  );
}

/** A checkbox that also shows "some selected" (indeterminate) for a company or the whole list. */
function Tick({ ids, state, onChange, label }: { ids: number[]; state: { checked: boolean; mixed: boolean }; onChange: (on: boolean) => void; label: string }) {
  return (
    <input
      type="checkbox"
      className="w-tick-box"
      aria-label={label}
      disabled={!ids.length}
      checked={state.checked}
      ref={(el) => {
        if (el) el.indeterminate = state.mixed;
      }}
      onChange={(e) => onChange(e.target.checked)}
    />
  );
}

/** Green tick when the source's latest run worked (for a company: every enabled source), with when. */
function Done({ rows }: { rows: Source[] }) {
  if (!rows.length) return null;
  const ok = rows.filter((s) => s.healthy && s.last_success_at);
  const latest = ok.map((s) => s.last_success_at!).sort().pop();
  if (ok.length === rows.length)
    return (
      <span className="w-done" title={`Scraped successfully, last ${latest ? stamp(latest) : ""}`}>
        <i>✓</i>
        {rows.length > 1 ? `All ${rows.length} · ` : ""}
        {ago(latest)}
      </span>
    );
  const failed = rows.filter((s) => !s.healthy).length;
  return (
    <span className={"w-done " + (failed ? "bad" : "wait")} title={failed ? "The latest run failed" : "Not scraped yet"}>
      <i>{failed ? "!" : "○"}</i>
      {rows.length > 1 ? `${ok.length} of ${rows.length}` : failed ? "Failed" : "Not yet"}
    </span>
  );
}
