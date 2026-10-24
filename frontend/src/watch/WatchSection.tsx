/* M0 Watch: continuous competitor intelligence. One section with its own tabs; a client login sees only this.
   The first three tabs are the setup steps (numbered, ticked when done); the rest open once data is collected.
   The tab you should open next is marked "Next", and one line beside the tabs says what to do there. */
import { useEffect, useState, type ReactNode } from "react";
import { json, request, setWatchClient, watchClientId } from "../api";
import { useToast } from "../components/Toast";
import type { User } from "../types";
import {
  rights,
  tabOpen,
  TAB_NEEDS,
  watchSteps,
  type Step,
  type StepKey,
  type TabKey,
} from "./format";
import { Loading, Problem, useLoad } from "./parts";
import { AdsPage } from "./AdsPage";
import { BriefPage } from "./BriefPage";
import { ComparePage } from "./ComparePage";
import { CompetitorsPage } from "./CompetitorsPage";
import { DataPage } from "./DataPage";
import { OpportunitiesPage } from "./OpportunitiesPage";
import { OverviewPage } from "./OverviewPage";
import { Setup } from "./Setup";
import { SourcesPage } from "./SourcesPage";
import type { Brief, ClientInfo, Progress, WeekSnapshot } from "./types";
import { Select } from "../components/Select";

/** Draws a ready weekly brief in a host's own look (the Odynza site uses its mission debrief). */
export type BriefBody = (brief: Brief, snapshot: WeekSnapshot | undefined, clientName: string | undefined) => ReactNode;

export type WatchTab = TabKey;

/** Setup steps first, in order; then the results. */
const STEPS: [WatchTab, string, StepKey][] = [
  ["setup", "Profile", "setup"],
  ["competitors", "Competitors", "competitors"],
  ["sources", "Collect", "collect"],
];
const RESULTS: [WatchTab, string][] = [
  ["overview", "Overview"],
  ["ads", "Ads"],
  ["compare", "Compare"],
  ["brief", "Brief"],
  ["opportunities", "Opportunities"],
  ["data", "All data"],
];
const ALL = [
  ...STEPS.map(([k, l]) => [k, l] as [WatchTab, string]),
  ...RESULTS,
];

const STEP_TAB: Record<StepKey, WatchTab> = {
  setup: "setup",
  competitors: "competitors",
  collect: "sources",
  signals: "sources",
  brief: "brief",
};
const NEED_TEXT: Record<StepKey, string> = {
  setup: "Save your profile first",
  competitors: "Confirm at least one competitor first",
  collect: "Run the first collection first",
  signals: "Wait for the first scored changes first",
  brief: "Make the first brief first",
};

const STORE = "radar-tab";

function savedTab(): WatchTab | null {
  try {
    const t = window.localStorage.getItem(STORE) as WatchTab | null;
    return t && ALL.some(([k]) => k === t) ? t : null;
  } catch {
    return null;
  }
}

/** Remounts everything below when the client changes, so no page shows the previous client's data. */
export function WatchSection({
  user,
  onOpenPlans,
  tab,
  onTab,
  hideNav = false,
  onClientChange,
  hidePicker = false,
  newClient,
  onNewClientDone,
  briefBody,
}: {
  user: User;
  onOpenPlans?: () => void;
  /** Controlled section (the Odynza site drives it from its own sidebar). */
  tab?: WatchTab | null;
  onTab?: (t: WatchTab) => void;
  /** Hide the tab row (the host shows its own navigation). */
  hideNav?: boolean;
  onClientChange?: () => void;
  /** Hide the client picker (the host shows its own switcher). */
  hidePicker?: boolean;
  /** Controlled "new client" form; onNewClientDone gets the new client's id, or null when cancelled. */
  newClient?: boolean;
  onNewClientDone?: (id: number | null) => void;
  /** Draws a ready weekly brief in the host's own look. */
  briefBody?: BriefBody;
}) {
  const [rev, setRev] = useState(0);
  const [own, setCreating] = useState(false);
  const creating = newClient ?? own;
  const switchTo = (id: number | null) => {
    setWatchClient(id);
    setCreating(false);
    setRev((r) => r + 1);
    onClientChange?.();
    onNewClientDone?.(id);
  };
  return (
    <WatchBody
      key={rev}
      user={user}
      onOpenPlans={onOpenPlans}
      creating={creating}
      onNew={() => setCreating(true)}
      onCancelNew={() => {
        setCreating(false);
        onNewClientDone?.(null);
      }}
      switchTo={switchTo}
      tab={tab}
      onTab={onTab}
      hideNav={hideNav}
      hidePicker={hidePicker}
      briefBody={briefBody}
    />
  );
}

function WatchBody({
  user,
  onOpenPlans,
  creating,
  onNew,
  onCancelNew,
  switchTo,
  tab: wanted,
  onTab,
  hideNav,
  hidePicker,
  briefBody,
}: {
  user: User;
  onOpenPlans?: () => void;
  creating: boolean;
  onNew: () => void;
  onCancelNew: () => void;
  switchTo: (id: number | null) => void;
  tab?: WatchTab | null;
  onTab?: (t: WatchTab) => void;
  hideNav?: boolean;
  hidePicker?: boolean;
  briefBody?: BriefBody;
}) {
  const can = rights(user.role);
  const [poll, setPoll] = useState(0);
  const info = useLoad<ClientInfo>("/watch/client", poll);
  const [own, setTabState] = useState<WatchTab | null>(savedTab);
  const tab = wanted !== undefined ? wanted : own;
  const steps = watchSteps(Boolean(info.data?.client), info.data?.progress);
  const current = steps.find((s) => !s.done) ?? null;
  const running = info.data?.progress?.running ?? null;

  useEffect(() => setPoll(running ? 4000 : 0), [running]);

  const setTab = (t: WatchTab) => {
    setTabState(t);
    onTab?.(t);
    info.reload();
    try {
      window.localStorage.setItem(STORE, t);
    } catch {
      /* private window */
    }
  };

  useEffect(() => {
    // The server falls back to an allowed client when the saved one is gone; remember what it chose.
    const id = info.data?.client?.id;
    if (id && String(id) !== watchClientId()) setWatchClient(id);
  }, [info.data?.client?.id]);

  if (!info.data)
    return info.error ? (
      <Problem text={info.error} />
    ) : (
      <Loading text="Opening Watch…" />
    );
  const counts = info.data.counts;
  const clients = info.data.clients ?? [];
  const picker = hidePicker ? null : (
    <div className="w-clientpick">
      <label>
        <span>Client</span>
        <Select
          aria-label="Client"
          value={creating ? "new" : (info.data.client?.id ?? "")}
          onChange={(e) =>
            e.target.value === "new"
              ? onNew()
              : switchTo(Number(e.target.value))
          }
          disabled={clients.length < 2 && !can.staff}
        >
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
          {creating || !clients.length ? (
            <option value="new">New client…</option>
          ) : null}
        </Select>
      </label>
      {can.staff && info.data.client && !creating ? (
        <button className="button secondary small-button" onClick={onNew}>
          + New client
        </button>
      ) : null}
    </div>
  );

  if (creating)
    return (
      <section
        id="watch-view"
        className="w-section"
        aria-label="Competitor watch"
      >
        <div className="w-topline">
          <p className="muted">
            Each client has its own competitors, collection, ads, briefs and
            opportunities. The current data stays as it is.
          </p>
          {picker}
        </div>
        <Setup
          info={{ ...info.data, client: null, logins: [] }}
          canEdit={can.staff}
          create
          onCancel={onCancelNew}
          onSaved={(_first, id) => switchTo(id ?? null)}
        />
      </section>
    );
  // Setup steps 1-3 decide where you land; once they are done you land on Overview.
  const setupLeft = steps.slice(0, 3).find((s) => !s.done);
  const fallback: WatchTab = setupLeft ? STEP_TAB[setupLeft.key] : "overview";
  const shown: WatchTab = tab && tabOpen(tab, steps) ? tab : fallback;
  // Only the setup steps drive the Next mark; after that, no tab stays highlighted.
  const nextTab: WatchTab | null = setupLeft ? STEP_TAB[setupLeft.key] : null;

  const button = (k: WatchTab, label: ReactNode, extra = "") => {
    const open = tabOpen(k, steps);
    const need = TAB_NEEDS[k];
    return (
      <button
        key={k}
        className={
          "w-tab" +
          extra +
          (shown === k ? " active" : "") +
          (open ? "" : " locked") +
          (nextTab === k && shown !== k ? " next" : "")
        }
        aria-current={shown === k ? "page" : undefined}
        disabled={!open}
        title={open ? undefined : `${NEED_TEXT[need!]}.`}
        onClick={() => setTab(k)}
      >
        {label}
        {k === "competitors" && counts?.proposed ? (
          <span className="nav-count pending-count">{counts.proposed}</span>
        ) : null}
        {k === "sources" && running ? (
          <span className="w-dot" aria-label="collecting now" />
        ) : null}
        {nextTab === k && shown !== k ? (
          <span className="w-next-tag">Next</span>
        ) : null}
      </button>
    );
  };

  return (
    <section
      id="watch-view"
      className="w-section"
      aria-label="Competitor watch"
    >
      <div className="w-topline">
        {hideNav ? <span /> : (
        <nav className="w-tabs" aria-label="Watch sections">
          {STEPS.map(([k, label, key], i) => {
            const done = steps.find((s) => s.key === key)!.done;
            return button(
              k,
              <>
                <span className={"w-num" + (done ? " done" : "")}>
                  {done ? "✓" : i + 1}
                </span>
                {label}
              </>,
              " w-step-tab",
            );
          })}
          <span className="w-tab-sep" aria-hidden="true" />
          {RESULTS.map(([k, label]) =>
            button(k, tabOpen(k, steps) ? label : <>🔒 {label}</>),
          )}
        </nav>
        )}
        {clients.length > 1 || can.staff ? picker : null}
      </div>
      {setupLeft || running ? (
        <NextLine
          step={setupLeft ?? current ?? steps[2]}
          progress={info.data.progress}
          canRun={can.staff}
          canEdit={can.staff}
          tab={shown}
          go={setTab}
          onStarted={info.reload}
        />
      ) : null}
      {shown === "setup" ? (
        <Setup
          info={info.data}
          canEdit={can.staff}
          onSaved={(first, id) => {
            if (first && id) setWatchClient(id);
            info.reload();
            if (first) setTab("competitors");
          }}
        />
      ) : shown === "overview" ? (
        <OverviewPage canDecide={can.decide} canRun={can.staff} go={setTab} />
      ) : shown === "competitors" ? (
        <CompetitorsPage
          canDecide={can.decide}
          canStaff={can.staff}
          onChanged={info.reload}
        />
      ) : shown === "ads" ? (
        <AdsPage canRun={can.staff} canDecide={can.decide} go={setTab} />
      ) : shown === "compare" ? (
        <ComparePage canDecide={can.decide} canStaff={can.staff} />
      ) : shown === "brief" ? (
        <BriefPage
          canStaff={can.staff}
          onChanged={info.reload}
          body={briefBody ? (b, snap) => briefBody(b, snap, info.data?.client?.name) : undefined}
        />
      ) : shown === "data" ? (
        <DataPage />
      ) : shown === "opportunities" ? (
        <OpportunitiesPage
          canDecide={can.decide}
          canStaff={can.staff}
          onOpenPlans={can.staff ? onOpenPlans : undefined}
        />
      ) : (
        <SourcesPage
          canDecide={can.decide}
          canStaff={can.staff}
          onChanged={info.reload}
        />
      )}
    </section>
  );
}

/** One line under the tabs: what to do next, with its button. */
function NextLine({
  step,
  progress,
  canRun,
  canEdit,
  tab,
  go,
  onStarted,
}: {
  step: Step;
  progress?: Progress;
  canRun: boolean;
  canEdit: boolean;
  tab: WatchTab;
  go: (t: WatchTab) => void;
  onStarted: () => void;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const running = progress?.running;

  async function collect() {
    setBusy(true);
    try {
      const out = await request<{ message: string }>(
        "/watch/run",
        json({ everything: true }),
      );
      toast(out.message);
      onStarted();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const target = STEP_TAB[step.key];
  let text: string;
  let action: { label: string; run: () => void } | null = null;
  if (running) {
    text = `Collecting now: ${running.done} of ${running.total} sources done.`;
  } else if (step.key === "setup") {
    text = canEdit
      ? "Save your company profile. Use Search by name to fill in your links."
      : "An admin has to save the client profile first.";
  } else if (step.key === "competitors") {
    text = "Confirm at least one competitor. Nothing is collected before that.";
  } else if (step.key === "collect") {
    text =
      "Collect the first data from your rivals' sites, social pages, ads and news.";
    if (canRun)
      action = { label: busy ? "Starting…" : "Collect now", run: collect };
  } else if (step.key === "signals") {
    text = progress?.scoring
      ? "n8n is scoring the changes found. They appear in Overview when done."
      : "Your data is ready to read. Changes appear after the next collection, which runs on its own schedule.";
    if (canRun && !progress?.scoring)
      action = {
        label: busy ? "Starting…" : "Collect again now",
        run: collect,
      };
  } else {
    text = "Make your first weekly brief. It also writes the opportunities.";
  }
  if (
    !action &&
    !running &&
    tab !== target &&
    (step.key !== "setup" || canEdit)
  )
    action = {
      label: `Go to ${ALL.find(([k]) => k === target)![1]} →`,
      run: () => go(target),
    };

  return (
    <div className="w-nextline" role="status">
      <span className="w-next-tag">Next</span>
      <span className="w-nextline-text">{text}</span>
      {running ? (
        <span className="w-progress" aria-hidden="true">
          <i
            style={{
              width: `${Math.round((100 * running.done) / Math.max(running.total, 1))}%`,
            }}
          />
        </span>
      ) : null}
      {action ? (
        <button
          className="button small-button"
          disabled={busy}
          onClick={action.run}
        >
          {action.label}
        </button>
      ) : null}
    </div>
  );
}
