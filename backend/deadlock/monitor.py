"""OS measurements, sampled once per process identity and attributed once per tree."""

from collections import deque
import ctypes
import os
from pathlib import Path
import plistlib
import subprocess
import time

import psutil


def rate(current, previous, elapsed):
    if current is None or previous is None or elapsed <= 0 or current < previous:
        return None
    return (current - previous) / elapsed


def cpu_busy(current, previous):
    if previous is None:
        return None
    # Linux guest time is already included in user/nice; iowait is not busy CPU.
    delta = {k: max(0, v - previous._asdict().get(k, v)) for k, v in current._asdict().items()}
    total = sum(v for k, v in delta.items() if k not in {"guest", "guest_nice"})
    idle = delta.get("idle", 0) + delta.get("iowait", 0)
    return round(100 * (total - idle) / total, 1) if total else None


def pressure():
    if os.uname().sysname == "Darwin":
        # Read-only XNU signal. A discrete level, never a fabricated percentage.
        value, size = ctypes.c_int(), ctypes.c_size_t(ctypes.sizeof(ctypes.c_int))
        libc = ctypes.CDLL(None, use_errno=True)
        result = libc.sysctlbyname(
            b"kern.memorystatus_vm_pressure_level", ctypes.byref(value), ctypes.byref(size), None, 0
        )
        return (
            {"source": "macOS kernel", "level": {1: "normal", 2: "warning", 4: "critical"}.get(value.value)}
            if result == 0
            else {"source": None, "level": None}
        )
    result = {"source": None, "level": None}
    for resource in ("cpu", "memory", "io"):
        try:
            lines = Path(f"/proc/pressure/{resource}").read_text().splitlines()
            result[resource] = {
                parts[0]: {k: float(v) for k, v in (p.split("=") for p in parts[1:])}
                for parts in (line.split() for line in lines)
            }
            result["source"] = "Linux PSI"
        except (OSError, ValueError):
            pass
    return result


def owner_of(pid, processes, roots, excluded):
    """Nearest registered root wins. Backend subtrees stop attribution to ancestors."""
    visited = set()
    while pid and pid not in visited:
        visited.add(pid)
        if pid in roots:
            return roots[pid]
        if pid in excluded or pid not in processes:
            return None
        pid = processes[pid]["ppid"]
    return None


class Monitor:
    def __init__(self):
        self.previous = {}
        self.last_time = None
        self.last_cpu = None
        self.last_cores = []
        self.last_io = {}
        self.history = deque(maxlen=600)
        self.processes = {}
        self.attributed = {}
        self.host = {}
        self.gpu = None
        self.gpu_sampled = 0

    def sample_gpu(self, now):
        if os.uname().sysname != "Darwin" or now - self.gpu_sampled < 3:
            return
        self.gpu_sampled = now
        try:
            output = subprocess.run(
                ["/usr/sbin/ioreg", "-a", "-r", "-c", "AGXAccelerator", "-d", "1"],
                capture_output=True,
                timeout=1,
                check=True,
            )
            devices = plistlib.loads(output.stdout)
            self.gpu = None
            for device in devices:
                stats = device.get("PerformanceStatistics", {})
                utilization = stats.get("Device Utilization %")
                if isinstance(utilization, (int, float)) and 0 <= utilization <= 100:
                    self.gpu = {
                        "name": str(device.get("model", "Apple GPU")),
                        "utilization": utilization,
                        "memory": stats.get("In use system memory"),
                        "source": "Apple GPU driver / IORegistry",
                        "updated": time.time(),
                    }
                    break
        except (OSError, ValueError, subprocess.SubprocessError):
            self.gpu = None

    def sample(self, agents):
        now, wall = time.monotonic(), time.time()
        elapsed = now - self.last_time if self.last_time else 0
        processes, previous, denied, ancestry, denied_pids = {}, {}, 0, {}, set()
        psutil.process_iter.cache_clear()
        for proc in psutil.process_iter(["pid", "ppid", "name", "create_time", "uids"], ad_value=None):
            try:
                info = proc.info
                ancestry[proc.pid] = {"ppid": info["ppid"]}
                key = (proc.pid, proc.create_time())
                with proc.oneshot():
                    times = proc.cpu_times()
                    cpu_time = times.user + times.system
                    memory = proc.memory_info().rss
                    before = self.previous.get(key, {})
                    cpu = rate(cpu_time, before.get("cpu_time"), elapsed)
                    try:
                        io = proc.io_counters()
                        read, write = io.read_bytes, io.write_bytes
                    except (AttributeError, psutil.Error, NotImplementedError):
                        read, write = None, None
                    item = {
                        "pid": proc.pid,
                        "ppid": info["ppid"],
                        "name": info["name"],
                        "created": key[1],
                        "cpu": round(cpu * 100, 2) if cpu is not None else None,
                        "memory": memory,
                        "read_rate": rate(read, before.get("read"), elapsed),
                        "write_rate": rate(write, before.get("write"), elapsed),
                        "threads": proc.num_threads(),
                        "status": proc.status(),
                    }
                    previous[key] = {"cpu_time": cpu_time, "read": read, "write": write}
                    processes[proc.pid] = item
            except (psutil.Error, OSError):
                denied += 1
                denied_pids.add(proc.pid)
        roots = {
            a["pid"]: a["id"]
            for a in agents
            if a.get("pid") in processes and a["created"] == processes[a["pid"]]["created"]
        }
        groups = {agent_id: [] for agent_id in roots.values()}
        for pid, item in processes.items():
            owner = owner_of(pid, ancestry, roots, {os.getpid()})
            if owner:
                groups[owner].append(item)
        metrics = {}
        cores = psutil.cpu_count() or 1
        for agent_id, items in groups.items():

            def total(field):
                values = [i[field] for i in items]
                return sum(values) if values and all(v is not None for v in values) else None

            cpu = total("cpu")
            metrics[agent_id] = {
                "cpu": round(cpu, 1) if cpu is not None else None,
                "cpu_capacity": round(cpu / cores, 2) if cpu is not None else None,
                "memory": total("memory"),
                "read_rate": total("read_rate"),
                "write_rate": total("write_rate"),
                "threads": total("threads"),
                "children": max(0, len(items) - 1),
                "sampled_at": wall,
                "metrics_partial": any(
                    owner_of(pid, ancestry, roots, {os.getpid()}) == agent_id for pid in denied_pids
                ),
            }
        vm, swap = psutil.virtual_memory(), psutil.swap_memory()
        cpu_times, core_times = psutil.cpu_times(), psutil.cpu_times(percpu=True)
        io = {}
        disk, net = psutil.disk_io_counters(), psutil.net_io_counters()
        for key, value in {
            "disk_read": disk.read_bytes if disk else None,
            "disk_write": disk.write_bytes if disk else None,
            "net_recv": net.bytes_recv if net else None,
            "net_sent": net.bytes_sent if net else None,
            "swap_in": swap.sin,
            "swap_out": swap.sout,
        }.items():
            io[key] = rate(value, self.last_io.get(key), elapsed)
            self.last_io[key] = value
        agent_cpu = [m["cpu_capacity"] for m in metrics.values()]
        self.sample_gpu(now)
        attributed_pids = {p["pid"] for group in groups.values() for p in group}
        self.host = {
            "cpu": cpu_busy(cpu_times, self.last_cpu),
            "cores": [
                cpu_busy(c, self.last_cores[i] if i < len(self.last_cores) else None)
                for i, c in enumerate(core_times)
            ],
            "memory_used": vm.total - vm.available,
            "memory_available": vm.available,
            "memory_total": vm.total,
            "memory_percent": vm.percent,
            "swap_used": swap.used,
            "swap_total": swap.total,
            "logical_cpus": cores,
            "platform": os.uname().sysname,
            "hostname": os.uname().nodename,
            "load": list(os.getloadavg()),
            "pressure": pressure(),
            "io": io,
            "agent_cpu": round(sum(agent_cpu), 2) if all(c is not None for c in agent_cpu) else None,
            "agent_memory": sum(m["memory"] or 0 for m in metrics.values()),
            "updated": wall,
            "interval": round(elapsed, 3),
            "unreadable_processes": denied,
            "process_count": len(processes),
            "gpu": self.gpu,
            "other_processes": sorted(
                (p for pid, p in processes.items() if pid not in attributed_pids),
                key=lambda p: p["cpu"] or 0,
                reverse=True,
            )[:8],
        }
        self.processes, self.attributed = processes, groups
        self.previous, self.last_time = previous, now
        self.last_cpu, self.last_cores = cpu_times, core_times
        self.history.append({"time": wall, "host": self.host, "agents": metrics})
        return metrics, self.host

    def series(self, seconds=300):
        cutoff = time.time() - seconds
        return {"samples": [h for h in list(self.history) if h["time"] >= cutoff], "retention_seconds": 600}
