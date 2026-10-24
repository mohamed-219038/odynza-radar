/* Overview's radar: each watched rival is a blip, closer to the centre (you) the more it did this week. */
import { useLoad } from "../watch/parts";
import type { Overview } from "../watch/types";

const COLORS = ["#4FD1E8", "#F5A35C", "#C9A7FF", "#FF8A6B", "#8BE36B", "#F2D06B"];

export function Radar() {
  const { data } = useLoad<Overview>("/watch/overview", 60000);
  const rivals = data?.snapshot?.rivals ?? [];
  if (!data || !rivals.length) return null;
  const score = (r: (typeof rivals)[number]) => r.posts_7d * 3 + r.news + (r.live_ads ?? 0) * 2 + Math.min(r.jobs ?? 0, 5);
  const top = Math.max(1, ...rivals.map(score));
  const ranked = rivals
    .map((r, i) => ({ ...r, s: score(r), color: COLORS[i % COLORS.length] }))
    .sort((a, b) => b.s - a.s);
  const blips = ranked.map((r, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / ranked.length + 0.6;
    const dist = 34 + (1 - r.s / top) * 96;
    const x = 200 + Math.cos(angle) * dist;
    const y = 150 + Math.sin(angle) * dist;
    return { ...r, x, y, right: x >= 200 };
  });
  return (
    <section className="odz-radar" aria-label="Rival activity radar">
      <svg viewBox="0 0 400 300" role="img" aria-label={`Rival activity this week: ${ranked.map((r) => r.name).join(", ")}, most active first`}>
        {[130, 88, 46].map((r) => (
          <circle key={r} cx="200" cy="150" r={r} fill="none" stroke="#22325A" />
        ))}
        <line x1="70" y1="150" x2="330" y2="150" stroke="#22325A" />
        <line x1="200" y1="20" x2="200" y2="280" stroke="#22325A" />
        <g className="odz-radar-arm">
          <path d="M200 150 L330 150 A130 130 0 0 0 292 58 Z" fill="#C6F432" fillOpacity=".09" />
          <line x1="200" y1="150" x2="330" y2="150" stroke="#C6F432" strokeWidth="2" />
        </g>
        <circle cx="200" cy="150" r="7" fill="#C6F432" />
        <text x="200" y="174" style={{ fill: "var(--odz-ink)" }} fontSize="12" textAnchor="middle">
          You
        </text>
        {blips.map((b) => (
          <g key={b.key}>
            <circle cx={b.x} cy={b.y} r="13" fill={b.color} fillOpacity=".18" />
            <circle cx={b.x} cy={b.y} r="6.5" fill={b.color} />
            <text x={b.right ? b.x + 13 : b.x - 13} y={b.y + 4} style={{ fill: "var(--odz-ink)" }} fontSize="12.5" textAnchor={b.right ? "start" : "end"}>
              {b.name}
            </text>
          </g>
        ))}
      </svg>
      <div>
        <span className="odz-eyebrow">ON YOUR RADAR THIS WEEK</span>
        <ol>
          {ranked.map((r) => (
            <li key={r.key}>
              <i className="odz-radar-dot" style={{ background: r.color }} aria-hidden="true" />
              <b>{r.name}</b>
              <span>
                {r.posts_7d} post{r.posts_7d === 1 ? "" : "s"} · {r.news} news{r.live_ads ? ` · ${r.live_ads} ads` : ""}
              </span>
            </li>
          ))}
        </ol>
        <p className="odz-fine" style={{ marginTop: 10 }}>
          Closer to the centre means more activity: posts, news, live ads and hiring in the last 7 days.
        </p>
      </div>
    </section>
  );
}
