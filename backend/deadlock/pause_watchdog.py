"""Independent, identity-checked resume lease for automatic suspension."""

import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

import psutil


class PauseLease:
    def __init__(self, seconds):
        self.deadline = time.monotonic() + seconds
        self.process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve())],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        try:
            self.send({"owner": [os.getpid(), psutil.Process().create_time()], "seconds": seconds})
        except Exception:
            self.disarm()
            raise

    def send(self, payload):
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()
        if (
            not select.select([self.process.stdout], [], [], 2)[0]
            or self.process.stdout.readline() != "ready\n"
        ):
            raise RuntimeError("Automatic pause watchdog did not acknowledge the lease")

    def watch(self, members):
        if time.monotonic() >= self.deadline:
            raise RuntimeError("Automatic pause deadline expired during tree enumeration")
        self.send({"members": [[p.pid, p.create_time()] for p in members]})

    def disarm(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        self.process.stdin.close()
        self.process.stdout.close()


def same_process(identity):
    try:
        proc = psutil.Process(identity[0])
        return (
            proc
            if proc.create_time() == identity[1]
            and proc.is_running()
            and proc.status() != psutil.STATUS_ZOMBIE
            else None
        )
    except psutil.Error:
        return None


def main():
    initial = json.loads(sys.stdin.readline())
    deadline = time.monotonic() + min(60, max(0.1, float(initial["seconds"])))
    members = []
    print("ready", flush=True)

    def resume_members():
        # Only identities registered before suspension; never a PID-only signal.
        for identity in reversed(members):
            proc = same_process(identity)
            if proc:
                try:
                    proc.resume()
                except psutil.Error:
                    pass

    try:
        while time.monotonic() < deadline and same_process(initial["owner"]):
            if select.select([sys.stdin], [], [], 0.1)[0]:
                line = sys.stdin.readline()
                if not line:
                    return
                members.extend(json.loads(line).get("members", []))
                print("ready", flush=True)
        # Stay alive after expiry until disarmed/owner exit. If the controller was
        # descheduled between its last acknowledgement and SIGSTOP, release that
        # late suspension too instead of leaving a stranded process.
        while same_process(initial["owner"]):
            resume_members()
            if select.select([sys.stdin], [], [], 0.1)[0]:
                line = sys.stdin.readline()
                if not line:
                    break
                print("expired", flush=True)
    finally:
        resume_members()


if __name__ == "__main__":
    main()
