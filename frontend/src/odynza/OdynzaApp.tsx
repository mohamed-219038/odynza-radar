/* Odynza Radar: the app shell (sign-in, sidebar with the M0, M1 and M2 agents, theme) around the pages. */
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { json, onUnauthorized, request, send, setCsrf, setWatchClient } from "../api";
import { ToastProvider } from "../components/Toast";
import type { AuthStatus, User } from "../types";
import { rights, tabOpen, TAB_NEEDS, watchSteps, type TabKey } from "../watch/format";
import type { ClientInfo } from "../watch/types";
import { WatchSection } from "../watch/WatchSection";
import { AgentMark, Brand, Mark, RadarArt } from "./Mark";
import { Debrief } from "./Debrief";
import { ThemeSwitch } from "./Theme";
import { Radar } from "./Radar";
import { AgentPages, type AgentMode } from "./AgentPages";
import { ClientSwitch } from "./ClientSwitch";
import { TeamPage } from "./TeamPage";

/** Sidebar sections in the order Odynza asked for (profile, competitors, overview, then the rest): the URL path,
    the Watch section it opens, its label. */
export const SECTIONS: [string, TabKey, string][] = [
  ["profile", "setup", "Profile"],
  ["competitors", "competitors", "Competitors"],
  ["overview", "overview", "Overview"],
  ["collect", "sources", "Collect"],
  ["ads", "ads", "Ads"],
  ["compare", "compare", "Compare"],
  ["brief", "brief", "Weekly brief"],
  ["opportunities", "opportunities", "Opportunities"],
  ["data", "data", "All data"],
];
const NEED: Record<string, string> = {
  setup: "Save your profile first",
  competitors: "Confirm a competitor first",
  collect: "Run the first collection first",
  brief: "Make the first brief first",
};

/** M1 and M2: the agents that take M0's opportunities further. */
const AGENTS: [AgentMode, string, string, string][] = [
  ["strategy", "M1", "Strategy", "Strategy plans"],
  ["content", "M2", "Social content", "Social content"],
];

function agentFromPath(): AgentMode | null {
  const slug = window.location.pathname.replace(/^\/+|\/+$/g, "");
  return AGENTS.find(([p]) => p === slug)?.[0] ?? null;
}

const onTeamPath = () => window.location.pathname.replace(/^\/+|\/+$/g, "") === "team";

function fromPath(): TabKey | null {
  const slug = window.location.pathname.replace(/^\/+|\/+$/g, "");
  return SECTIONS.find(([p]) => p === slug)?.[1] ?? null;
}

export function OdynzaApp() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const status = await request<AuthStatus>("/auth/status");
      setCsrf(status.csrf);
      setAuth(status);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    load();
    onUnauthorized(() => {
      setCsrf("");
      setAuth({ authenticated: false });
    });
  }, [load]);

  if (!auth)
    return (
      <div className="odz-splash" role={error ? "alert" : "status"}>
        <Mark size={56} spinning={!error} />
        <p>{error ? `${error} Start the Odynza Radar server, then reload.` : "Opening Odynza Radar…"}</p>
      </div>
    );
  return (
    <ToastProvider>
      {auth.authenticated && auth.user ? (
        <Shell user={auth.user} onSignedOut={() => setAuth({ authenticated: false })} />
      ) : (
        <SignIn
          status={auth}
          onSignedIn={(s) => {
            setCsrf(s.csrf);
            setAuth(s);
          }}
        />
      )}
    </ToastProvider>
  );
}

function SignIn({ status, onSignedIn }: { status: AuthStatus; onSignedIn: (s: AuthStatus) => void }) {
  const canSignUp = !status.setup_required && Boolean(status.signup) && status.signup !== "off";
  const [token] = useState(() => (window.location.pathname.replace(/\/+$/, "") === "/reset" ? new URLSearchParams(window.location.search).get("token") ?? "" : ""));
  const [mode, setMode] = useState<"in" | "up" | "setup" | "forgot" | "reset">(token ? "reset" : status.setup_allowed ? "setup" : "in");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [busy, setBusy] = useState(false);
  const switchTo = (m: "in" | "up" | "forgot") => {
    setMode(m);
    setError("");
    setDone("");
    setPassword("");
    setRepeat("");
  };
  async function submit(e: FormEvent) {
    e.preventDefault();
    if ((mode === "up" || mode === "setup" || mode === "reset") && password !== repeat) {
      setError("The passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (mode === "forgot" || mode === "reset") {
        const out =
          mode === "forgot"
            ? await request<{ message: string }>("/auth/forgot", json({ username: username.trim() }))
            : await request<{ message: string }>("/auth/reset", json({ token, password }));
        if (mode === "reset") window.history.replaceState(null, "", "/");
        setDone(out.message);
        setMode("in");
        setPassword("");
        setRepeat("");
        return;
      }
      const path = mode === "in" ? "/auth/login" : mode === "up" ? "/auth/signup" : "/auth/setup";
      const out = await request<AuthStatus & { pending?: boolean }>(path, json({ username: username.trim(), password }));
      if (out.pending) {
        setDone(`Thanks, ${username.trim()}. An admin has to approve your account before you can sign in.`);
        setMode("in");
        setPassword("");
        setRepeat("");
      } else onSignedIn(out);
    } catch (err) {
      setError((err as Error).message);
      setPassword("");
      setRepeat("");
    } finally {
      setBusy(false);
    }
  }
  const label =
    mode === "in"
      ? ["Sign in", "Signing in…"]
      : mode === "up"
        ? ["Create account", "Creating…"]
        : mode === "forgot"
          ? ["Email me a reset link", "Sending…"]
          : mode === "reset"
            ? ["Save new password", "Saving…"]
            : ["Create the admin account", "Creating…"];
  return (
    <div className="odz-signin">
      <ThemeSwitch />
      <div className="odz-signin-art" aria-hidden="true">
        <RadarArt size={340} />
      </div>
      <main className="odz-signin-card" id="main">
        <Brand size={34} />
        <span className="odz-eyebrow">ODYNZA RADAR · M0 WATCH · M1 PLAN · M2 CREATE</span>
        <h1>
          Watch. Plan. Create. <em>Before they do.</em>
        </h1>
        {mode === "setup" ? (
          <p className="odz-note">No account exists yet. Create the first admin account.</p>
        ) : status.setup_required ? (
          <p className="odz-note">No account exists yet. Open this page on the server computer, or run <code>python scripts/create_user.py yourname --admin</code> there.</p>
        ) : mode === "forgot" ? (
          <p className="odz-note">Type your username (your email address). We email you a link to choose a new password.</p>
        ) : mode === "reset" ? (
          <p className="odz-note">Choose a new password: at least 10 characters. Every browser signed in as you is signed out.</p>
        ) : mode === "up" ? (
          <p className="odz-note">
            {status.signup === "viewer" ? "New accounts can look at everything but change nothing." : "An admin approves new accounts before they can sign in."}
          </p>
        ) : null}
        {done ? (
          <p className="odz-note" role="status">
            {done}
          </p>
        ) : null}
        <form onSubmit={submit}>
          {mode !== "reset" ? (
            <label>
              Username
              <input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required minLength={mode === "in" || mode === "forgot" ? 1 : 3} maxLength={64} />
            </label>
          ) : null}
          {mode !== "forgot" ? (
            <label>
              {mode === "reset" ? "New password" : "Password"}
              <input
                type="password"
                autoComplete={mode === "in" ? "current-password" : "new-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={mode === "in" ? 1 : 10}
                maxLength={256}
              />
            </label>
          ) : null}
          {mode === "up" || mode === "setup" || mode === "reset" ? (
            <label>
              Repeat password
              <input type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} required maxLength={256} />
            </label>
          ) : null}
          {error ? (
            <p className="odz-error" role="alert">
              {error}
            </p>
          ) : null}
          <button className="odz-button primary" disabled={busy}>
            {busy ? label[1] : label[0]}
          </button>
        </form>
        {mode === "in" ? (
          <p className="odz-fine">
            <button type="button" className="odz-link" onClick={() => switchTo("forgot")}>
              Forgot password?
            </button>
          </p>
        ) : mode === "forgot" || mode === "reset" ? (
          <p className="odz-fine">
            <button
              type="button"
              className="odz-link"
              onClick={() => {
                if (mode === "reset") window.history.replaceState(null, "", "/");
                switchTo("in");
              }}
            >
              Back to sign in
            </button>
          </p>
        ) : null}
        {mode === "forgot" || mode === "reset" ? null : canSignUp ? (
          <p className="odz-fine">
            {mode === "in" ? "New here? " : "Already have an account? "}
            <button type="button" className="odz-link" onClick={() => switchTo(mode === "in" ? "up" : "in")}>
              {mode === "in" ? "Sign up" : "Sign in"}
            </button>
          </p>
        ) : (
          <p className="odz-fine">Client logins see only their own company.</p>
        )}
      </main>
    </div>
  );
}

function greeting(now = new Date()) {
  const h = now.getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function Shell({ user, onSignedOut }: { user: User; onSignedOut: () => void }) {
  const can = rights(user.role);
  const [tab, setTab] = useState<TabKey | null>(fromPath);
  const [info, setInfo] = useState<ClientInfo | null>(null);
  const [rev, setRev] = useState(0);
  const [menu, setMenu] = useState(false);
  const [m0Open, setM0Open] = useState(true);
  const [agent, setAgent] = useState<AgentMode | null>(agentFromPath);
  const [adding, setAdding] = useState(false);
  const [team, setTeam] = useState(() => user.role === "admin" && onTeamPath());
  const [pending, setPending] = useState(0);

  useEffect(() => {
    let live = true;
    const get = () =>
      request<ClientInfo>("/watch/client")
        .then((d) => live && setInfo(d))
        .catch(() => undefined);
    get();
    const t = window.setInterval(() => !document.hidden && get(), 8000);
    return () => {
      live = false;
      window.clearInterval(t);
    };
  }, [rev]);
  useEffect(() => {
    const back = () => {
      setTab(fromPath());
      setAgent(agentFromPath());
      setTeam(user.role === "admin" && onTeamPath());
    };
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, []);

  const steps = watchSteps(Boolean(info?.client), info?.progress);
  useEffect(() => {
    if (user.role !== "admin") return;
    request<{ role: string }[]>("/auth/users")
      .then((list) => setPending(list.filter((u) => u.role === "pending").length))
      .catch(() => undefined);
  }, [user.role]);
  const goTeam = () => {
    setTeam(true);
    setAgent(null);
    setAdding(false);
    setMenu(false);
    if (window.location.pathname !== "/team") window.history.pushState(null, "", "/team");
    window.scrollTo({ top: 0 });
  };
  const goAgent = (a: AgentMode) => {
    setTeam(false);
    setAgent(a);
    setMenu(false);
    if (window.location.pathname !== `/${a}`) window.history.pushState(null, "", `/${a}`);
    window.scrollTo({ top: 0 });
  };
  const go = (t: TabKey) => {
    setTeam(false);
    setAgent(null);
    setAdding(false);
    setTab(t);
    setMenu(false);
    const slug = SECTIONS.find(([, k]) => k === t)?.[0] ?? "";
    if (window.location.pathname !== `/${slug}`) window.history.pushState(null, "", `/${slug}`);
    window.scrollTo({ top: 0 });
  };
  async function signOut() {
    await send("/auth/logout", { method: "POST" }).catch(() => undefined);
    setCsrf("");
    onSignedOut();
  }
  const current = team ? "Team" : agent ? AGENTS.find(([a]) => a === agent)![3] : SECTIONS.find(([, k]) => k === tab)?.[2] ?? "Overview";
  const running = info?.progress?.running;

  return (
    <div className={"odz-shell" + (menu ? " menu-open" : "")}>
      <a className="odz-skip" href="#odz-main">
        Skip to content
      </a>
      <aside className="odz-side">
        <div className="odz-side-top">
          <Brand size={30} />
          <button className="odz-menu-button" aria-expanded={menu} aria-controls="odz-nav" onClick={() => setMenu(!menu)}>
            {menu ? "Close" : "Menu"}
          </button>
        </div>
        <nav id="odz-nav" aria-label="Odynza sections">
          <span className="odz-eyebrow">AGENTS</span>
          <div className={"odz-agent" + (m0Open ? " open" : "")}>
            <button className="odz-agent-head" aria-expanded={m0Open} aria-controls="odz-m0" onClick={() => setM0Open(!m0Open)}>
              <AgentMark code="M0" />
              <span>
                <b>Competitor Intelligence</b>
                <small>{running ? "Collecting now" : info?.counts?.proposed ? `${info.counts.proposed} waiting for you` : "Watching your rivals"}</small>
              </span>
              <i className="odz-chev" aria-hidden="true" />
            </button>
            <div hidden={!m0Open}>
              <ClientSwitch
                info={info}
                canAdd={can.staff}
                adding={adding}
                onPick={(id) => {
                  setWatchClient(id);
                  setAdding(false);
                  setRev((r) => r + 1);
                }}
                onAdd={() => {
                  setAdding(true);
                  if (agent) setAgent(null);
                  setMenu(false);
                }}
              />
            </div>
            <div id="odz-m0" className="odz-agent-tabs" hidden={!m0Open}>
          {SECTIONS.filter(([, k]) => k !== "setup" || can.staff).map(([slug, key, label]) => {
            const open = tabOpen(key, steps);
            const need = TAB_NEEDS[key];
            const active = !team && !agent && !adding && (tab ?? "overview") === key;
            return (
              <button
                key={slug}
                className={"odz-nav" + (active ? " active" : "") + (open ? "" : " locked")}
                aria-current={active ? "page" : undefined}
                disabled={!open}
                title={open ? undefined : `${NEED[need ?? ""] ?? "Not ready yet"}.`}
                onClick={() => go(key)}
              >
                <i aria-hidden="true" />
                {label}
                {key === "sources" && running ? <span className="odz-live">live</span> : null}
                {key === "competitors" && info?.counts?.proposed ? <span className="odz-count">{info.counts.proposed}</span> : null}
              </button>
            );
          })}
            </div>
          </div>
          {can.staff
            ? AGENTS.map(([a, code, name]) => (
                <button key={a} className={"odz-agent-link" + (agent === a ? " active" : "")} aria-current={agent === a ? "page" : undefined} onClick={() => goAgent(a)}>
                  <AgentMark code={code as "M1" | "M2"} />
                  <span>
                    <b>{name}</b>
                    <small>{a === "strategy" ? "Plans from your rivals' moves" : "Drafts for LinkedIn, Instagram, Facebook"}</small>
                  </span>
                </button>
              ))
            : null}
          {user.role === "admin" ? (
            <button className={"odz-agent-link odz-team-link" + (team ? " active" : "")} aria-current={team ? "page" : undefined} onClick={goTeam}>
              <span className="odz-team-icon" aria-hidden="true">
                ⚇
              </span>
              <span>
                <b>Team</b>
                <small>{pending ? `${pending} waiting for approval` : "Accounts and roles"}</small>
              </span>
              {pending ? <span className="odz-count">{pending}</span> : null}
            </button>
          ) : null}
        </nav>
        <div className="odz-side-foot">
          {running ? (
            <div className="odz-sweep">
              <span className="odz-eyebrow">COLLECTING NOW</span>
              <b>
                {running.done} of {running.total} sources
              </b>
              <span className="odz-bar">
                <i style={{ width: `${Math.round((100 * running.done) / Math.max(1, running.total))}%` }} />
              </span>
            </div>
          ) : null}
          <ThemeSwitch />
          <div className="odz-user">
            <span className="odz-avatar" aria-hidden="true">
              {user.username.slice(0, 1).toUpperCase()}
            </span>
            <span>
              <b>{user.username}</b>
              <small>{user.role === "client" ? "Client" : user.role === "admin" ? "Admin" : user.role === "viewer" ? "Viewer" : "Team"}</small>
            </span>
            <button className="odz-link" onClick={signOut}>
              Sign out
            </button>
          </div>
        </div>
      </aside>
      <main className="odz-main odz-scope" id="odz-main">
        <header className="odz-head">
          <div>
            <span className="odz-hello">
              {greeting()}, {user.username}
            </span>
            <h1>{adding && !agent && !team ? "New client" : current}</h1>
          </div>
        </header>
        <PageRise when={`${team ? "team" : ""}:${agent ?? ""}:${tab ?? ""}`}>
        {team ? (
          <TeamPage me={user} onChange={setPending} />
        ) : agent && can.staff ? (
          <AgentPages user={user} mode={agent} onMode={goAgent} onOpportunities={() => go("opportunities")} />
        ) : (
          <>
            {!adding && (tab ?? "overview") === "overview" && tabOpen("overview", steps) ? <Radar key={`r${rev}`} /> : null}
            <WatchSection
              key={rev}
              user={user}
              tab={tab}
              onTab={go}
              hideNav
              onClientChange={() => setRev((r) => r + 1)}
              hidePicker
              newClient={adding}
              onNewClientDone={() => setAdding(false)}
              onOpenPlans={can.staff ? () => goAgent("strategy") : undefined}
              briefBody={(b, snap, name) => (
                <Debrief
                  brief={b}
                  snap={snap}
                  clientName={name}
                  onOpportunities={() => go("opportunities")}
                  onPlan={can.staff ? () => goAgent("strategy") : undefined}
                  onContent={can.staff ? () => goAgent("content") : undefined}
                />
              )}
            />
          </>
        )}
        </PageRise>
        <ToTop />
      </main>
    </div>
  );
}

/** A round button that appears after scrolling down a long page and takes you back to the top. */
function ToTop() {
  const [show, setShow] = useState(false);
  useEffect(() => {
    const on = () => setShow(window.scrollY > 900);
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  return (
    <button type="button" className={"odz-totop" + (show ? " on" : "")} aria-label="Back to the top" tabIndex={show ? 0 : -1} onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>
      ↑
    </button>
  );
}

/** Lets the new tab rise in softly, without remounting it (each tab keeps its loaded data and filters). */
function PageRise({ when, children }: { when: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    ref.current?.animate?.([{ opacity: 0, transform: "translateY(10px)" }, { opacity: 1, transform: "none" }], { duration: 320, easing: "ease-out" });
  }, [when]);
  return (
    <div className="odz-page" ref={ref}>
      {children}
    </div>
  );
}
