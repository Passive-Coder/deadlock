export type Event = {
  time: number;
  type: string;
  message: string;
  seq?: number;
  worker_id?: string;
};
export type Agent = {
  id: string;
  name: string;
  provider: "codex" | "claude";
  state: string;
  source: string;
  cwd: string;
  pid: number | null;
  created: number;
  cpu: number | null;
  memory: number | null;
  children?: number;
  cpu_capacity?: number | null;
  read_rate?: number | null;
  write_rate?: number | null;
  threads?: number;
  sampled_at?: number;
  metrics_partial?: boolean;
  pause_owner?: "automatic" | "manual" | null;
  note?: string;
  controls: string[];
  protected: boolean;
  session_id?: string;
  access?: string;
  exit_code?: number;
  logs?: { time: number; text: string }[];
  log_truncated?: boolean;
  open_files?: { path: string; pid: number; kind: string }[];
  process_tree?: ProcessMetric[];
  inspection_error?: string;
};
export type Worker = {
  id: string;
  name: string;
  kind: string;
  state: string;
  attempt: string;
  progress: number;
  total: number;
  waiting: string | null;
  needs: string[];
  checkpoint_work: number;
  checkpoint_id: string | null;
  last_progress: number;
  capabilities: string[];
};
export type Resource = {
  id: string;
  name: string;
  owner: string | null;
  version: number;
  capacity: number;
  exclusive: boolean;
};
export type Candidate = {
  id: string;
  worker_id: string;
  operation: string;
  lost_work: number;
  checkpoint_work: number;
  evidence_id: string;
  snapshot_id: string;
};
export type Incident = {
  id: string;
  status: string;
  key: string;
  members: string[];
  resources: string[];
  detected: number;
  ended: number | null;
  attempts: number;
  tool_calls: number;
  model: string | null;
  reason: string | null;
  trace: { time: number; tool: string; arguments: unknown; result: unknown }[];
  plan: { id: string; rationale: string; candidate: Candidate } | null;
  verification: {
    valid: boolean;
    resources_clear: boolean;
    evidence_complete: boolean;
    checks: {
      worker_id: string;
      completed: boolean;
      valid: boolean;
      error?: string;
    }[];
  } | null;
};
export type Run = {
  id: string;
  scenario: string;
  strategy: string;
  status: string;
  seed: number;
  started: number;
  ended: number | null;
  auto_recover: boolean;
  config: { incident_budget_seconds: number };
  mode: string;
  workers: Worker[];
  resources: Resource[];
  incident: Incident | null;
  events: Event[];
  evidence_gap: boolean;
  discarded_work: number;
  preserved_work: number;
  artifacts: {
    worker_id: string;
    filename: string;
    valid: boolean;
    size: number;
    sha256: string;
  }[];
};
export type State = {
  time: number;
  agents: Agent[];
  run: Run | null;
  host: Host;
  governor: GovernorState;
  containers: {
    available: boolean;
    updated: number | null;
    error: string | null;
    items: {
      id: string;
      name: string;
      cpu: string;
      memory: string;
      block_io: string;
      network_io: string;
    }[];
  };
  telemetry: {
    engine: string;
    available: boolean;
    error: string | null;
    last_success: number | null;
  };
  integrations: {
    codex: boolean;
    claude: boolean;
    codex_sessions: string | null;
    mediator: string;
  };
  roots: string[];
  scenarios: Record<string, string>;
  events: Event[];
  errors: { component: string; error: string }[];
};

export type ProcessMetric = {
  pid: number;
  name: string;
  status: string;
  cpu: number | null;
  memory: number;
  threads: number;
};
export type Host = {
  cpu: number | null;
  cores: (number | null)[];
  logical_cpus: number;
  memory_used: number;
  memory_total: number;
  memory_available: number;
  memory_percent: number;
  swap_used: number;
  swap_total: number;
  platform: string;
  hostname: string;
  updated: number;
  load: number[];
  interval: number;
  agent_cpu: number | null;
  agent_memory: number;
  unreadable_processes: number;
  process_count: number;
  io: Record<string, number | null>;
  pressure: {
    source: string | null;
    level: string | null;
    memory?: { full?: { avg10: number }; some?: { avg10: number } };
  };
  gpu: {
    name: string;
    utilization: number;
    memory: number | null;
    source: string;
    updated: number;
  } | null;
  other_processes: ProcessMetric[];
};
export type GovernorState = {
  enabled: boolean;
  status: string;
  reason: string;
  exempt: string[];
  cooldown_until: number;
  overload_since: number | null;
  policy: {
    cpu_high: number;
    cpu_low: number;
    sustain_seconds: number;
    recovery_seconds: number;
    max_pause_seconds: number;
    cooldown_seconds: number;
    minimum_agent_cpu: number;
  };
  paused: {
    agent_id: string;
    name: string;
    since: number;
    resume_by: number;
    reason: string;
  } | null;
};
export type MetricFrame = {
  time: number;
  host: Pick<
    Host,
    | "cpu"
    | "memory_used"
    | "memory_total"
    | "memory_available"
    | "agent_cpu"
    | "agent_memory"
    | "pressure"
    | "io"
    | "gpu"
  >;
  agents: Record<
    string,
    Pick<
      Agent,
      | "cpu"
      | "cpu_capacity"
      | "memory"
      | "read_rate"
      | "write_rate"
      | "children"
      | "threads"
    >
  >;
};
export type MetricHistory = {
  samples: MetricFrame[];
  retention_seconds: number;
};
