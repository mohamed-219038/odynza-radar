/* Small pieces shared by the Watch pages. */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { request, watchClientId } from "../api";
import { safeUrl } from "../format";
import { useToast } from "../components/Toast";
import { ago, fieldLabel, SCORE_LABEL, shortUrl, stamp } from "./format";
import type { Signal } from "./types";
import { Select } from "../components/Select";

/** Loads a GET endpoint, with reload and an optional poll while the page is visible. */
export function useLoad<T>(path: string | null, pollMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState(0);
  const load = useCallback(async () => {
    if (!path) return;
    try {
      setData(await request<T>(path));
      setError("");
      setStatus(200);
    } catch (e) {
      setError((e as Error).message);
      setStatus((e as { status?: number }).status ?? 0);
    }
  }, [path]);
  useEffect(() => {
    load();
    if (!pollMs) return;
    const t = window.setInterval(() => {
      if (!document.hidden) load();
    }, pollMs);
    return () => window.clearInterval(t);
  }, [load, pollMs]);
  return { data, error, status, reload: load, setData };
}

export function ScoreBadge({ score, corrected }: { score: number | null; corrected?: boolean }) {
  return (
    <span className={`w-score s${score ?? 0}`} title={score ? `${score} = ${SCORE_LABEL[score]}${corrected ? " (corrected by a person)" : ""}` : "Not scored yet"}>
      {score ?? "·"}
      {corrected ? <i aria-label="corrected">✎</i> : null}
    </span>
  );
}

/** Grey shapes in the layout's place while data loads, with the words for screen readers. */
export function Loading({ text = "Loading…" }: { text?: string }) {
  return (
    <div className="loading-state skel" role="status" aria-live="polite">
      <span className="skel-text">{text}</span>
      <span className="skel-row" aria-hidden="true">
        <i />
        <i />
        <i />
        <i />
      </span>
      <span className="skel-line" aria-hidden="true" />
      <span className="skel-line short" aria-hidden="true" />
    </div>
  );
}

/** A number that counts up from zero the first time it is shown ("1,819", "12", "8"). Anything else is shown as is. */
export function CountUp({ value, ms = 700 }: { value: string; ms?: number }) {
  const m = /^([^\d]*)([\d,]+)([^\d]*)$/.exec(value);
  const target = m ? Number(m[2].replace(/,/g, "")) : NaN;
  const [shown, setShown] = useState(() => (Number.isFinite(target) && !reduced() ? 0 : target));
  useEffect(() => {
    if (!Number.isFinite(target) || reduced()) {
      setShown(target);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / ms);
      setShown(Math.round(target * (1 - Math.pow(1 - k, 3))));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  if (!m || !Number.isFinite(target)) return <>{value}</>;
  return (
    <>
      {m[1]}
      {shown.toLocaleString("en-US")}
      {m[3]}
    </>
  );
}
const reduced = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export function Empty({ icon = "✳", title, children }: { icon?: string; title: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      <span>{icon}</span>
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
    </div>
  );
}

export function Problem({ text }: { text: string }) {
  return text ? (
    <div className="alert" role="alert">
      {text}
    </div>
  ) : null;
}

export function ExtLink({ href, children }: { href: string; children?: ReactNode }) {
  const url = safeUrl(href);
  if (!url) return <>{children ?? href}</>;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer nofollow">
      {children ?? shortUrl(url)} ↗
    </a>
  );
}

/** Horizontal bars, "you" highlighted. */
export function Bars({ rows, format }: { rows: { name: string; value: number | null; you?: boolean }[]; format: (v: number | null) => string }) {
  const max = Math.max(0, ...rows.map((r) => r.value ?? 0)) || 1;
  return (
    <div className="w-bars">
      {rows.map((r) => (
        <div key={r.name} className={"w-bar" + (r.you ? " you" : "")}>
          <div className="w-bar-label">
            <span>{r.name}</span>
            <b>{format(r.value)}</b>
          </div>
          <div className="channel-track">
            <div className="channel-fill" style={{ width: `${r.value ? Math.max(3, Math.round((r.value / max) * 100)) : 0}%` }}></div>
          </div>
        </div>
      ))}
    </div>
  );
}

/** One scored change: what changed, what it means, the evidence, and a score a person can correct. */
export function SignalCard({ signal, canCorrect, onChanged, showCompany = true }: { signal: Signal; canCorrect: boolean; onChanged?: () => void; showCompany?: boolean }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [score, setScore] = useState(signal.score ?? 3);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const ev = signal.evidence;

  async function save() {
    setBusy(true);
    try {
      await request(`/watch/signals/${signal.id}/score`, { method: "PATCH", body: JSON.stringify({ score, reason }) });
      toast("Score corrected. The impact agent uses your correction as an example next time.");
      setEditing(false);
      onChanged?.();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="w-signal" data-signal={signal.id}>
      <ScoreBadge score={signal.score} corrected={signal.corrected} />
      <div className="w-signal-body">
        <div className="w-signal-top">
          {showCompany ? <b>{signal.competitor}</b> : null}
          <span className="badge neutral">{signal.type}</span>
          {signal.theme ? <span className="badge">{signal.theme}</span> : null}
          <small>{ago(signal.captured_at)}</small>
        </div>
        <h3>{signal.title}</h3>
        <p className="w-meaning">
          <b>What it means for you:</b> {signal.meaning}
        </p>
        {signal.reason ? (
          <p className="w-reason">
            Why {signal.score}: {signal.reason}
            {signal.corrected && signal.ai_score ? ` (the AI said ${signal.ai_score}, corrected by ${signal.corrected_by})` : ""}
          </p>
        ) : null}
        <div className="w-signal-actions">
          <ExtLink href={signal.source_url} />
          {ev ? (
            <button type="button" className="text-link" aria-expanded={open} onClick={() => setOpen(!open)}>
              {open ? "Hide evidence" : "Evidence: before / after"}
            </button>
          ) : null}
          {canCorrect && signal.score ? (
            <button type="button" className="text-link" onClick={() => setEditing(!editing)}>
              Correct score
            </button>
          ) : null}
        </div>
        {open && ev ? (
          <div className="w-evidence">
            <div>
              <small>
                Before · {fieldLabel(ev.field)} · {stamp(ev.before_at)}
              </small>
              <pre>{ev.before || "(nothing)"}</pre>
            </div>
            <div>
              <small>
                After · {ev.kind} · {stamp(ev.after_at ?? signal.captured_at)}
              </small>
              <pre>{ev.after || "(removed)"}</pre>
            </div>
          </div>
        ) : null}
        {editing ? (
          <div className="w-correct">
            <label>
              Score
              <Select value={score} onChange={(e) => setScore(Number(e.target.value))}>
                {[5, 4, 3, 2, 1].map((n) => (
                  <option key={n} value={n}>
                    {n} · {SCORE_LABEL[n]}
                  </option>
                ))}
              </Select>
            </label>
            <label>
              Why <span className="optional">optional</span>
              <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} placeholder="e.g. They only serve banks, we don't" />
            </label>
            <button type="button" className="button primary small-button" disabled={busy} onClick={save}>
              Save
            </button>
          </div>
        ) : null}
      </div>
    </article>
  );
}

const noLogo = new Set<string>();

/** A company's logo (social profile picture, site logo or site icon), with its initials until it loads or if none. */
export function Logo({ id, name, size = 28 }: { id: string | number; name: string; size?: number }) {
  const client = watchClientId();
  const key = `${client}:${id}`;
  const [failed, setFailed] = useState(noLogo.has(key));
  const [loaded, setLoaded] = useState(false);
  const initials =
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase())
      .join("") || "?";
  return (
    <span className={"w-logo" + (loaded ? " loaded" : "")} style={{ width: size, height: size, fontSize: Math.round(size * 0.38) }} aria-hidden="true">
      {!loaded ? initials : null}
      {!failed ? (
        <img
          src={`/watch/logo/${encodeURIComponent(String(id))}?${client ? `client=${client}&` : ""}v=2`}
          alt=""
          loading="lazy"
          onLoad={() => setLoaded(true)}
          onError={() => {
            noLogo.add(key);
            setFailed(true);
          }}
        />
      ) : null}
    </span>
  );
}

/** The app's own address for a saved picture: shown through Radar (some CDNs refuse other sites), or downloaded. */
export function imageUrl(url: string, download = false) {
  const client = watchClientId();
  return `/watch/image?u=${encodeURIComponent(url)}${download ? "&download=1" : ""}${client ? `&client=${client}` : ""}`;
}
