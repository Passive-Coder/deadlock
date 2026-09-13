import asyncio
from collections import namedtuple
import subprocess
import sys
import time
from types import SimpleNamespace

import psutil

from deadlock.agents import AgentManager
from deadlock.governor import Governor
from deadlock.monitor import Monitor, cpu_busy, owner_of, rate
from deadlock.pause_watchdog import PauseLease


def test_rates_missing_reset_and_cpu_semantics():
    assert rate(10, None, 1) is None
    assert rate(2, 10, 1) is None
    assert rate(10, 2, 0) is None
    assert rate(10, 2, 2) == 4
    Cpu = namedtuple("Cpu", "user system idle iowait guest guest_nice")
    assert cpu_busy(Cpu(20, 10, 60, 10, 10, 0), Cpu(0, 0, 0, 0, 0, 0)) == 30
    assert cpu_busy(Cpu(20, 10, 60, 10, 10, 0), None) is None


def test_nearest_root_attribution_excludes_backend_but_keeps_managed_children():
    tree = {1: {"ppid": 0}, 2: {"ppid": 1}, 3: {"ppid": 2}, 4: {"ppid": 3}, 5: {"ppid": 4}}
    roots = {1: "shared", 4: "managed"}
    assert owner_of(2, tree, roots, {3}) == "shared"
    assert owner_of(3, tree, roots, {3}) is None
    assert owner_of(5, tree, roots, {3}) == "managed"
    assert owner_of(99, tree, roots, {3}) is None


async def test_real_nested_processes_are_sampled_and_counted_once(tmp_path):
    pidfile = tmp_path / "child"
    code = f"import subprocess,sys,time,pathlib;p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']);pathlib.Path({str(pidfile)!r}).write_text(str(p.pid));time.sleep(30)"
    parent = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
    child = None
    try:
        for _ in range(100):
            if pidfile.exists():
                break
            await asyncio.sleep(0.02)
        child = psutil.Process(int(pidfile.read_text()))
        roots = [
            {"id": "parent", "pid": parent.pid, "created": psutil.Process(parent.pid).create_time()},
            {"id": "child", "pid": child.pid, "created": child.create_time()},
        ]
        monitor = Monitor()
        first, _ = monitor.sample(roots)
        assert first["parent"]["cpu"] is None
        await asyncio.sleep(0.12)
        metrics, host = monitor.sample(roots)
        assert metrics["parent"]["memory"] > 0
        assert metrics["child"]["memory"] > 0
        assert metrics["parent"]["cpu"] is not None
        members = [p["pid"] for group in monitor.attributed.values() for p in group]
        assert sorted(members) == sorted([parent.pid, child.pid])
        assert host["agent_memory"] == sum(m["memory"] for m in metrics.values())
        assert host["memory_used"] + host["memory_available"] == host["memory_total"]
        assert len(monitor.series()["samples"]) == 2
        roots[0]["created"] += 1
        assert "parent" not in monitor.sample(roots)[0]
    finally:
        if child:
            child.kill()
        parent.kill()
        parent.wait(timeout=2)


async def test_watchdog_resumes_on_deadline_and_controller_pipe_loss():
    for eof in (False, True):
        child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], start_new_session=True)
        proc = psutil.Process(child.pid)
        lease = PauseLease(0.6 if not eof else 20)
        try:
            lease.watch([proc])
            proc.suspend()
            assert proc.status() == psutil.STATUS_STOPPED
            if eof:
                lease.process.stdin.close()  # Also happens on abrupt backend exit.
            for _ in range(100):
                if proc.status() != psutil.STATUS_STOPPED:
                    break
                await asyncio.sleep(0.02)
            assert proc.status() != psutil.STATUS_STOPPED
            lease.process.wait(timeout=2)
        finally:
            lease.disarm()
            proc.resume()
            child.terminate()
            child.wait(timeout=2)


def fake_manager(tmp_path, agents):
    manager = SimpleNamespace(
        settings=SimpleNamespace(data_dir=tmp_path),
        host={},
        auto_leases={},
        monitor=SimpleNamespace(history=[]),
        list=lambda: agents,
        events=[],
        released=[],
    )
    manager.event = lambda *args: manager.events.append(args)
    manager.release_auto = lambda agent_id: manager.released.append(agent_id)
    return manager


def host_at(now, cpu=95, **extra):
    return {
        "updated": now,
        "interval": 1,
        "cpu": cpu,
        "memory_available": 5 * 1024**3,
        "memory_total": 16 * 1024**3,
        "pressure": {"level": "normal"},
        **extra,
    }


async def test_governor_hysteresis_exemptions_manual_pause_staleness_and_deadline(tmp_path):
    agents = [
        {
            "id": "protected",
            "name": "Protected",
            "pid": 1,
            "protected": True,
            "state": "RUNNING",
            "cpu_capacity": 60,
            "controls": ["pause"],
        },
        {"id": "manual", "name": "Manual", "pid": 2, "state": "PAUSED", "controls": ["resume"]},
        {
            "id": "exempt",
            "name": "Exempt",
            "pid": 3,
            "state": "RUNNING",
            "cpu_capacity": 40,
            "controls": ["pause"],
        },
        {
            "id": "busy",
            "name": "Busy",
            "pid": 4,
            "state": "RUNNING",
            "cpu_capacity": 20,
            "controls": ["pause"],
        },
    ]
    manager = fake_manager(tmp_path, agents)
    paused = []

    async def control(agent_id, action, **kwargs):
        paused.append(agent_id)
        manager.auto_leases[agent_id] = SimpleNamespace(process=SimpleNamespace(poll=lambda: None))

    manager.control = control
    governor = Governor(manager)
    governor.set_agent("exempt", False)
    for now in [100, 103, 107]:
        manager.host = host_at(now)
        await governor.tick(now)
    assert not paused
    manager.host = host_at(108)
    await governor.tick(108)
    assert paused == ["busy"]
    assert governor.paused["resume_by"] == 128
    for now in [109, 112, 114]:
        manager.host = host_at(now, cpu=50)
        await governor.tick(now)
    assert manager.released == ["busy"]
    assert governor.paused is None
    assert governor.status == "cooldown"
    # Sampling gaps reset sustained-pressure evidence.
    governor.cooldown_until = 0
    manager.host = host_at(120)
    await governor.tick(120)
    await governor.tick(130)
    assert governor.status == "stale"
    manager.host = host_at(131)
    await governor.tick(131)
    assert len(paused) == 1
    manager.host = host_at(140)
    await governor.tick(140)
    assert len(paused) == 2
    manager.host = host_at(160)
    await governor.tick(160)
    assert governor.paused is None
    assert len(manager.released) == 2
    assert "manual" not in paused + manager.released


async def test_memory_pressure_does_not_pause_idle_agents_or_claim_reclaim(tmp_path):
    agents = [
        {
            "id": "idle",
            "name": "Idle",
            "pid": 2,
            "state": "RUNNING",
            "cpu_capacity": 0,
            "memory": 1024**3,
            "controls": ["pause"],
        }
    ]
    manager = fake_manager(tmp_path, agents)
    governor = Governor(manager)
    manager.host = host_at(100, cpu=20, pressure={"level": "critical"})
    await governor.tick(100)
    manager.host = host_at(109, cpu=20, pressure={"level": "critical"})
    await governor.tick(109)
    assert governor.paused is None
    assert governor.status == "limited"
    governor.configure(False)
    assert not Governor(manager).enabled


async def test_real_governor_pause_and_disable_resume(runner):
    child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], start_new_session=True)
    manager = AgentManager(runner.settings)
    manager.records["fixture"] = {
        "id": "fixture",
        "name": "Disposable control fixture",
        "pid": child.pid,
        "created": psutil.Process(child.pid).create_time(),
        "state": "RUNNING",
        "controls": ["pause", "stop"],
        "source": "adopted process",
        "cpu_capacity": 50,
    }
    governor = Governor(manager)
    try:
        # Inject pressure into the policy test; signals target a real disposable process.
        now = time.time()
        manager.host = host_at(now)
        await governor.tick(now)
        manager.host = host_at(now + 9)
        await governor.tick(now + 9)
        assert psutil.Process(child.pid).status() == psutil.STATUS_STOPPED
        assert manager.records["fixture"]["pause_owner"] == "automatic"
        governor.configure(False)
        assert psutil.Process(child.pid).status() != psutil.STATUS_STOPPED
        assert not manager.auto_leases
    finally:
        governor.release("Test cleanup")
        psutil.Process(child.pid).resume()
        child.terminate()
        child.wait(timeout=2)
