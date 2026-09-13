"""Real local agent observations and explicit lifecycle controls."""

import asyncio
from collections import deque
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import signal
import time
import threading
from uuid import uuid4

import psutil

from .runner import Rejection
from .monitor import Monitor
from .pause_watchdog import PauseLease


def identify(name, executable, args):
    bases = {Path(name or "").name.lower(), Path(executable or "").name.lower()}
    if "codex" in bases or any("@openai/codex/" in a and a.endswith(".js") for a in args[:2]):
        return "codex"
    if "claude" in bases or any("@anthropic-ai/claude-code/" in a and a.endswith(".js") for a in args[:2]):
        return "claude"
    return None


def redact(text):
    import re

    text = re.sub(
        r"(?i)(api[_-]?key|authorization|password|token)([\s\"':=]+)([^\s,\"}]{8,})", r"\1\2[redacted]", text
    )
    return re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,})", "[redacted]", text)


class CodexBridge:
    def __init__(self):
        self.process = None
        self.reader = None
        self.futures = {}
        self.sequence = 0
        self.error = "Not connected"
        self.lock = asyncio.Lock()
        self.sessions = []
        self.protected_thread = os.getenv("CODEX_THREAD_ID")

    async def connect(self):
        async with self.lock:
            if self.process and self.process.returncode is None:
                return
            executable = shutil.which("codex")
            if not executable:
                self.error = "Codex CLI is not installed"
                return
            argv = [executable, "app-server", "proxy"]
            if os.getenv("CODEX_APP_SERVER_SOCKET"):
                argv += ["--sock", os.environ["CODEX_APP_SERVER_SOCKET"]]
            try:
                self.process = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=4 * 1024 * 1024,
                )
                self.reader = asyncio.create_task(self.read())
                await self.call(
                    "initialize",
                    {"clientInfo": {"name": "deadlock", "title": "DEADLOCK", "version": "0.1.0"}},
                )
                await self.send({"method": "initialized", "params": {}})
                self.error = None
            except (OSError, TimeoutError, RuntimeError) as exc:
                self.error = "Shared Codex daemon unavailable: " + str(exc)[:160]
                await self.close()

    async def send(self, payload):
        if not self.process or self.process.returncode is not None:
            raise RuntimeError("Codex shared daemon is disconnected")
        self.process.stdin.write((json.dumps(payload) + "\n").encode())
        await self.process.stdin.drain()

    async def call(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.futures[request_id] = future
        try:
            await self.send({"id": request_id, "method": method, "params": params})
            return await asyncio.wait_for(future, 6)
        finally:
            self.futures.pop(request_id, None)

    async def read(self):
        try:
            while line := await self.process.stdout.readline():
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                future = self.futures.get(message.get("id"))
                if "method" not in message and future and not future.done():
                    if "error" in message:
                        future.set_exception(
                            RuntimeError(message["error"].get("message", "Codex request rejected"))
                        )
                    else:
                        future.set_result(message.get("result", {}))
                elif "id" in message and "method" in message:
                    # This client does not silently approve tools on resumed sessions.
                    method = message["method"]
                    if method.endswith("requestApproval"):
                        await self.send({"id": message["id"], "result": {"decision": "decline"}})
                    else:
                        await self.send(
                            {
                                "id": message["id"],
                                "error": {
                                    "code": -32601,
                                    "message": "Respond to this request in the original Codex client",
                                },
                            }
                        )
        except (OSError, ValueError, asyncio.CancelledError):
            pass
        finally:
            for future in self.futures.values():
                if not future.done():
                    future.set_exception(RuntimeError("Codex connection closed"))

    async def refresh(self):
        await self.connect()
        if self.error:
            self.sessions = []
            return
        try:
            result = await self.call("thread/list", {"limit": 100, "archived": False})
            sessions = []
            for thread in result.get("data", []):
                raw = thread.get("status", {})
                kind = raw.get("type", "unknown") if isinstance(raw, dict) else str(raw)
                state = {
                    "active": "RUNNING",
                    "idle": "IDLE",
                    "notLoaded": "SAVED",
                    "systemError": "ERROR",
                }.get(kind, kind.upper())
                protected = thread["id"] == self.protected_thread
                sessions.append(
                    {
                        "id": "session:" + thread["id"],
                        "session_id": thread["id"],
                        "provider": "codex",
                        "name": thread.get("name")
                        or thread.get("preview", "").split("\n")[0][:90]
                        or "Codex session",
                        "state": state,
                        "source": "shared session",
                        "cwd": thread.get("cwd"),
                        "pid": None,
                        "cpu": None,
                        "memory": None,
                        "created": thread.get("createdAt"),
                        "updated": thread.get("updatedAt"),
                        "protected": protected,
                        "controls": []
                        if protected
                        else (["interrupt"] if state == "RUNNING" else ["continue"]),
                        "note": "Current build session is protected"
                        if protected
                        else "Session metrics cannot be separated from the shared Codex process",
                    }
                )
            self.sessions = sessions
            self.error = None
        except (OSError, RuntimeError, TimeoutError) as exc:
            self.error = str(exc)[:180]
            self.sessions = []

    async def control(self, session_id, action, prompt=None):
        if session_id == self.protected_thread:
            raise Rejection("PROTECTED_SESSION", "The session building DEADLOCK is protected")
        if action == "interrupt":
            thread = (await self.call("thread/read", {"threadId": session_id, "includeTurns": True}))[
                "thread"
            ]
            turn = next(
                (t for t in reversed(thread.get("turns", [])) if t.get("status") == "inProgress"), None
            )
            if not turn:
                raise Rejection("NO_ACTIVE_TURN", "This session has no active turn on the connected daemon")
            await self.call("turn/interrupt", {"threadId": session_id, "turnId": turn["id"]})
            return {"status": "INTERRUPT_REQUESTED"}
        if action == "continue" and prompt and prompt.strip():
            await self.call("thread/resume", {"threadId": session_id})
            result = await self.call(
                "turn/start", {"threadId": session_id, "input": [{"type": "text", "text": prompt.strip()}]}
            )
            return {"status": "TURN_STARTED", "turn_id": result["turn"]["id"]}
        raise Rejection("UNSUPPORTED_CONTROL", "Use interrupt or provide a follow-up prompt to continue")

    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()  # Only the owned proxy; never the shared daemon.
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.reader:
            self.reader.cancel()


class AgentManager:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.records = {}
        self.processes = {}
        self.tasks = set()
        self.observed = []
        self.monitor = Monitor()
        self.auto_leases = {}
        self.events = deque(maxlen=300)
        event_path = settings.data_dir / "agent-events.jsonl"
        if event_path.exists():
            try:
                with event_path.open("rb") as stream:
                    offset = max(0, event_path.stat().st_size - 256 * 1024)
                    stream.seek(offset)
                    if offset:
                        stream.readline()
                    for line in deque(stream, maxlen=300):
                        try:
                            event = json.loads(line)
                            if {"time", "type", "message"} <= event.keys():
                                self.events.append(event)
                        except (ValueError, AttributeError):
                            pass
            except OSError:
                pass
        self.bridge = CodexBridge()
        self.host = {}
        self.available = {name: shutil.which(name) is not None for name in ("codex", "claude")}
        self.paused = {}
        self.stopping = set()
        self.state_path = settings.data_dir / "agents.json"
        self._load_records()

    def _load_records(self):
        try:
            records = json.loads(self.state_path.read_text())
            for record in records:
                if record["state"] in {"RUNNING", "PAUSED", "STOPPING", "STARTING"}:
                    record["state"] = "INTERRUPTED"
                    record["note"] = "Backend restarted; rediscover and adopt the process to control it"
                record["controls"] = ["continue"] if record.get("session_id") else []
                self.records[record["id"]] = record
        except (OSError, ValueError):
            pass

    def save(self):
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(list(self.records.values())))
        temp.replace(self.state_path)

    def event(self, kind, message, agent_id=None, **details):
        event = {"time": time.time(), "type": kind, "message": message, "agent_id": agent_id, **details}
        self.events.append(event)
        with (self.settings.data_dir / "agent-events.jsonl").open("a") as stream:
            stream.write(json.dumps(event) + "\n")

    def protected_pids(self):
        return {os.getpid(), *[p.pid for p in psutil.Process().parents()]}

    def discover(self):
        with self.lock:
            self._discover()

    def _discover(self):
        psutil.process_iter.cache_clear()
        protected = self.protected_pids()
        internal = {p.pid for p in psutil.Process().children(recursive=True)}
        matches = []
        for proc in psutil.process_iter(["pid", "name", "exe", "uids"], ad_value=None):
            try:
                if proc.info["uids"] and proc.info["uids"].real != os.getuid():
                    continue
                name = proc.info["name"] or ""
                if name.lower() not in {"codex", "claude", "node", "nodejs"}:
                    continue
                args = proc.cmdline()
                provider = identify(name, proc.info["exe"], args)
                if not provider:
                    continue
                infrastructure = any(a in {"app-server", "exec-server", "daemon", "proxy"} for a in args[1:4])
                matches.append((proc, provider, infrastructure))
            except (psutil.Error, OSError):
                continue
        match_pids = {p.pid for p, _, _ in matches}
        standalone_pids = {p.pid for p, _, infra in matches if not infra}
        observed = []
        owned_pids = {
            r.get("pid")
            for r in self.records.values()
            if r["state"] in {"RUNNING", "PAUSED", "STOPPING", "STARTING"}
        }
        for proc, provider, infrastructure in matches:
            try:
                ancestors = {p.pid for p in proc.parents()}
                if (
                    proc.pid in internal
                    or proc.pid in owned_pids
                    or ancestors.intersection(standalone_pids | owned_pids)
                    or (infrastructure and ancestors.intersection(match_pids))
                ):
                    continue
                created = proc.create_time()
                proc_id = f"process:{proc.pid}:{created}"
                is_protected = proc.pid in protected or infrastructure
                observed.append(
                    {
                        "id": proc_id,
                        "name": f"{provider.title()} {'runtime' if infrastructure else 'CLI'}",
                        "provider": provider,
                        "source": "observed process",
                        "pid": proc.pid,
                        "created": created,
                        "state": "PAUSED" if proc.status() == psutil.STATUS_STOPPED else "RUNNING",
                        "cwd": proc.cwd(),
                        "protected": is_protected,
                        "controls": [] if is_protected else ["adopt"],
                        "note": "Shared runtime / parent process — observe only"
                        if is_protected
                        else "Adopt this process to enable lifecycle controls",
                        "cpu": None,
                        "memory": None,
                    }
                )
            except (psutil.Error, OSError):
                continue
        for record in list(self.records.values()):
            if record["state"] not in {"RUNNING", "PAUSED", "STOPPING", "STARTING"} or not record.get("pid"):
                continue
            try:
                proc = self.checked_process(record)
                if record["source"] == "adopted process" and record["state"] != "STOPPING":
                    record["state"] = "PAUSED" if proc.status() == psutil.STATUS_STOPPED else "RUNNING"
                    record["controls"] = (
                        ["resume", "stop"] if record["state"] == "PAUSED" else ["pause", "stop"]
                    )
            except (psutil.Error, Rejection):
                if record["source"] == "adopted process":
                    if record["id"] in self.stopping:
                        continue
                    record["state"] = "STOPPED" if record["state"] == "STOPPING" else "EXITED"
                    record["controls"] = []
                    record["cpu"], record["memory"] = 0, 0
        self.observed = observed
        active = [
            r for r in self.records.values() if r["state"] in {"RUNNING", "PAUSED", "STOPPING", "STARTING"}
        ]
        measured, self.host = self.monitor.sample([*active, *observed])
        for record in [*active, *observed]:
            if record["id"] in measured:
                record.update(measured[record["id"]])
            else:
                record.update(cpu=None, memory=None, cpu_capacity=None, metrics_partial=True)

    def checked_process(self, record):
        try:
            proc = psutil.Process(record["pid"])
            if (
                proc.create_time() != record["created"]
                or not proc.is_running()
                or proc.status() == psutil.STATUS_ZOMBIE
            ):
                raise Rejection("PROCESS_CHANGED", "Process exited or PID was reused")
        except psutil.NoSuchProcess:
            raise Rejection("PROCESS_CHANGED", "Process exited before the action") from None
        if proc.pid in self.protected_pids():
            raise Rejection("PROTECTED_PROCESS", "DEADLOCK and its parent processes cannot be controlled")
        return proc

    def workspace(self, cwd):
        path = Path(cwd).expanduser().resolve()
        if not path.is_dir() or not any(path == root or root in path.parents for root in self.settings.roots):
            raise Rejection("WORKSPACE_NOT_ALLOWED", "Choose a directory within configured workspace roots")
        return path

    async def launch(self, provider, cwd, prompt, name=None, resume=None, access="read-only"):
        if provider not in {"codex", "claude"} or not shutil.which(provider):
            raise Rejection("PROVIDER_UNAVAILABLE", "The selected coding agent CLI is not installed")
        if not prompt.strip() or len(prompt) > 30000:
            raise Rejection("INVALID_PROMPT", "Provide a prompt between 1 and 30,000 characters")
        if access not in {"read-only", "workspace-write"}:
            raise Rejection("INVALID_ACCESS", "Unknown workspace permission mode")
        path = self.workspace(cwd)
        if resume and (len(resume) > 100 or not all(c.isalnum() or c in "-_" for c in resume)):
            raise Rejection("INVALID_SESSION", "Invalid session identifier")
        if provider == "codex":
            args = [
                shutil.which(provider),
                "exec",
                "--json",
                "--color",
                "never",
                "--sandbox",
                access,
                "-C",
                str(path),
                "-c",
                'approval_policy="never"',
            ]
            if resume:
                # Resume has its own parser: global options must precede the subcommand.
                args += ["resume", resume, "-"]
            else:
                args += ["-"]
        else:
            args = [
                shutil.which(provider),
                "-p",
                "--output-format",
                "stream-json",
                "--verbose",
                "--permission-mode",
                "dontAsk",
            ]
            if access == "read-only":
                args += ["--tools", "Read,Glob,Grep", "--allowedTools", "Read,Glob,Grep"]
            else:
                args += ["--allowedTools", "Read,Glob,Grep,Edit,Write,Bash"]
            if resume:
                args += ["--resume", resume]
        agent_id = str(uuid4())
        record = {
            "id": agent_id,
            "provider": provider,
            "name": name or f"{provider.title()} · {path.name}",
            "cwd": str(path),
            "source": "managed process",
            "state": "STARTING",
            "session_id": resume,
            "created": time.time(),
            "pid": None,
            "cpu": 0,
            "memory": 0,
            "children": 0,
            "controls": [],
            "protected": False,
            "access": access,
            "logs": [],
            "log_truncated": False,
            "exit_code": None,
            "note": None,
        }
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)
        env.pop("CODEX_THREAD_ID", None)
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=path,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
            limit=2 * 1024 * 1024,
        )
        record.update(
            pid=proc.pid,
            created=psutil.Process(proc.pid).create_time(),
            state="RUNNING",
            controls=["pause", "stop"],
        )
        self.records[agent_id] = record
        self.processes[agent_id] = proc
        proc.stdin.write(prompt.encode())
        await proc.stdin.drain()
        proc.stdin.close()
        self.event("agent.started", f"Started {record['name']} in {path}", agent_id)
        task = asyncio.create_task(self.read_output(agent_id, proc))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        self.save()
        return deepcopy(record)

    async def read_output(self, agent_id, proc):
        record = self.records[agent_id]
        try:
            while line := await proc.stdout.readline():
                decoded = line.decode(errors="replace").strip()
                try:
                    event = json.loads(decoded)
                    if event.get("type") == "thread.started":
                        record["session_id"] = event.get("thread_id")
                    if event.get("session_id"):
                        record["session_id"] = event["session_id"]
                    # Deliberately exclude raw model reasoning blocks.
                    item = event.get("item", {})
                    if item.get("type") == "reasoning" or event.get("type") == "stream_event":
                        continue
                    if event.get("type") == "assistant":
                        event.get("message", {})["content"] = [
                            c
                            for c in event.get("message", {}).get("content", [])
                            if c.get("type") != "thinking"
                        ]
                    decoded = json.dumps(event)
                except (ValueError, TypeError):
                    pass
                record["logs"].append({"time": time.time(), "text": redact(decoded[:12000])})
                if len(record["logs"]) > 300:
                    record["logs"] = record["logs"][-300:]
                    record["log_truncated"] = True
        except (OSError, ValueError):
            record["note"] = "Output stream ended unexpectedly"
        finally:
            code = await proc.wait()
            record["exit_code"] = code
            record["state"] = (
                "STOPPING"
                if agent_id in self.stopping
                else (
                    "STOPPED"
                    if record["state"] in {"STOPPING", "STOPPED"}
                    else (
                        "STOP_FAILED"
                        if record["state"] == "STOP_FAILED"
                        else ("COMPLETED" if code == 0 else "FAILED")
                    )
                )
            )
            record["controls"] = (
                ["continue"] if record.get("session_id") and agent_id not in self.stopping else []
            )
            record["cpu"], record["memory"] = 0, 0
            self.event("agent.exited", f"{record['name']} exited with code {code}", agent_id)
            self.save()

    def adopt(self, process_id):
        with self.lock:
            return self._adopt(process_id)

    def _adopt(self, process_id):
        observation = next((r for r in self.observed if r["id"] == process_id), None)
        if not observation or observation["protected"]:
            raise Rejection(
                "NOT_ADOPTABLE", "Only a currently observed standalone coding-agent process can be adopted"
            )
        proc = self.checked_process(observation)
        if not identify(proc.name(), proc.exe(), proc.cmdline()):
            raise Rejection("PROCESS_CHANGED", "Process is no longer a recognized coding agent")
        record = {
            **observation,
            "source": "adopted process",
            "logs": [],
            "note": "Adopted process; output stream is owned by its original terminal",
            "controls": ["resume", "stop"] if observation["state"] == "PAUSED" else ["pause", "stop"],
        }
        self.records[process_id] = record
        self.observed = [r for r in self.observed if r["id"] != process_id]
        self.event("agent.adopted", f"Adopted {record['name']} (PID {record['pid']})", process_id)
        self.save()
        return deepcopy(record)

    async def control(self, agent_id, action, prompt=None, *, automatic=False, lease_seconds=20):
        with self.lock:
            return await self._control(
                agent_id, action, prompt, automatic=automatic, lease_seconds=lease_seconds
            )

    async def _control(self, agent_id, action, prompt=None, *, automatic=False, lease_seconds=20):
        if agent_id.startswith("session:"):
            return await self.bridge.control(agent_id.removeprefix("session:"), action, prompt)
        if action == "adopt":
            return self.adopt(agent_id)
        record = self.records.get(agent_id)
        if not record or action not in record["controls"]:
            raise Rejection(
                "UNSUPPORTED_CONTROL", "This action is not available for the agent's current state"
            )
        if action == "continue":
            return await self.launch(
                record["provider"],
                record["cwd"],
                prompt or "",
                record["name"],
                record.get("session_id"),
                record.get("access", "read-only"),
            )
        proc = self.checked_process(record)
        if not automatic:
            record["manual_until"] = time.time() + 60
        if action == "pause":
            paused = []
            lease = PauseLease(lease_seconds) if automatic else None
            try:
                # Freeze the parent first so it cannot create more children while enumerating.
                if proc.status() == psutil.STATUS_STOPPED:
                    raise Rejection("ALREADY_PAUSED", "This process was already suspended externally")
                if lease:
                    lease.watch([proc])
                proc.suspend()
                paused.append(proc)
                pending = deque([proc])
                seen = {proc.pid}
                while pending:
                    parent = pending.popleft()
                    try:
                        children = parent.children()
                    except psutil.NoSuchProcess:
                        continue
                    for child in children:
                        if child.pid in seen:
                            continue
                        seen.add(child.pid)
                        try:
                            if child.status() != psutil.STATUS_STOPPED:
                                if lease:
                                    lease.watch([child])
                                child.suspend()
                                paused.append(child)
                            # Enumerate descendants only after their parent is frozen.
                            pending.append(child)
                        except psutil.NoSuchProcess:
                            pass
            except (psutil.Error, Rejection, RuntimeError, OSError):
                for item in reversed(paused):
                    try:
                        item.resume()
                    except psutil.Error:
                        pass
                if lease:
                    lease.disarm()
                raise Rejection(
                    "PAUSE_FAILED",
                    "Could not suspend the entire visible process tree; suspension was rolled back",
                ) from None
            if lease:
                self.auto_leases[agent_id] = lease
            self.paused[agent_id] = paused
            record["pause_owner"] = "automatic" if automatic else "manual"
            record["state"], record["controls"] = "PAUSED", ["resume", "stop"]
        elif action in {"resume", "stop"}:
            for child in reversed(
                self.paused[agent_id] if agent_id in self.paused else [proc, *proc.children(recursive=True)]
            ):
                try:
                    child.resume()
                except psutil.NoSuchProcess:
                    continue
            self.paused.pop(agent_id, None)
            lease = self.auto_leases.pop(agent_id, None)
            if lease:
                lease.disarm()
            record["pause_owner"] = None
            if action == "resume":
                record["state"], record["controls"] = "RUNNING", ["pause", "stop"]
            else:
                members = [proc, *proc.children(recursive=True)]
                record["state"], record["controls"] = "STOPPING", []
                self.stopping.add(agent_id)
                record["note"] = (
                    "Stopping the visible process tree; remaining processes are killed after 3 seconds"
                )
                for member in reversed(members):
                    try:
                        member.send_signal(signal.SIGTERM)
                    except psutil.NoSuchProcess:
                        pass
                    except psutil.AccessDenied:
                        record["note"] = "A process denied termination; verifying remaining processes"
                task = asyncio.create_task(self.finish_stop(agent_id, members))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
        self.event(f"agent.{action}", f"{action.title()} requested for {record['name']}", agent_id)
        self.save()
        return deepcopy(record)

    def release_auto(self, agent_id):
        with self.lock:
            self._release_auto(agent_id)

    def _release_auto(self, agent_id):
        # Release surviving children even if the original root exited while paused.
        if agent_id not in self.auto_leases:
            return
        for proc in reversed(self.paused.get(agent_id, [])):
            try:
                proc.resume()
            except psutil.NoSuchProcess:
                pass
        self.auto_leases.pop(agent_id).disarm()
        self.paused.pop(agent_id, None)
        record = self.records.get(agent_id)
        if record:
            record["pause_owner"] = None
            if record["state"] == "PAUSED":
                record["state"], record["controls"] = "RUNNING", ["pause", "stop"]
        self.save()

    async def finish_stop(self, agent_id, members):
        def live_members(items):
            alive = []
            for proc in items:
                try:
                    if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                        alive.append(proc)
                except psutil.NoSuchProcess:
                    pass
                except psutil.AccessDenied:
                    alive.append(proc)
            return alive

        deadline = time.monotonic() + 3
        remaining = members
        while remaining and time.monotonic() < deadline:
            remaining = live_members(remaining)
            if remaining:
                await asyncio.sleep(0.05)
        for proc in remaining:
            try:
                # psutil checks PID + creation time before sending the signal.
                proc.kill()
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                self.records[agent_id]["note"] = "A process denied termination; check its original terminal"
        if remaining:
            self.event(
                "agent.stop_escalated",
                "Requested force termination after the grace period",
                agent_id,
            )
        deadline = time.monotonic() + 1
        while remaining and time.monotonic() < deadline:
            remaining = live_members(remaining)
            if remaining:
                await asyncio.sleep(0.02)
        self.stopping.discard(agent_id)
        record = self.records[agent_id]
        record["state"] = "STOP_FAILED" if remaining else "STOPPED"
        record["note"] = (
            "Some processes remain; check their original terminal"
            if remaining
            else "Visible process tree stopped"
        )
        record["controls"] = ["continue"] if record.get("session_id") and not remaining else []
        if not remaining:
            record["cpu"], record["memory"] = 0, 0
        self.save()

    def detail(self, agent_id):
        record = next((r for r in self.list() if r["id"] == agent_id), None)
        if not record:
            raise Rejection("NOT_FOUND", "Agent no longer exists")
        record = deepcopy(record)
        record["open_files"], record["process_tree"], record["inspection_error"] = [], [], None
        if record.get("pid"):
            try:
                proc = psutil.Process(record["pid"])
                if proc.create_time() != record["created"]:
                    raise psutil.NoSuchProcess(proc.pid)
                attributed = self.monitor.attributed.get(agent_id, [])
                for measured in attributed[:100]:
                    item = psutil.Process(measured["pid"])
                    if item.create_time() != measured["created"]:
                        continue
                    record["process_tree"].append({**measured, "status": item.status()})
                    for opened in item.open_files()[:40]:
                        record["open_files"].append(
                            {
                                "path": opened.path,
                                "pid": item.pid,
                                "kind": "open file; lock ownership unknown",
                            }
                        )
            except psutil.Error as exc:
                record["inspection_error"] = type(exc).__name__ + ": some process details are unavailable"
        return record

    def list(self):
        with self.lock:
            return deepcopy(self._list())

    def _list(self):
        owned_session_ids = {
            r.get("session_id")
            for r in self.records.values()
            if r["state"] in {"RUNNING", "PAUSED", "STARTING", "STOPPING"}
        }
        entries = [
            *self.records.values(),
            *self.observed,
            *[s for s in self.bridge.sessions if s["session_id"] not in owned_session_ids],
        ]
        # Rediscovered adopted identities supersede saved INTERRUPTED observations.
        return list({entry["id"]: entry for entry in entries}.values())

    async def close(self):
        for agent_id in list(self.auto_leases):
            self.release_auto(agent_id)
        # Do not strand paused processes when the dashboard exits.
        for items in self.paused.values():
            for proc in reversed(items):
                try:
                    proc.resume()
                except psutil.Error:
                    pass
        for agent_id, proc in self.processes.items():
            if proc.returncode is None:
                try:
                    if "stop" in self.records[agent_id]["controls"]:
                        await self.control(agent_id, "stop")
                except (ProcessLookupError, psutil.Error, Rejection):
                    pass
        if self.tasks:
            await asyncio.wait(self.tasks, timeout=5)
        await self.bridge.close()
