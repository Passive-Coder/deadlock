# Implementation contract

DEADLOCK has two connected workspaces: real local coding agents, and an instrumented resource-recovery lab. Process CPU, RSS memory, working directories, children, and open files are observations. Open files are not exclusive locks. Resource ownership and wait edges come only from the instrumented runner.

The backend is a single-process FastAPI service on loopback. React renders real polled state. SQLite is the explicit development analytics engine; selecting Exasol uses PyExasol transactions and SQL on Exasol, and never silently falls back. Snapshots and relevant-scope version checks protect recovery. Artifacts are validated before publication and independently revalidated at incident resolution.

Codex sessions use the documented app-server protocol when a shared daemon is available. Standalone Codex/Claude CLI processes can be observed and explicitly adopted after identity checks; infrastructure and ancestors of DEADLOCK are protected. Managed runs use an executable allowlist, argv (no shell interpolation), scoped workspaces, bounded output, and real OS process controls. Pause suspends execution and retains resources. Stop is a termination request, not rollback. Resuming a saved conversation starts a new turn, not a frozen process.

## Interface direction

Visual thesis: a precise charcoal operations console, quiet dividers, warm white typography, and one lime accent. Content: agent/resource workspace first, selected-item inspector second, evidence and recovery lab on demand. Interaction: restrained view transitions, live status pulses, and an accessible inspector/modal reveal, all respecting reduced motion.

## Research ledger — 2026-09-13

- [Codex app-server](https://developers.openai.com/codex/app-server): JSON-RPC initialization, thread listing/read/resume, turn start/interrupt. Verified installed CLI `0.154.0-alpha.6.2` exposes `app-server proxy` for the shared daemon. A separate server does not automatically control another process's active turns.
- [Claude programmatic use](https://code.claude.com/docs/en/headless): `-p`, `stream-json --verbose`, `--resume`, structured output, SIGINT vs SIGTERM semantics. Installed CLI `2.1.216`; authentication absent at initial inspection.
- [PyExasol API](https://exasol.github.io/pyexasol/master/api.html): explicit transaction management and typed parameter formatting. Credentials and server availability are prerequisites to Exasol verification.
- [psutil](https://psutil.readthedocs.io/): process identity, CPU/RSS, child enumeration, suspend/resume, and access-denied handling. No inference of resource deadlock from low CPU or elapsed time.
- [Event brief](https://www.exasol.com/events/exasol-devjam/): submission reference from the supplied PRD.

## Release honesty

Local deterministic tests are not live-model tests. SQLite tests are not Exasol tests. Missing credentials, unsupported platform operations, and unavailable shared-daemon sessions appear as explicit integration limitations. Evaluation records include unsuccessful trials.
