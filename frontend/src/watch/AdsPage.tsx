/* Every watched competitor's Meta ads (Ad Library through Apify), live first, with images and the landing page. */
import { useState } from "react";
import { json, request } from "../api";
import { useToast } from "../components/Toast";
import { ago, TIER_LABEL } from "./format";
import { Empty, ExtLink, Loading, Logo, Problem, useLoad } from "./parts";
import { AdCard, type Who } from "./PlatformCard";
import type { Ad, Source, Tier } from "./types";

interface AdsCompany {
  competitor_id: number;
  name: string;
  tier: Tier;
  facebook: string;
  socials: Record<string, string>;
  source: Source | null;
  ads: { items: Ad[]; metrics: { live_ads?: number; ads_seen?: number; other_pages_dropped?: number }; captured_at: string | null; unchecked?: boolean } | null;
}

export function AdsPage({ canRun, canDecide, go }: { canRun: boolean; canDecide: boolean; go: (tab: "competitors" | "sources") => void }) {
  const toast = useToast();
  const { data, error, reload } = useLoad<{ companies: AdsCompany[] }>("/watch/ads");
  const [who, setWho] = useState<number | "all">("all");
  const [liveOnly, setLiveOnly] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [fb, setFb] = useState<Record<number, string>>({});

  async function saveFacebook(c: AdsCompany) {
    const url = (fb[c.competitor_id] ?? "").trim();
    if (!/^https?:\/\/(www\.|m\.)?facebook\.com\/.+/i.test(url)) {
      toast("Paste the full Facebook page link, like https://www.facebook.com/pagename");
      return;
    }
    setBusy(c.competitor_id);
    try {
      const socials = { instagram: c.socials.instagram ?? "", facebook: url, linkedin: c.socials.linkedin ?? "" };
      await request(`/watch/competitors/${c.competitor_id}`, { method: "PATCH", body: JSON.stringify({ socials }) });
      toast(`Saved. ${c.name}'s Facebook page and ads are now watched. Press Check ads now to get them.`);
      reload();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function check(c: AdsCompany) {
    if (!c.source) return;
    setBusy(c.competitor_id);
    try {
      const out = await request<{ message: string }>("/watch/run", json({ source_ids: [c.source.id] }));
      toast(out.message + " The ads show here when it finishes.");
      window.setTimeout(reload, 60000);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (!data) return error ? <Problem text={error} /> : <Loading text="Loading ads…" />;
  const companies = data.companies;
  const shown = companies.filter((c) => who === "all" || c.competitor_id === who);
  const total = (c: AdsCompany) => (c.ads && !c.ads.unchecked ? c.ads.items.length : 0);
  const live = (c: AdsCompany) => (c.ads && !c.ads.unchecked ? c.ads.items.filter((a) => a.active).length : 0);

  return (
    <div className="w-main">
      <div className="w-heading">
        <div>
          <h2>Competitor ads</h2>
          <p>Ads each rival's own Facebook page runs on Facebook and Instagram, from the Meta Ad Library. Checked weekly for direct and adjacent rivals. Meta shows no spend for Egyptian ads, so only the ads themselves are listed.</p>
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={liveOnly} onChange={(e) => setLiveOnly(e.target.checked)} /> Live ads only
        </label>
      </div>
      {companies.length ? (
        <div className="w-switch" role="group" aria-label="Competitor">
          <button className={who === "all" ? "selected" : ""} aria-pressed={who === "all"} onClick={() => setWho("all")}>
            All <span>{companies.reduce((n, c) => n + total(c), 0)}</span>
          </button>
          {companies.map((c) => (
            <button key={c.competitor_id} className={who === c.competitor_id ? "selected" : ""} aria-pressed={who === c.competitor_id} onClick={() => setWho(c.competitor_id)}>
              <Logo id={c.competitor_id} name={c.name} size={18} /> {c.name} <span>{c.ads?.unchecked ? "?" : total(c)}</span>
            </button>
          ))}
        </div>
      ) : (
        <Empty icon="▤" title="No watched competitors yet.">
          <button className="text-link" onClick={() => go("competitors")}>
            Confirm a competitor →
          </button>
        </Empty>
      )}
      {shown.map((c) => {
        const items = c.ads && !c.ads.unchecked ? c.ads.items.filter((a) => !liveOnly || a.active).sort((a, b) => Number(b.active) - Number(a.active) || (b.start ?? "").localeCompare(a.start ?? "")) : [];
        return (
          <section key={c.competitor_id} className="w-panel w-ads-company">
            <div className="section-heading">
              <div>
                <h3 className="w-sub w-who">
                  <Logo id={c.competitor_id} name={c.name} size={30} /> {c.name} <span className="badge neutral">{TIER_LABEL[c.tier]}</span>
                </h3>
                <p className="muted">
                  {!c.facebook
                    ? "No Facebook page saved, so its ads cannot be checked."
                    : !c.source
                      ? `${TIER_LABEL[c.tier]} rivals are not checked for ads.`
                      : c.source.last_error
                        ? `Last check failed: ${c.source.last_error}`
                        : !c.ads
                          ? "Not checked yet."
                          : c.ads.unchecked
                            ? "The last check was saved before ads were matched to this page, so it is hidden. Check again to get this page's own ads."
                            : `${live(c)} live · ${total(c)} seen · checked ${ago(c.ads.captured_at)}${c.ads.metrics.other_pages_dropped ? ` · ${c.ads.metrics.other_pages_dropped} ads from other pages left out` : ""}`}
                </p>
              </div>
              <div className="w-actions">
                {c.facebook ? <ExtLink href={c.facebook}>Facebook page</ExtLink> : null}
                {canRun && c.source ? (
                  <button className="button secondary small-button" disabled={busy === c.competitor_id} onClick={() => check(c)}>
                    {busy === c.competitor_id ? "Starting…" : "Check ads now"}
                  </button>
                ) : null}
                {!c.facebook && canDecide ? (
                  <form
                    className="w-inline-form"
                    onSubmit={(e) => {
                      e.preventDefault();
                      saveFacebook(c);
                    }}
                  >
                    <input aria-label={`${c.name} Facebook page`} placeholder="https://www.facebook.com/…" value={fb[c.competitor_id] ?? ""} onChange={(e) => setFb({ ...fb, [c.competitor_id]: e.target.value })} />
                    <button className="button secondary small-button" disabled={busy === c.competitor_id}>
                      Add Facebook page
                    </button>
                  </form>
                ) : null}
              </div>
            </div>
            {items.length ? (
              <div className="w-evidence-grid">
                {items.map((a) => (
                  <LibraryAd key={a.id} ad={a} who={{ name: c.name, logo: c.competitor_id }} />
                ))}
              </div>
            ) : c.ads && !c.ads.unchecked ? (
              <p className="w-filter-empty">{liveOnly && total(c) ? "No live ads right now." : "This page runs no ads in Egypt right now, and none were found in the Ad Library."}</p>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}

function LibraryAd({ ad, who }: { ad: Ad; who: Who }) {
  return (
    <div className={"pf-item" + (ad.active ? " live" : "")}>
      <AdCard ad={ad} who={who} />
      <div className="pf-under">
        <ExtLink href={ad.url}>Open in the Ad Library</ExtLink>
        {ad.landing ? <ExtLink href={ad.landing}>Landing page</ExtLink> : null}
      </div>
    </div>
  );
}
