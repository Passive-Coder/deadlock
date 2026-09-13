"""Measured evaluation. Live trials make genuine model calls; failures are retained."""

import argparse
import asyncio
import json
from pathlib import Path
import platform
import subprocess
import time

from deadlock.analytics import Analytics
from deadlock.config import Settings
from deadlock.mediator import Mediator
from deadlock.runner import Runner


async def trial(settings, scenario, strategy, seed):
    analytics = Analytics(settings)
    runner = Runner(settings, analytics)
    runner.start(scenario, seed, strategy)
    mediator = Mediator(runner)
    task = None
    started = time.time()
    try:
        while time.time() - started < 85:
            await asyncio.to_thread(runner.tick)
            incident = runner.run["incident"]
            if incident and task is None and strategy != "none":
                task = asyncio.create_task(mediator.investigate())
            if runner.run["status"] != "RUNNING" or (incident and incident["status"] == "UNRESOLVED"):
                break
            if strategy == "none" and time.time() - started > 10:
                break
            await asyncio.sleep(0.2)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        incident = runner.run["incident"]
        result = {
            "run_id": runner.run["id"],
            "scenario": scenario,
            "strategy": strategy,
            "seed": seed,
            "engine": analytics.kind,
            "telemetry_available": analytics.available,
            "status": runner.run["status"]
            if runner.run["status"] != "RUNNING"
            else ("TIMEOUT" if strategy == "none" else "UNRESOLVED"),
            "incident_status": incident["status"] if incident else None,
            "reason": incident["reason"] if incident else analytics.error,
            "duration_seconds": round(time.time() - started, 3),
            "recovery_seconds": round(incident["ended"] - incident["detected"], 3)
            if incident and incident["ended"]
            else None,
            "discarded_work": runner.run["discarded_work"],
            "preserved_work": runner.run["preserved_work"],
            "artifact_count": len(runner.run["artifacts"]),
            "validated": bool(incident and incident["verification"] and incident["verification"]["valid"]),
            "model": incident["model"] if incident else None,
            "model_latency_ms": incident["model_latency_ms"] if incident else 0,
            "model_calls": incident.get("model_calls", 0) if incident else 0,
            "tool_calls": incident["tool_calls"] if incident else 0,
            "plan_attempts": incident["attempts"] if incident else 0,
            "selected_worker": incident["plan"]["candidate"]["worker_id"]
            if incident and incident["plan"]
            else None,
            "sql_query_ms": [q["duration_ms"] for q in analytics.queries],
            "evidence_gap": runner.run["evidence_gap"],
            "config": runner.run["config"],
        }
        (runner.directory / "evaluation-evidence.json").write_text(json.dumps(runner.export(), indent=2))
        runner.stop()
        return result
    finally:
        if analytics.db:
            analytics.db.close()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--output", default="docs/evaluation.json")
    args = parser.parse_args()
    settings = Settings(data_dir=Path(".deadlock/evaluation").resolve())
    configurations = [
        ("canonical", "none"),
        ("canonical", "restart_all"),
        ("canonical", "deterministic"),
        ("changed_candidate", "deterministic"),
        ("healthy", "deterministic"),
    ]
    if args.live:
        configurations += [("canonical", "live")] * args.trials + [
            ("stale_plan", "live"),
            ("no_recovery", "live"),
        ]
    output = Path(args.output)
    report = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "machine": {
            "os": platform.system(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "live_trials_requested": args.live,
        "exasol_verified": False,
        "trials": [],
    }
    try:
        report["codex_version"] = subprocess.check_output(["codex", "--version"], text=True).strip()
    except (OSError, subprocess.SubprocessError):
        report["codex_version"] = None
    for scenario, strategy in configurations:
        result = await trial(settings, scenario, strategy, 42)
        report["trials"].append(result)
        report["exasol_verified"] = settings.database == "exasol" and any(
            r["validated"] for r in report["trials"]
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in [
                        "scenario",
                        "strategy",
                        "status",
                        "incident_status",
                        "recovery_seconds",
                        "model",
                        "reason",
                    ]
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
