"""Measured-pressure governor. Suspension throttles work; it never releases locks or RAM."""

import json
import time

from .runner import Rejection


class Governor:
    def __init__(self, manager):
        self.manager = manager
        self.path = manager.settings.data_dir / "governor.json"
        self.enabled = True
        self.exempt = set()
        try:
            saved = json.loads(self.path.read_text())
            self.enabled = bool(saved.get("enabled", True))
            self.exempt = set(saved.get("exempt", []))
        except (OSError, ValueError):
            pass
        self.policy = {
            "cpu_high": 90,
            "cpu_low": 70,
            "sustain_seconds": 8,
            "recovery_seconds": 5,
            "max_pause_seconds": 20,
            "cooldown_seconds": 30,
            "minimum_agent_cpu": 3,
            "minimum_growth_bytes": 1024 * 1024,
        }
        self.high_since = None
        self.low_since = None
        self.last_sample = None
        self.cooldown_until = 0
        self.paused = None
        self.reason = "Waiting for OS samples"
        self.status = "warming"

    def state(self):
        return {
            "enabled": self.enabled,
            "status": self.status,
            "reason": self.reason,
            "policy": self.policy,
            "paused": self.paused,
            "exempt": sorted(self.exempt),
            "cooldown_until": self.cooldown_until,
            "overload_since": self.high_since,
        }

    def save(self):
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps({"enabled": self.enabled, "exempt": sorted(self.exempt)}))
        temp.replace(self.path)

    def configure(self, enabled):
        self.enabled = enabled
        if not enabled:
            self.release("Automatic control disabled")
            self.status, self.reason = "disabled", "Monitoring only"
        self.high_since = None
        self.save()
        self.manager.event(
            "governor.configured", "Automatic pressure control " + ("enabled" if enabled else "disabled")
        )

    def set_agent(self, agent_id, enabled):
        if not any(a["id"] == agent_id for a in self.manager.list()):
            raise Rejection("NOT_FOUND", "Agent no longer exists")
        if enabled:
            self.exempt.discard(agent_id)
        else:
            self.exempt.add(agent_id)
            if self.paused and self.paused["agent_id"] == agent_id:
                self.release("Agent excluded from automatic control")
        self.save()

    def release(self, reason):
        if not self.paused:
            return
        agent_id = self.paused["agent_id"]
        self.manager.release_auto(agent_id)
        self.manager.event("governor.resumed", reason, agent_id)
        self.paused = None
        self.cooldown_until = time.time() + self.policy["cooldown_seconds"]
        self.high_since, self.low_since = None, None
        self.status, self.reason = "cooldown", reason

    async def tick(self, now=None):
        now = time.time() if now is None else now
        host = self.manager.host
        fresh = host.get("updated") is not None and 0 <= now - host["updated"] < 4
        if self.paused:
            agent_id = self.paused["agent_id"]
            lease = self.manager.auto_leases.get(agent_id)
            if not self.enabled or not fresh:
                self.release("Control disabled or measurements stale; released automatic pause")
            elif now >= self.paused["resume_by"] or not lease or lease.process.poll() is not None:
                self.release("Pause deadline reached or watchdog released the process")
        if not self.enabled:
            self.status, self.reason = "disabled", "Monitoring only"
            return
        if not fresh or host.get("cpu") is None or host.get("interval", 0) > 4:
            if self.paused:
                self.release("Sampling gap; released automatic pause")
            self.high_since, self.low_since = None, None
            self.status, self.reason = "stale", "Waiting for fresh OS measurements"
            return
        if host["updated"] == self.last_sample:
            return
        self.last_sample = host["updated"]
        pressure = host.get("pressure", {})
        available = host["memory_available"] / max(1, host["memory_total"])
        psi = pressure.get("memory", {}).get("full", {}).get("avg10", 0)
        memory_high = pressure.get("level") == "critical" or available < 0.08 or psi >= 10
        cpu_high = host["cpu"] >= self.policy["cpu_high"]
        high = cpu_high or memory_high
        low = (
            host["cpu"] <= self.policy["cpu_low"]
            and available >= 0.12
            and pressure.get("level") not in {"warning", "critical"}
            and psi < 2
        )
        if self.paused:
            self.low_since = (self.low_since if self.low_since is not None else now) if low else None
            if self.low_since is not None and now - self.low_since >= self.policy["recovery_seconds"]:
                self.release("Device pressure recovered; resumed automatically")
            return
        if now < self.cooldown_until:
            self.status, self.reason = "cooldown", "Allowing agents to make progress before another pause"
            self.high_since = None
            return
        self.high_since = (self.high_since if self.high_since is not None else now) if high else None
        if not high:
            self.status, self.reason = "watching", "Watching CPU saturation and memory headroom"
            return
        self.status, self.reason = (
            "watching",
            "Confirming sustained " + ("CPU saturation" if cpu_high else "memory pressure"),
        )
        if now - self.high_since < self.policy["sustain_seconds"]:
            return
        candidates = []
        samples = list(self.manager.monitor.history)
        baseline = next((s for s in reversed(samples) if s["time"] <= now - 5), None)
        for agent in self.manager.list():
            if (
                agent.get("protected")
                or agent["id"] in self.exempt
                or agent["state"] != "RUNNING"
                or not agent.get("pid")
                or agent.get("metrics_partial")
                or now < agent.get("manual_until", 0)
                or not ({"pause", "adopt"} & set(agent.get("controls", [])))
            ):
                continue
            cpu = agent.get("cpu_capacity") or 0
            old = baseline["agents"].get(agent["id"]) if baseline else None
            growth = (
                (agent["memory"] - old["memory"]) / (now - baseline["time"])
                if old and old.get("memory") is not None and agent.get("memory") is not None
                else 0
            )
            if cpu_high and cpu >= self.policy["minimum_agent_cpu"]:
                candidates.append((cpu, agent, "CPU saturation"))
            elif memory_high and growth >= self.policy["minimum_growth_bytes"]:
                candidates.append(
                    (growth / 1024**2, agent, "Memory pressure with a growing agent working set")
                )
        if not candidates:
            self.status, self.reason = (
                "limited",
                "Pressure is high; no eligible agent is contributing enough to throttle",
            )
            return
        _, agent, reason = max(candidates, key=lambda item: item[0])
        try:
            if "adopt" in agent["controls"]:
                self.manager.adopt(agent["id"])
            duration = self.policy["max_pause_seconds"]
            await self.manager.control(agent["id"], "pause", automatic=True, lease_seconds=duration)
            self.paused = {
                "agent_id": agent["id"],
                "name": agent["name"],
                "since": now,
                "resume_by": now + duration,
                "reason": reason,
                "host_cpu": host["cpu"],
                "agent_cpu": agent.get("cpu_capacity"),
                "memory_available": host["memory_available"],
            }
            self.status, self.reason = "throttling", reason + "; one agent temporarily suspended"
            self.low_since = None
            self.manager.event(
                "governor.paused",
                f"{agent['name']}: {reason}; automatic resume within {duration}s",
                agent["id"],
            )
        except (Rejection, OSError, RuntimeError) as exc:
            self.status, self.reason = "limited", "Automatic pause rejected: " + str(exc)[:160]
            self.cooldown_until = now + self.policy["cooldown_seconds"]
            self.high_since = None
            self.manager.event("governor.rejected", self.reason, agent["id"])
