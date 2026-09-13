import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Box,
  Check,
  CheckCircle2,
  ChevronRight,
  Code2,
  Command,
  Database,
  FileText,
  Folder,
  GitBranch,
  History,
  LayoutDashboard,
  Loader2,
  LockKeyhole,
  Monitor,
  Network,
  Pause,
  Play,
  Plus,
  Radio,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Square,
  Terminal,
  Unplug,
  X,
  Zap,
  AlertTriangle,
} from "lucide-react";
import { api, bytes, clock, label, shortPath } from "./api";
import type { Agent, Candidate, Event, Run, State } from "./types";
import {
  HardwareDashboard,
  GovernorPanel,
  AgentResources,
  AgentPerformance,
  AgentTrend,
  useMetrics,
  percent,
} from "./monitor";
import type { MetricHistory } from "./types";
import "./styles.css";
import "./monitor.css";

type View =
  "overview" | "resources" | "lab" | "activity" | "history" | "connections";
type ModalState =
  | { kind: "launch"; agent?: Agent }
  | { kind: "confirm"; agent: Agent; action: string }
  | null;
const activeStates = ["RUNNING", "PAUSED", "STARTING", "STOPPING"];
const cx = (...classes: (string | boolean | undefined)[]) =>
  classes.filter(Boolean).join(" ");

function Brand({ small = false }: { small?: boolean }) {
  return (
    <div className={cx("brand", small && "small")}>
      <span className="brand-mark">
        <span />
        <span />
      </span>
      {!small && (
        <>
          DEADLOCK<span className="brand-dot">.</span>
        </>
      )}
    </div>
  );
}
function Provider({ provider }: { provider: string }) {
  return (
    <span className={"provider " + provider}>
      {provider === "codex" ? (
        <Command size={18} />
      ) : (
        <span className="claude-star">✳</span>
      )}
    </span>
  );
}
function Status({ value }: { value: string }) {
  return (
    <span className={"status " + value.toLowerCase()}>
      <span />
      {label(value)}
    </span>
  );
}
function Empty({
  icon: Icon = Radio,
  title,
  children,
  action,
}: {
  icon?: typeof Radio;
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <Icon size={28} strokeWidth={1.3} />
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}
function Spark({ values }: { values: number[] }) {
  const max = Math.max(10, ...values);
  return (
    <svg className="spark" viewBox="0 0 130 32" aria-hidden="true">
      <path
        d={values
          .map(
            (v, i) =>
              `${i ? "L" : "M"} ${(i * 130) / Math.max(1, values.length - 1)} ${30 - (v / max) * 27}`,
          )
          .join(" ")}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
    </svg>
  );
}

function App() {
  const { history: metricsHistory, error: metricsError } = useMetrics();
  const [data, setData] = useState<State | null>(null),
    [connectionError, setConnectionError] = useState(""),
    [view, setView] = useState<View>("overview");
  const [modal, setModal] = useState<ModalState>(null),
    [selected, setSelected] = useState<Agent | null>(null),
    [toast, setToast] = useState(""),
    [busy, setBusy] = useState("");
  const [filter, setFilter] = useState("active"),
    [search, setSearch] = useState(""),
    [samples, setSamples] = useState<number[]>([]);
  const refresh = useCallback(async () => {
    try {
      const state = await api<State>("/state");
      setData(state);
      setConnectionError("");
      if (state.host.cpu != null)
        setSamples((a) => [...a.slice(-29), state.host.cpu!]);
    } catch (e) {
      setConnectionError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const interval = setInterval(() => void refresh(), 1000);
    return () => clearInterval(interval);
  }, [refresh]);
  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    const interval = setInterval(() => {
      api<Agent>(`/agents/${encodeURIComponent(selected.id)}`)
        .then((a) => {
          if (!cancelled) setSelected(a);
        })
        .catch(() => {});
    }, 1500);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [selected?.id]);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(""), 5000);
    return () => clearTimeout(id);
  }, [toast]);
  const execute = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setToast((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const control = async (agent: Agent, action: string) => {
    if (action === "continue") {
      setModal({ kind: "launch", agent });
      return;
    }
    if (action === "stop" || action === "adopt" || action === "interrupt") {
      setModal({ kind: "confirm", agent, action });
      return;
    }
    await execute(agent.id, () =>
      api(`/agents/${encodeURIComponent(agent.id)}/control`, { action }),
    );
    if (selected?.id === agent.id)
      setSelected(await api<Agent>(`/agents/${encodeURIComponent(agent.id)}`));
  };
  const inspect = async (agent: Agent) => {
    setSelected(agent);
    try {
      setSelected(await api<Agent>(`/agents/${encodeURIComponent(agent.id)}`));
    } catch (e) {
      setToast((e as Error).message);
    }
  };
  const agents = data?.agents || [],
    active = agents.filter((a) => activeStates.includes(a.state));
  const titles: Record<View, [string, string]> = {
    overview: [
      "Live resource monitor",
      "Real coding agents. Real device activity. Automatic pressure control.",
    ],
    resources: [
      "Device resources",
      "CPU, memory, GPU, disk, and network — measured on this machine.",
    ],
    lab: [
      "Recovery lab",
      "Detect a real resource cycle. Recover it. Verify the result.",
    ],
    activity: [
      "Activity",
      "Lifecycle changes and recovery evidence, as they happen.",
    ],
    history: ["Run history", "Recorded outcomes from your recovery sessions."],
    connections: [
      "Connections",
      "Local runtimes, analytics, and mediator configuration.",
    ],
  };
  const navs: { id: View; name: string; icon: typeof Activity }[] = [
    { id: "overview", name: "Live monitor", icon: LayoutDashboard },
    { id: "resources", name: "Device resources", icon: Network },
    { id: "activity", name: "Activity", icon: Activity },
  ];
  const filtered = agents.filter(
    (a) =>
      (filter === "all" ||
        (filter === "active"
          ? activeStates.includes(a.state)
          : filter === "paused"
            ? a.state === "PAUSED"
            : !activeStates.includes(a.state))) &&
      `${a.name} ${a.provider} ${a.cwd} ${a.pid || ""}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Brand />
        <div className="workspace">
          <span className="workspace-icon">
            <Terminal size={17} />
          </span>
          <div>
            <strong>Local workspace</strong>
            <span>Personal environment</span>
          </div>
          <LockKeyhole size={12} />
        </div>
        <div className="nav-caption">WORKSPACE</div>
        <nav>
          {navs.map(({ id, name, icon: Icon }) => (
            <button
              key={id}
              aria-label={name}
              className={cx(view === id && "selected")}
              onClick={() => setView(id)}
            >
              <Icon size={17} />
              <span>{name}</span>
              {id === "overview" && active.length > 0 && (
                <em>{active.length}</em>
              )}
            </button>
          ))}
        </nav>
        <div className="nav-caption secondary">SYSTEM</div>
        <nav>
          <button
            className={cx(view === "lab" && "selected")}
            onClick={() => setView("lab")}
          >
            <GitBranch size={17} />
            Recovery lab <small>Optional</small>
          </button>
          <button
            className={cx(view === "history" && "selected")}
            onClick={() => setView("history")}
          >
            <History size={17} />
            Run history
          </button>
          <button
            className={cx(view === "connections" && "selected")}
            onClick={() => setView("connections")}
          >
            <Settings2 size={17} />
            Connections
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="host-mini">
            <div>
              <Monitor size={15} />
              <span>{data?.host.platform || "Local machine"}</span>
              <span className="live-dot" />
            </div>
            <p>
              Host CPU <strong>{percent(data?.host.cpu)}</strong>
            </p>
            <Spark values={samples} />
          </div>
          <div className="local-note">
            <ShieldCheck size={14} />
            <span>Runs on your machine</span>
          </div>
          <span className="version">
            DEADLOCK <span>v0.1.0</span>
          </span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>{titles[view][0]}</strong>
          </div>
          <div className="topbar-right">
            <span className={cx("connection", !!connectionError && "offline")}>
              <span />
              {connectionError ? "Disconnected" : "Live connection"}
            </span>
            <span className="vertical-rule" />
            <button
              className="icon-button"
              aria-label="Refresh dashboard"
              onClick={() => void refresh()}
            >
              <RefreshCw size={15} />
            </button>
            <span className="avatar">L</span>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">LOCAL CONTROL CENTER</div>
              <h1>{titles[view][0]}</h1>
              <p>{titles[view][1]}</p>
            </div>
            <button
              className="button primary"
              onClick={() => setModal({ kind: "launch" })}
            >
              <Plus size={16} />
              New agent
            </button>
          </div>
          {connectionError && (
            <div className="notice error">
              <Unplug size={17} />
              <span>
                Connection lost. Displaying the last observation.{" "}
                {connectionError}
              </span>
              <button onClick={() => void refresh()}>Retry</button>
            </div>
          )}
          {!data ? (
            <div className="loading">
              <Loader2 className="spin" />
              Connecting to local control plane…
            </div>
          ) : (
            <>
              {(view === "overview" || view === "resources") && (
                <HardwareDashboard
                  data={data}
                  history={metricsHistory}
                  historyError={metricsError}
                  full={view === "resources"}
                />
              )}
              {view === "overview" && (
                <div className="overview-grid">
                  <section className="agent-section">
                    <div className="section-header">
                      <h2>
                        Agents <span className="count">{agents.length}</span>
                      </h2>
                      <span className="subtle">
                        <span className="live-dot" /> Updated every second
                      </span>
                    </div>
                    <div className="table-toolbar">
                      <div className="filter-tabs">
                        {[
                          ["active", "Active"],
                          ["all", "All agents"],
                          ["paused", "Paused"],
                          ["finished", "Saved & finished"],
                        ].map(([key, text]) => (
                          <button
                            key={key}
                            onClick={() => setFilter(key)}
                            className={cx(filter === key && "active")}
                          >
                            {text}
                          </button>
                        ))}
                      </div>
                      <label className="search">
                        <Search size={14} />
                        <input
                          aria-label="Search agents"
                          placeholder="Search agents…"
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                        />
                        <span>⌕</span>
                      </label>
                    </div>
                    <div className="table-scroll">
                      <table className="agent-table">
                        <thead>
                          <tr>
                            <th>AGENT / WORKSPACE</th>
                            <th>STATUS</th>
                            <th title="Percent of total host CPU capacity">
                              CPU / TREND
                            </th>
                            <th>MEMORY</th>
                            <th aria-label="Controls" />
                          </tr>
                        </thead>
                        <tbody>
                          {filtered.map((a) => (
                            <tr
                              key={a.id}
                              className={cx(
                                selected?.id === a.id && "row-selected",
                              )}
                            >
                              <td>
                                <button
                                  className="agent-name"
                                  onClick={() => void inspect(a)}
                                >
                                  <Provider provider={a.provider} />
                                  <span>
                                    <strong>{a.name}</strong>
                                    <small>
                                      <Folder size={11} />
                                      {shortPath(a.cwd)}
                                    </small>
                                  </span>
                                </button>
                              </td>
                              <td>
                                <Status value={a.state} />
                                {a.pause_owner === "automatic" && (
                                  <span className="auto-tag">Auto-paused</span>
                                )}
                                <span className="table-source">
                                  {a.source === "shared session"
                                    ? "Session"
                                    : a.source === "observed process"
                                      ? "Observed"
                                      : a.source === "adopted process"
                                        ? "Adopted"
                                        : "Managed"}
                                  {a.pid && ` · ${a.pid}`}
                                  {a.metrics_partial && " · Partial sample"}
                                </span>
                              </td>
                              <td className="mono">
                                {percent(a.cpu_capacity)}
                                <AgentTrend
                                  agent={a}
                                  history={metricsHistory}
                                />
                              </td>
                              <td className="mono">{bytes(a.memory)}</td>
                              <td>
                                <div className="row-controls">
                                  {!a.protected &&
                                    activeStates.includes(a.state) &&
                                    a.pid && (
                                      <button
                                        className={cx(
                                          "auto-agent-toggle",
                                          !data.governor.exempt.includes(
                                            a.id,
                                          ) && "enabled",
                                        )}
                                        role="switch"
                                        aria-checked={
                                          !data.governor.exempt.includes(a.id)
                                        }
                                        aria-label={`Automatic pressure control for ${a.name}`}
                                        title="Allow automatic temporary pauses when this agent contributes to overload"
                                        onClick={() =>
                                          void execute(a.id, () =>
                                            api(
                                              `/agents/${encodeURIComponent(a.id)}/automation`,
                                              {
                                                enabled:
                                                  data.governor.exempt.includes(
                                                    a.id,
                                                  ),
                                              },
                                            ),
                                          )
                                        }
                                      >
                                        Auto
                                      </button>
                                    )}
                                  {a.controls.includes("pause") && (
                                    <button
                                      className="icon-button"
                                      title="Suspend process tree; resources stay held"
                                      aria-label={`Pause ${a.name}`}
                                      onClick={() => void control(a, "pause")}
                                      disabled={busy === a.id}
                                    >
                                      <Pause size={14} />
                                    </button>
                                  )}
                                  {a.controls.includes("resume") && (
                                    <button
                                      className="icon-button lime"
                                      aria-label={`Resume ${a.name}`}
                                      onClick={() => void control(a, "resume")}
                                    >
                                      <Play size={14} />
                                    </button>
                                  )}
                                  {a.controls.includes("adopt") && (
                                    <button
                                      className="button mini"
                                      onClick={() => void control(a, "adopt")}
                                    >
                                      Adopt
                                    </button>
                                  )}
                                  {a.controls.includes("continue") && (
                                    <button
                                      className="icon-button"
                                      aria-label={`Continue ${a.name}`}
                                      onClick={() =>
                                        void control(a, "continue")
                                      }
                                    >
                                      <Play size={14} />
                                    </button>
                                  )}
                                  {a.controls.includes("stop") && (
                                    <button
                                      className="icon-button"
                                      aria-label={`Stop ${a.name}`}
                                      onClick={() => void control(a, "stop")}
                                    >
                                      <Square size={13} />
                                    </button>
                                  )}
                                  {a.controls.includes("interrupt") && (
                                    <button
                                      className="icon-button"
                                      aria-label={`Interrupt ${a.name}`}
                                      onClick={() =>
                                        void control(a, "interrupt")
                                      }
                                    >
                                      <Square size={13} />
                                    </button>
                                  )}
                                  <button
                                    className="icon-button"
                                    aria-label={`Inspect ${a.name}`}
                                    onClick={() => void inspect(a)}
                                  >
                                    <ChevronRight size={16} />
                                  </button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {filtered.length === 0 && (
                        <Empty
                          icon={Terminal}
                          title={
                            search
                              ? "No matching agents"
                              : "No agents in this view"
                          }
                          action={
                            <button
                              className="button"
                              onClick={() => setModal({ kind: "launch" })}
                            >
                              <Plus size={14} />
                              Launch an agent
                            </button>
                          }
                        >
                          {search
                            ? "Try a different name, workspace, or process ID."
                            : "Start Codex or Claude here, or choose All agents to inspect saved sessions."}
                        </Empty>
                      )}
                    </div>
                    <div className="table-footer">
                      <span>
                        {filtered.length}{" "}
                        {filtered.length === 1 ? "agent" : "agents"} shown
                      </span>
                      <span>
                        <LockKeyhole size={12} /> Shared runtimes are protected
                      </span>
                    </div>
                    <section className="recent-activity">
                      <div className="section-header">
                        <h2>Recent activity</h2>
                        <button
                          className="text-button"
                          onClick={() => setView("activity")}
                        >
                          View all <ArrowRight size={13} />
                        </button>
                      </div>
                      <EventList
                        events={[...data.events]
                          .sort((a, b) => b.time - a.time)
                          .slice(0, 4)}
                      />
                    </section>
                  </section>
                  <aside className="overview-aside">
                    <GovernorPanel data={data} execute={execute} busy={busy} />
                  </aside>
                </div>
              )}
              {view === "resources" && (
                <AgentResources data={data} inspect={inspect} />
              )}
              {view === "lab" && (
                <Lab
                  data={data}
                  refresh={refresh}
                  execute={execute}
                  busy={busy}
                />
              )}
              {view === "activity" && (
                <ActivityView
                  events={[...data.events, ...(data.run?.events || [])]}
                />
              )}
              {view === "history" && (
                <HistoryView refreshKey={data.run?.status || ""} />
              )}
              {view === "connections" && (
                <Connections
                  data={data}
                  reconnect={() =>
                    execute("reconnect", () => api("/telemetry/reconnect", {}))
                  }
                  busy={busy}
                />
              )}
            </>
          )}
        </main>
        <footer className="statusbar">
          <span>
            <span className={cx("live-dot", connectionError && "offline")} />
            {connectionError ? "Last known state" : "Local control plane"}
            <span className="statusbar-sep">/</span>
            {data?.telemetry.engine === "exasol"
              ? "Exasol analytics"
              : "SQLite · local development"}
          </span>
          <span>
            {data?.telemetry.available ? (
              <>
                <ShieldCheck size={12} />
                Telemetry connected
              </>
            ) : (
              <>
                <AlertTriangle size={12} />
                Telemetry unavailable
              </>
            )}
            <span className="statusbar-sep">·</span>No cloud sync
          </span>
        </footer>
      </div>
      {selected && (
        <Inspector
          history={metricsHistory}
          agent={selected}
          close={() => setSelected(null)}
          control={control}
          reload={() => void inspect(selected)}
        />
      )}
      {modal && (
        <Modal close={() => setModal(null)}>
          {modal.kind === "launch" ? (
            <LaunchForm
              data={data}
              agent={modal.agent}
              close={() => setModal(null)}
              submit={async (values) => {
                await api("/agents", values);
                setModal(null);
                setToast(
                  "Agent launched. Live output is available in its inspector.",
                );
                await refresh();
              }}
              continueSession={async (prompt) => {
                await api(
                  `/agents/${encodeURIComponent(modal.agent!.id)}/control`,
                  { action: "continue", prompt },
                );
                setModal(null);
                await refresh();
              }}
            />
          ) : (
            <ConfirmControl
              agent={modal.agent}
              action={modal.action}
              close={() => setModal(null)}
              confirm={async () => {
                await api(
                  `/agents/${encodeURIComponent(modal.agent!.id)}/control`,
                  { action: modal.action },
                );
                setModal(null);
                await refresh();
                setSelected(null);
              }}
            />
          )}
        </Modal>
      )}
      {toast && (
        <div className="toast" role="status">
          <span>{toast}</span>
          <button
            className="icon-button"
            onClick={() => setToast("")}
            aria-label="Dismiss notification"
          >
            <X size={15} />
          </button>
        </div>
      )}
    </div>
  );
}

function EventList({ events }: { events: Event[] }) {
  return events.length ? (
    <div className="event-list">
      {events.map((e, i) => (
        <div className="event-row" key={e.time + ":" + i}>
          <span
            className={cx("event-icon", e.type.includes("resolved") && "lime")}
          >
            {e.type.includes("failed") || e.type.includes("unresolved") ? (
              <AlertTriangle size={14} />
            ) : e.type.includes("completed") || e.type.includes("resolved") ? (
              <Check size={14} />
            ) : (
              <Activity size={14} />
            )}
          </span>
          <div>
            <strong>{e.message}</strong>
            <span>{e.type}</span>
          </div>
          <time>{clock(e.time)}</time>
        </div>
      ))}
    </div>
  ) : (
    <div className="activity-empty">
      <span className="live-dot" />
      Listening for agent and runner events. Start an agent or a lab run to
      begin.
    </div>
  );
}

function DependencyGraph({
  run,
  onSelect,
}: {
  run: Run;
  onSelect: (id: string) => void;
}) {
  const workers = run.workers,
    resources = run.resources,
    width = 760,
    wx = (i: number) =>
      65 + (i * (width - 130)) / Math.max(1, workers.length - 1),
    rx = (i: number) =>
      120 + (i * (width - 240)) / Math.max(1, resources.length - 1);
  return (
    <div className="dependency-graph">
      <svg
        viewBox={`0 0 ${width} 300`}
        role="img"
        aria-label="Dependency graph: solid lines show ownership and dashed lines show blocking waits"
      >
        <defs>
          <marker
            id="arrow-owned"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#9fb789" />
          </marker>
          <marker
            id="arrow-wait"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#dfb267" />
          </marker>
        </defs>
        {resources.map(
          (r, i) =>
            r.owner && (
              <path
                key={"own" + r.id}
                d={`M ${rx(i)} 205 C ${rx(i)} 145 ${wx(workers.findIndex((w) => w.id === r.owner))} 145 ${wx(workers.findIndex((w) => w.id === r.owner))} 95`}
                className="edge-owned"
                markerEnd="url(#arrow-owned)"
              />
            ),
        )}
        {workers.map(
          (w, i) =>
            w.waiting && (
              <path
                key={"wait" + w.id}
                d={`M ${wx(i) + 12} 95 C ${wx(i) + 12} 155 ${rx(resources.findIndex((r) => r.id === w.waiting)) + 12} 155 ${rx(resources.findIndex((r) => r.id === w.waiting)) + 12} 205`}
                className="edge-wait"
                markerEnd="url(#arrow-wait)"
              />
            ),
        )}
        {workers.map((w, i) => (
          <g
            className="graph-node"
            key={w.id}
            tabIndex={0}
            role="button"
            aria-label={`Inspect ${w.name}`}
            onClick={() => onSelect(w.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") onSelect(w.id);
            }}
          >
            <rect
              x={wx(i) - 49}
              y="29"
              width="98"
              height="66"
              rx="7"
              className={
                w.state === "WAITING"
                  ? "node-waiting"
                  : w.state === "COMPLETED"
                    ? "node-complete"
                    : ""
              }
            />
            <text x={wx(i)} y="53" className="node-title">
              {w.name}
            </text>
            <text x={wx(i)} y="75" className="node-sub">
              {label(w.state)}
            </text>
          </g>
        ))}
        {resources.map((r, i) => (
          <g className="resource-node" key={r.id}>
            <rect x={rx(i) - 68} y="205" width="136" height="55" rx="5" />
            <text x={rx(i)} y="227" className="node-title">
              {r.name}
            </text>
            <text x={rx(i)} y="247" className="node-sub">
              {r.owner ? `Held by ${r.owner}` : "Available"}
            </text>
          </g>
        ))}
      </svg>
      <div className="graph-legend">
        <span>
          <i className="line-owned" />
          Holds exclusive lease
        </span>
        <span>
          <i className="line-wait" />
          Blocking request
        </span>
        <span>
          <span className="legend-square" />
          Scripted worker
        </span>
      </div>
    </div>
  );
}

function Lab({
  data,
  execute,
  busy,
}: {
  data: State;
  refresh: () => Promise<void>;
  execute: (key: string, fn: () => Promise<unknown>) => Promise<void>;
  busy: string;
}) {
  const [scenario, setScenario] = useState("canonical"),
    [strategy, setStrategy] = useState("deterministic"),
    [automatic, setAutomatic] = useState(true),
    [seed, setSeed] = useState(42),
    [node, setNode] = useState("B"),
    [showSql, setShowSql] = useState(false),
    [evidence, setEvidence] = useState<{
      queries: {
        file: string;
        engine: string;
        sql: string;
        duration_ms: number;
        snapshot_id: string;
        rows: unknown[];
      }[];
    } | null>(null),
    [candidates, setCandidates] = useState<Candidate[]>([]);
  const run = data.run,
    incident = run?.incident;
  useEffect(() => {
    if (
      incident &&
      ["DETECTED", "INVESTIGATING", "PLAN_READY"].includes(incident.status)
    )
      api<Candidate[]>("/recovery/candidates")
        .then(setCandidates)
        .catch(() => setCandidates([]));
  }, [incident?.status, incident?.attempts]);
  const start = () =>
    execute("run", () =>
      api("/runs", { scenario, strategy, seed, auto_recover: automatic }),
    );
  const selected = run?.workers.find((w) => w.id === node) || run?.workers[0];
  const fetchEvidence = async () => {
    setEvidence(await api("/runs/evidence"));
    setShowSql(true);
  };
  return (
    <>
      <div className="notice lab-boundary">
        <GitBranch size={18} />
        <div>
          <strong>Instrumented sandbox</strong>
          <span>
            Workers follow scripted policies and create real files. Resources
            are logical exclusive leases. This lab does not stop your coding
            agents.
          </span>
        </div>
        <span className="scope-label">
          {
            {
              live: "Live LLM mediator",
              deterministic: "Deterministic policy",
              none: "Observe only",
              restart_all: "Restart-all baseline",
            }[run?.strategy || strategy]
          }
        </span>
      </div>
      <div className="lab-controls">
        <label>
          Scenario
          <select
            value={scenario}
            onChange={(e) => setScenario(e.target.value)}
          >
            {Object.entries(data.scenarios).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          Recovery policy
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
          >
            <option value="deterministic">Least-cost · deterministic</option>
            <option value="live">Live LLM mediator</option>
            <option value="none">Observe · no recovery</option>
            <option value="restart_all">Restart all · baseline</option>
          </select>
        </label>
        <label className="seed">
          Seed
          <input
            type="number"
            min="0"
            max="2147483647"
            value={seed}
            onChange={(e) => setSeed(Number(e.target.value))}
          />
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={automatic}
            onChange={(e) => setAutomatic(e.target.checked)}
          />
          Auto-recover
        </label>
        <button
          className="button primary"
          disabled={busy === "run" || run?.status === "RUNNING"}
          onClick={start}
        >
          {busy === "run" ? (
            <Loader2 className="spin" size={14} />
          ) : (
            <Play size={14} />
          )}
          Start run
        </button>
        {run?.status === "RUNNING" && (
          <button
            className="button"
            onClick={() => execute("stop-run", () => api("/runs/stop", {}))}
          >
            <Square size={12} />
            Stop run
          </button>
        )}
      </div>
      {!data.telemetry.available && (
        <div className="notice error">
          <AlertTriangle size={17} />
          <span>
            Telemetry unavailable. New recoveries are blocked.{" "}
            {data.telemetry.error}
          </span>
        </div>
      )}
      {!run ? (
        <div className="lab-intro">
          <div className="lab-flow">
            <span>
              <Database size={25} />
              Dataset
            </span>
            <i />
            <span>
              <FileText size={25} />
              Renderer
            </span>
            <i />
            <span>
              <Box size={25} />
              Artifact
            </span>
          </div>
          <h2>
            Three agents. Three resources.
            <br />
            One circular wait.
          </h2>
          <p>
            Start a run to watch workers acquire resources, form a persistent
            cycle, and recover from a verified checkpoint.
          </p>
          <button className="button primary" onClick={start}>
            <Play size={14} />
            Start the canonical scenario
          </button>
          <span className="muted">
            Seeded input · Real outputs · Inspectable evidence
          </span>
        </div>
      ) : (
        <>
          <div className="run-strip">
            <div>
              <span className="mono">RUN {run.id.slice(0, 8)}</span>
              <Status value={run.status} />
              <span>Seed {run.seed}</span>
              <span>
                {run.strategy === "live" ? "Live LLM" : label(run.strategy)}
              </span>
            </div>
            <div>
              <span>
                {Math.max(0, (run.ended || data.time) - run.started).toFixed(1)}
                s elapsed
              </span>
              <button
                className="text-button"
                onClick={() => execute("evidence", fetchEvidence)}
              >
                <Code2 size={14} />
                SQL evidence
              </button>
              <a className="text-button" href="/api/runs/export" download>
                <ArrowDownToLine size={14} />
                Export
              </a>
            </div>
          </div>
          <div className="lab-grid">
            <section>
              <div className="section-header">
                <h2>Dependency graph</h2>
                <span className="subtle">
                  {incident?.key || "Waiting for qualifying cycle"}
                </span>
              </div>
              <DependencyGraph run={run} onSelect={setNode} />
              <div className="section-header">
                <h2>Worker progress</h2>
                <span className="subtle">Actual processed rows</span>
              </div>
              <div className="worker-progress">
                {run.workers.map((w) => (
                  <button
                    key={w.id}
                    onClick={() => setNode(w.id)}
                    className={cx(selected?.id === w.id && "selected")}
                  >
                    <div>
                      <span className="worker-initial">{w.id}</span>
                      <strong>{w.name}</strong>
                      <Status value={w.state} />
                      <span className="mono">
                        {w.progress}/{w.total}
                      </span>
                    </div>
                    <div className="meter">
                      <span
                        style={{ width: `${(w.progress / w.total) * 100}%` }}
                      />
                    </div>
                  </button>
                ))}
              </div>
              {selected && (
                <div className="worker-detail">
                  <span className="eyebrow">SELECTED WORKER</span>
                  <h3>{selected.name}</h3>
                  <div>
                    <span>
                      Attempt <code>{selected.attempt.slice(0, 8)}</code>
                    </span>
                    <span>
                      Checkpoint{" "}
                      <strong>{selected.checkpoint_work} units</strong>
                    </span>
                    <span>
                      Waiting{" "}
                      <strong>
                        {selected.waiting
                          ? run.resources.find((r) => r.id === selected.waiting)
                              ?.name
                          : "None"}
                      </strong>
                    </span>
                  </div>
                </div>
              )}
            </section>
            <aside className="investigation">
              <div className="section-header">
                <h2>Investigation</h2>
                <Zap size={16} />
              </div>
              {!incident ? (
                <div className="investigation-empty">
                  <span className="radar">
                    <Radio size={24} />
                  </span>
                  <h3>Watching resource state</h3>
                  <p>
                    A cycle must persist for two seconds without stage progress
                    before an incident opens.
                  </p>
                </div>
              ) : (
                <>
                  <Status value={incident.status} />
                  <h3 className="diagnosis">
                    {incident.status === "RESOLVED"
                      ? "Work is moving again."
                      : incident.status === "UNRESOLVED"
                        ? "Recovery needs attention."
                        : ["EXECUTING", "VERIFYING"].includes(incident.status)
                          ? "Verifying completed work."
                          : "A circular wait is blocking progress."}
                  </h3>
                  <p>
                    {incident.reason ||
                      (["EXECUTING", "VERIFYING"].includes(incident.status)
                        ? "Waiting for affected workers to finish, output checks to pass, and leases to clear."
                        : `${incident.key} → ${incident.members[0]}. Each worker is holding a resource another needs.`)}
                  </p>
                  <div className="incident-stats">
                    <span>
                      Plans<strong>{incident.attempts}/2</strong>
                    </span>
                    <span>
                      Tool calls<strong>{incident.tool_calls}/8</strong>
                    </span>
                    <span>
                      Recovery
                      <strong>
                        {incident.ended
                          ? (incident.ended - incident.detected).toFixed(1) +
                            "s"
                          : Math.max(
                              0,
                              run.config.incident_budget_seconds -
                                (data.time - incident.detected),
                            ).toFixed(0) + "s left"}
                      </strong>
                    </span>
                  </div>
                  {incident.model && (
                    <div className="model-label">
                      <Zap size={12} />
                      {incident.model}
                    </div>
                  )}
                  {incident.plan ? (
                    <div className="recovery-decision">
                      <span className="eyebrow">SELECTED INTERVENTION</span>
                      <h3>
                        {label(incident.plan.candidate.operation)} ·{" "}
                        {incident.plan.candidate.worker_id}
                      </h3>
                      <p>{incident.plan.rationale}</p>
                      <div>
                        <span>
                          <strong>{incident.plan.candidate.lost_work}</strong>{" "}
                          discarded units
                        </span>
                        <span>
                          <strong>
                            {incident.plan.candidate.checkpoint_work}
                          </strong>{" "}
                          checkpointed units
                        </span>
                      </div>
                    </div>
                  ) : (
                    candidates.length > 0 && (
                      <div className="candidate-list">
                        <h4>Eligible candidates</h4>
                        {candidates.slice(0, 6).map((c) => (
                          <div key={c.id}>
                            <span>
                              {c.worker_id} · {label(c.operation)}
                            </span>
                            <strong>{c.lost_work} lost</strong>
                          </div>
                        ))}
                      </div>
                    )
                  )}
                  {incident.status === "DETECTED" && (
                    <button
                      className="button primary wide"
                      onClick={() =>
                        execute("investigate", () =>
                          api("/recovery/investigate", {}),
                        )
                      }
                    >
                      Investigate & propose <ArrowRight size={14} />
                    </button>
                  )}
                  {incident.status === "PLAN_READY" && incident.plan && (
                    <button
                      className="button primary wide"
                      onClick={() =>
                        execute("recover", () =>
                          api("/recovery/execute", {
                            plan_id: incident.plan!.id,
                            operation_id: crypto.randomUUID(),
                          }),
                        )
                      }
                    >
                      Execute reviewed plan <Play size={14} />
                    </button>
                  )}
                  {incident.verification && (
                    <div className="verification">
                      <h4>Independent verification</h4>
                      {incident.verification.checks.map((c) => (
                        <div key={c.worker_id}>
                          {c.valid && c.completed ? (
                            <CheckCircle2 size={14} />
                          ) : (
                            <span className="pending-dot" />
                          )}
                          <span>
                            Worker {c.worker_id} ·{" "}
                            {c.valid && c.completed
                              ? "output validated"
                              : c.error || "pending"}
                          </span>
                        </div>
                      ))}
                      <div>
                        {incident.verification.resources_clear ? (
                          <CheckCircle2 size={14} />
                        ) : (
                          <span className="pending-dot" />
                        )}
                        <span>All affected leases and waits cleared</span>
                      </div>
                    </div>
                  )}
                </>
              )}
            </aside>
          </div>
          <div className="artifacts-section">
            <div className="section-header">
              <h2>
                Output artifacts{" "}
                <span className="count">{run.artifacts.length}</span>
              </h2>
              <span className="subtle">
                Content validated before publication
              </span>
            </div>
            {run.artifacts.length ? (
              <div className="artifacts-list">
                {run.artifacts.map((a) => (
                  <a
                    key={a.filename}
                    href={`/api/runs/${run.id}/artifacts/${a.filename}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <FileText size={22} />
                    <div>
                      <strong>{a.filename}</strong>
                      <span>
                        Worker {a.worker_id} · {a.size.toLocaleString()} bytes
                      </span>
                    </div>
                    <span className="artifact-verified">
                      <CheckCircle2 size={14} />
                      Validated
                    </span>
                    <ArrowUpRight size={16} />
                  </a>
                ))}
              </div>
            ) : (
              <div className="activity-empty">
                Artifacts appear after workers complete and content validators
                pass.
              </div>
            )}
          </div>
          <div className="section-header">
            <h2>Execution trace</h2>
            <span className="subtle">
              Actual actions · no generated thought stream
            </span>
          </div>
          <ActivityView events={run.events} compact />
          {showSql && (
            <Modal close={() => setShowSql(false)} wide>
              <div className="modal-heading">
                <span className="eyebrow">ANALYTICAL EVIDENCE</span>
                <h2>SQL queries & results</h2>
                <p>
                  Executed against {data.telemetry.engine}. Snapshot IDs isolate
                  each observation.
                </p>
              </div>
              <button
                className="button"
                onClick={() => execute("evidence", fetchEvidence)}
              >
                <RefreshCw size={14} />
                Refresh evidence
              </button>
              <div className="sql-list">
                {evidence?.queries
                  ?.slice(-6)
                  .reverse()
                  .map((q, i) => (
                    <details key={i} open={i === 0}>
                      <summary>
                        {q.file}
                        <span>
                          {q.duration_ms.toFixed(2)} ms · {q.rows.length} rows
                        </span>
                      </summary>
                      <p className="muted small-copy">
                        Snapshot {q.snapshot_id}
                      </p>
                      <pre>{q.sql}</pre>
                      <pre>{JSON.stringify(q.rows, null, 2)}</pre>
                    </details>
                  ))}
              </div>
            </Modal>
          )}
        </>
      )}
    </>
  );
}

function ActivityView({
  events,
  compact = false,
}: {
  events: Event[];
  compact?: boolean;
}) {
  const [paused, setPaused] = useState(false),
    [frozen, setFrozen] = useState<Event[]>([]),
    [query, setQuery] = useState("");
  const items = (paused ? frozen : events)
    .filter((e) =>
      `${e.message} ${e.type}`.toLowerCase().includes(query.toLowerCase()),
    )
    .slice()
    .sort((a, b) => b.time - a.time);
  return (
    <section className={cx("activity-view", compact && "compact")}>
      <div className="activity-toolbar">
        <label className="search">
          <Search size={14} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter events…"
            aria-label="Filter events"
          />
        </label>
        <button
          className="button mini"
          onClick={() => {
            setFrozen(events);
            setPaused(!paused);
          }}
        >
          {paused ? <Play size={12} /> : <Pause size={12} />}{" "}
          {paused ? "Resume trace" : "Pause trace"}
        </button>
        <span className="subtle">
          {paused ? "Paused for reading" : `${items.length} events`}
        </span>
      </div>
      <EventList events={items.slice(0, compact ? 30 : 300)} />
    </section>
  );
}

function HistoryView({ refreshKey }: { refreshKey: string }) {
  const [rows, setRows] = useState<
      {
        id: string;
        scenario: string;
        strategy: string;
        status: string;
        started: number;
        ended: number;
        discarded_work: number;
        preserved_work: number;
      }[]
    >([]),
    [error, setError] = useState("");
  useEffect(() => {
    api<typeof rows>("/runs/history")
      .then(setRows)
      .catch((e) => setError(e.message));
  }, [refreshKey]);
  return (
    <section>
      <div className="section-header">
        <h2>
          Recorded runs <span className="count">{rows.length}</span>
        </h2>
        <span className="subtle">Preserved across application restarts</span>
      </div>
      {error && <div className="notice error">{error}</div>}
      {rows.length ? (
        <div className="table-scroll">
          <table className="history-table">
            <thead>
              <tr>
                <th>RUN / SCENARIO</th>
                <th>POLICY</th>
                <th>STATUS</th>
                <th>DURATION</th>
                <th>LOST WORK</th>
                <th>PRESERVED</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    <strong>{label(r.scenario)}</strong>
                    <span className="table-source">
                      {r.id.slice(0, 8)} ·{" "}
                      {new Date(r.started * 1000).toLocaleString()}
                    </span>
                  </td>
                  <td>{label(r.strategy)}</td>
                  <td>
                    <Status value={r.status} />
                  </td>
                  <td className="mono">
                    {r.ended ? (r.ended - r.started).toFixed(1) + "s" : "—"}
                  </td>
                  <td>{r.discarded_work} units</td>
                  <td>{r.preserved_work} units</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty icon={History} title="No runs recorded yet">
          Start a scenario in the recovery lab. Completed, failed, and
          interrupted outcomes are retained here.
        </Empty>
      )}
    </section>
  );
}

function Connections({
  data,
  reconnect,
  busy,
}: {
  data: State;
  reconnect: () => void;
  busy: string;
}) {
  return (
    <div className="connections-view">
      <div className="connection-row">
        <Provider provider="codex" />
        <div>
          <h2>Codex CLI</h2>
          <p>Managed CLI runs and discovered local processes.</p>
          <code>codex login</code>
        </div>
        <Status value={data.integrations.codex ? "INSTALLED" : "UNAVAILABLE"} />
      </div>
      <div className="connection-row">
        <Provider provider="claude" />
        <div>
          <h2>Claude Code</h2>
          <p>
            Managed streaming runs. Authentication is checked by the CLI when a
            run starts.
          </p>
          <code>claude auth login</code>
        </div>
        <Status
          value={data.integrations.claude ? "INSTALLED" : "UNAVAILABLE"}
        />
      </div>
      <div className="connection-row">
        <span className="connection-icon">
          <Network size={21} />
        </span>
        <div>
          <h2>Codex shared sessions</h2>
          <p>
            {data.integrations.codex_sessions ||
              "Connected to the shared app-server. Existing sessions are visible in Overview."}
          </p>
          <span className="muted">
            Requires a running Codex app-server daemon and its control socket.
          </span>
        </div>
        <Status
          value={data.integrations.codex_sessions ? "UNAVAILABLE" : "CONNECTED"}
        />
      </div>
      <div className="connection-row">
        <span className="connection-icon">
          <Database size={21} />
        </span>
        <div>
          <h2>
            {data.telemetry.engine === "sqlite"
              ? "SQLite · local analytics"
              : "Exasol analytics"}
          </h2>
          <p>
            {data.telemetry.error ||
              "Complete snapshots, relational cycle detection, and candidate comparison."}
          </p>
          {data.telemetry.engine === "sqlite" && (
            <span className="muted">
              Exasol is a separate integration. Configure it in .env to verify
              the hackathon database requirements.
            </span>
          )}
        </div>
        <button
          className="button"
          onClick={reconnect}
          disabled={busy === "reconnect"}
        >
          <RefreshCw size={14} />
          Reconnect
        </button>
      </div>
      <div className="connection-row">
        <span className="connection-icon">
          <Zap size={21} />
        </span>
        <div>
          <h2>Live mediator</h2>
          <p>
            {data.integrations.mediator === "codex"
              ? "Uses the authenticated Codex CLI with a structured, bounded recovery-tool protocol."
              : data.integrations.mediator === "openai"
                ? "Uses OpenAI Responses function calls. API credentials and a model must be configured."
                : "Live mediator is disabled."}
          </p>
          <span className="muted">
            Live model errors stay visible; deterministic policy is a separate
            selection.
          </span>
        </div>
        <span className="scope-label">{data.integrations.mediator}</span>
      </div>
      <div className="settings-note">
        <ShieldCheck size={21} />
        <div>
          <h3>Local execution boundary</h3>
          <p>
            New agents can work within the directories below. Configure
            additional roots with DEADLOCK_WORKSPACE_ROOTS in your local .env
            file.
          </p>
          {data.roots.map((root) => (
            <code key={root}>{root}</code>
          ))}
          <p>
            Pause suspends a process tree. It keeps files, locks, and in-flight
            remote requests intact. Stop requests process termination; it does
            not undo changes.
          </p>
        </div>
      </div>
    </div>
  );
}

function Modal({
  children,
  close,
  wide = false,
}: {
  children: React.ReactNode;
  close: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = ref.current;
    node?.showModal();
    return () => node?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={cx("modal", wide && "wide-modal")}
      onCancel={close}
      onClick={(e) => {
        if (e.target === ref.current) close();
      }}
    >
      <div className="modal-inner">
        <button
          className="icon-button modal-close"
          onClick={close}
          aria-label="Close dialog"
        >
          <X size={19} />
        </button>
        {children}
      </div>
    </dialog>
  );
}
type LaunchValues = {
  provider: string;
  name: string;
  cwd: string;
  prompt: string;
  access: string;
  resume?: string;
};
function LaunchForm({
  data,
  agent,
  submit,
  continueSession,
  close,
}: {
  data: State | null;
  agent?: Agent;
  submit: (v: LaunchValues) => Promise<void>;
  continueSession: (p: string) => Promise<void>;
  close: () => void;
}) {
  const [provider, setProvider] = useState(agent?.provider || "codex"),
    [name, setName] = useState(agent?.name || ""),
    [cwd, setCwd] = useState(agent?.cwd || data?.roots[0] || ""),
    [prompt, setPrompt] = useState(""),
    [access, setAccess] = useState(agent?.access || "read-only"),
    [pending, setPending] = useState(false),
    [error, setError] = useState("");
  const continued = !!agent;
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setPending(true);
        setError("");
        try {
          if (continued) await continueSession(prompt);
          else await submit({ provider, name, cwd, prompt, access });
        } catch (e) {
          setError((e as Error).message);
        } finally {
          setPending(false);
        }
      }}
    >
      <div className="modal-heading">
        <span className="eyebrow">
          {continued ? "CONTINUE A SESSION" : "MANAGED EXECUTION"}
        </span>
        <h2>{continued ? "Pick up the work" : "Launch a coding agent"}</h2>
        <p>
          {continued
            ? "Send a new turn to this existing conversation."
            : "Run a real coding agent with live output and process controls."}
        </p>
      </div>
      {!continued && (
        <>
          <div className="provider-options">
            {(["codex", "claude"] as const).map((p) => (
              <button
                type="button"
                key={p}
                onClick={() => setProvider(p)}
                className={cx(provider === p && "selected")}
              >
                <Provider provider={p} />
                <div>
                  <strong>{p === "codex" ? "Codex" : "Claude Code"}</strong>
                  <span>
                    {data?.integrations[p]
                      ? "Installed locally"
                      : "CLI not found"}
                  </span>
                </div>
                {provider === p && <CheckCircle2 size={16} />}
              </button>
            ))}
          </div>
          <label className="form-label">
            Agent name <span>optional</span>
            <input
              placeholder="e.g. API refactor"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={100}
            />
          </label>
          <label className="form-label">
            Working directory
            <input
              required
              value={cwd}
              onChange={(e) => setCwd(e.target.value)}
            />
          </label>
        </>
      )}
      <label className="form-label">
        {continued ? "Follow-up instruction" : "Task"}
        <textarea
          required
          autoFocus
          placeholder="What should the agent work on?"
          rows={5}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          maxLength={30000}
        />
      </label>
      {!continued && (
        <label className="form-label">
          Workspace permissions
          <select value={access} onChange={(e) => setAccess(e.target.value)}>
            <option value="read-only">Read only · inspect and explain</option>
            <option value="workspace-write">
              Workspace write · implement changes
            </option>
          </select>
        </label>
      )}
      <div className="form-note">
        <ShieldCheck size={15} />
        <span>
          {continued
            ? "A continuation starts a new turn; it does not reverse a previous stop."
            : "Uses your local CLI login. Model usage is billed by your provider. Workspace write permits file changes and coding tools."}
        </span>
      </div>
      {error && (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}
      <div className="modal-actions">
        <button type="button" className="button" onClick={close}>
          Cancel
        </button>
        <button
          className="button primary"
          disabled={pending || (!continued && !data?.integrations[provider])}
        >
          {pending ? (
            <Loader2 className="spin" size={15} />
          ) : (
            <Play size={14} />
          )}{" "}
          {pending
            ? "Starting…"
            : continued
              ? "Continue session"
              : "Launch agent"}
        </button>
      </div>
    </form>
  );
}
function ConfirmControl({
  agent,
  action,
  confirm,
  close,
}: {
  agent: Agent;
  action: string;
  confirm: () => Promise<void>;
  close: () => void;
}) {
  const [pending, setPending] = useState(false),
    [error, setError] = useState("");
  return (
    <>
      <div className="modal-heading">
        <span className="eyebrow">
          {action === "adopt" ? "PROCESS CONTROL" : "LIFECYCLE ACTION"}
        </span>
        <h2>
          {label(action)} {agent.name}?
        </h2>
        <p>
          {action === "adopt"
            ? `Enable pause, resume, and stop for this existing ${agent.provider} process (PID ${agent.pid}). Its output stays in the original terminal.`
            : action === "interrupt"
              ? "Cancel the active Codex turn through the shared daemon. Completed edits remain on disk."
              : "Stop this coding agent and its visible children. Remaining processes are killed after 3 seconds. Saved changes and external actions are not rolled back."}
        </p>
      </div>
      <div className="form-note">
        <Folder size={16} />
        <span>{shortPath(agent.cwd)}</span>
      </div>
      {error && (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}
      <div className="modal-actions">
        <button className="button" onClick={close}>
          Cancel
        </button>
        <button
          className={cx("button", action === "adopt" ? "primary" : "danger")}
          disabled={pending}
          onClick={async () => {
            setPending(true);
            try {
              await confirm();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setPending(false);
            }
          }}
        >
          {pending ? (
            <Loader2 size={14} className="spin" />
          ) : action === "adopt" ? (
            <ShieldCheck size={14} />
          ) : (
            <Square size={12} />
          )}{" "}
          {label(action)} agent
        </button>
      </div>
    </>
  );
}

function Inspector({
  history,
  agent,
  close,
  control,
  reload,
}: {
  history: MetricHistory;
  agent: Agent;
  close: () => void;
  control: (a: Agent, action: string) => void;
  reload: () => void;
}) {
  const [tab, setTab] = useState("resources");
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = ref.current;
    node?.showModal();
    return () => node?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="inspector-backdrop"
      onCancel={close}
      aria-label={`Inspect ${agent.name}`}
      onClick={(e) => {
        if (e.target === ref.current) close();
      }}
    >
      <aside className="inspector" onClick={(e) => e.stopPropagation()}>
        <div className="inspector-top">
          <span>AGENT INSPECTOR</span>
          <div>
            <button
              className="icon-button"
              onClick={reload}
              aria-label="Refresh agent details"
            >
              <RefreshCw size={14} />
            </button>
            <button
              className="icon-button"
              onClick={close}
              aria-label="Close inspector"
            >
              <X size={18} />
            </button>
          </div>
        </div>
        <div className="inspector-identity">
          <Provider provider={agent.provider} />
          <h2>{agent.name}</h2>
          <Status value={agent.state} />
          <p>{agent.note || `${label(agent.source)} · ${agent.provider}`}</p>
        </div>
        <div className="inspector-actions">
          {agent.controls.map((action) => (
            <button
              className={cx("button", action === "resume" && "primary")}
              key={action}
              onClick={() => control(agent, action)}
            >
              {action === "pause" ? (
                <Pause size={13} />
              ) : action === "stop" || action === "interrupt" ? (
                <Square size={12} />
              ) : (
                <Play size={13} />
              )}{" "}
              {label(action)}
            </button>
          ))}
        </div>
        <dl className="agent-facts">
          <dt>Working directory</dt>
          <dd>{shortPath(agent.cwd)}</dd>
          <dt>Process ID</dt>
          <dd>{agent.pid || "Shared session"}</dd>
          <dt>CPU / Memory</dt>
          <dd>
            {agent.cpu == null
              ? "Not attributable"
              : agent.cpu.toFixed(1) + "%"}{" "}
            / {bytes(agent.memory)}
          </dd>
          <dt>Session</dt>
          <dd className="mono">{agent.session_id || "Not reported"}</dd>
          {agent.exit_code != null && (
            <>
              <dt>Exit code</dt>
              <dd>{agent.exit_code}</dd>
            </>
          )}
        </dl>
        <div className="filter-tabs inspector-tabs">
          <button
            className={cx(tab === "resources" && "active")}
            onClick={() => setTab("resources")}
          >
            Resources
          </button>
          <button
            className={cx(tab === "output" && "active")}
            onClick={() => setTab("output")}
          >
            Live output
          </button>
        </div>
        {tab === "resources" ? (
          <div className="inspector-content">
            <AgentPerformance agent={agent} history={history} />
            <h3>Attributed processes</h3>
            <p className="small-copy muted">
              CPU below uses 100% per core. Each process is counted once across
              agents.
            </p>
            {agent.process_tree?.length ? (
              agent.process_tree.map((p) => (
                <div className="process-row" key={p.pid}>
                  <Terminal size={13} />
                  <strong>{p.name}</strong>
                  <code>{p.pid}</code>
                  <span>
                    {percent(p.cpu)} · {bytes(p.memory)}
                  </span>
                </div>
              ))
            ) : (
              <p className="muted">
                Process details are unavailable for this session.
              </p>
            )}
            <h3>
              Open files{" "}
              <span className="count">{agent.open_files?.length || 0}</span>
            </h3>
            <p className="small-copy muted">
              Observed file handles. Exclusive lock ownership is unknown.
            </p>
            {agent.open_files?.map((f, i) => (
              <div className="open-file" key={i}>
                <FileText size={13} />
                <span>{shortPath(f.path)}</span>
              </div>
            ))}
            {agent.inspection_error && (
              <div className="form-note">{agent.inspection_error}</div>
            )}
          </div>
        ) : (
          <div className="inspector-content">
            {agent.log_truncated && (
              <div className="form-note">
                Showing the latest 300 output events.
              </div>
            )}
            {agent.logs?.length ? (
              <pre className="agent-output">
                {agent.logs
                  .map((l) => `[${clock(l.time)}] ${l.text}`)
                  .join("\n\n")}
              </pre>
            ) : (
              <p className="muted">
                Output is captured for runs launched through DEADLOCK. Use the
                original client for other sessions.
              </p>
            )}
            <button className="button mini" onClick={reload}>
              <RefreshCw size={12} />
              Refresh output
            </button>
          </div>
        )}
      </aside>
    </dialog>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
