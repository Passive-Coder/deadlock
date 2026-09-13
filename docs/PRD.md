# DEADLOCK — Product Requirements Document

| Field | Value |
|---|---|
| Version | 1.0 |
| Status | Ready for MVP implementation |
| Product | DEADLOCK |
| One-line description | An AI mediator that detects resource deadlocks between agents, executes a valid recovery, and verifies that work completes. |
| Target release | Exasol AI + Data Challenge 2026 hackathon submission |
| Track | AI Agents That Get Things Done |
| Planning assumption | 3–5 people, starting from scratch, approximately one day to build |
| Submission deadline | September 13, 2026, 11:59 p.m. IST, as published in the event brief [1] |

## 1. Product summary

DEADLOCK helps a developer recover a group of agents that have stopped progressing because each holds a resource another needs. It collects instrumented execution state, uses Exasol to identify a circular dependency, and gives a tool-calling mediator enough evidence to select a supported recovery operation. The runner executes that operation and confirms whether the affected jobs finish.

The defining experience is observable: three workers become blocked, a dependency graph exposes the cycle, the mediator explains and executes a targeted intervention, and the workers produce actual output files. An independent verifier confirms the outputs and resource state. The system preserves unrelated work and reports partial or unsuccessful recovery honestly.

The hackathon release is a local, single-operator application. Its worker agents use scripted tool policies so the failure is reproducible; its mediator uses a live LLM. The interface and README must state this distinction. Adding model-driven workers is optional after the core workflow passes its acceptance tests.

**Pitch:** “When agents block each other, DEADLOCK gets the work moving again.”

## 2. Problem and user

### 2.1 Problem

Tool-using agents can share limited resources: dataset sessions, report-rendering slots, artifact-writing slots, or application reservations. Different workers may acquire these resources in different orders. A worker can remain active and keep sending heartbeats while waiting indefinitely for a resource held by another worker.

The operator needs to know what is blocked, whether the blockage is a true resource cycle, what intervention is supported, and whether that intervention actually solved the task. Restarting everything may discard progress and affect unrelated work. A recovery suggestion without execution still leaves the operator to repair the run manually.

### 2.2 Primary user

An engineer building or demonstrating multi-agent workflows who controls the runner and can expose structured ownership, waiting, and recovery information. The MVP does not attach to arbitrary agents or third-party applications automatically.

### 2.3 Job to be done

“When my workers stop making progress, identify the dependency causing the blockage, recover it using supported operations, and show evidence that the affected work completed.”

### 2.4 User stories

| ID | Story | Successful outcome |
|---|---|---|
| US-01 | As an operator, I want to distinguish a resource deadlock from a slow task. | Only a qualifying resource cycle is labeled deadlocked. |
| US-02 | As an operator, I want to understand the proposed intervention. | I can inspect the selected worker, affected resources, preserved checkpoint, and expected lost work. |
| US-03 | As an operator, I want recovery to complete without editing locks manually. | The mediator initiates a supported action and affected workers resume. |
| US-04 | As an operator, I want unrelated work preserved. | Workers outside the recovery scope are not cancelled or restarted. |
| US-05 | As a reviewer, I want proof of the outcome. | I can open validated outputs and inspect the action record, SQL evidence, and result. |

## 3. Goals, success, and boundaries

### 3.1 MVP goals

1. Reproduce and detect resource cycles of length two and three.
2. Recover the canonical three-worker scenario through a real runner operation.
3. Use Exasol for cycle detection and recovery-candidate analysis.
4. Demonstrate a live LLM selecting among valid actions and adapting to one changed-state scenario.
5. Preserve completed checkpoints and unaffected work where the selected action allows it.
6. Produce inspectable artifacts and a reproducible evaluation report.

### 3.2 Release acceptance

The release passes when all P0 functional requirements and the acceptance suite in Section 14 pass. The canonical scenario must complete successfully in five consecutive live-mediator trials. All defined invalid-action and stale-state tests must reject execution. These are targets, not measured results.

### 3.3 Performance targets

| Metric | Initial target | Measurement boundary |
|---|---|---|
| Detection latency | Within 3 seconds after the configured persistence window | Complete Exasol snapshot available → incident detected |
| Recovery latency | Within 30 seconds on the canonical fixture | Incident detected → affected workers complete and artifacts validate |
| Interface refresh | Within 2 seconds of a runner state change | Runner event → rendered state |
| Mediator budget | At most 8 tool calls and 2 recovery-plan attempts per incident | Excludes deterministic verification polling |
| Recovery scope | No unrelated worker restarts | Compare worker attempt IDs before and after |

Measure and publish actual results on the demo machine. A missed latency target must be disclosed; it must not be hidden by speeding up an animation or replaying a previous model response as live.

### 3.4 Non-goals

- Operating-system deadlock recovery, arbitrary process termination, or kernel lock inspection.
- Universal undo for tool calls, emails, payments, or external side effects.
- Production cluster management, distributed consensus, or multi-tenant access control.
- General detection of livelocks, starvation, semantic disagreements, or all graph cycle lengths.
- Reconstructing missing telemetry or inventing recovery capabilities.
- Resuming an in-flight run after a backend process crash.
- Proving the LLM outperforms deterministic recovery policies in all settings.

## 4. Canonical demonstration

### 4.1 Workload

Three scripted worker agents operate on an immutable, seeded dataset. Each produces its own artifact independently. Their outputs do not depend on each other; the only cycle is in resource ownership.

| Worker | Job and output | Resource initially held | Resource requested next |
|---|---|---|---|
| Analyst A | Compute a summary CSV | Dataset session | Renderer slot |
| Reporter B | Build a preview HTML report | Renderer slot | Artifact slot |
| Packager C | Package a dataset snapshot and manifest | Artifact slot | Dataset session |

These are logical, exclusive, single-capacity resources implemented by the sandbox runner. They model poorly coordinated tool integrations. No real OS locks or cloud services are involved.

The fixture uses a synchronization barrier: each worker obtains its first resource before any requests its second. This creates a real persistent cycle in runner state, rather than a UI-only animation. The fixture and its intentionally conflicting acquisition policy are visible in the repository.

### 4.2 Recovery sequence

1. Workers reach the barrier and enter their resource waits.
2. Runner snapshots are written to Exasol.
3. SQL identifies A → B → C → A under the supported resource semantics.
4. The mediator inspects the workers' recovery capabilities and candidate costs.
5. In the default fixture, B has a verified checkpoint and a lower amount of non-checkpointed work than the other workers.
6. The mediator selects `yield_and_resume` for B and identifies the evidence supporting that choice.
7. The runner validates live ownership and versions, parks B, withdraws its pending request, and releases its held resource.
8. A acquires the renderer, completes its job, and releases its resources. C then completes.
9. B is admitted only when its full remaining resource set can be granted together. It resumes from its checkpoint and completes.
10. The verifier checks all three artifacts, terminal worker states, absence of remaining waits, and released leases.

Parking B is essential: immediate reacquisition could reproduce the same deadlock. Recovery must include controlled readmission, not only a release call.

### 4.3 Demonstration variants

- **Different least-cost candidate:** Change valid checkpoint placement so the mediator must inspect current evidence rather than always select B.
- **Stale plan:** Change an affected ownership version after planning. Reject the stale action and refresh the investigation.
- **Slow but healthy:** A worker progresses while another waits, with no cycle. Do not recover it.
- **No supported recovery:** All cycle members lack a permitted action. Keep the incident unresolved and explain the missing capability.

## 5. User experience

### 5.1 Single-screen layout

The desktop interface has four areas:

| Area | Required content |
|---|---|
| Run controls | Scenario selector, Start run, recovery status, Reset, live/replay label |
| Dependency graph | Worker and resource nodes, ownership edges, wait edges, highlighted incident cycle |
| Investigation panel | Plain-language diagnosis, evidence records, candidate comparison, chosen action, concise tool trace |
| Results panel | Worker progress, validated artifacts, recovery timing, preserved/lost work, unresolved issues |

Default to automatic recovery within the local scenario's preconfigured action policy. The operator authorizes that policy when starting the run; do not require approval for every tool call. Manual proposal review is a P1 option.

### 5.2 Interaction details

- Selecting a node shows current state, owned resources, pending requests, checkpoint status, and last progress time.
- Selecting a cycle shows its worker/resource sequence and Exasol snapshot ID.
- Selecting a recovery candidate shows why it is eligible and its estimated discarded work.
- Selecting an artifact opens the actual generated file or a validated preview.
- Reset ends the current demo session, stops its workers, and creates a fresh session. It does not silently rewrite the history of completed runs.
- Replay, if implemented, is prominently labeled and never counted as a live model trial.

### 5.3 Visual and accessibility requirements

Use readable labels and a graph legend. Distinguish running, waiting, recovering, complete, and unresolved states using text/icons as well as color. Keep keyboard access to controls and allow the event trace to be paused for reading. Show business-language explanations first, with SQL and structured records available on demand.

Do not display fabricated model reasoning or an animated thought stream. Display concise decisions, actual tool calls, returned evidence, and action results.

## 6. Functional requirements

P0 is required for submission. P1 is optional and must not delay P0 completion.

| ID | Priority | Requirement | Acceptance criterion |
|---|---|---|---|
| FR-01 | P0 | Run isolated, reproducible scenarios. | A seed and scenario configuration recreate the intended resource conditions; every session has a new ID. |
| FR-02 | P0 | Record ownership, waits, progress, checkpoints, and capabilities. | Every recovery decision is traceable to structured state. |
| FR-03 | P0 | Persist consistent snapshots in Exasol. | Detection reads only complete snapshots and never mixes rows from different snapshots. |
| FR-04 | P0 | Detect two- and three-worker cycles with SQL. | Returned cycles contain distinct workers and explicit resource edges, with rotational duplicates removed. |
| FR-05 | P0 | Avoid treating ordinary waiting as deadlock. | Acyclic waits, healthy progress, incomplete snapshots, and unsupported resource models do not trigger recovery. |
| FR-06 | P0 | Produce evidence-backed recovery candidates. | Each candidate names a current capability, supported worker, checkpoint if applicable, and estimated lost work. |
| FR-07 | P0 | Use a live model to investigate and select a plan. | Model tool calls and structured plan are saved; an invented candidate is rejected. |
| FR-08 | P0 | Execute allowlisted recovery operations. | Valid operations update real runner state, park the victim, and enable controlled readmission. |
| FR-09 | P0 | Reject stale execution and duplicate operations. | Ownership/version conflicts cause no mutation; repeated operation IDs do not repeat effects. |
| FR-10 | P0 | Verify actual task completion. | All affected outputs satisfy validators; affected workers are complete and their leases/waits are cleared. |
| FR-11 | P0 | Preserve unrelated work. | A worker outside the selected cycle retains its attempt and progress. |
| FR-12 | P0 | Bound unsuccessful recovery. | Tool/attempt/time budgets end in an explicit unresolved state rather than an infinite loop. |
| FR-13 | P0 | Show a live, inspectable product interface. | The operator can observe the incident, action, and validated artifacts without reading backend logs. |
| FR-14 | P0 | Export run evidence and evaluation results. | Export includes session, snapshot, selected plan, action outcomes, artifact checks, timings, and model/config identifiers. |
| FR-15 | P1 | Replay a completed run. | Replay is labeled and uses the recorded event sequence. |
| FR-16 | P1 | Require manual review before recovery. | The reviewed plan is revalidated against live state before execution. |
| FR-17 | P1 | Show historical strategy outcomes. | Exasol aggregates measured outcomes by scenario and recovery strategy, with sample counts. |
| FR-18 | P1 | Replace scripted worker policies with LLM workers. | Worker model calls are genuine and clearly labeled; reproducible evaluation fixtures remain available. |

## 7. Detection semantics

### 7.1 Supported deadlock model

Each resource has exactly one unit of exclusive capacity. Each blocked worker has one active request for an additional resource, retains its current resource while waiting, and cannot complete its current stage without the request. Requests have no automatic expiry or fallback during the canonical scenario. Completed and failed workers release their resources.

A wait-for edge X → Y exists when X has an active blocking request for a resource currently owned by Y in the same snapshot. Under these restricted semantics, a cycle is evidence of resource deadlock. The detector does not generalize this conclusion to shared locks, multi-capacity resources, optional requests, or jobs with alternate runnable paths.

### 7.2 Incident opening

Open an incident only when:

1. A two- or three-worker cycle exists in a complete snapshot.
2. The same cycle's ownership/wait configuration persists for the configured window, initially 2 seconds.
3. All participating workers remain blocked with no meaningful stage progress during that window.
4. The snapshot is fresh, initially no more than 2 seconds old.

Heartbeats do not count as meaningful progress. Stage completion or an increased completed-work counter does. Timing constants must be configurable for tests and recorded with evaluation results.

### 7.3 SQL responsibilities

Create a wait-edge view using the snapshot's ownership and request records. Use self-joins to enumerate length-two and length-three cycles and canonicalize their worker sequence. Join cycle membership with checkpoint/capability records to derive eligible interventions and estimated discarded work.

Implement and test SQL against Exasol itself. Do not compute the entire answer in Python and insert only the conclusion into the database. Python may format query results, validate invariants, and orchestrate actions.

## 8. Mediator and recovery policy

### 8.1 Responsibility split

| Component | Decides or performs |
|---|---|
| Exasol queries | Cycle membership, relevant state, candidate eligibility inputs, analytical comparison |
| Deterministic validator | Resource semantics, permissible actions, hard constraints, plan completeness |
| LLM mediator | Which evidence to inspect, which supported candidate to propose, explanation, replanning after conflicts |
| Runner | Live ownership validation, worker parking, resource release, retries, readmission |
| Verifier | Progress and artifact checks; final incident status |

The model cannot create capabilities or change success criteria. Worker descriptions and notes are data; they do not authorize tool execution. Numerical cost and progress calculations are supplied by code and SQL.

### 8.2 Selection objective

First satisfy hard constraints: target a cycle participant, preserve unrelated workers, use a declared operation, and operate before an irreversible boundary. Among feasible candidates, prefer the smallest estimated discarded work, then fewer interrupted workers, then the lower expected restart cost when measured data exists. Use a stable worker-ID tie-breaker if candidates remain equivalent.

For the MVP, a plan interrupts one worker. The mediator's rationale must reference evidence IDs. Unknown restart costs remain unknown; they must not become invented estimates. A valid checkpoint contributes only the work it has actually captured.

### 8.3 Supported operations

**`yield_and_resume`:** Available only at a declared cooperative checkpoint. Verify the checkpoint exists and belongs to the current attempt; park the worker, withdraw its outstanding request, release its leases, and queue it for readmission. Resume from that checkpoint when all its remaining resources can be acquired atomically.

**`restart_and_requeue`:** Available only for a sandbox worker with no committed external effects. Cooperatively stop the attempt, invalidate its temporary outputs, withdraw requests, release leases, and queue a fresh attempt. Never force-kill arbitrary processes or claim to reverse external effects.

The runner performs the validation and state transition under one application-level mutex. A checkpoint failure or inability to park must leave ownership unchanged. The first failure-injection implementation occurs before the mutation boundary so the behavior is deterministic and testable.

### 8.4 Retry and stop rules

- Allow one active recovery incident per demo session.
- On a stale-state conflict, read fresh evidence and permit one revised plan.
- On an uncertain response, query the existing operation ID before retrying.
- Do not retry an unsupported operation, wrong owner, or invalid checkpoint as though it were a temporary error.
- Stop after two plan attempts, eight mediator tool calls, or a 60-second incident budget.
- If no candidate is valid, transition to `UNRESOLVED` with the exact blocking capability or constraint.

## 9. State and consistency

### 9.1 Worker states

`QUEUED → RUNNING → WAITING → PARKED → QUEUED → RUNNING → COMPLETED`

Workers may also transition to `FAILED` or `CANCELLED` through declared operations. Waiting workers retain leases until normal completion or a validated recovery transition. A restart creates a new attempt ID; resuming a checkpoint retains the logical job identity.

### 9.2 Incident states

`DETECTED → INVESTIGATING → PLAN_READY → EXECUTING → VERIFYING → RESOLVED`

Execution conflicts return to `INVESTIGATING` within budget. Terminal failures go to `UNRESOLVED`. The absence of a cycle is necessary but insufficient for `RESOLVED`: affected jobs must finish and their output checks must pass.

### 9.3 Source of truth

The single-process runner owns live resource state. Exasol stores consistent analytical snapshots and durable evidence. Every decision carries a session epoch, snapshot ID, and relevant state versions. Before execution, the runner compares live ownership, request, capability, and checkpoint versions for the affected scope.

Unrelated progress must not invalidate a plan. Compare relevant versions rather than a global version that increments on every heartbeat. If the incident has already disappeared, return `ALREADY_CLEAR` and verify current state instead of making a stale intervention.

### 9.4 Snapshot and outage behavior

Capture a consistent runner snapshot, then persist its records and completion marker in one Exasol transaction. Detection selects only committed complete snapshots. Previous snapshots remain immutable for evidence.

If Exasol is unavailable or stale, do not begin a new recovery. Show “Telemetry unavailable” and allow workers already running to progress normally. Retain events in a bounded in-memory retry buffer; overflow marks an evidence gap and prevents a fully verified success claim. No evidence may be silently dropped.

The MVP does not guarantee recovery across backend crashes. A restart creates a new session epoch and marks previous active sessions interrupted. Old plans cannot execute in the new session. The UI provides an explicit fresh-run action.

## 10. Data model

These are logical tables; physical indexes, SQL types, and query tuning belong in implementation work.

| Table | Grain and required fields | Purpose |
|---|---|---|
| `RUNS` | One session: ID, epoch, scenario, seed, mode, start/end, status, model/config IDs | Reproducibility and honest live/replay labeling |
| `SNAPSHOTS` | One complete observation: ID, run, capture time, persisted time, complete flag | Consistent evidence boundary |
| `WORKER_STATE` | One worker per snapshot: worker/attempt, state, progress counter, stage version, checkpoint ID/version, completed and checkpointed work units | Progress and recovery eligibility |
| `RESOURCE_STATE` | One resource per snapshot: owner, lease ID/version, exclusive capacity | Ownership |
| `WAIT_REQUESTS` | One request per snapshot: requester, target resource, request ID/version, blocking flag, start time | Wait-for edges |
| `RECOVERY_CAPABILITIES` | One operation per worker per snapshot: operation, eligible flag, checkpoint reference, constraints, estimated lost work | Bounded action choices |
| `INCIDENTS` | One incident: run, cycle key, first/latest snapshot, status, chosen plan, outcome | Investigation lifecycle |
| `EVENTS` | One event: sequence, run/worker/incident, type, operation ID, time, structured payload | Actual tool/action history |
| `ARTIFACTS` | One validated output: run, job/attempt, logical output ID, path, hash, validator status | Outcome proof |

Use session IDs in every relevant join. Evidence payloads may use JSON text where convenient, but ownership, requests, and candidate fields must be directly queryable. Secrets and model credentials must never enter event payloads.

## 11. Tool and API contracts

These are proposed application contracts, not claims about existing Exasol tool names.

| Tool | Input | Output | Mutation |
|---|---|---|---|
| `inspect_incident` | Incident ID | Cycle evidence, snapshot freshness, worker/resource details | No |
| `list_recovery_candidates` | Incident ID, snapshot ID | Valid candidate IDs, capabilities, checkpoint references, calculated costs | No |
| `inspect_candidate` | Candidate ID | Detailed evidence, affected scope, version preconditions | No |
| `propose_recovery` | Incident, candidate, evidence IDs, concise rationale | Validated plan ID or structured rejection | Plan record only |
| `execute_recovery` | Plan ID, operation ID | Applied, rejected, already applied, or already clear | Yes, runner state |
| `get_operation` | Operation ID | Current/terminal result and affected attempt | No |
| `verify_incident` | Incident ID | Worker completion, resource checks, artifact checks, result | Verification record |

`execute_recovery` must not accept arbitrary SQL, shell commands, file paths, or model-supplied inverse operations. The plan resolves to a registered runner capability. For the process lifetime, an operation ID is bound to a plan and payload; reuse with a different payload is rejected.

Expose minimal operator endpoints for starting a scenario, fetching live state, streaming events, resetting a session, and exporting evidence. Server-sent events or simple polling are both acceptable. Avoid building a general workflow editor.

## 12. Implementation direction

### 12.1 Recommended shape

- One Python backend containing the runner, detector orchestration, mediator loop, and verifier.
- Exasol Personal running locally as the analytical database.
- PyExasol for typed backend queries and event/snapshot persistence.
- A lightweight browser interface with a graph and evidence panel; use the frontend stack the team already knows.
- One existing tool-calling model API, configured through environment variables.
- Local output files, scoped to each run directory.

These are architecture decisions for this MVP, not requirements to learn new libraries. The official Exasol MCP integration can supply analytical access if the team already has it working; it is P1 integration work if it delays the core typed tools. The current Exasol tool documentation describes SELECT execution, profiling, and a separate reviewed write path.[2] Runner recovery remains an application operation regardless of transport.

### 12.2 Output correctness

Use a fixed small input dataset and deterministic validators. The summary CSV must contain expected totals, the HTML report must reference the correct input hash and contain expected sections, and the package must contain the expected files and manifest. Each logical job publishes exactly one canonical output path.

Write temporary artifacts inside the run directory, validate them, then publish atomically through the runner's output registry. A restarted attempt must not overwrite a completed output from another job. A file's mere existence is not sufficient proof of success.

### 12.3 Exasol demonstration

Show the actual cycle query, input snapshot, result rows, and query duration. Show the query that compares candidate lost-work estimates. Export accumulated run outcomes for strategy comparison. A seeded historical dataset may be used for load demonstrations only when it is labeled synthetic and separated from actual evaluation trials.

No minimum large-data benchmark is required for the MVP. Correct analytical use on actual run records takes priority over generating millions of irrelevant events.

## 13. Evaluation and baselines

Compare identical scenario seeds and checkpoint configurations under:

1. **No recovery:** Establish persistent blocking during a fixed observation window; abort afterward and report timeout rather than an infinite completion time.
2. **Restart all affected workers:** Restart all cycle members and readmit them without recreating the same acquisition cycle. Count lost work.
3. **Deterministic least-cost recovery:** Select the least-cost valid candidate from the same structured evidence without an LLM.
4. **LLM-mediated recovery:** Use the live investigator and validated plan execution.

The deterministic baseline is important: a simple structured scenario may not benefit from an LLM. Report equal performance when it occurs. The product hypothesis is that a mediator can use contextual tool information and changing capabilities effectively; the MVP does not establish superiority unless the measurements show it.

Record completion rate, false interventions, recovery time, discarded work units, preserved checkpointed work, duplicate artifacts, unrelated restarts, SQL latency, model latency, and model calls. Discarded work equals completed work not captured in a reusable validated checkpoint at intervention. Do not count idle waiting or fabricated estimates as saved work.

## 14. Acceptance test suite

| ID | Scenario | Required assertion |
|---|---|---|
| AT-01 | Canonical three-worker cycle | Exasol identifies exactly one normalized cycle; a valid recovery produces all three validated outputs. |
| AT-02 | Two-worker cycle | Detection and recovery succeed without including unrelated workers. |
| AT-03 | Healthy long-running work | No cycle incident or recovery despite elapsed waiting time. |
| AT-04 | Temporary acyclic contention | Worker resumes normally; no mediator mutation. |
| AT-05 | Mixed or incomplete snapshot | Detector ignores incomplete data and never constructs a cycle across snapshot IDs. |
| AT-06 | Ownership changes after planning | Execution rejects the stale plan with no resource mutation; fresh planning stays within budget. |
| AT-07 | Duplicate operation or lost response | Operation lookup/retry does not repeat release, restart, or output publication. |
| AT-08 | Missing/invalid checkpoint | Yield action is rejected before parking or releasing resources. |
| AT-09 | Unsupported operation or invented candidate | Validator rejects it; no runner mutation. |
| AT-10 | Injected failure before action commit | Ownership stays intact; outcome is explicit and bounded. |
| AT-11 | No permissible recovery | Incident becomes unresolved with evidence; no arbitrary cancellation. |
| AT-12 | Victim attempts early reacquisition | Parked worker cannot reacquire a subset and recreate the original cycle. |
| AT-13 | Unrelated fourth worker | Its attempt and completed progress remain unchanged by recovery. |
| AT-14 | Corrupted or missing output | Incident is not marked resolved even if the cycle disappears. |
| AT-15 | Exasol unavailable | No new recovery starts; telemetry state is visible and any evidence gap is reported. |
| AT-16 | Backend restarts with an old plan | Epoch mismatch prevents execution; prior active session is interrupted. |
| AT-17 | Invalid model response or timeout | Limited retry or unresolved result; no substituted fake live response. |
| AT-18 | Least-cost candidate changes | New candidates reflect current checkpoints; recorded selection and costs are evaluated against the baseline. |

Run deterministic contract tests for all applicable cases. Separately run five live-mediator trials of AT-01 and at least one live stale-state and no-valid-action case. Save failures as well as successes in the evaluation report.

## 15. Delivery plan and ownership

| Time envelope | Work | Exit condition |
|---|---|---|
| Hours 0–2 | Confirm Exasol connection; implement resource ownership and canonical fixture | Real blocked cycle exists in runner state |
| Hours 2–6 | Snapshot tables, cycle SQL, checkpoint and recovery transitions | Deterministic recovery completes the three jobs |
| Hours 6–10 | Typed tools, model loop, plan validation, verification | Live mediator recovers canonical scenario |
| Hours 10–14 | Graph, investigation view, artifacts, scenario controls | Full product flow is visible |
| Hours 14–19 | Failure cases, baselines, live trials | P0 acceptance results recorded; material defects fixed |
| Hours 19–22 | README, run guide, pitch deck, clean-machine rehearsal | Teammate reproduces the workflow from instructions |
| Hours 22–24 | Demo recording, final packaging, submission buffer | Submission assets complete and checked |

For three people: one owns runner/recovery/verifier; one owns Exasol/detection/mediator; one owns UI/demo/documentation. With four or five, split data from mediator and assign a dedicated evaluation owner. All owners agree on snapshot fields and tool responses during the first two hours.

If deterministic recovery does not work by hour 6, simplify worker jobs and checkpoint handling before adding the model. If the complete live flow does not work by hour 10, cut all P1 features. Keep the failure checks that prevent misleading success; do not sacrifice them for graph animation.

## 16. Demo and submission

### 16.1 Three-minute recording

| Time | Content |
|---|---|
| 0:00–0:20 | Start a run and explain the three worker goals. |
| 0:20–0:45 | Show the blocked cycle and Exasol evidence. |
| 0:45–1:20 | Show the mediator inspecting candidates and selecting a checkpoint-preserving intervention. |
| 1:20–1:55 | Execute recovery; show workers completing and open validated artifacts. |
| 1:55–2:25 | Demonstrate a stale-plan rejection or a healthy wait that is left alone. |
| 2:25–3:00 | Present measured outcomes, Exasol's role, and the reproducible setup. |

### 16.2 Required repository contents

The event requests a public repository with a pitch deck, a demo of at most three minutes, README, and run instructions.[1] The project repository should also contain scenario fixtures, schema/query files, configuration examples without secrets, acceptance tests, and an evaluation-results file. Include this PRD or a repository copy as the product contract.

The README must explain which components are scripted, which use a live model, which resources are simulated, and which output artifacts are real. Package dependencies at tested versions and record the demo machine's relevant configuration. Do not claim automatic compatibility with external agent frameworks.

## 17. Risks and product decisions

| Risk | Decision |
|---|---|
| The model adds little beyond a deterministic scheduler | Include the deterministic least-cost baseline and report results candidly. |
| Telemetry describes an old ownership state | Use consistent snapshots plus live, scope-specific version validation. |
| Releasing a resource creates the same deadlock again | Park the victim and reacquire its remaining resource set together. |
| The fixture confuses resource and output dependencies | Workers independently consume immutable input; only logical resources form the cycle. |
| A graph looks resolved while work failed | Resolve only after worker completion, resource cleanup, and artifact validation. |
| Exasol becomes decorative storage | Execute detection and candidate analysis in Exasol and expose their results. |
| Broad recovery promises exceed implementation | Publish explicit supported runner operations and simulation boundaries. |
| Deadline pressure expands scope | Complete P0 before MCP expansion, model-driven workers, replay, or historical dashboards. |

## 18. Definition of done

- [ ] A fresh setup can start the canonical run with Exasol Personal connected.
- [ ] Exasol SQL detects supported cycles using complete snapshots.
- [ ] A live mediator proposes a valid recovery from actual returned evidence.
- [ ] The runner rejects invalid or stale actions and handles duplicate requests.
- [ ] Controlled readmission prevents recurrence of the canonical cycle.
- [ ] All affected jobs produce validated artifacts and release resources.
- [ ] Unrelated work remains intact.
- [ ] Failure states, model mode, simulation boundaries, and evidence gaps are visible.
- [ ] Acceptance tests and live-trial results are saved, including failures.
- [ ] No-recovery, restart, and deterministic least-cost baselines are documented.
- [ ] README, run guide, pitch deck, and demo video are complete.
- [ ] The product's claims match the measured implementation.

## References

1. Exasol. [Exasol AI + Data Challenge 2026](https://www.exasol.com/events/exasol-devjam/). Event constraints and submission requirements, checked September 12, 2026.
2. Exasol. [Exasol MCP Server Tools](https://exasol.github.io/mcp-server/main/user_guide/tool_list.html). Current documentation, checked September 12, 2026. Package capabilities must be checked against the version installed for implementation.

All architecture, requirement IDs, acceptance targets, tool contracts, and time allocations in this document are proposed product decisions. They are not benchmark results or statements that an implementation already exists.
