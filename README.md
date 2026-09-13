# DEADLOCK

A local dashboard for actual Codex and Claude coding agents, with an instrumented lab for resource deadlock detection and verified recovery.

## Run locally

Requires macOS or Linux, Python 3.11+, [uv](https://docs.astral.sh/uv/), and Node.js 22+. Install and authenticate the Codex or Claude CLI to launch that provider. The dashboard and deterministic lab work without either CLI.

```sh
git clone https://github.com/Passive-Coder/deadlock.git
cd deadlock
./scripts/dev.sh
```

Open **http://127.0.0.1:8765**. The script installs locked dependencies, builds the frontend, and starts one local backend. Runtime data is stored in `.deadlock/` and excluded from Git. Copy `.env.example` to `.env` to customize configuration. `DEADLOCK_WORKSPACE_ROOTS` sets colon-separated allowed launch directories; it defaults to this repository.

For separate frontend development, run the backend and `npm --prefix frontend run dev`. Vite proxies `/api` to port 8765.

## Agent dashboard

The Agents view discovers same-user Codex/Claude CLI processes. It reports process-tree CPU, resident memory, workspace, children, and accessible open files. Select an agent for its inspector. CPU can exceed 100% when multiple cores are busy; the first sample is a warm-up. RSS sums may include shared pages, so totals are observations rather than exclusive physical-memory accounting.

| Agent connection | Supported behavior |
| --- | --- |
| Launched from DEADLOCK | Real CLI execution; streamed output; pause, resume, stop; continue a reported conversation ID after exit |
| Existing standalone CLI | Discover, inspect, explicitly adopt, then pause/resume/stop; its original terminal retains the output stream |
| Codex shared daemon | List/read sessions, continue a turn, interrupt an active turn through the documented app-server proxy, when an attachable daemon is available |
| Shared desktop runtime or parent process | Observe only; stopping a shared runtime could affect multiple tasks |

**Pause** suspends the visible process tree and keeps its resources. **Resume** continues those processes. **Stop** requests termination of the visible process tree and kills remaining processes after a three-second grace period; it is not a rollback. **Continue** starts a new turn in a saved conversation. These are distinct actions.

New launches default to read-only access. Workspace-write uses the provider's corresponding permission mode. Workspace roots restrict where DEADLOCK launches a process; they are not an operating-system sandbox. Claude tool permissions and Codex sandbox behavior remain provider-specific.

The installed desktop Codex runtime on the validation machine exposes only private stdio servers, so per-task shared-daemon control is unavailable there. Standalone Codex launch, pause, resume, stop, completion, and conversation reporting were tested against the actual CLI. Claude launch/error reporting was tested, but this machine has no Claude login, so a successful Claude model turn remains unverified. See [agent validation](docs/agent-validation.json).

## Recovery lab

Choose a scenario, seed, and strategy, then start a run. The graph, worker checkpoints, incident details, SQL evidence, tool trace, validators, and downloadable outputs all come from backend state.

The **worker policies are scripted**, making the resource cycle reproducible. The three resources are application-managed exclusive leases representing a dataset, renderer, and artifact writer. They are not claims about OS file locks. Workers do real data processing and write real validated CSV, HTML, and ZIP outputs. The live mediator makes genuine model calls; deterministic and restart-all strategies are explicitly labeled baselines.

Canonical cycle: A holds the dataset and waits for the renderer; B holds the renderer and waits for the artifact writer; C holds the writer and waits for the dataset. SQL identifies a complete, persistent, non-progressing cycle. B's valid checkpoint preserves 18 units and loses 3. Recovery parks B before releasing its lease, then readmits it only when all required leases can be acquired together.

The runner checks the current epoch, relevant versions, candidate registration, checkpoint identity/hash, operation ID, and declared capability before mutation. `RESOLVED` requires affected jobs to complete, output content/hash validators to pass, and leases/waits to clear. Eight tool calls, two proposals, and a 60-second incident budget bound recovery. SQL failure disables new recovery; it never switches engines silently.

Variants cover two-worker cycles, healthy work, acyclic contention, a changed least-cost candidate, unrelated work, missing capabilities, stale plans, and injected park failure. Manual proposal review is also available.

## Exasol

SQLite is the explicit default for an easy local start. To satisfy the Exasol workflow, select `DEADLOCK_DATABASE=exasol` and supply `EXASOL_DSN`, `EXASOL_USER`, `EXASOL_PASSWORD`, and `EXASOL_SCHEMA`. TLS is enabled; use a trusted certificate or a verified certificate fingerprint in the DSN. All snapshot writes and detection/candidate SQL then execute in Exasol.

See [Exasol setup](docs/EXASOL.md). The same recovery acceptance tests can run against either database. Do not run multiple backend instances against the same runtime directory. Use separate Exasol schemas for independent tests/evaluators to avoid competing transactions.

## Live mediator

The default live provider is the authenticated `codex` executable on `PATH`, run ephemerally with read-only sandboxing, structured JSON output, and low reasoning effort. Set `OPENAI_MODEL` to override its model. Alternatively set `DEADLOCK_MEDIATOR=openai`, `OPENAI_API_KEY`, and `OPENAI_MODEL` to use the Responses API. `DEADLOCK_MEDIATOR=disabled` prevents live calls. The UI's strategy selection determines whether any model is called.

Only the synthetic lab's structured candidate evidence is sent to the mediator. Process discovery is local. Explicit coding-agent prompts go to that provider. Credentials, runtime logs, and local run exports are excluded from Git; inspect exported agent logs before sharing them because redaction is best effort.

## Verify

```sh
uv sync --locked
DEADLOCK_DATABASE=sqlite uv run pytest -q
uv run ruff check backend tests scripts
npm --prefix frontend ci
npm --prefix frontend run build
# Real configured Exasol, separate schema recommended:
DEADLOCK_TEST_DATABASE=exasol EXASOL_SCHEMA=DEADLOCK_TEST uv run pytest -q
# Genuine model calls using the configured engine; consumes provider usage:
PYTHONPATH=backend uv run python scripts/evaluate.py --live --trials 5
```

See [evaluation results](docs/EVALUATION.md), [product requirements](docs/PRD.md), [research and architecture](docs/ARCHITECTURE.md), and [demo run guide](docs/DEMO.md). Measured results include failures and missed latency targets. A green local suite does not imply compatibility with every CLI version, operating system, or database release.

## Submission artifacts

- [Pitch deck](docs/DEADLOCK-pitch.pptx): six editable slides.
- [Recorded evidence walkthrough](docs/DEADLOCK-demo.mp4): 104.3 seconds, reconstructed from measured backend states and explicitly labeled.
- [Source evidence and sample outputs](docs/demo-evidence/manifest.json).

## Repository map

- `backend/deadlock/`: process adapters, SQL persistence, runner, mediator, HTTP API
- `frontend/`: React/TypeScript dashboard
- `sql/`: schema and actual detection/candidate queries
- `tests/`: recovery, lifecycle, and API contracts
- `scripts/`: startup and measured evaluation
- `docs/`: PRD, research, measured results, setup, and submission artifacts

This release is for a single local operator on macOS/Linux. It is not a remote multi-user service. It does not infer deadlocks from CPU inactivity, discover arbitrary framework leases, or automatically recover external coding-agent tool locks. Windows process controls, model-driven lab workers, replay UI, and Exasol historical aggregation are outside this release.
