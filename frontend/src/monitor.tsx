import { useEffect, useId, useState, useRef } from "react";
import {
  Cpu,
  MemoryStick,
  ShieldCheck,
  Pause,
  Play,
  ChevronRight,
  Monitor,
  Activity,
  LockKeyhole,
} from "lucide-react";
import { api, bytes, clock } from "./api";
import type { Agent, State, MetricFrame, MetricHistory } from "./types";

export const percent = (v: number | null | undefined) =>
  v == null ? "—" : `${v.toFixed(1)}%`;
const throughput = (v: number | null | undefined) =>
  v == null ? "Unavailable" : `${bytes(v)}/s`;
const active = (a: Agent) =>
  !!a.pid && ["RUNNING", "PAUSED", "STARTING", "STOPPING"].includes(a.state);

export function useMetrics() {
  const [history, setHistory] = useState<MetricHistory>({
    samples: [],
    retention_seconds: 600,
  });
  const [error, setError] = useState("");
  useEffect(() => {
    let closed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await api<MetricHistory>("/metrics?seconds=600");
        if (!closed) {
          setHistory(result);
          setError("");
        }
      } catch (e) {
        if (!closed) setError((e as Error).message);
      }
      if (!closed) timer = setTimeout(poll, 2000);
    }
    void poll();
    return () => {
      closed = true;
      clearTimeout(timer);
    };
  }, []);
  return { history, error };
}

type Series = {
  name: string;
  color: string;
  value: (frame: MetricFrame) => number | null | undefined;
  dashed?: boolean;
};
export function TimeChart({
  title,
  frames,
  lines,
  format = percent,
  ceiling,
  threshold,
  seconds = 120,
}: {
  title: string;
  frames: MetricFrame[];
  lines: Series[];
  format?: (v: number | null | undefined) => string;
  ceiling?: number;
  threshold?: number;
  seconds?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const id = useId().replace(/:/g, "");
  const plotRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  useEffect(() => {
    const observer = new ResizeObserver((entries) => {
      const size = entries[0]?.contentRect.width;
      if (size) setWidth(Math.max(240, Math.round(size)));
    });
    if (plotRef.current) observer.observe(plotRef.current);
    return () => observer.disconnect();
  }, []);
  const end = frames.at(-1)?.time || 0,
    start = end - seconds;
  const points = frames.filter((f) => f.time >= start);
  const max =
    ceiling ??
    Math.max(1, ...points.flatMap((f) => lines.map((l) => l.value(f) || 0))) *
      1.15;
  const height = 155,
    left = Math.max(46, Math.min(88, format(max).length * 6 + 8)),
    right = 10,
    top = 12,
    bottom = 23;
  const x = (t: number) =>
    left + ((t - start) / seconds) * (width - left - right);
  const y = (v: number) =>
    top + (1 - Math.min(max, Math.max(0, v)) / max) * (height - top - bottom);
  const index =
    hover == null
      ? points.length - 1
      : points.reduce(
          (best, frame, i) =>
            Math.abs(frame.time - hover) < Math.abs(points[best].time - hover)
              ? i
              : best,
          0,
        );
  const point = points[index];
  const available = points.some((f) => lines.some((l) => l.value(f) != null));
  return (
    <section className="time-chart" aria-label={title}>
      <div className="chart-heading">
        <h3>{title}</h3>
        <span>{point ? clock(point.time) : "Collecting"}</span>
      </div>
      <div className="chart-legend">
        {lines.map((line) => (
          <span key={line.name}>
            <i style={{ background: line.color }} />
            {line.name}
            <strong>{format(point ? line.value(point) : null)}</strong>
          </span>
        ))}
      </div>
      <div ref={plotRef} className="plot" onMouseLeave={() => setHover(null)}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={`${title}, last ${seconds / 60} minutes. ${available ? "Measured operating system samples" : "Waiting for available measurements"}.`}
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const t =
              start +
              Math.max(
                0,
                Math.min(
                  1,
                  (((e.clientX - rect.left) / rect.width) * width - left) /
                    (width - left - right),
                ),
              ) *
                seconds;
            if (points.length) setHover(t);
          }}
        >
          <defs>
            <clipPath id={id}>
              <rect
                x={left}
                y={top}
                width={width - left - right}
                height={height - top - bottom}
              />
            </clipPath>
          </defs>
          {[0, 0.5, 1].map((n) => (
            <g key={n}>
              <line
                x1={left}
                x2={width - right}
                y1={y(max * n)}
                y2={y(max * n)}
                className="chart-grid"
              />
              <text x={left - 7} y={y(max * n) + 3} textAnchor="end">
                {format(max * n)}
              </text>
            </g>
          ))}
          {threshold != null && (
            <g>
              <line
                x1={left}
                x2={width - right}
                y1={y(threshold)}
                y2={y(threshold)}
                className="threshold"
              />
              <text x={width - right - 3} y={y(threshold) - 4} textAnchor="end">
                pause threshold
              </text>
            </g>
          )}
          {lines.map((line) => {
            let previous: MetricFrame | null = null;
            const path = points
              .map((f) => {
                const v = line.value(f);
                if (v == null) {
                  previous = null;
                  return "";
                }
                const draw = `${previous && f.time - previous.time < 4 ? "L" : "M"}${x(f.time).toFixed(1)},${y(v).toFixed(1)}`;
                previous = f;
                return draw;
              })
              .join(" ");
            return (
              <path
                key={line.name}
                d={path}
                clipPath={`url(#${id})`}
                fill="none"
                stroke={line.color}
                strokeWidth="1.8"
                strokeDasharray={line.dashed ? "4 3" : undefined}
                vectorEffect="non-scaling-stroke"
              />
            );
          })}
          {point && hover != null && (
            <line
              x1={x(point.time)}
              x2={x(point.time)}
              y1={top}
              y2={height - bottom}
              className="chart-cursor"
            />
          )}
          <text x={left} y={height - 3}>
            {seconds / 60} min ago
          </text>
          <text x={(width + left) / 2} y={height - 3} textAnchor="middle">
            {seconds / 120} min
          </text>
          <text x={width - right} y={height - 3} textAnchor="end">
            Latest sample
          </text>
        </svg>
        {!available && (
          <div className="plot-empty">
            {points.length < 2
              ? "Collecting interval measurements…"
              : "This metric is unavailable on this host"}
          </div>
        )}
      </div>
      <input
        className="chart-scrubber"
        type="range"
        min={0}
        max={Math.max(0, points.length - 1)}
        value={Math.max(0, index)}
        onChange={(e) => setHover(points[Number(e.target.value)]?.time ?? null)}
        style={{ marginLeft: left, width: `calc(100% - ${left}px)` }}
        aria-label={`Inspect ${title} history`}
        aria-valuetext={
          point
            ? `${clock(point.time)}; ${lines.map((l) => `${l.name}: ${format(l.value(point))}`).join(", ")}`
            : "No samples"
        }
      />
    </section>
  );
}

export function HardwareDashboard({
  data,
  history,
  historyError,
  full = false,
}: {
  data: State;
  history: MetricHistory;
  historyError: string;
  full?: boolean;
}) {
  const [seconds, setSeconds] = useState(120);
  const h = data.host;
  const frames = history.samples;
  const memoryPressure =
    h.pressure?.level ||
    (h.pressure?.memory?.full
      ? `${h.pressure.memory.full.avg10.toFixed(1)}% stalled`
      : "Unavailable");
  return (
    <section className="hardware-dashboard">
      <div className="hardware-strip">
        <div>
          <span>
            <Cpu size={14} />
            Host CPU
          </span>
          <strong>{percent(h.cpu)}</strong>
          <small>
            {h.logical_cpus || "—"} logical cores · all applications
          </small>
        </div>
        <div>
          <span>
            <MemoryStick size={14} />
            Memory headroom
          </span>
          <strong>{bytes(h.memory_available)}</strong>
          <small>
            {bytes(h.memory_total)} installed · {bytes(h.swap_used)} swap used
          </small>
        </div>
        <div>
          <span>
            <Monitor size={14} />
            GPU utilization
          </span>
          <strong>{percent(h.gpu?.utilization)}</strong>
          <small>
            {h.gpu?.name || "GPU telemetry unavailable"} · host total
          </small>
        </div>
        <div
          className={
            h.pressure?.level === "critical"
              ? "pressure-critical"
              : h.pressure?.level === "warning"
                ? "pressure-warning"
                : ""
          }
        >
          <span>
            <Activity size={14} />
            Memory pressure
          </span>
          <strong className="pressure-word">{memoryPressure}</strong>
          <small>{h.pressure?.source || "No kernel pressure signal"}</small>
        </div>
      </div>
      <div className="live-section-heading">
        <div>
          <span className="live-dot" />
          <h2>Device activity</h2>
          <span className="subtle">{h.platform} · sampled every ~1s</span>
        </div>
        <div className="filter-tabs">
          {[120, 300, 600].map((s) => (
            <button
              key={s}
              className={s === seconds ? "active" : ""}
              onClick={() => setSeconds(s)}
            >
              {s / 60}m
            </button>
          ))}
        </div>
      </div>
      {historyError && (
        <div className="notice error">
          Graph updates unavailable. Showing the last received samples.
        </div>
      )}
      {h.updated && data.time - h.updated > 4 && (
        <div className="notice error">
          Hardware measurements are stale. Automatic pauses are suspended.
        </div>
      )}
      <div className="device-charts">
        <TimeChart
          title="CPU utilization"
          frames={frames}
          ceiling={100}
          threshold={data.governor.policy.cpu_high}
          seconds={seconds}
          lines={[
            { name: "Host", color: "#c6f36b", value: (f) => f.host.cpu },
            {
              name: "Coding agents",
              color: "#a2b4c2",
              value: (f) => f.host.agent_cpu,
              dashed: true,
            },
          ]}
        />
        <TimeChart
          title="Memory allocation"
          frames={frames}
          ceiling={h.memory_total || 1}
          seconds={seconds}
          format={bytes}
          lines={[
            {
              name: "Host in use",
              color: "#c6f36b",
              value: (f) => f.host.memory_used,
            },
            {
              name: "Agent RSS",
              color: "#a2b4c2",
              value: (f) => f.host.agent_memory,
              dashed: true,
            },
          ]}
        />
        {full && (
          <>
            <TimeChart
              title="GPU utilization"
              frames={frames}
              ceiling={100}
              seconds={seconds}
              lines={[
                {
                  name: h.gpu?.name || "Host GPU",
                  color: "#c6f36b",
                  value: (f) =>
                    f.host.gpu && f.time - f.host.gpu.updated < 5
                      ? f.host.gpu.utilization
                      : null,
                },
              ]}
            />
            <TimeChart
              title="Disk throughput"
              frames={frames}
              seconds={seconds}
              format={throughput}
              lines={[
                {
                  name: "Read",
                  color: "#c6f36b",
                  value: (f) => f.host.io.disk_read,
                },
                {
                  name: "Write",
                  color: "#a2b4c2",
                  value: (f) => f.host.io.disk_write,
                  dashed: true,
                },
              ]}
            />
            <TimeChart
              title="Network throughput"
              frames={frames}
              seconds={seconds}
              format={throughput}
              lines={[
                {
                  name: "Received",
                  color: "#c6f36b",
                  value: (f) => f.host.io.net_recv,
                },
                {
                  name: "Sent",
                  color: "#a2b4c2",
                  value: (f) => f.host.io.net_sent,
                  dashed: true,
                },
              ]}
            />
            <TimeChart
              title="Swap activity"
              frames={frames}
              seconds={seconds}
              format={throughput}
              lines={[
                {
                  name: "In",
                  color: "#c6f36b",
                  value: (f) => f.host.io.swap_in,
                },
                {
                  name: "Out",
                  color: "#a2b4c2",
                  value: (f) => f.host.io.swap_out,
                  dashed: true,
                },
              ]}
            />
          </>
        )}
      </div>
      <p className="measurement-note">
        CPU uses total host capacity. RAM headroom is OS available memory; agent
        RSS includes shared pages and excludes compressed memory. Graphs retain
        up to 10 minutes since server startup. Gaps mean missing samples.
      </p>
    </section>
  );
}

export function GovernorPanel({
  data,
  execute,
  busy,
}: {
  data: State;
  execute: (key: string, fn: () => Promise<unknown>) => Promise<void>;
  busy: string;
}) {
  const g = data.governor,
    p = g.policy;
  const eligible = data.agents.filter(
    (a) =>
      active(a) &&
      !a.protected &&
      !g.exempt.includes(a.id) &&
      (a.controls.includes("pause") || a.controls.includes("adopt")),
  ).length;
  return (
    <section className="governor-panel" aria-label="Automatic pressure control">
      <div className="section-header">
        <h2>
          <ShieldCheck size={17} />
          Automatic control
        </h2>
        <button
          role="switch"
          aria-checked={g.enabled}
          aria-label="Automatic pressure control"
          className={`control-switch ${g.enabled ? "on" : ""}`}
          disabled={busy === "governor"}
          onClick={() =>
            void execute("governor", () =>
              api("/governor", { enabled: !g.enabled }),
            )
          }
        >
          <span />
        </button>
      </div>
      <div className={`governor-state ${g.status}`}>
        <span className="live-dot" />
        {g.status === "throttling"
          ? "Temporarily throttling"
          : g.enabled
            ? g.status === "limited"
              ? "Limited control"
              : g.status === "cooldown"
                ? "Recovery cooldown"
                : "Monitoring pressure"
            : "Monitoring only"}
      </div>
      <p>{g.reason}</p>
      {g.paused && (
        <div className="auto-paused">
          <Pause size={15} />
          <div>
            <strong>{g.paused.name}</strong>
            <span>
              Resumes within{" "}
              {Math.max(0, Math.ceil(g.paused.resume_by - data.time))}s
            </span>
          </div>
          <button
            className="icon-button"
            aria-label="Resume throttled agent now"
            onClick={() =>
              void execute(g.paused!.agent_id, () =>
                api(
                  `/agents/${encodeURIComponent(g.paused!.agent_id)}/control`,
                  { action: "resume" },
                ),
              )
            }
          >
            <Play size={16} />
          </button>
        </div>
      )}
      <dl className="policy-facts">
        <dt>CPU trigger</dt>
        <dd>
          ≥ {p.cpu_high}% for {p.sustain_seconds}s
        </dd>
        <dt>Recovery</dt>
        <dd>
          ≤ {p.cpu_low}% for {p.recovery_seconds}s + RAM headroom
        </dd>
        <dt>Pause ceiling</dt>
        <dd>{p.max_pause_seconds}s · one agent at a time</dd>
        <dt>Cooldown</dt>
        <dd>{p.cooldown_seconds}s between pauses</dd>
        <dt>Eligible now</dt>
        <dd>
          {eligible} standalone agent{eligible === 1 ? "" : "s"}
        </dd>
      </dl>
      <p className="policy-note">
        Critical memory pressure or less than 8% headroom can pause an agent
        growing ≥ 1 MiB/s to slow allocation. Suspension retains memory and
        locks; it cannot resolve a lock deadlock. Every automatic pause has an
        independent resume watchdog. Standalone processes are adopted
        automatically when needed.
      </p>
      <div className="protected-note">
        <LockKeyhole size={13} />
        Shared runtimes and manual pauses are protected.
      </div>
      <div className="core-heading">
        <h3>CPU cores</h3>
        <span>{data.host.logical_cpus} logical</span>
      </div>
      <div className="core-map">
        {data.host.cores?.map((value, i) => (
          <div key={i} title={`Core ${i + 1}: ${percent(value)}`}>
            <span>{i + 1}</span>
            <strong>{percent(value)}</strong>
            <i style={{ height: `${value || 0}%` }} />
          </div>
        ))}
      </div>
      <div className="host-throughput">
        <span>
          Disk read / write
          <strong>
            {throughput(data.host.io?.disk_read)} /{" "}
            {throughput(data.host.io?.disk_write)}
          </strong>
        </span>
        <span>
          Network received / sent
          <strong>
            {throughput(data.host.io?.net_recv)} /{" "}
            {throughput(data.host.io?.net_sent)}
          </strong>
        </span>
      </div>
    </section>
  );
}

export function AgentTrend({
  agent,
  history,
}: {
  agent: Agent;
  history: MetricHistory;
}) {
  const values = history.samples.slice(-40);
  const max = Math.max(
    5,
    ...values.map((f) => f.agents[agent.id]?.cpu_capacity || 0),
  );
  return (
    <svg
      className="agent-trend"
      viewBox="0 0 90 24"
      role="img"
      aria-label={`${agent.name} recent CPU trend`}
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        d={values
          .map((f, i) => {
            const v = f.agents[agent.id]?.cpu_capacity;
            if (v == null) return "";
            const prev = values[i - 1];
            return `${prev && prev.agents[agent.id]?.cpu_capacity != null && f.time - prev.time < 4 ? "L" : "M"}${(i / Math.max(1, values.length - 1)) * 90},${22 - (v / max) * 20}`;
          })
          .join(" ")}
      />
    </svg>
  );
}

export function AgentPerformance({
  agent,
  history,
}: {
  agent: Agent;
  history: MetricHistory;
}) {
  return (
    <div className="agent-performance">
      <TimeChart
        title="Agent CPU · host capacity"
        frames={history.samples}
        ceiling={100}
        lines={[
          {
            name: "Process tree",
            color: "#c6f36b",
            value: (f) => f.agents[agent.id]?.cpu_capacity,
          },
        ]}
      />
      <TimeChart
        title="Agent resident memory"
        frames={history.samples}
        format={bytes}
        lines={[
          {
            name: "RSS",
            color: "#c6f36b",
            value: (f) => f.agents[agent.id]?.memory,
          },
        ]}
      />
    </div>
  );
}

export function AgentResources({
  data,
  inspect,
}: {
  data: State;
  inspect: (a: Agent) => void;
}) {
  const agents = data.agents
    .filter(active)
    .sort((a, b) => (b.cpu_capacity || 0) - (a.cpu_capacity || 0));
  return (
    <section className="resource-attribution">
      <div className="section-header">
        <h2>Resource attribution by agent</h2>
        <span className="subtle">Process + attributed descendants</span>
      </div>
      <div className="table-scroll">
        <table className="agent-table attribution-table">
          <thead>
            <tr>
              <th>AGENT / PID</th>
              <th>HOST CPU</th>
              <th>RESIDENT RAM</th>
              <th>PROCESSES</th>
              <th>THREADS</th>
              <th>DISK READ / WRITE</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.id}>
                <td>
                  <button className="agent-name" onClick={() => inspect(a)}>
                    <span>
                      <strong>{a.name}</strong>
                      <small>
                        PID {a.pid} ·{" "}
                        {a.protected ? "Protected runtime" : a.source}
                      </small>
                    </span>
                    <ChevronRight size={14} />
                  </button>
                </td>
                <td>{percent(a.cpu_capacity)}</td>
                <td>{bytes(a.memory)}</td>
                <td>{(a.children || 0) + 1}</td>
                <td>{a.threads ?? "—"}</td>
                <td>
                  {throughput(a.read_rate)} / {throughput(a.write_rate)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="measurement-note">
        Select an agent for graphs, individual process usage, and open file
        handles. Per-process disk counters are unavailable on macOS. GPU and
        network throughput are measured for the host; remote model inference is
        outside this device.
      </p>
      {(data.containers?.available || data.containers?.items.length > 0) && (
        <section className="container-resources">
          <div className="section-header other-process-heading">
            <h2>Container workloads</h2>
            <span className="subtle">
              Docker ·{" "}
              {data.containers.updated
                ? clock(data.containers.updated)
                : "Waiting"}
            </span>
          </div>
          <p className="measurement-note">
            Live Docker statistics. Agent ownership is unknown; detached
            container work continues when a CLI is paused.
          </p>
          <div className="table-scroll">
            <table className="agent-table attribution-table">
              <thead>
                <tr>
                  <th>CONTAINER</th>
                  <th>CPU · 100% = 1 vCPU</th>
                  <th>MEMORY / LIMIT</th>
                  <th>BLOCK I/O TOTAL</th>
                  <th>NETWORK I/O TOTAL</th>
                </tr>
              </thead>
              <tbody>
                {data.containers.items.map((c) => (
                  <tr key={c.id}>
                    <td>{c.name}</td>
                    <td>{c.cpu}</td>
                    <td>{c.memory}</td>
                    <td>{c.block_io}</td>
                    <td>{c.network_io}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {data.containers?.error && (
        <p className="measurement-note">
          Container measurements unavailable: {data.containers.error}
        </p>
      )}
      <div className="section-header other-process-heading">
        <h2>Other processes using this device</h2>
        <span className="subtle">Excludes attributed agent processes</span>
      </div>
      <div className="other-process-list">
        {data.host.other_processes?.map((p) => (
          <div key={p.pid}>
            <span>
              <strong>{p.name}</strong>
              <small>PID {p.pid}</small>
            </span>
            <span>
              {percent(p.cpu == null ? null : p.cpu / data.host.logical_cpus)}
              <small>host CPU</small>
            </span>
            <span>
              {bytes(p.memory)}
              <small>RSS</small>
            </span>
          </div>
        ))}
      </div>
      <p className="measurement-note">
        {data.host.process_count} readable processes ·{" "}
        {data.host.unreadable_processes} inaccessible or exited during the
        sample. Each row is one OS process.
      </p>
    </section>
  );
}
