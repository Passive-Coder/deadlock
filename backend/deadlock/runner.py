from collections import deque
from copy import deepcopy
from functools import wraps
import json
import threading
import time
from uuid import uuid4

from . import artifacts


def uid():
    return str(uuid4())


SCENARIOS = {
    "canonical": "Three-agent deadlock",
    "two_cycle": "Two-agent deadlock",
    "healthy": "Slow, healthy work",
    "contention": "Temporary contention",
    "changed_candidate": "Different checkpoint costs",
    "unrelated": "Preserve unrelated work",
    "no_recovery": "No supported recovery",
    "stale_plan": "Ownership changes after planning",
    "failure": "Failure before action commit",
}
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


class Rejection(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def synchronized(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)

    return locked


class Runner:
    def __init__(self, settings, analytics):
        self.settings, self.analytics = settings, analytics
        self.epoch = uid()
        self.lock = threading.RLock()
        self.run = None
        self.plans, self.operations = {}, {}
        self.candidate_records = {}
        self.snap = None
        self.persisted = None
        self.cycle_since = {}
        self.pending = deque(maxlen=32)
        self.last_snapshot = 0.0
        self.interrupted = []
        for path in (settings.data_dir / "runs").glob("*/state.json"):
            try:
                previous = json.loads(path.read_text())
                if previous["status"] == "RUNNING":
                    previous["status"] = "INTERRUPTED"
                    previous["ended"] = time.time()
                    path.write_text(json.dumps(previous))
                    self.interrupted.append(previous["id"])
            except (OSError, ValueError, KeyError):
                continue

    @property
    def directory(self):
        return self.settings.data_dir / "runs" / self.run["id"]

    @synchronized
    def event(self, kind, message, **data):
        event = {
            "seq": self.run["event_count"] + 1,
            "time": time.time(),
            "type": kind,
            "message": message,
            **data,
        }
        self.run["event_count"] += 1
        self.run["events"].append(event)
        self.run["events"] = self.run["events"][-500:]
        with (self.directory / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(event) + "\n")
        return event

    @synchronized
    def save(self):
        temporary = self.directory / "state.tmp"
        temporary.write_text(json.dumps(self.run))
        temporary.replace(self.directory / "state.json")

    def start(self, scenario="canonical", seed=42, strategy="deterministic", auto_recover=True):
        with self.lock:
            if scenario not in SCENARIOS or strategy not in {"deterministic", "live", "none", "restart_all"}:
                raise Rejection("INVALID_CONFIGURATION", "Unknown scenario or recovery strategy")
            if self.run and self.run["status"] == "RUNNING":
                self.stop()
            self.run = {
                "id": uid(),
                "epoch": self.epoch,
                "scenario": scenario,
                "seed": seed,
                "strategy": strategy,
                "auto_recover": auto_recover,
                "mode": "scripted workers / logical resources",
                "started": time.time(),
                "ended": None,
                "status": "RUNNING",
                "workers": [],
                "resources": [],
                "incident": None,
                "artifacts": [],
                "events": [],
                "event_count": 0,
                "evidence_gap": False,
                "discarded_work": 0,
                "preserved_work": 0,
                "barrier_open": False,
                "config": {
                    "persistence_seconds": self.settings.persistence,
                    "freshness_seconds": self.settings.freshness,
                    "incident_budget_seconds": self.settings.incident_budget,
                    "sql_engine": self.analytics.kind,
                    "mediator": self.settings.mediator,
                    "mediator_reasoning_effort": "low",
                },
                "failure_injected": False,
            }
            self.directory.mkdir(parents=True, mode=0o700)
            rows = artifacts.dataset(seed)
            (self.directory / "input.csv").write_bytes(artifacts.csv_bytes(rows))
            self.rows = rows
            count = 2 if scenario == "two_cycle" else 3
            names = ["Dataset session", "Renderer slot", "Artifact slot"][:count]
            for index, name in enumerate(names):
                self.run["resources"].append(
                    {
                        "id": f"r{index}",
                        "name": name,
                        "owner": None,
                        "version": 0,
                        "capacity": 1,
                        "exclusive": True,
                    }
                )
            for index in range(count + int(scenario == "unrelated")):
                worker_id = "ABCD"[index]
                checkpoint = [8, 18, 4, 0][index]
                if scenario == "changed_candidate":
                    checkpoint = [23, 2, 4, 0][index]
                needs = [f"r{index}", f"r{(index + 1) % count}"] if index < count else []
                if scenario in {"healthy", "contention"}:
                    needs = ["r0"]
                self.run["workers"].append(
                    {
                        "id": worker_id,
                        "name": ["Analyst", "Reporter", "Packager", "Audit"][index] + f" {worker_id}",
                        "kind": ["summary", "report", "package", "audit"][index],
                        "attempt": uid(),
                        "state": "QUEUED",
                        "progress": 0,
                        "total": len(rows),
                        "computed_total": 0,
                        "prepared_work": [24, 21, 18, 60][index],
                        "checkpoint_at": checkpoint,
                        "checkpoint_id": None,
                        "checkpoint_version": 0,
                        "checkpoint_work": 0,
                        "checkpoint_hash": None,
                        "version": 0,
                        "request_version": 0,
                        "capability_version": 1,
                        "waiting": None,
                        "needs": needs,
                        "atomic": False,
                        "last_progress": time.time(),
                        "capabilities": []
                        if scenario == "no_recovery"
                        else ["yield_and_resume", "restart_and_requeue"],
                    }
                )
            self.snap, self.persisted = None, None
            self.cycle_since.clear()
            self.pending.clear()
            self.last_snapshot = 0
            self.event("run.started", f"Started {SCENARIOS[scenario]}", strategy=strategy, seed=seed)
            self.save()
            return self.state()

    def worker(self, wid):
        return next(w for w in self.run["workers"] if w["id"] == wid)

    def resource(self, rid):
        return next(r for r in self.run["resources"] if r["id"] == rid)

    def transition(self, w, state):
        if w["state"] != state:
            w["state"] = state
            w["version"] += 1

    def request(self, w, rid):
        if w["waiting"] != rid:
            w["waiting"] = rid
            w["request_version"] += 1
            if rid:
                self.event(
                    "resource.wait",
                    f"{w['name']} is waiting for {self.resource(rid)['name']}",
                    worker_id=w["id"],
                )

    def acquire(self, w, resources):
        if any(self.resource(r)["owner"] not in {None, w["id"]} for r in resources):
            return False
        for rid in resources:
            r = self.resource(rid)
            if r["owner"] is None:
                r["owner"] = w["id"]
                r["version"] += 1
                self.event(
                    "resource.acquired",
                    f"{w['name']} acquired {r['name']}",
                    worker_id=w["id"],
                    resource_id=rid,
                )
        self.request(w, None)
        return True

    def release(self, w):
        self.request(w, None)
        for r in self.run["resources"]:
            if r["owner"] == w["id"]:
                r["owner"] = None
                r["version"] += 1

    def work(self, w, limit, units=3):
        for _ in range(units):
            if w["progress"] >= limit:
                break
            w["computed_total"] += self.rows[w["progress"]]["amount"]
            w["progress"] += 1
            w["version"] += 1
            w["last_progress"] = time.time()
            if w["progress"] == w["checkpoint_at"] and not w["checkpoint_id"]:
                w["checkpoint_id"] = uid()
                w["checkpoint_work"] = w["progress"]
                w["checkpoint_version"] += 1
                payload = json.dumps(
                    {
                        "attempt": w["attempt"],
                        "progress": w["progress"],
                        "computed_total": w["computed_total"],
                    }
                ).encode()
                (self.directory / f"checkpoint-{w['checkpoint_id']}.json").write_bytes(payload)
                w["checkpoint_hash"] = artifacts.digest(payload)
                self.event(
                    "checkpoint.saved",
                    f"{w['name']} checkpointed {w['progress']} work units",
                    worker_id=w["id"],
                )

    def advance(self):
        cycle_fixture = self.run["scenario"] not in {"healthy", "contention"}
        members = [w for w in self.run["workers"] if w["needs"]]
        if (
            cycle_fixture
            and not self.run["barrier_open"]
            and all(w["progress"] >= w["prepared_work"] for w in members)
        ):
            self.run["barrier_open"] = True
            self.event("barrier.open", "All workers hold their first resource; requesting the next resource")
        for w in self.run["workers"]:
            if w["state"] in TERMINAL:
                continue
            if w["state"] == "PARKED":
                if not self.acquire(w, w["needs"]):
                    continue
                self.transition(w, "RUNNING")
                self.event(
                    "worker.readmitted",
                    f"{w['name']} acquired all remaining resources together",
                    worker_id=w["id"],
                )
            if w["state"] == "QUEUED":
                if not self.acquire(w, w["needs"][:1]):
                    self.request(w, w["needs"][0])
                    continue
                self.transition(w, "RUNNING")
            preparing = cycle_fixture and not self.run["barrier_open"] and bool(w["needs"])
            if preparing:
                self.work(w, w["prepared_work"])
                continue
            if not self.acquire(w, w["needs"]):
                target = next(r for r in w["needs"] if self.resource(r)["owner"] not in {None, w["id"]})
                self.request(w, target)
                self.transition(w, "WAITING")
                continue
            self.transition(w, "RUNNING")
            self.work(w, w["total"], 1 if self.run["scenario"] == "healthy" else 6)
            if w["progress"] == w["total"]:
                try:
                    if w["computed_total"] != sum(row["amount"] for row in self.rows):
                        raise ValueError("Computed work does not match input")
                    self.run["artifacts"].append(artifacts.publish(self.directory, w, self.rows))
                    self.transition(w, "COMPLETED")
                    self.event(
                        "worker.completed", f"{w['name']} published a validated output", worker_id=w["id"]
                    )
                except (ValueError, OSError) as exc:
                    self.transition(w, "FAILED")
                    self.event("worker.failed", str(exc), worker_id=w["id"])
                self.release(w)

    @synchronized
    def snapshot(self):
        return {
            "id": uid(),
            "run_id": self.run["id"],
            "epoch": self.epoch,
            "captured": time.time(),
            "workers": deepcopy(self.run["workers"]),
            "resources": deepcopy(self.run["resources"]),
        }

    @synchronized
    def refresh_snapshot(self):
        snap = self.snapshot()
        if not self.analytics.snapshot(snap):
            raise Rejection("TELEMETRY_UNAVAILABLE", "Cannot refresh complete recovery evidence")
        self.persisted = snap
        return snap

    def detect(self, snap, now=None):
        now = time.time() if now is None else now
        if now - snap["captured"] > self.settings.freshness or not self.analytics.available:
            return []
        rows = self.analytics.query("cycles.sql", snap)
        qualifying, present = [], set()
        for row in rows:
            members = [row[k] for k in ("a", "b", "c") if row[k]]
            resources = [row[k] for k in ("ra", "rb", "rc") if row[k]]
            ws = [w for w in snap["workers"] if w["id"] in members]
            rs = [r for r in snap["resources"] if r["id"] in resources]
            if any(w["state"] != "WAITING" for w in ws):
                continue
            key = "→".join(members)
            signature = json.dumps(
                [
                    [(w["id"], w["attempt"], w["progress"], w["waiting"], w["request_version"]) for w in ws],
                    [(r["id"], r["owner"], r["version"]) for r in rs],
                ]
            )
            present.add(key)
            previous = self.cycle_since.get(key)
            if previous is None or previous[1] != signature:
                self.cycle_since[key] = (now, signature)
                continue
            if now - previous[0] >= self.settings.persistence and all(
                now - w["last_progress"] >= self.settings.persistence for w in ws
            ):
                qualifying.append(
                    {
                        "key": key,
                        "members": members,
                        "resources": resources,
                        "snapshot_id": snap["id"],
                        "first_seen": previous[0],
                    }
                )
        self.cycle_since = {k: v for k, v in self.cycle_since.items() if k in present}
        return qualifying

    def tick(self):
        with self.lock:
            if not self.run or self.run["status"] != "RUNNING":
                return
            self.advance()
            now = time.time()
            if now - self.last_snapshot >= self.settings.snapshot_interval:
                self.last_snapshot = now
                self.snap = self.snapshot()
                if self.analytics.snapshot(self.snap):
                    self.persisted = self.snap
                    try:
                        cycles = self.detect(self.snap)
                    except Exception as exc:
                        self.analytics.available = False
                        self.analytics.error = f"Detection query failed ({type(exc).__name__})"
                        cycles = []
                    if cycles and not self.run["incident"]:
                        cycle = cycles[0]
                        self.run["incident"] = {
                            "id": uid(),
                            **cycle,
                            "status": "DETECTED",
                            "detected": now,
                            "ended": None,
                            "attempts": 0,
                            "tool_calls": 0,
                            "trace": [],
                            "plan": None,
                            "verification": None,
                            "reason": None,
                            "model": None,
                            "model_latency_ms": 0,
                            "model_calls": 0,
                        }
                        self.event(
                            "incident.detected",
                            "Persistent resource cycle detected: " + cycle["key"],
                            snapshot_id=self.snap["id"],
                        )
                else:
                    if len(self.pending) == self.pending.maxlen:
                        self.run["evidence_gap"] = True
                    self.pending.append(self.snap)
            incident = self.run["incident"]
            if incident:
                if incident["status"] in {"EXECUTING", "VERIFYING"}:
                    self.verify()
                if (
                    incident["status"] not in {"RESOLVED", "UNRESOLVED"}
                    and now - incident["detected"] > self.settings.incident_budget
                ):
                    self.unresolved("Incident exceeded the configured time budget")
            if all(w["state"] in TERMINAL for w in self.run["workers"]):
                if incident and incident["status"] not in {"RESOLVED", "UNRESOLVED"}:
                    self.verify()
                self.run["status"] = (
                    "COMPLETED" if all(w["state"] == "COMPLETED" for w in self.run["workers"]) else "FAILED"
                )
                if incident and incident["status"] != "RESOLVED":
                    self.run["status"] = "FAILED"
                self.run["ended"] = time.time()
                self.event("run.finished", f"Run {self.run['status'].lower()}")
                if not self.analytics.record(self.run["id"], "run", self.export()):
                    self.run["evidence_gap"] = True
                    if incident:
                        self.unresolved("Final evidence could not be persisted")
                        self.run["status"] = "FAILED"
            self.save()

    @synchronized
    def candidates(self):
        incident = self.run["incident"]
        if not incident or not self.persisted or not self.analytics.available:
            return []
        if time.time() - self.persisted["captured"] > self.settings.freshness:
            raise Rejection("STALE_TELEMETRY", "No fresh complete snapshot is available")
        rows = self.analytics.query("candidates.sql", self.persisted)
        result = [
            {
                **r,
                "id": f"{self.persisted['id']}:{r['worker_id']}:{r['operation']}",
                "snapshot_id": self.persisted["id"],
                "evidence_id": f"candidate:{r['worker_id']}:{r['operation']}",
            }
            for r in rows
            if r["worker_id"] in incident["members"]
        ]
        for candidate in result:
            self.candidate_records[candidate["id"]] = {
                "candidate": deepcopy(candidate),
                "scope": self.scope(incident["members"]),
            }
        if len(self.candidate_records) > 500:
            self.candidate_records = dict(list(self.candidate_records.items())[-250:])
        return result

    @synchronized
    def scope(self, members):
        return {
            "workers": [
                {
                    k: w[k]
                    for k in [
                        "id",
                        "attempt",
                        "version",
                        "request_version",
                        "capability_version",
                        "checkpoint_id",
                        "checkpoint_version",
                        "checkpoint_hash",
                    ]
                }
                for w in self.run["workers"]
                if w["id"] in members
            ],
            "resources": [
                {k: r[k] for k in ["id", "owner", "version", "capacity", "exclusive"]}
                for r in self.run["resources"]
                if r["id"] in self.run["incident"]["resources"]
            ],
        }

    def propose(self, candidate, evidence_ids, rationale):
        with self.lock:
            incident = self.run["incident"]
            registered = self.candidate_records.get(candidate.get("id"))
            if not registered or registered["candidate"] != candidate:
                raise Rejection("INVALID_CANDIDATE", "Candidate is not in the current allowlist")
            valid = registered["candidate"]
            if registered["scope"] != self.scope(incident["members"]):
                raise Rejection("STALE_PLAN", "Candidate evidence changed; inspect fresh evidence")
            if valid["evidence_id"] not in evidence_ids:
                raise Rejection("MISSING_EVIDENCE", "Rationale must cite the selected candidate evidence")
            if incident["attempts"] >= 2:
                raise Rejection("ATTEMPT_BUDGET", "Recovery plan budget exhausted")
            plan = {
                "id": uid(),
                "run_id": self.run["id"],
                "epoch": self.epoch,
                "incident_id": incident["id"],
                "candidate": valid,
                "scope": self.scope(incident["members"]),
                "evidence_ids": evidence_ids,
                "rationale": rationale[:2000],
                "created": time.time(),
            }
            self.plans[plan["id"]] = plan
            incident["plan"] = plan
            incident["attempts"] += 1
            incident["status"] = "PLAN_READY"
            self.event(
                "plan.proposed",
                f"Proposed {valid['operation']} for {valid['worker_id']}",
                plan_id=plan["id"],
                rationale=rationale[:2000],
            )
            return plan

    def checkpoint(self, w):
        try:
            raw = (self.directory / f"checkpoint-{w['checkpoint_id']}.json").read_bytes()
            saved = json.loads(raw)
            valid = artifacts.digest(raw) == w["checkpoint_hash"] and saved["attempt"] == w["attempt"]
            valid = valid and saved["progress"] == w["checkpoint_work"]
            valid = valid and saved["computed_total"] == sum(
                r["amount"] for r in self.rows[: saved["progress"]]
            )
            if not valid:
                raise ValueError()
            return saved
        except (OSError, ValueError, KeyError, TypeError):
            raise Rejection(
                "INVALID_CHECKPOINT", "Checkpoint is missing, corrupted, or belongs to another attempt"
            ) from None

    def restart_all(self, operation_id):
        """Evaluation baseline: cooperatively restart only the affected sandbox workers."""
        with self.lock:
            incident = self.run["incident"]
            if self.run["strategy"] != "restart_all" or incident["status"] != "INVESTIGATING":
                raise Rejection("INVALID_STATE", "Restart-all is available only in its evaluation baseline")
            if (
                not self.analytics.available
                or not self.persisted
                or time.time() - self.persisted["captured"] > self.settings.freshness
            ):
                raise Rejection("TELEMETRY_UNAVAILABLE", "Fresh telemetry is required")
            members = [self.worker(wid) for wid in incident["members"]]
            if any(
                "restart_and_requeue" not in w["capabilities"] or w["state"] != "WAITING" for w in members
            ):
                raise Rejection(
                    "UNSUPPORTED_OPERATION", "All affected workers must support cooperative restart"
                )
            lost = sum(w["progress"] for w in members)
            for w in members:
                self.transition(w, "PARKED")
                self.release(w)
                w["attempt"] = uid()
                w["progress"], w["computed_total"] = 0, 0
                w["checkpoint_id"], w["checkpoint_hash"], w["checkpoint_work"] = None, None, 0
                w["checkpoint_version"] += 1
                w["atomic"] = True
            self.run["discarded_work"] += lost
            incident["status"] = "VERIFYING"
            incident["attempts"] = 1
            incident["model"] = "deterministic restart-all baseline"
            result = {
                "status": "APPLIED",
                "operation_id": operation_id,
                "workers": incident["members"],
                "lost_work": lost,
                "preserved_work": 0,
            }
            self.event(
                "baseline.applied",
                "Cooperatively restarted all affected workers with atomic readmission",
                **result,
            )
            return result

    def execute(self, plan_id, operation_id, fail_before_commit=False):
        with self.lock:
            if operation_id in self.operations:
                result = self.operations[operation_id]
                if result["plan_id"] != plan_id:
                    raise Rejection("OPERATION_ID_REUSED", "Operation ID is already bound to another plan")
                return {**result, "duplicate": True}
            plan = self.plans.get(plan_id)
            if not plan or plan["epoch"] != self.epoch or plan["run_id"] != self.run["id"]:
                raise Rejection("EPOCH_MISMATCH", "Plan does not belong to this active session epoch")
            incident = self.run["incident"]
            if incident["id"] != plan["incident_id"] or incident["status"] not in {
                "PLAN_READY",
                "INVESTIGATING",
            }:
                raise Rejection("INVALID_STATE", "Incident cannot execute a recovery in its current state")
            if (
                not self.analytics.available
                or not self.persisted
                or time.time() - self.persisted["captured"] > self.settings.freshness
            ):
                raise Rejection(
                    "TELEMETRY_UNAVAILABLE", "Fresh complete telemetry is required before recovery"
                )
            if self.run["evidence_gap"]:
                raise Rejection("EVIDENCE_GAP", "Telemetry buffer overflow prevents verified recovery")
            members = incident["members"]
            still_blocked = all(
                self.worker(wid)["state"] == "WAITING"
                and self.worker(wid)["waiting"] is not None
                and self.resource(self.worker(wid)["waiting"])["owner"] == members[(index + 1) % len(members)]
                for index, wid in enumerate(members)
            )
            if not still_blocked:
                result = {
                    "status": "ALREADY_CLEAR",
                    "operation_id": operation_id,
                    "plan_id": plan_id,
                    "time": time.time(),
                }
                self.operations[operation_id] = result
                incident["status"] = "VERIFYING"
                self.event(
                    "recovery.already_clear",
                    "Original cycle cleared before execution; verifying outputs",
                    **result,
                )
                self.verify()
                return result
            if self.scope(incident["members"]) != plan["scope"]:
                raise Rejection(
                    "STALE_PLAN", "Relevant ownership, request, checkpoint, or capability changed"
                )
            candidate = plan["candidate"]
            w = self.worker(candidate["worker_id"])
            op = candidate["operation"]
            if (
                w["id"] not in incident["members"]
                or op not in w["capabilities"]
                or op not in {"yield_and_resume", "restart_and_requeue"}
            ):
                raise Rejection("UNSUPPORTED_OPERATION", "Worker does not declare this operation")
            saved = self.checkpoint(w) if op == "yield_and_resume" else {"progress": 0, "computed_total": 0}
            if fail_before_commit:
                raise Rejection("PARK_FAILED", "Injected failure before parking; ownership is unchanged")
            # Commit boundary: all validation is complete; no external work occurs below.
            lost = w["progress"] - saved["progress"]
            self.run["discarded_work"] += lost
            self.run["preserved_work"] += saved["progress"]
            self.transition(w, "PARKED")
            self.release(w)
            w["progress"], w["computed_total"] = saved["progress"], saved["computed_total"]
            w["atomic"] = True
            if op == "restart_and_requeue":
                w["attempt"] = uid()
                w["checkpoint_id"], w["checkpoint_hash"], w["checkpoint_work"] = None, None, 0
                w["checkpoint_version"] += 1
            incident["status"] = "VERIFYING"
            result = {
                "status": "APPLIED",
                "operation_id": operation_id,
                "plan_id": plan_id,
                "worker_id": w["id"],
                "attempt": w["attempt"],
                "lost_work": lost,
                "preserved_work": saved["progress"],
                "time": time.time(),
            }
            self.operations[operation_id] = result
            self.event(
                "recovery.applied",
                f"Parked {w['name']}; released resources and retained {saved['progress']} work units",
                **result,
            )
            self.save()
            return result

    @synchronized
    def verify(self):
        incident = self.run["incident"]
        members = [self.worker(wid) for wid in incident["members"]]
        checks = []
        for w in members:
            output = next(
                (
                    a
                    for a in self.run["artifacts"]
                    if a["worker_id"] == w["id"] and a["attempt"] == w["attempt"]
                ),
                None,
            )
            check = (
                artifacts.validate(self.directory / output["filename"], w["kind"], self.rows)
                if output
                else {"valid": False, "error": "Output not yet published"}
            )
            if output and check["sha256"] != output["sha256"]:
                check["valid"], check["error"] = False, "Published artifact hash changed"
            checks.append({"worker_id": w["id"], "completed": w["state"] == "COMPLETED", **check})
        clear = not any(w["waiting"] for w in members) and not any(
            r["owner"] in incident["members"] for r in self.run["resources"]
        )
        success = (
            clear and all(c["completed"] and c["valid"] for c in checks) and not self.run["evidence_gap"]
        )
        incident["verification"] = {
            "checks": checks,
            "resources_clear": clear,
            "evidence_complete": not self.run["evidence_gap"],
            "valid": success,
        }
        if success:
            incident["status"], incident["ended"] = "RESOLVED", time.time()
            incident["reason"] = (
                "Affected workers completed, artifacts validated, and all leases and waits cleared"
            )
            self.event("incident.resolved", incident["reason"])
        elif all(w["state"] in TERMINAL for w in members):
            self.unresolved("Completion, artifact validation, or evidence integrity failed")
        return incident["verification"]

    @synchronized
    def unresolved(self, reason):
        incident = self.run["incident"]
        incident["status"], incident["reason"], incident["ended"] = "UNRESOLVED", reason, time.time()
        self.event("incident.unresolved", reason)

    def stop(self):
        with self.lock:
            if self.run and self.run["status"] == "RUNNING":
                for w in self.run["workers"]:
                    if w["state"] not in TERMINAL:
                        self.transition(w, "CANCELLED")
                        self.release(w)
                if self.run["incident"] and self.run["incident"]["status"] not in {"RESOLVED", "UNRESOLVED"}:
                    self.unresolved("Run stopped by operator")
                self.run["status"], self.run["ended"] = "CANCELLED", time.time()
                self.event("run.cancelled", "Run stopped; active leases released")
                self.save()

    @synchronized
    def state(self):
        return deepcopy(self.run)

    @synchronized
    def export(self):
        if not self.run:
            return None
        result = deepcopy(self.run)
        result["events"] = [
            json.loads(line) for line in (self.directory / "events.jsonl").read_text().splitlines()
        ]
        result["snapshots"] = {"latest": self.persisted, "pending_count": len(self.pending)}
        result["queries"] = deepcopy(self.analytics.queries)
        result["operations"] = [
            deepcopy(v)
            for v in self.operations.values()
            if self.plans[v["plan_id"]]["run_id"] == self.run["id"]
        ]
        result["telemetry"] = self.analytics.status()
        return result

    @synchronized
    def history(self):
        runs = []
        for path in (self.settings.data_dir / "runs").glob("*/state.json"):
            try:
                r = json.loads(path.read_text())
                runs.append(
                    {
                        k: r.get(k)
                        for k in [
                            "id",
                            "scenario",
                            "strategy",
                            "status",
                            "started",
                            "ended",
                            "discarded_work",
                            "preserved_work",
                        ]
                    }
                )
            except (ValueError, OSError):
                continue
        return sorted(runs, key=lambda r: r["started"], reverse=True)[:100]
