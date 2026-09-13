# DEADLOCK

A local dashboard for real Codex and Claude coding agents, plus an instrumented lab for detecting resource deadlocks and verifying recovery.

Implementation in progress. The product contract is in [docs/PRD.md](docs/PRD.md), and researched integration boundaries are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Development

Requires Python 3.11+, uv, and Node.js 22+.

```sh
uv sync
npm --prefix frontend install
npm --prefix frontend run build
uv run uvicorn deadlock.api:app --app-dir backend --host 127.0.0.1 --port 8765
```

Open http://127.0.0.1:8765. Configure optional integrations using `.env.example`. Runtime state, prompts, credentials, and local evidence are excluded from Git.
