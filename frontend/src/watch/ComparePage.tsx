/* You against the watched set: scorecard per platform, content gaps and the claim map. */
import { useState, type FormEvent } from "react";
import { json, request } from "../api";
import { useToast } from "../components/Toast";
import { count, KIND_LABEL, pct } from "./format";
import { CompetitorDialog } from "./CompetitorDialog";
import { Empty, Loading, Logo, Problem, useLoad } from "./parts";
import type { Claim, CompareData, SocialKind } from "./types";
import { Select } from "../components/Select";
import { BestPosts, PlatformGlyph } from "./Visuals";

const SOCIAL: SocialKind[] = ["instagram", "facebook", "linkedin"];
const STATUS_HELP: Record<Claim["status"], string> = {
  crowded: "3 or more rivals say it. Hard to stand out here.",
  contested: "1 or 2 rivals say it.",
  unclaimed: "No watched rival says it. A possible opening.",
};

export function ComparePage({ canDecide, canStaff }: { canDecide: boolean; canStaff: boolean }) {
  const toast = useToast();
  const { data, error, reload } = useLoad<CompareData>("/watch/compare");
  const [platform, setPlatform] = useState<SocialKind>("instagram");
  const [open, setOpen] = useState<{ id: number; live: boolean } | null>(null);
  const [label, setLabel] = useState("");

  async function toggle(claim: Claim, key: string) {
    const holds = !claim.holders[key];
    try {
      await request(`/watch/claims/${claim.id}/holders`, { method: "PUT", body: JSON.stringify({ company: key, holds }) });
      reload();
    } catch (e) {
      toast((e as Error).message);
    }
  }

  async function addClaim(e: FormEvent) {
    e.preventDefault();
    try {
      await request("/watch/claims", json({ label, synonyms: [] }));
      setLabel("");
      reload();
    } catch (err) {
      toast((err as Error).message);
    }
  }

  async function merge(claim: Claim, into: string) {
    if (!into) return;
    try {
      await request(`/watch/claims/${claim.id}/merge/${into}`, { method: "POST" });
      toast(`"${claim.label}" merged. Its wording is kept as a synonym.`);
      reload();
    } catch (e) {
      toast((e as Error).message);
    }
  }

  if (!data) return error ? <Problem text={error} /> : <Loading text="Lining up the set…" />;
  const rows = data.scorecard.rows;
  return (
    <div className="w-main">
      <div className="w-heading">
        <div>
          <h2>You against the watched set</h2>
          <p>Engagement rate leads, not followers: interactions per post divided by followers, averaged over the last 30 days.</p>
        </div>
        <div className="tabs">
          {SOCIAL.map((k) => (
            <button key={k} className={"tab w-tab-glyph" + (platform === k ? " active" : "")} onClick={() => setPlatform(k)}>
              <PlatformGlyph kind={k} size={16} /> {KIND_LABEL[k]}
            </button>
          ))}
        </div>
      </div>
      <Problem text={error} />
      <div className="w-panel w-table-wrap">
        <table className="plan-table w-score-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Engagement rate</th>
              <th>Followers</th>
              <th>Posts / week</th>
              <th>Last post</th>
              <th>Formats (30 days)</th>
              <th>Live ads</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const p = r.platforms[platform];
              return (
                <tr key={r.key} className={r.you ? "w-you" : ""}>
                  <td>
                    <span className="w-who">
                      <Logo id={r.you ? "client" : r.id!} name={r.name} size={24} />
                      {r.you ? (
                        <b>You ({r.name})</b>
                      ) : (
                        <button className="w-name" onClick={() => setOpen({ id: r.id!, live: false })}>
                          {r.name}
                        </button>
                      )}
                    </span>
                    <small>{r.you ? "client" : r.tier}</small>
                  </td>
                  <td>
                    <b>{pct(p?.engagement_rate)}</b>
                  </td>
                  <td>{count(p?.followers)}</td>
                  <td>{p?.posts_per_week ?? "—"}</td>
                  <td>{p?.days_since_last_post === null || p?.days_since_last_post === undefined ? "—" : p.days_since_last_post === 0 ? "today" : `${p.days_since_last_post} days ago`}</td>
                  <td>{p?.format_mix ? Object.entries(p.format_mix).map(([f, n]) => `${f} ${n}`).join(", ") || "none" : "—"}</td>
                  <td>
                    {count(r.live_ads)}
                    {r.live_ads && !r.you ? (
                      <button className="text-link w-inline" onClick={() => setOpen({ id: r.id!, live: true })}>
                        List
                      </button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {platform === "instagram" ? <p className="muted w-pad">Instagram shares are not public, so Instagram engagement counts likes and comments only.</p> : null}
      </div>

      <BestPosts title="Best post of each company" sub="The post with the most interactions from each company's latest capture, you included." />
      <section className="w-panel">
        <h3 className="w-sub">Content gaps</h3>
        <p className="muted">Where at least two rivals are active and you are not.</p>
        {data.gaps.length ? (
          <div className="plan-cards">
            {data.gaps.map((g, i) => (
              <div key={i} className="plan-card">
                <span className="badge neutral">{g.kind}</span>
                <h4>{g.label}</h4>
                <p>{g.detail}</p>
                <small>{g.rivals.join(", ")}</small>
              </div>
            ))}
          </div>
        ) : (
          <Empty icon="◇" title="No gaps found yet.">
            Gaps appear once at least two rivals and your own pages have social captures.
          </Empty>
        )}
      </section>

      <section className="w-panel">
        <div className="section-heading">
          <div>
            <h3 className="w-sub">Claim map</h3>
            <p className="muted">Who says what. Tick a cell to correct it by hand.</p>
          </div>
          {canDecide ? (
            <form className="w-inline-form" onSubmit={addClaim}>
              <input aria-label="New claim" placeholder="Add a claim…" minLength={2} maxLength={120} required value={label} onChange={(e) => setLabel(e.target.value)} />
              <button className="button secondary small-button">Add</button>
            </form>
          ) : null}
        </div>
        {data.claims.length ? (
          <div className="w-table-wrap">
            <table className="plan-table w-claims">
              <thead>
                <tr>
                  <th>Claim</th>
                  <th>Status</th>
                  {data.companies.map((c) => (
                    <th key={c.key}>
                      <span className="w-who w-who-col">
                        <Logo id={c.key} name={c.name} size={26} />
                        {c.you ? "You" : c.name}
                      </span>
                    </th>
                  ))}
                  {canStaff ? <th>Merge into</th> : null}
                </tr>
              </thead>
              <tbody>
                {data.claims.map((cl) => (
                  <tr key={cl.id}>
                    <td>
                      <b>{cl.label}</b>
                      {cl.synonyms.length ? <small>also: {cl.synonyms.join(", ")}</small> : null}
                    </td>
                    <td>
                      <span className={"badge " + (cl.status === "crowded" ? "warn" : cl.status === "unclaimed" ? "" : "running")} title={STATUS_HELP[cl.status]}>
                        {cl.status}
                      </span>
                    </td>
                    {data.companies.map((c) => {
                      const h = cl.holders[c.key];
                      return (
                        <td key={c.key} className="w-cell" title={h?.quote || undefined}>
                          {canDecide ? (
                            <button className={"w-tick" + (h ? " on" : "")} aria-pressed={Boolean(h)} aria-label={`${c.name} ${h ? "claims" : "does not claim"} ${cl.label}`} onClick={() => toggle(cl, c.key)}>
                              {h ? "✓" : ""}
                            </button>
                          ) : h ? (
                            "✓"
                          ) : (
                            ""
                          )}
                        </td>
                      );
                    })}
                    {canStaff ? (
                      <td>
                        <Select aria-label={`Merge ${cl.label}`} value="" onChange={(e) => merge(cl, e.target.value)} className="w-mini-select">
                          <option value="">—</option>
                          {data.claims
                            .filter((x) => x.id !== cl.id)
                            .map((x) => (
                              <option key={x.id} value={x.id}>
                                {x.label}
                              </option>
                            ))}
                        </Select>
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon="✦" title="No claims yet.">
            Claims come from your profile, the scored changes and the weekly brief.
          </Empty>
        )}
      </section>
      <CompetitorDialog id={open?.id ?? null} liveAds={open?.live} canDecide={canDecide} canRun={canStaff} onClose={() => setOpen(null)} onChanged={reload} />
    </div>
  );
}
