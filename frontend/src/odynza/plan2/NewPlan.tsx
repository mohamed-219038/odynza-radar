/* M1 Strategy · New plan: goal and money, a voice per platform (Radar's pick marked ★), and what Radar sends in. */
import { useEffect, useMemo, useState } from "react";
import { json, request } from "../../api";
import { useToast } from "../../components/Toast";
import { Select } from "../../components/Select";
import type { Platform } from "../../types";
import { PlatformGlyph } from "../../watch/Visuals";
import type { RadarDefaults, RadarPlanSummary, VoiceKey } from "./types";
import { EventChip, fmtDate, money } from "./ui";

const PLATFORMS: Platform[] = ["LinkedIn", "Instagram", "Facebook"];
const LENGTHS = [30, 60, 90, 180];
const addDays = (iso: string, n: number) => {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
};

export function NewPlan({ onCancel, onCreated }: { onCancel: () => void; onCreated: (p: RadarPlanSummary) => void }) {
  const toast = useToast();
  const [d, setD] = useState<RadarDefaults | null>(null);
  const [error, setError] = useState("");
  const [goal, setGoal] = useState("Leads");
  const [objective, setObjective] = useState("");
  const [audience, setAudience] = useState("");
  const [budget, setBudget] = useState("20000");
  const [currency, setCurrency] = useState("EGP");
  const [start, setStart] = useState("");
  const [days, setDays] = useState(90);
  const [events, setEvents] = useState("");
  const [voices, setVoices] = useState<Record<Platform, { key: VoiceKey; custom: string }>>({
    LinkedIn: { key: "formal", custom: "" }, Instagram: { key: "funky", custom: "" }, Facebook: { key: "friendly", custom: "" },
  });
  const [inputs, setInputs] = useState<string[]>([]);
  const [paid, setPaid] = useState<string[]>(["Meta ads", "LinkedIn ads"]);
  const [focus, setFocus] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    request<RadarDefaults>("/strategy/radar/defaults")
      .then((x) => {
        setD(x);
        setBudget(String(x.budget));
        setCurrency(x.currency);
        setStart(x.start_date);
        setAudience(x.client.audience || "");
        setVoices({
          LinkedIn: { key: x.voices.LinkedIn.suggested, custom: "" },
          Instagram: { key: x.voices.Instagram.suggested, custom: "" },
          Facebook: { key: x.voices.Facebook.suggested, custom: "" },
        });
        setInputs(x.inputs.filter((i) => i.count > 0).map((i) => i.key));
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  const end = start ? addDays(start, days - 1) : "";
  const inPeriod = useMemo(() => (d?.events ?? []).filter((e) => start && e.date <= end && (e.end_date || e.date) >= start), [d, start, end]);
  const monthly = Number(budget.replace(/,/g, ""));
  const total = Number.isFinite(monthly) ? Math.round((monthly * days) / 30.4) : 0;

  async function submit() {
    setBusy(true);
    try {
      const body = {
        goal, objective, audience, currency, start_date: start, end_date: end, events,
        budget: budget.trim() === "" ? null : monthly,
        voices: Object.fromEntries(PLATFORMS.map((p) => [p, voices[p]])),
        inputs, paid, opportunity_id: focus ? Number(focus) : null,
      };
      const plan = await request<RadarPlanSummary>("/strategy/radar/plans", json(body));
      toast("The strategy agents are writing your plan in n8n.");
      onCreated(plan);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="alert">{error}</div>;
  if (!d) return <div className="loading-state">Reading what Radar knows…</div>;
  const customMissing = PLATFORMS.some((p) => voices[p].key === "custom" && voices[p].custom.trim().length < 3);
  return (
    <div className="p2 p2-new">
      <header className="p2-head">
        <span className="p2-kicker">M1 Strategy · New plan for {d.client.name}</span>
        <h2>Build a {days}-day plan from what Radar saw</h2>
        <p>Radar fills in your rivals, their moves and your openings. You set the goal, the money and how you sound on each platform.</p>
      </header>

      <section className="p2-box" aria-labelledby="np1">
        <h3 id="np1"><b>1</b> Goal and money</h3>
        <div className="p2-chips" role="radiogroup" aria-label="Goal">
          {d.goals.map((g) => (
            <button key={g} type="button" role="radio" aria-checked={goal === g} className={"p2-chip" + (goal === g ? " on" : "")} onClick={() => setGoal(g)}>
              {g}
            </button>
          ))}
        </div>
        <div className="p2-grid4">
          <label>
            Monthly budget
            <input inputMode="numeric" value={budget} onChange={(e) => setBudget(e.target.value)} aria-describedby="np-total" />
          </label>
          <label>
            Currency
            <Select value={currency} onChange={(e) => setCurrency(e.target.value)} aria-label="Currency">
              {["EGP", "USD", "SAR", "AED", "EUR"].map((c) => <option key={c} value={c}>{c}</option>)}
            </Select>
          </label>
          <label>
            Starts on
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label>
            Plan length
            <Select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Plan length">
              {LENGTHS.map((n) => <option key={n} value={n}>{n} days</option>)}
            </Select>
          </label>
        </div>
        <p id="np-total" className="p2-fine">
          {start ? `${fmtDate(start)} to ${fmtDate(end)}` : ""} · about {money(total, currency)} for the whole plan. The agents only split it; the amounts are worked out here.
        </p>
        <div className="p2-grid2">
          <label>
            What does a win look like? (optional)
            <input value={objective} onChange={(e) => setObjective(e.target.value)} placeholder="40 demo requests from Cairo SMEs" maxLength={600} />
          </label>
          <label>
            Who are we talking to?
            <input value={audience} onChange={(e) => setAudience(e.target.value)} maxLength={300} />
          </label>
          <label>
            Your own dates (optional)
            <input value={events} onChange={(e) => setEvents(e.target.value)} placeholder="Product launch 15 Dec, webinar 20 Jan" maxLength={600} />
          </label>
        </div>
        <div className="p2-paid" role="group" aria-label="Paid channels">
          <span>Paid ads on</span>
          {d.paid.map((p) => (
            <label key={p} className="p2-check">
              <input type="checkbox" checked={paid.includes(p)} onChange={() => setPaid(paid.includes(p) ? paid.filter((x) => x !== p) : [...paid, p])} />
              {p}
            </label>
          ))}
        </div>
        {inPeriod.length ? (
          <div className="p2-events">
            <span>Dates Radar will plan around</span>
            <div>{inPeriod.map((e) => <EventChip key={e.date + e.title} e={e} />)}</div>
            <small>* date depends on the moon or the organiser: check it before you book anything.</small>
          </div>
        ) : null}
      </section>

      <section className="p2-box" aria-labelledby="np2">
        <h3 id="np2"><b>2</b> Voice per platform</h3>
        <p className="p2-fine">The content agents write every post in this voice. Every platform is written in English.</p>
        <div className="p2-voices">
          {PLATFORMS.map((p) => (
            <fieldset key={p} className="p2-voice">
              <legend>
                <PlatformGlyph kind={p.toLowerCase()} size={18} /> {p} <small>{d.languages[p]}</small>
              </legend>
              {[...d.voice_options, { key: "custom" as VoiceKey, label: "Custom voice", style: "Describe it in your own words." }].map((o) => (
                <label key={o.key} className={"p2-voice-opt" + (voices[p].key === o.key ? " on" : "")}>
                  <input type="radio" name={`voice-${p}`} checked={voices[p].key === o.key} onChange={() => setVoices({ ...voices, [p]: { ...voices[p], key: o.key } })} />
                  <span>
                    <b>
                      {o.label}
                      {d.voices[p].suggested === o.key ? <em title={d.voices[p].why}> ★ Radar pick</em> : null}
                    </b>
                    <small>{o.style}</small>
                  </span>
                </label>
              ))}
              {voices[p].key === "custom" ? (
                <input aria-label={`Custom voice for ${p}`} value={voices[p].custom} maxLength={300} placeholder="Cheeky, short, Cairo slang, no emojis"
                  onChange={(e) => setVoices({ ...voices, [p]: { ...voices[p], custom: e.target.value } })} />
              ) : null}
              <p className="p2-why">★ {d.voices[p].why}</p>
            </fieldset>
          ))}
        </div>
      </section>

      <section className="p2-box" aria-labelledby="np3">
        <h3 id="np3"><b>3</b> What Radar sends in</h3>
        <div className="p2-inputs">
          {d.inputs.map((i) => (
            <label key={i.key} className={"p2-input" + (inputs.includes(i.key) ? " on" : "") + (i.count ? "" : " empty")}>
              <input type="checkbox" checked={inputs.includes(i.key)} disabled={!i.count}
                onChange={() => setInputs(inputs.includes(i.key) ? inputs.filter((x) => x !== i.key) : [...inputs, i.key])} />
              <span>
                <b>{i.label}</b>
                <small>{i.count ? (i.key === "brief" ? `Week of ${i.note}` : `${i.count} ready`) : "Nothing collected yet"}</small>
              </span>
            </label>
          ))}
        </div>
        {d.opportunities.length ? (
          <label className="p2-focus">
            Build the plan around one opportunity (optional)
            <Select value={focus} onChange={(e) => setFocus(e.target.value)} aria-label="Opportunity to build around">
              <option value="">No, weigh them all</option>
              {d.opportunities.map((o) => <option key={o.id} value={String(o.id)}>{o.angle} ({o.confidence})</option>)}
            </Select>
          </label>
        ) : null}
      </section>

      <div className="p2-actions">
        <button className="button secondary" onClick={onCancel}>Cancel</button>
        <button className="button primary" disabled={busy || !start || customMissing} onClick={submit}>
          {busy ? "Starting…" : "Write the plan"}
        </button>
      </div>
    </div>
  );
}
