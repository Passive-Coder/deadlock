# Measured validation — 2026-09-13

## Functional checks

- **44 local tests passed** on macOS / Python 3.11.5 with SQLite. These include the PRD's AT-01–AT-18 cases, real disposable process-tree signals, PID reuse protection, API boundaries, output corruption, stale/manual deadlines, and configuration defaults.
- **42 tests passed with real Exasol persistence and queries**. After the final refinements, eight agent/configuration checks and three affected recovery checks also passed against Exasol. Database failure cases intentionally inject an outage; their assertions verify rejection rather than successful persistence.
- GitHub Actions runs the test suite, Ruff, and the production frontend build on Ubuntu. The first Linux run exposed a race between requesting SIGKILL and observing exit. The implementation now waits for observed process exit; subsequent checks pass.
- Real Codex CLI launch, pause, resume, stop, successful completion, and reported conversation IDs were tested. A browser-driven launch/pause/resume flow also completed successfully. [Agent results](agent-validation.json).
- Claude's installed CLI returned a real authentication failure. Successful Claude model execution remains unverified until the operator logs in. Shared desktop Codex processes on this host do not expose an attachable daemon socket; the UI labels them observe-only.

## Exasol and live model trials

[Full final evaluation](evaluation.json), with every trial retained. The canonical live runs were five consecutive trials using `gpt-6-astra`, low reasoning effort, seed 42, a 2-second persistence window, 2-second evidence freshness, and a 60-second incident budget.

| Trial / strategy | Outcome | Recovery latency | Discarded work | Preserved checkpoint work |
| --- | --- | ---: | ---: | ---: |
| No recovery, fixed observation | Persistent cycle; timeout | — | 0 | 0 |
| Restart all affected | Completed, validated | 13.185 s | 63 | 0 |
| Deterministic least-cost | Completed, validated | 11.742 s | 3 | 18 |
| Different checkpoint placement | Completed; selected A | 18.195 s | 1 | 23 |
| Live canonical 1 | Completed, validated | 37.134 s | 3 | 18 |
| Live canonical 2 | Completed, validated | 42.384 s | 3 | 18 |
| Live canonical 3 | Completed, validated | 57.418 s | 3 | 18 |
| Live canonical 4 | Completed, validated | 59.037 s | 3 | 18 |
| Live canonical 5 | Completed, validated | 45.904 s | 3 | 18 |
| Live stale-plan retry | Unresolved at budget | 60.035 s | 0 | 0 |
| Live missing capability | Unresolved; no intervention | 10.417 s | 0 | 0 |

**5/5 canonical live runs validated all three outputs.** Each used two genuine model calls and four traced tool operations. All chose B based on current checkpoint evidence. No duplicate artifacts were published.

**Performance target missed:** canonical live recovery median was **45.904 s** (range 37.134–59.037 s); all five exceeded the PRD's 30-second recovery target. The deterministic policy was faster on this fixture. The results do not establish an LLM advantage.

The stale case rejected the first plan after an ownership-version change, then exhausted the incident budget during re-investigation. It did not report resolution. A separate faster-model trial using `gpt-5.3-codex-spark` returned a candidate outside the allowlist; the runner rejected it with zero mutation in 7.809 seconds. That [unsuccessful trial](evaluation-spark-stale.json) is also retained. Availability probes for Luna and Spark did not justify changing the default model.

The original healthy-work evaluation stopped at its 85-second harness limit, with **no incident and no intervention**. This workload deliberately processes one row per step, and SQL persistence plus host load slowed it down. The evaluator now allows 300 seconds for that scenario. The longer trial completed in **153.685 seconds**, validated all three outputs, and made **zero interventions**. Its [measured result](evaluation-healthy.json) is recorded separately; the original timeout remains in the full evaluation.

## Measurement scope

Recovery latency runs from incident detection to verified resolution or unresolved termination. It includes model calls, real runner execution, database latency, and validators. It does not include preparation before incident detection. Manual-review time is included in the same incident budget. The browser's successful manual run therefore is not a fair speed comparison with automatic recovery.

The report retains the last 30 SQL query durations per trial. The pooled p95 of those retained query samples was **308.454 ms**; this is a partial observation window, not a full-run or production p95. The app does not claim an unmeasured throughput target. Snapshots use batched rows within one transaction and become visible to detection only when marked complete.

Machine: macOS ARM64, Python 3.11.5, 16 GiB host RAM, 10 logical CPUs. Docker was limited to 2 CPUs and 4 GiB memory. The official ARM64 image `exasol/nano:2026.2.0-nano.2` reported `2026.2.0-dev.0`. TLS used a fingerprint verified from the local container certificate. Codex CLI was `0.154.0-alpha.6.2`; Claude CLI was `2.1.216`. The host was busy during benchmarks; this was not an isolated performance machine.

## Preserved earlier results

- [Initial SQLite live evaluation](evaluation-initial.json): 5/5 canonical success, four 30-second target misses, stale retry timeout.
- [Competing-schema attempt](evaluation-exasol-concurrent.json): snapshot persistence failure while independent writers competed. Tests and evaluators now use separate schemas.
- [Earlier Exasol baselines](evaluation-exasol-initial.json): completed measurements retained when the run was stopped to batch snapshot inserts.
- [Recorded demo evidence](demo-evidence/manifest.json): exact source runs, timestamps, event/tool traces, timelines, and example artifacts for the video.

The 104.3-second [demo video](DEADLOCK-demo.mp4) is explicitly a visualization reconstructed from recorded backend states, not browser footage. It preserves recorded timing within the shown segments and labels the stale-case excerpt. The six-slide [pitch deck](DEADLOCK-pitch.pptx) contains editable text and tables; package/layout checks passed and every rendered slide was inspected. Native PowerPoint/Google Slides application behavior was not tested.
