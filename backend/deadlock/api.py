import asyncio
from contextlib import asynccontextmanager, suppress
import json
import os
from pathlib import Path
import time
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .agents import AgentManager
from .analytics import Analytics
from .config import Settings
from .mediator import Mediator
from .runner import Rejection, Runner, SCENARIOS


class StartRun(BaseModel):
    scenario: str = "canonical"
    seed: int = Field(default=42, ge=0, le=2147483647)
    strategy: Literal["deterministic", "live", "none", "restart_all"] = "deterministic"
    auto_recover: bool = True


class LaunchAgent(BaseModel):
    provider: Literal["codex", "claude"]
    cwd: str = Field(max_length=4096)
    prompt: str = Field(min_length=1, max_length=30000)
    name: str | None = Field(default=None, max_length=100)
    resume: str | None = Field(default=None, max_length=100)
    access: Literal["read-only", "workspace-write"] = "read-only"


class ControlAgent(BaseModel):
    action: Literal["pause", "resume", "stop", "adopt", "interrupt", "continue"]
    prompt: str | None = Field(default=None, max_length=30000)


class ExecutePlan(BaseModel):
    plan_id: str = Field(max_length=100)
    operation_id: str = Field(min_length=8, max_length=100)


def create_app(settings=None):
    settings = settings or Settings()
    analytics = Analytics(settings)
    runner = Runner(settings, analytics)
    agents = AgentManager(settings)
    mediator = Mediator(runner)
    tasks = set()
    jobs = {"mediator": None}
    errors = []

    def spawn(coroutine):
        task = asyncio.create_task(coroutine)
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return task

    async def runner_loop():
        while True:
            try:
                await asyncio.to_thread(runner.tick)
                if runner.run and runner.run["incident"] and (not jobs["mediator"] or jobs["mediator"].done()):
                    jobs["mediator"] = spawn(mediator.investigate())
            except Exception as exc:
                errors.append({"time": time.time(), "component": "runner", "error": type(exc).__name__})
                del errors[:-20]
            await asyncio.sleep(0.2)

    async def process_loop():
        while True:
            try:
                await asyncio.to_thread(agents.discover)
            except Exception as exc:
                errors.append({"time": time.time(), "component": "process monitor", "error": type(exc).__name__})
                del errors[:-20]
            await asyncio.sleep(1)

    async def session_loop():
        while True:
            with suppress(Exception):
                await agents.bridge.refresh()
            await asyncio.sleep(8)

    @asynccontextmanager
    async def lifespan(app):
        spawn(runner_loop())
        spawn(process_loop())
        spawn(session_loop())
        yield
        for task in list(tasks):
            task.cancel()
        if tasks:
            await asyncio.gather(*list(tasks), return_exceptions=True)
        runner.stop()
        await agents.close()
        if analytics.db:
            analytics.db.close()

    app = FastAPI(title="DEADLOCK", version="0.1.0", lifespan=lifespan)
    app.state.runner, app.state.agents, app.state.mediator = runner, agents, mediator

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return JSONResponse({"detail": "DEADLOCK only serves loopback hosts"}, status_code=403)
        if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse({"detail": "DEADLOCK accepts local connections only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc not in {request.url.netloc, "127.0.0.1:5173", "localhost:5173"}:
            return JSONResponse({"detail": "Cross-origin access is not allowed"}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.headers.get("x-deadlock-control") != "1":
            return JSONResponse({"detail": "Missing local control header"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        if request.url.path.startswith("/api/runs/") and "/artifacts/" in request.url.path:
            response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
        return response

    @app.exception_handler(Rejection)
    async def rejection_handler(request, exc):
        return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=409)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0", "epoch": runner.epoch, "telemetry": analytics.status()}

    @app.get("/api/state")
    def state():
        with runner.lock:
            run = runner.state()
        return {"time": time.time(), "agents": [{k: v for k, v in a.items() if k != "logs"} for a in agents.list()],
                "host": agents.host, "run": run, "telemetry": analytics.status(), "errors": errors,
                "integrations": {"codex": agents.available["codex"], "claude": agents.available["claude"],
                                 "codex_sessions": agents.bridge.error, "mediator": settings.mediator},
                "roots": [str(p) for p in settings.roots], "scenarios": SCENARIOS, "events": list(agents.events)[-100:]}

    @app.post("/api/agents")
    async def launch(body: LaunchAgent):
        return await agents.launch(**body.model_dump())

    @app.get("/api/agents/{agent_id}")
    def agent_detail(agent_id: str):
        return agents.detail(agent_id)

    @app.post("/api/agents/{agent_id}/control")
    async def agent_control(agent_id: str, body: ControlAgent):
        try:
            return await agents.control(agent_id, body.action, body.prompt)
        except (RuntimeError, OSError, TimeoutError) as exc:
            raise HTTPException(409, str(exc)[:300]) from None

    @app.post("/api/runs")
    def start_run(body: StartRun):
        return runner.start(**body.model_dump())

    @app.post("/api/runs/stop")
    def stop_run():
        runner.stop()
        return runner.state()

    @app.get("/api/runs/history")
    def history():
        return runner.history()

    @app.get("/api/runs/evidence")
    def evidence():
        with runner.lock:
            return runner.export()

    @app.get("/api/runs/export")
    def export():
        with runner.lock:
            payload = runner.export()
        return JSONResponse(payload, headers={"Content-Disposition": 'attachment; filename="deadlock-evidence.json"'})

    @app.get("/api/runs/{run_id}/artifacts/{filename}")
    def artifact(run_id: str, filename: str):
        if not all(c.isalnum() or c == "-" for c in run_id) or Path(filename).name != filename:
            raise HTTPException(404, "Artifact not found")
        directory = settings.data_dir / "runs" / run_id
        try:
            saved = json.loads((directory / "state.json").read_text())
        except (OSError, ValueError):
            raise HTTPException(404, "Run not found") from None
        if filename not in {a["filename"] for a in saved["artifacts"]}:
            raise HTTPException(404, "Artifact not registered")
        target = (directory / filename).resolve()
        if not target.is_file() or directory.resolve() not in target.parents:
            raise HTTPException(404, "Artifact not found")
        return FileResponse(target)

    @app.get("/api/recovery/candidates")
    def candidates():
        with runner.lock:
            return runner.candidates() if runner.run else []

    @app.post("/api/recovery/investigate")
    async def investigate():
        if not runner.run or not runner.run["incident"] or runner.run["incident"]["status"] != "DETECTED":
            raise Rejection("INVALID_STATE", "No detected incident is awaiting investigation")
        if jobs["mediator"] and not jobs["mediator"].done():
            raise Rejection("BUSY", "Investigation is already running")
        jobs["mediator"] = spawn(mediator.investigate(force=True))
        return {"status": "INVESTIGATING"}

    @app.post("/api/recovery/execute")
    def execute(body: ExecutePlan):
        return runner.execute(body.plan_id, body.operation_id)

    @app.get("/api/recovery/operations/{operation_id}")
    def operation(operation_id: str):
        if operation_id not in runner.operations:
            raise HTTPException(404, "Operation not found")
        return runner.operations[operation_id]

    @app.post("/api/telemetry/reconnect")
    def reconnect():
        with runner.lock:
            if analytics.db:
                with suppress(Exception):
                    analytics.db.close()
            analytics.connect()
            while runner.pending and analytics.available:
                if analytics.snapshot(runner.pending[0]):
                    runner.pending.popleft()
                else:
                    break
            return analytics.status()

    @app.get("/api/events")
    async def events(request: Request):
        async def stream():
            last = None
            while not await request.is_disconnected():
                payload = json.dumps({"agents": list(agents.events)[-30:], "runner": runner.run["events"][-30:] if runner.run else []})
                if payload != last:
                    yield "data: " + payload + "\n\n"
                    last = payload
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type="text/event-stream")

    build = Path(__file__).resolve().parents[2] / "frontend" / "dist"

    @app.get("/{path:path}")
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "API route not found")
        target = (build / path).resolve()
        if build.resolve() not in target.parents or not target.is_file():
            target = build / "index.html"
        if not target.is_file():
            return JSONResponse({"detail": "Build the dashboard with npm --prefix frontend run build"}, status_code=503)
        return FileResponse(target)

    return app


app = create_app()


def main():
    import uvicorn
    host = os.getenv("DEADLOCK_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("DEADLOCK_HOST must be loopback")
    uvicorn.run(app, host=host, port=int(os.getenv("DEADLOCK_PORT", "8765")))


if __name__ == "__main__":
    main()
