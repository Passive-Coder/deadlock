# Live device monitoring and automatic control

This workspace measures actual operating-system processes. No lab worker, seeded workload, model response, or synthetic resource lease supplies its CPU, RAM, GPU, disk, network, or pressure graphs.

## Measurement contract

| Signal | Source / scope | Interpretation |
| --- | --- | --- |
| Host and per-core CPU | psutil OS CPU-time counters | Busy fraction between samples; Linux guest time is not double-counted and iowait is not counted as busy CPU |
| Agent CPU | Process user + system CPU-time deltas, PID + birth identity | Parent and attributed descendants; normalized by logical core count for comparison with the host; first observations of already-running processes are unknown |
| Agent RAM | Process `memory_info().rss` | Sum of visible resident mappings; shared pages can be counted in more than one mapping, compressed pages are absent; no claim of exclusive physical footprint |
| Available RAM | `virtual_memory().available` | OS estimate of headroom; displayed alongside installed memory and swap usage |
| macOS memory pressure | Read-only `kern.memorystatus_vm_pressure_level` via `sysctlbyname` | XNU userspace levels 1/2/4 → normal/warning/critical; no invented percentage |
| Linux memory pressure | `/proc/pressure/memory` | Ten-second `full` stall average used by the controller; missing PSI remains unavailable |
| Apple Silicon GPU | Read-only `ioreg -a -r -c AGXAccelerator -d 1`, `PerformanceStatistics` | Driver-reported device utilization; host-wide, approximately three-second collection; unavailable if that driver field is absent |
| Disk / network / swap | OS cumulative byte counters | Deltas per second; binary units; disk devices/interfaces are aggregated, including loopback network traffic |
| Containers | `docker stats --no-stream` in the configured Docker context | Container CPU (100% = one virtual core), CLI-reported RAM/limit, and cumulative block/network I/O; refreshed independently about every 5–13 seconds; ownership by an agent is unknown |
| Agent disk | Process I/O counters when supported | Unavailable on macOS; never substituted with host disk usage |
| Processes / threads / open files | Same sampled identities; process inspection | Open handles do not establish exclusive lock ownership; visible descendants only |

Every readable process is sampled once. The nearest registered agent root owns its sample, avoiding overlap when an agent is under a shared runtime or another root. DEADLOCK's backend subtree stops attribution to its parent runtime. Shared Codex sessions do not get fabricated per-session CPU or RAM. Missing or exited processes can make a sample incomplete; inaccessible descendants mark the agent as partial and exclude it from automatic selection. Processes that start and finish entirely between samples can be missed. OS sampling is not atomic across all processes and devices.

History retains at most 600 samples in memory, normally about ten minutes. It survives browser reloads, not backend restarts. Samples are spaced by actual timestamps; gaps and unknown values break graph lines. UI graph inspection supports pointer movement, a keyboard range control, and three time windows. No cloud synchronization is involved.

## Automatic policy

Defaults are enabled, 90% host CPU for eight seconds, at least 3% host CPU contribution by an eligible agent, and one automatic pause at a time. Memory-only intervention requires critical macOS pressure, less than 8% available memory, or Linux full-memory PSI ≥10%, plus agent RSS growth ≥1 MiB/s over a baseline of at least five seconds. A warning level alone does not suspend a stable-memory agent.

An eligible agent must be running, have valid observed metrics, be a recognized standalone Codex/Claude process, and support adoption or pause. Shared infrastructure, backend ancestors, excluded agents, manually stopped processes, and agents manually controlled in the last 60 seconds are skipped. Existing standalone agents are adopted only when an actual automatic action is selected.

A pause ends after five consecutive seconds at CPU ≤70%, RAM headroom ≥12%, macOS pressure neither warning nor critical, and Linux full-memory stalls below 2%; it also ends at the independent 20-second resume deadline, on stale measurements, on disable/exclusion, or on manual control. A 30-second cooldown and a new eight-second overload observation precede another pause. Staleness is four seconds; a sampling interval above four seconds also blocks selection.

The watchdog is a separate local Python process. It knows the backend's PID/creation time and receives identity-checked members before they are suspended. Parents are frozen before their children are enumerated. Pre-existing stopped descendants are not registered or resumed. At expiry the watchdog resumes registered identities; while waiting for the controller to disarm it, it also releases a late SIGSTOP caused by controller descheduling. A closed controller pipe or dead controller also causes release. PID reuse never authorizes a signal to a replacement process. Manual controls release any automatic lease first.

The policy is deterministic; no model decides which real user process to suspend. It does not terminate processes automatically. Termination is a separate manual control. Preferences are stored in `.deadlock/governor.json`; process events including intervention measurements are appended to `.deadlock/agent-events.jsonl`.

## Limits that matter

Suspension retains locks and allocated memory. It can reduce CPU execution and slow additional allocation; it cannot reclaim an agent's existing memory or solve an arbitrary lock cycle. It may delay an in-flight tool call or a lock holder, which is why pauses are short, bounded and followed by cooldowns. There is no guarantee against an OS OOM killer, a machine-wide scheduling freeze, inaccessible/detached processes, or loss of both the controller and watchdog. Strong resource isolation would require per-agent containers/cgroups or provider cooperation.

Other applications and detached containers can dominate load. Docker Linux memory usage follows the CLI convention of subtracting inactive file cache, and is not the same metric as process RSS. The monitor shows their observed CPU/RSS separately; the governor does not kill or suspend them. GPU and network usage are not attributed to individual agents. Remote model inference and remote/cloud agents are outside this local host. The GPU driver fields and macOS pressure sysctl are platform-specific implementation interfaces and may become unavailable on a future OS; unavailability is reported rather than replaced with fabricated readings.

## Validation

The local suite includes real disposable process-tree suspension/resumption/termination; nested CPU/RSS attribution without duplicate members; PID identity changes; watchdog expiry and controller pipe loss; preservation of an already-paused child; governor hysteresis, deadline, cooldown, stale data, exemptions and manual-pause protections; and the local API boundary. Policy tests inject pressure to avoid stressing the host and explicitly label this distinction. GPU discovery is also read live from this Apple M5 host.

During integration verification on 2026-09-13, the enabled governor automatically adopted the existing Claude CLI and paused it during sustained measured CPU saturation. The first pause event was recorded at Unix time 1789313815.057 and the controller's resume observation at 1789313835.451 (20.394 seconds apart; the independent watchdog uses its own 20-second lease). The Codex shared runtime remained protected. A separate `psutil.cpu_percent(interval=0.3)` reading and the dashboard both reported 99.7% host CPU during a later spot check. These observations establish real operation, not universal overload relief or external-deadlock recovery.

The browser was checked against the running backend for live values, all device graphs, per-agent inspector graphs, process details, time-window selection and global control. Missing per-process macOS disk counters render as unavailable. Tests and final CI status are recorded in the task's delivery message.

## Research sources

- [psutil official API reference](https://psutil.readthedocs.io/): process identity, process/host CPU semantics, RSS, available memory, platform-specific counters, suspend/resume. The installed library source/docstrings were checked alongside actual host readings.
- [Linux kernel PSI documentation](https://docs.kernel.org/accounting/psi.html): `some` versus `full`, ten/sixty/300-second stall averages and the meaning of pressure.
- [Apple XNU memory-pressure implementation](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_memorystatus_notify.c): read-only userspace pressure conversion. The SDK's dispatch memory-pressure constants and the live sysctl value were also inspected.
- [Apple IORegistry tools source](https://github.com/apple-oss-distributions/IOKitTools): IORegistry inspection. GPU field availability and names were verified from this machine's live `AGXAccelerator` output; Apple does not promise these performance fields as a stable public telemetry API.

- [Docker statistics reference](https://docs.docker.com/reference/cli/docker/container/stats/): JSON output fields, non-streaming sampling, memory-cache adjustments, and cumulative network/block I/O. Container totals are kept separate from host and agent totals.
