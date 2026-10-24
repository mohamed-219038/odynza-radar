/* The register: proposals wait for a person, confirmed competitors are watched by tier. */
import { useState, type FormEvent } from "react";
import { json, request } from "../api";
import { useToast } from "../components/Toast";
import { ago, TIER_HELP, TIER_LABEL } from "./format";
import { CompetitorDialog } from "./CompetitorDialog";
import { Empty, ExtLink, Loading, Logo, Problem, useLoad } from "./parts";
import type { Competitor, Tier } from "./types";
import { Select } from "../components/Select";
import { Thumbs } from "./Visuals";

const TIERS = Object.keys(TIER_LABEL) as Tier[];
const GROUPS: [Competitor["status"], string, string][] = [
  ["proposed", "Waiting for your decision", "Nothing is collected until a person confirms it."],
  ["confirmed", "Watched", "Checked automatically by tier."],
  ["rejected", "Rejected", "Kept so the search does not propose them again."],
];

export function CompetitorsPage({ canDecide, canStaff, onChanged }: { canDecide: boolean; canStaff: boolean; onChanged?: () => void }) {
  const toast = useToast();
  const { data, error, reload: load } = useLoad<Competitor[]>("/watch/competitors");
  const reload = () => {
    load();
    onChanged?.();
  };
  const [busy, setBusy] = useState("");
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [tiers, setTiers] = useState<Record<number, Tier>>({});

  async function propose() {
    setBusy("propose");
    try {
      const out = await request<{ added: Competitor[]; notice: string }>("/watch/competitors/propose", { method: "POST" });
      toast(out.added.length ? `${out.added.length} competitors proposed. Confirm the ones to watch.` : out.notice || "No new competitors found.");
      reload();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function decide(c: Competitor, status: Competitor["status"]) {
    setBusy(`c${c.id}`);
    try {
      const out = await request<Competitor>(`/watch/competitors/${c.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status, tier: tiers[c.id] ?? c.tier }),
      });
      toast(status === "confirmed" ? `${out.name} is watched now (${out.sources} sources). Its first run is the baseline.` : `${out.name} ${status === "rejected" ? "rejected" : "moved back to proposals"}.`);
      reload();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  if (!data) return error ? <Problem text={error} /> : <Loading text="Opening the register…" />;
  return (
    <div className="w-main">
      <div className="w-heading">
        <div>
          <h2>Competitor register</h2>
          <p>Proposals come from the competitor search. You decide who is watched and how closely.</p>
        </div>
        <div className="w-actions">
          {canStaff ? (
            <button className="button secondary" disabled={Boolean(busy)} onClick={propose}>
              {busy === "propose" ? "Searching… (up to a minute)" : "Find competitors"}
            </button>
          ) : null}
          {canDecide ? (
            <button className="button primary" onClick={() => setAdding(!adding)}>
              <span>＋</span> Add a competitor
            </button>
          ) : null}
        </div>
      </div>
      <Problem text={error} />
      {adding ? (
        <AddForm
          onDone={() => {
            setAdding(false);
            reload();
          }}
        />
      ) : null}
      <div className="w-tier-help">
        {TIERS.map((t) => (
          <span key={t}>
            <b>{TIER_LABEL[t]}</b> {TIER_HELP[t]}
          </span>
        ))}
      </div>
      {!data.length ? (
        <Empty icon="◎" title="No competitors yet.">
          Use Find competitors to search for them, or add the ones you already know.
        </Empty>
      ) : null}
      {GROUPS.map(([status, title, note]) => {
        const rows = data.filter((c) => c.status === status || (status === "proposed" && c.status === "queued"));
        if (!rows.length) return null;
        return (
          <section key={status} className="w-group">
            <h3 className="w-sub">
              {title} <span className="count">{rows.length}</span>
            </h3>
            <p className="muted">{note}</p>
            {rows.map((c) => (
              <div key={c.id} className="session-row w-comp" data-competitor={c.id}>
                <Logo id={c.id} name={c.name} size={40} />
                <span className="session-info">
                  <h3>
                    <button type="button" className="w-name" onClick={() => setOpen(c.id)}>
                      {c.name}
                    </button>{" "}
                    {c.review_due ? <span className="badge warn">Review due</span> : null}
                  </h3>
                  <small>
                    <ExtLink href={c.website} /> {c.why ? <span>· {c.why.slice(0, 160)}</span> : null}
                  </small>
                  <small>
                    {c.origin === "manual" ? "Added by hand" : "Proposed by search"}
                    {c.decided_by ? ` · ${c.status} by ${c.decided_by} ${ago(c.decided_at)}` : ""}
                    {c.sources ? ` · ${c.sources} sources` : ""}
                  </small>
                  {c.status === "confirmed" ? <Thumbs companyKey={String(c.id)} /> : null}
                </span>
                <span className="session-end w-comp-actions">
                  {canDecide && c.status !== "rejected" ? (
                    <Select aria-label={`Tier for ${c.name}`} value={tiers[c.id] ?? c.tier} onChange={(e) => setTiers({ ...tiers, [c.id]: e.target.value as Tier })}>
                      {TIERS.map((t) => (
                        <option key={t} value={t}>
                          {TIER_LABEL[t]}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <span className="badge neutral">{TIER_LABEL[c.tier]}</span>
                  )}
                  {canDecide && c.status !== "confirmed" ? (
                    <button className="button primary small-button" disabled={busy === `c${c.id}`} onClick={() => decide(c, "confirmed")}>
                      Confirm
                    </button>
                  ) : null}
                  {canDecide && c.status === "confirmed" && tiers[c.id] && tiers[c.id] !== c.tier ? (
                    <button className="button primary small-button" disabled={busy === `c${c.id}`} onClick={() => decide(c, "confirmed")}>
                      Save tier
                    </button>
                  ) : null}
                  {canDecide && c.status !== "rejected" ? (
                    <button className="button secondary small-button" disabled={busy === `c${c.id}`} onClick={() => decide(c, "rejected")}>
                      Reject
                    </button>
                  ) : null}
                  {canDecide && c.status === "rejected" ? (
                    <button className="button secondary small-button" disabled={busy === `c${c.id}`} onClick={() => decide(c, "proposed")}>
                      Undo
                    </button>
                  ) : null}
                  <button className="button secondary small-button" onClick={() => setOpen(c.id)}>
                    Details ↗
                  </button>
                </span>
              </div>
            ))}
          </section>
        );
      })}
      <CompetitorDialog id={open} canDecide={canDecide} canRun={canStaff} onClose={() => setOpen(null)} onChanged={reload} />
    </div>
  );
}

function AddForm({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ name: "", website: "", tier: "direct" as Tier, instagram: "", facebook: "", linkedin: "", why: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const out = await request<Competitor>(
        "/watch/competitors",
        json({ name: f.name, website: f.website, tier: f.tier, why: f.why, socials: { instagram: f.instagram, facebook: f.facebook, linkedin: f.linkedin } }),
      );
      toast(`${out.name} added and watched (${out.sources} sources).`);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="w-panel w-form" onSubmit={submit}>
      <h3 className="w-sub">Add a competitor you know</h3>
      <p className="muted">Added by a person, so it is confirmed at once. Pages are found from its homepage links.</p>
      <fieldset disabled={busy}>
        <div className="plan-grid">
          <label>
            Name
            <input required minLength={2} maxLength={200} value={f.name} onChange={set("name")} />
          </label>
          <label>
            Website
            <input required maxLength={500} value={f.website} onChange={set("website")} placeholder="https://…" />
          </label>
          <label>
            Tier
            <Select value={f.tier} onChange={set("tier")}>
              {TIERS.map((t) => (
                <option key={t} value={t}>
                  {TIER_LABEL[t]} · {TIER_HELP[t]}
                </option>
              ))}
            </Select>
          </label>
          <label>
            Why watch them <span className="optional">optional</span>
            <input maxLength={600} value={f.why} onChange={set("why")} />
          </label>
          <label>
            Instagram <span className="optional">optional</span>
            <input value={f.instagram} onChange={set("instagram")} />
          </label>
          <label>
            Facebook page <span className="optional">optional, needed for ads</span>
            <input value={f.facebook} onChange={set("facebook")} />
          </label>
          <label>
            LinkedIn company page <span className="optional">optional</span>
            <input value={f.linkedin} onChange={set("linkedin")} />
          </label>
        </div>
      </fieldset>
      {error ? <p className="form-error report-error">{error}</p> : null}
      <div className="dialog-actions">
        <button type="button" className="button secondary" onClick={onDone}>
          Cancel
        </button>
        <button className="button primary" disabled={busy}>
          {busy ? "Adding…" : "Add and watch"}
        </button>
      </div>
    </form>
  );
}
