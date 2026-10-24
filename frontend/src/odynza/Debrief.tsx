/* The weekly brief as a "mission debrief" (the look Odynza picked): status headline, a radar of the rivals,
   four signal tiles, you against the rivals, a contact log, what was intercepted, and the next moves for each agent.
   Everything comes from the brief and the week's snapshot; nothing here is made up. */
import { count, pct, TIER_LABEL } from "../watch/format";
import { ExtLink, Logo, ScoreBadge } from "../watch/parts";
import type { Brief, WeekSnapshot } from "../watch/types";
import { AgentMark } from "./Mark";
import { FieldStrip, PlatformItem, useGallery } from "../watch/Visuals";
import { findAd, findMention, findPost, keyOf } from "../watch/WeekView";

const PLATFORM = { instagram: "Instagram", facebook: "Facebook", linkedin: "LinkedIn" } as const;
const BLIP = ["#4FD1E8", "#F5A35C", "#FF8A6B", "#B79CFF", "#7EE0A1", "#F7D154"];

type Rival = WeekSnapshot["rivals"][number];

/** How loud a rival was this week: posts and ads count most, then news and hiring. */
export function activity(r: Rival) {
  return r.posts_7d * 3 + (r.live_ads ?? 0) * 4 + r.news + (r.jobs ? 1 : 0);
}

export function status(brief: Brief) {
  const top = Math.max(0, ...brief.items.map((i) => i.score));
  if (top >= 5) return { code: "RED ALERT", tone: "red" };
  if (top >= 4) return { code: "CONTACTS INBOUND", tone: "orange" };
  if (brief.items.length) return { code: "LIGHT TRAFFIC", tone: "cyan" };
  return { code: "QUIET SKIES", tone: "lime" };
}

/** Rivals placed on the radar: louder ones sit closer to you in the centre. */
export function placeRivals(rivals: Rival[]) {
  const top = Math.max(1, ...rivals.map(activity));
  return rivals.slice(0, 8).map((r, i, all) => {
    const a = activity(r) / top;
    const radius = 58 + (1 - a) * 66;
    const angle = -2.2 + (i * (Math.PI * 2)) / Math.max(all.length, 1);
    const ring = a > 0.66 ? "CLOSE" : a > 0.33 ? "MID" : "FAR";
    return { r, x: 200 + Math.cos(angle) * radius, y: 150 + Math.sin(angle) * radius, colour: BLIP[i % BLIP.length], ring };
  });
}

function RadarPlot({ snap }: { snap: WeekSnapshot }) {
  const dots = placeRivals(snap.rivals);
  return (
    <div className="odz-db-radar">
      <svg viewBox="0 0 400 300" width="100%" role="img" aria-label={`Radar of ${dots.length} rivals; closer to the centre means more active this week`}>
        {[130, 86, 42].map((r) => (
          <circle key={r} cx="200" cy="150" r={r} fill="none" stroke="#22304F" strokeWidth="1.5" />
        ))}
        <path d="M70 150 H330 M200 20 V280" stroke="#1A2642" strokeWidth="1" />
        <g className="odz-db-sweep">
          <path d="M200 150 L312 84 A130 130 0 0 0 200 20 Z" fill="#C6F432" fillOpacity=".14" />
          <path d="M200 150 L312 84" stroke="#C6F432" strokeWidth="2.5" strokeLinecap="round" />
        </g>
        <circle cx="200" cy="150" r="7" fill="#C6F432" />
        <text x="200" y="176" textAnchor="middle" className="odz-db-label">
          You
        </text>
        {dots.map((d) => (
          <g key={d.r.key}>
            <circle cx={d.x} cy={d.y} r="16" fill={d.colour} fillOpacity=".18" />
            <circle cx={d.x} cy={d.y} r="7" fill={d.colour} />
            <text x={d.x + (d.x < 200 ? -14 : 14)} y={d.y - 14} textAnchor={d.x < 200 ? "end" : "start"} className="odz-db-label">
              {d.r.name}
            </text>
          </g>
        ))}
      </svg>
      <small>Closer to the centre means more active this week</small>
    </div>
  );
}

function Bars({ snap }: { snap: WeekSnapshot }) {
  const rows = snap.standing.filter((s) => s.you !== null || s.rivals_avg !== null);
  if (!rows.length) return null;
  return (
    <section className="odz-db-card">
      <h3>You against the rivals</h3>
      {rows.map((s) => {
        const top = Math.max(s.you ?? 0, s.rivals_avg ?? 0) || 1;
        const ahead = (s.you ?? 0) >= (s.rivals_avg ?? 0);
        return (
          <div key={s.platform} className="odz-db-bar">
            <div>
              <span>{PLATFORM[s.platform]} · you</span>
              <b className={ahead ? "good" : "bad"}>{pct(s.you)}</b>
            </div>
            <i className="you" style={{ width: `${Math.max(2, ((s.you ?? 0) / top) * 100)}%` }} />
            <div className="muted">
              <span>Rivals' average{s.leader ? ` · best: ${s.leader} ${pct(s.leader_rate)}` : ""}</span>
              <b>{pct(s.rivals_avg)}</b>
            </div>
            <i className="them" style={{ width: `${Math.max(2, ((s.rivals_avg ?? 0) / top) * 100)}%` }} />
          </div>
        );
      })}
      <small className="odz-db-note">Engagement rate: interactions per post divided by followers.</small>
    </section>
  );
}

function ContactLog({ snap }: { snap: WeekSnapshot }) {
  if (!snap.rivals.length) return null;
  const dots = placeRivals(snap.rivals);
  const facts = (r: Rival) =>
    [
      r.posts_7d ? `${r.posts_7d} post${r.posts_7d === 1 ? "" : "s"}` : "no posts",
      r.news ? `${r.news} news mention${r.news === 1 ? "" : "s"}` : "",
      r.jobs ? `hiring ${r.jobs} roles` : "",
      r.live_ads ? `${r.live_ads} live ad${r.live_ads === 1 ? "" : "s"}` : "",
      r.followers && r.platform ? `${count(r.followers)} on ${PLATFORM[r.platform]}` : "",
    ]
      .filter(Boolean)
      .join(", ");
  return (
    <section className="odz-db-card">
      <h3>Contact log</h3>
      <ul className="odz-db-log">
        {dots
          .slice()
          .sort((a, b) => activity(b.r) - activity(a.r))
          .map((d) => (
            <li key={d.r.key}>
              <Logo id={d.r.key} name={d.r.name} size={30} />
              <span>
                <b>{d.r.name}</b> <small>{TIER_LABEL[d.r.tier]}</small>
                <em>{facts(d.r)}</em>
              </span>
              <code style={{ color: d.colour }}>{d.ring}</code>
            </li>
          ))}
      </ul>
    </section>
  );
}

function Intercepted({ snap }: { snap: WeekSnapshot }) {
  const gallery = useGallery();
  const cards = [
    ...snap.posts.map((p, i) => (
      <div key={"p" + i} className="w-week-feed-item">
        <code className="odz-db-tag cyan">{`${p.company} · ${PLATFORM[p.platform]}${p.this_week ? " · this week" : ""}`.toUpperCase()}</code>
        <PlatformItem kind={p.platform} raw={findPost(gallery, p)} who={{ name: p.company, logo: p.key }} />
      </div>
    )),
    ...snap.news.map((n, i) => (
      <div key={"n" + i} className="w-week-feed-item">
        <code className="odz-db-tag orange">{`${n.company} · ${n.kind === "news" ? "news" : "web"}`.toUpperCase()}</code>
        <PlatformItem kind="web" raw={findMention(gallery, n)} who={{ name: n.company, logo: keyOf(gallery, n.company) }} />
      </div>
    )),
  ].slice(0, 6);
  if (!cards.length) return null;
  return (
    <section>
      <h3 className="odz-db-h">Intercepted this week</h3>
      <div className="w-week-feed">{cards}</div>
    </section>
  );
}

function PaidSignals({ snap }: { snap: WeekSnapshot }) {
  const gallery = useGallery();
  return (
    <section className="odz-db-card">
      <h3>Paid signals</h3>
      {snap.ads.length ? (
        <div className="w-week-feed">
          {snap.ads.map((a, i) => (
            <div key={i} className="w-week-feed-item">
              <code className="odz-db-tag orange">{`${a.company}${a.start ? ` · live since ${a.start}` : ""}`.toUpperCase()}</code>
              <PlatformItem kind="ads" raw={findAd(gallery, a)} who={{ name: a.company, logo: keyOf(gallery, a.company) }} />
            </div>
          ))}
        </div>
      ) : (
        <p className="odz-db-empty">{snap.numbers.live_ads === null ? "Ads have not been checked yet." : "No watched rival runs ads in Egypt right now. The paid space is open."}</p>
      )}
    </section>
  );
}

export function Debrief({
  brief,
  snap,
  clientName,
  onOpportunities,
  onPlan,
  onContent,
}: {
  brief: Brief;
  snap?: WeekSnapshot;
  clientName?: string;
  onOpportunities?: () => void;
  onPlan?: () => void;
  onContent?: () => void;
}) {
  const st = status(brief);
  const quiet = brief.quiet || !brief.items.length;
  const n = snap?.numbers;
  const tiles: [string, string, string][] = n
    ? [
        ["CONTACTS", count(n.rivals), "rivals on watch"],
        ["TRANSMISSIONS", count(n.posts_7d), "rival posts in 7 days"],
        ["PAID SIGNALS", n.live_ads === null ? "—" : count(n.live_ads), n.live_ads === null ? "not checked yet" : "live ads found"],
        ["CHATTER", count(n.news), "news and web mentions"],
      ]
    : [];
  const moves = brief.items.filter((i) => i.move).slice(0, 3);
  return (
    <div className="odz-debrief">
      <header className="odz-db-top">
        <code>
          DEBRIEF {String(brief.id).padStart(3, "0")} · WEEK OF {brief.week_start}
          {clientName ? ` · CLIENT: ${clientName.toUpperCase()}` : ""}
        </code>
      </header>

      <section className="odz-db-hero">
        <div>
          <code className={"odz-db-status " + st.tone}>STATUS: {st.code}</code>
          <h2>{brief.headline || (quiet ? "No big moves on the radar." : "Rivals moved this week.")}</h2>
          <p>
            {quiet
              ? "No rival change scored 3 or more this week. Here is what the market did instead."
              : `${brief.items.length} move${brief.items.length === 1 ? "" : "s"} worth your attention, scored 1 to 5 against your profile.`}
          </p>
        </div>
        {snap?.rivals.length ? <RadarPlot snap={snap} /> : null}
      </section>

      {tiles.length ? (
        <section className="odz-db-tiles">
          {tiles.map(([k, v, note]) => (
            <article key={k}>
              <code>{k}</code>
              <strong>{v}</strong>
              <small>{note}</small>
            </article>
          ))}
        </section>
      ) : null}

      {brief.items.length ? (
        <section>
          <h3 className="odz-db-h">Priority contacts</h3>
          <div className="odz-db-items">
            {brief.items.map((it, i) => (
              <article key={it.signal_id} className="odz-db-card odz-db-item">
                <ScoreBadge score={it.score} />
                <div>
                  <code>
                    {String(i + 1).padStart(2, "0")} · {it.competitor.toUpperCase()} · {it.type.toUpperCase()}
                  </code>
                  <h4 dir="auto">{it.title}</h4>
                  <p>
                    <b>What it means for you:</b> {it.meaning}
                  </p>
                  {it.move ? (
                    <p className="odz-db-move">
                      <b>Your move:</b> {it.move}
                    </p>
                  ) : null}
                  <ExtLink href={it.source_url} />
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {snap?.takeaways.length ? (
        <section className="odz-db-card">
          <h3>Field notes</h3>
          <ul className="odz-db-notes">
            {snap.takeaways.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {snap ? (
        <div className="odz-db-grid2">
          <Bars snap={snap} />
          <ContactLog snap={snap} />
        </div>
      ) : null}
      {snap ? <Intercepted snap={snap} /> : null}
      <FieldStrip title="Field photos" sub="The rivals' newest posts and ads with pictures, saved on your PC." filter={(c) => !c.you} limit={12} />
      {snap ? <PaidSignals snap={snap} /> : null}

      <section className="odz-db-next">
        <code>NEXT MOVES</code>
        <div>
          {moves.map((m) => (
            <div key={m.signal_id} className="odz-db-next-item">
              <AgentMark code="M0" />
              <span>
                <b>{m.competitor}</b>
                <small>{m.move}</small>
              </span>
            </div>
          ))}
          {onOpportunities ? (
            <button className="odz-db-next-item" onClick={onOpportunities}>
              <AgentMark code="M0" />
              <span>
                <b>Pick an opportunity</b>
                <small>Ranked openings from this week's watch.</small>
              </span>
            </button>
          ) : null}
          {onPlan ? (
            <button className="odz-db-next-item" onClick={onPlan}>
              <AgentMark code="M1" />
              <span>
                <b>Plan a response</b>
                <small>Turn a move or an open space into a strategy plan.</small>
              </span>
            </button>
          ) : null}
          {onContent ? (
            <button className="odz-db-next-item" onClick={onContent}>
              <AgentMark code="M2" />
              <span>
                <b>Make the posts</b>
                <small>Draft LinkedIn, Instagram and Facebook posts from a plan.</small>
              </span>
            </button>
          ) : null}
        </div>
      </section>

      <footer className="odz-db-foot">
        <code>ODYNZA RADAR · WATCH. PLAN. CREATE. BEFORE THEY DO.</code>
        {snap?.as_of ? <code>DATA AS OF {snap.as_of.replace("T", " ")} UTC</code> : null}
      </footer>
    </div>
  );
}
