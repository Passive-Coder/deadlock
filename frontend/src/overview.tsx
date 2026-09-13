import { Activity, AlertTriangle, ArrowRight, ShieldCheck } from "lucide-react";
import { bytes } from "./api";
import { percent } from "./monitor";
import type { State } from "./types";

export function OverviewSummary({
  data,
  disconnected,
  onResources,
}: {
  data: State;
  disconnected: boolean;
  onResources: () => void;
}) {
  const h = data.host;
  const stale = disconnected || !h.updated || data.time - h.updated > 4;
  const lowMemory =
    h.memory_total > 0 && h.memory_available / h.memory_total < 0.08;
  const memoryStalls = (h.pressure?.memory?.full?.avg10 ?? 0) >= 10;
  const criticalMemory =
    h.pressure?.level === "critical" || lowMemory || memoryStalls;
  const highCpu = h.cpu != null && h.cpu >= data.governor.policy.cpu_high;
  const warning = h.pressure?.level === "warning";
  const title = stale
    ? "Waiting for fresh measurements"
    : criticalMemory
      ? "Memory is under pressure"
      : highCpu
        ? "CPU usage is high"
        : warning
          ? "Memory pressure is elevated"
          : "Machine overview";
  const description = stale
    ? "The readings below are the last available sample."
    : criticalMemory
      ? "Review device resources to see what is using memory."
      : highCpu
        ? "Review device resources to see what is keeping your CPU busy."
        : warning
          ? "Your system is reporting a memory warning."
          : "Live CPU and available memory across all applications.";
  const needsAttention = !stale && (criticalMemory || highCpu || warning);
  const Icon = needsAttention ? AlertTriangle : Activity;
  return (
    <section className="overview-summary" aria-label="Machine overview">
      <div className="overview-summary-heading">
        <span className={`summary-symbol ${needsAttention ? "attention" : ""}`}>
          <Icon size={21} />
        </span>
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </div>
      <div className="summary-readings">
        <div>
          <span>CPU usage</span>
          <strong>{percent(h.cpu)}</strong>
        </div>
        <div>
          <span>Available memory</span>
          <strong>
            {bytes(h.memory_available)}{" "}
            <small>of {bytes(h.memory_total)}</small>
          </strong>
        </div>
        <button className="text-button" onClick={onResources}>
          View device resources <ArrowRight size={15} />
        </button>
      </div>
    </section>
  );
}

export function ControlSummary({
  data,
  onManage,
  onResume,
  busy,
}: {
  data: State;
  onManage: () => void;
  onResume: () => void;
  busy: string;
}) {
  const g = data.governor;
  const status = !g.enabled
    ? "Off"
    : g.paused
      ? "Agent paused"
      : g.status === "limited"
        ? "Limited"
        : g.status === "cooldown"
          ? "Cooling down"
          : "On";
  const description = g.paused
    ? `${g.paused.name} resumes within ${Math.max(0, Math.ceil(g.paused.resume_by - data.time))}s.`
    : !g.enabled
      ? "Agents won’t be paused automatically."
      : g.status === "limited"
        ? g.reason
        : "Temporarily pauses eligible agents during overload.";
  return (
    <section
      className={`control-summary ${g.paused ? "has-paused-agent" : ""}`}
      aria-label="Automatic control status"
    >
      <ShieldCheck size={18} />
      <div className="control-summary-copy">
        <h2>
          Automatic control <span>{status}</span>
        </h2>
        <p>{description}</p>
      </div>
      <div className="control-summary-actions">
        {g.paused && (
          <button
            className="button mini"
            onClick={onResume}
            disabled={busy === g.paused.agent_id}
          >
            Resume now
          </button>
        )}
        <button
          className="text-button"
          onClick={onManage}
          aria-label="Manage automatic control"
        >
          Manage
        </button>
      </div>
    </section>
  );
}
