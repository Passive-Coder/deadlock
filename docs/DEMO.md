# Three-minute demonstration guide

Start the backend, verify **Connections → Exasol available**, and authenticate Codex before recording. Close private agent inspectors before publishing any capture. The coding-agent dashboard and the recovery lab have different data sources; say so explicitly.

| Time | Show | Explain |
| --- | --- | --- |
| 0:00–0:25 | Agents overview and a disposable managed Codex run | These are real local coding-agent processes. CPU/RSS are observed; shared desktop runtimes are protected. |
| 0:25–0:45 | Pause, resume, stop the disposable run | Pause holds resources; stop requests termination. Neither action pretends to roll back a coding task. |
| 0:45–1:00 | Recovery lab, canonical scenario, seed 42, live mediator | Lab workers use scripted policies and application-managed leases. The mediator makes live model calls. |
| 1:00–1:25 | Circular waits and incident | A holds the dataset, B the renderer, C the artifact writer. SQL detects a persistent cycle from a complete Exasol snapshot. |
| 1:25–1:55 | Candidate evidence, tool trace, plan | B's checkpoint preserves 18 work units and discards 3. The runner revalidates the plan, parks B, releases, and readmits atomically. Let actual model latency remain visible. |
| 1:55–2:15 | Validated outputs and empty waits | Open CSV, HTML, or ZIP. Resolution requires real content validation and worker completion. |
| 2:15–2:40 | Changed candidate or stale-plan variant | The chosen worker follows current costs; stale proposals cannot mutate state. A retry is bounded. |
| 2:40–3:00 | Evaluation report and integration boundaries | Show measured live successes, baseline timings, and missed targets. Claude needs its own login; shared Codex session controls require an attachable daemon. |

Use the repository's measured evaluation file when discussing performance. A recorded walkthrough must be labeled recorded; never substitute a recording for a purported live model response. The app's export button downloads the current run's state, SQL observations, events, tool trace, operation outcomes, and artifact validation.
