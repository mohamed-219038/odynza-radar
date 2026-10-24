/* Client profile: who we watch for. The first save also sets up the client's own sources. */
import { useState, type FormEvent } from "react";
import { request, streamDiscovery } from "../api";
import type { Candidate, CompanyProfile } from "../types";
import { useToast } from "../components/Toast";
import { splitList } from "./format";
import { ExtLink } from "./parts";
import type { ClientInfo, WatchClient } from "./types";
import { Select } from "../components/Select";
import { Cover } from "./Visuals";

const CHANNELS = [
  "LinkedIn",
  "Instagram",
  "Facebook",
  "TikTok",
  "YouTube",
  "X",
  "Email",
  "Website",
];

export function Setup({
  info,
  canEdit,
  onSaved,
  create = false,
  onCancel,
}: {
  info: ClientInfo;
  canEdit: boolean;
  onSaved: (first: boolean, id?: number) => void;
  create?: boolean;
  onCancel?: () => void;
}) {
  const toast = useToast();
  const c: Partial<WatchClient> = info.client ?? {};
  const [form, setForm] = useState({
    name: c.name ?? "",
    website: c.website ?? "",
    sector: c.sector ?? "Software / AI",
    market: c.market ?? "Egypt",
    offer: c.offer ?? "",
    audience: c.audience ?? "",
    positioning: c.positioning ?? "",
    price_position: c.price_position ?? "mid",
    instagram: c.socials?.instagram ?? "",
    facebook: c.socials?.facebook ?? "",
    linkedin: c.socials?.linkedin ?? "",
    emails: (c.brief_emails ?? []).join(", "),
    extraClaims: (c.claims ?? [])
      .filter((x) => !info.starter_claims.includes(x))
      .join(", "),
  });
  const [channels, setChannels] = useState<string[]>(
    c.channels ?? ["LinkedIn", "Instagram", "Facebook"],
  );
  const [claims, setClaims] = useState<string[]>(
    (c.claims ?? []).filter((x) => info.starter_claims.includes(x)),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState<{
    status: string;
    busy: boolean;
    found: Candidate[] | null;
    profile: CompanyProfile | null;
  }>({ status: "", busy: false, found: null, profile: null });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: e.target.value });
  const toggle = (
    list: string[],
    value: string,
    setter: (v: string[]) => void,
  ) =>
    setter(
      list.includes(value) ? list.filter((x) => x !== value) : [...list, value],
    );

  /** The company search: finds the official website and social pages from the name. */
  async function find() {
    if (form.name.trim().length < 2) {
      setSearch({
        status: "Type the company name first.",
        busy: false,
        found: null,
        profile: null,
      });
      return;
    }
    setSearch({
      status:
        "Searching Google for the official website and social pages… Usually under 30 seconds.",
      busy: true,
      found: null,
      profile: null,
    });
    const started = Date.now();
    try {
      const data = await streamDiscovery(
        {
          company_name: form.name.trim(),
          context: form.market.trim().slice(0, 200),
          website: "",
          phase: "identify",
          market_scope: "local_first",
          refresh: false,
        },
        (ev) => {
          if (ev.type === "stage")
            setSearch((x) => ({
              ...x,
              status: `${ev.message} · ${Math.round((Date.now() - started) / 1000)} s`,
            }));
          if (ev.type === "partial")
            setSearch((x) => ({
              ...x,
              found: ev.candidates,
              profile: ev.company_profile ?? x.profile,
            }));
        },
      );
      const found = data.candidates ?? [];
      setSearch({
        status: found.length
          ? `${found.length} match${found.length === 1 ? "" : "es"} found. Pick yours to fill in the links.`
          : data.notice || "No match found. Type the links by hand.",
        busy: false,
        found,
        profile: data.company_profile ?? null,
      });
    } catch (err) {
      setSearch({
        status: (err as Error).message,
        busy: false,
        found: null,
        profile: null,
      });
    }
  }

  function use(cand: Candidate) {
    const p = search.profile;
    const offer =
      p?.offerings
        ?.map((o) => o.label)
        .filter(Boolean)
        .join(", ") ?? "";
    const audience =
      p?.offerings
        ?.map((o) => o.buyer)
        .filter(Boolean)
        .join(", ") ?? "";
    setForm((f) => ({
      ...f,
      name: f.name || cand.name,
      website: cand.website || f.website,
      instagram: cand.instagram || f.instagram,
      facebook: cand.facebook || f.facebook,
      linkedin: cand.linkedin || f.linkedin,
      market: f.market || p?.market || "",
      offer: f.offer || offer.slice(0, 600),
      audience: f.audience || audience.slice(0, 600),
    }));
    toast(`Filled in from ${cand.name}. Check the links, then save.`);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const out = await request<{ rescore_hint: boolean; client: WatchClient }>(
        create ? "/watch/clients" : "/watch/client",
        {
          method: create ? "POST" : "PUT",
          body: JSON.stringify({
            name: form.name,
            website: form.website,
            sector: form.sector,
            market: form.market,
            offer: form.offer,
            audience: form.audience,
            positioning: form.positioning,
            price_position: form.price_position,
            channels,
            claims: [...claims, ...splitList(form.extraClaims)].slice(0, 20),
            socials: {
              instagram: form.instagram,
              facebook: form.facebook,
              linkedin: form.linkedin,
            },
            brief_emails: splitList(form.emails),
          }),
        },
      );
      toast(
        out.rescore_hint
          ? "Profile saved. Use Rescore on Overview so past signals are judged against the new profile."
          : "Profile saved. Your own website and social pages are now watched too.",
      );
      onSaved(!info.client, out.client?.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {info.client && !create ? <Cover companyKey="client" /> : null}
      <form className="w-panel w-form" onSubmit={submit}>
        <div className="section-heading">
          <div>
            <h2>
              {create
                ? "New client"
                : info.client
                  ? "Client profile"
                  : "Start with the client profile"}
            </h2>
            <p>
              Every change is scored against this profile, so the more precise
              it is, the better the scores.
            </p>
          </div>
          {info.client ? (
            <span className="badge neutral">Version {info.client.version}</span>
          ) : null}
        </div>
        {canEdit ? (
          <div className="w-find">
            <div>
              <b>Find your website and social pages</b>
              <p className="muted">
                Type the company name below, then search. It uses the same
                Google search as Research, and checks each social page against
                the website.
              </p>
            </div>
            <button
              type="button"
              className="button secondary small-button"
              disabled={search.busy || busy}
              onClick={find}
            >
              {search.busy ? "Searching…" : "Search by name"}
            </button>
            {search.status ? (
              <p className="w-find-status" role="status">
                {search.status}
              </p>
            ) : null}
            {search.found?.length ? (
              <div className="w-find-list">
                {search.found.map((cand) => (
                  <div key={cand.name + cand.website} className="w-find-card">
                    <div>
                      <b>{cand.name}</b>
                      {cand.description ? (
                        <small>{cand.description.slice(0, 160)}</small>
                      ) : null}
                      <div className="w-links">
                        {cand.website ? (
                          <ExtLink href={cand.website} />
                        ) : (
                          <span className="muted">no website</span>
                        )}
                        {(["instagram", "facebook", "linkedin"] as const).map(
                          (k) =>
                            cand[k] ? (
                              <span
                                key={k}
                                title={
                                  cand.social_checks?.[k] === "unconfirmed"
                                    ? "Not confirmed on the website"
                                    : "Linked from the website or matched"
                                }
                              >
                                <ExtLink href={cand[k]!}>
                                  {k === "linkedin"
                                    ? "LinkedIn"
                                    : k.charAt(0).toUpperCase() + k.slice(1)}
                                </ExtLink>
                                {cand.social_checks?.[k] === "unconfirmed"
                                  ? " ?"
                                  : ""}
                              </span>
                            ) : null,
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="button small-button"
                      onClick={() => use(cand)}
                    >
                      Use this
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
        <fieldset disabled={!canEdit || busy}>
          <div className="plan-grid">
            <label>
              Company name
              <input
                required
                minLength={2}
                maxLength={200}
                value={form.name}
                onChange={set("name")}
                placeholder="Odynza"
              />
            </label>
            <label>
              Website
              <input
                required
                maxLength={500}
                value={form.website}
                onChange={set("website")}
                placeholder="https://odynza.com"
              />
            </label>
            <label>
              Sector
              <input
                maxLength={120}
                value={form.sector}
                onChange={set("sector")}
              />
            </label>
            <label>
              Market
              <input
                maxLength={120}
                value={form.market}
                onChange={set("market")}
              />
            </label>
          </div>
          <label>
            What you sell
            <textarea
              rows={2}
              maxLength={2000}
              value={form.offer}
              onChange={set("offer")}
              placeholder="AI agents and automation for marketing teams"
            />
          </label>
          <label>
            Who you sell to
            <textarea
              rows={2}
              maxLength={2000}
              value={form.audience}
              onChange={set("audience")}
              placeholder="Marketing managers at Egyptian SMEs and agencies"
            />
          </label>
          <label>
            How you position yourself
            <textarea
              rows={2}
              maxLength={2000}
              value={form.positioning}
              onChange={set("positioning")}
            />
          </label>
          <div className="plan-grid">
            <label>
              Price position
              <Select
                value={form.price_position}
                onChange={set("price_position")}
              >
                <option value="budget">Budget</option>
                <option value="mid">Mid-market</option>
                <option value="premium">Premium</option>
              </Select>
            </label>
            <label>
              Brief recipients <span className="optional">comma separated</span>
              <input
                value={form.emails}
                onChange={set("emails")}
                placeholder="you@example.com"
              />
            </label>
          </div>
          <fieldset className="plan-channels">
            <legend>Channels you use</legend>
            <div className="w-checks">
              {CHANNELS.map((ch) => (
                <label key={ch} className="checkbox">
                  <input
                    type="checkbox"
                    checked={channels.includes(ch)}
                    onChange={() => toggle(channels, ch, setChannels)}
                  />{" "}
                  {ch}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className="plan-channels">
            <legend>Claims you make</legend>
            <div className="w-checks">
              {info.starter_claims.map((cl) => (
                <label key={cl} className="checkbox">
                  <input
                    type="checkbox"
                    checked={claims.includes(cl)}
                    onChange={() => toggle(claims, cl, setClaims)}
                  />{" "}
                  {cl}
                </label>
              ))}
            </div>
            <label>
              Other claims <span className="optional">comma separated</span>
              <input value={form.extraClaims} onChange={set("extraClaims")} />
            </label>
          </fieldset>
          <div className="plan-grid w-socials">
            <label>
              Instagram <span className="optional">optional</span>
              <input
                value={form.instagram}
                onChange={set("instagram")}
                placeholder="https://www.instagram.com/…"
              />
            </label>
            <label>
              Facebook page <span className="optional">optional</span>
              <input
                value={form.facebook}
                onChange={set("facebook")}
                placeholder="https://www.facebook.com/…"
              />
            </label>
            <label>
              LinkedIn company page <span className="optional">optional</span>
              <input
                value={form.linkedin}
                onChange={set("linkedin")}
                placeholder="https://www.linkedin.com/company/…"
              />
            </label>
          </div>
        </fieldset>
        {error ? <p className="form-error report-error">{error}</p> : null}
        {canEdit ? (
          <div className="dialog-actions">
            {onCancel ? (
              <button
                type="button"
                className="button secondary"
                onClick={onCancel}
              >
                Cancel
              </button>
            ) : null}
            <button className="button primary" disabled={busy}>
              {busy
                ? "Saving…"
                : info.client
                  ? "Save profile"
                  : "Save and start watching"}
            </button>
          </div>
        ) : (
          <p className="muted">
            Only an admin or team member can change the profile.
          </p>
        )}
      </form>
      {canEdit && info.client && !create ? (
        <ClientLogins
          key={info.client.id}
          name={info.client.name}
          start={info.logins ?? []}
        />
      ) : null}
    </>
  );
}

/** Client accounts that see only this client in Watch. */
function ClientLogins({ name, start }: { name: string; start: string[] }) {
  const toast = useToast();
  const [text, setText] = useState(start.join(", "));
  const [busy, setBusy] = useState(false);
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const out = await request<{ logins: string[] }>("/watch/client/logins", {
        method: "PUT",
        body: JSON.stringify({ usernames: splitList(text) }),
      });
      setText(out.logins.join(", "));
      toast(
        out.logins.length
          ? `Saved. ${out.logins.join(", ")} now see${out.logins.length === 1 ? "s" : ""} only ${name}.`
          : "Saved. No client login is linked to this client.",
      );
    } catch (err) {
      toast((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="w-panel w-form w-logins" onSubmit={save}>
      <h3 className="w-sub">Client logins for {name}</h3>
      <p className="muted">
        Usernames of Client accounts (made in Team, role Client) that should see
        this client only. A Client account that is not linked here sees the
        first client.
      </p>
      <div className="w-inline-form">
        <input
          aria-label="Client usernames"
          placeholder="e.g. shop-owner, shop-marketing"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button className="button secondary small-button" disabled={busy}>
          {busy ? "Saving…" : "Save logins"}
        </button>
      </div>
    </form>
  );
}
