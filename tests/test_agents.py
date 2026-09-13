import asyncio
import os
import signal
import subprocess
import sys

import psutil
import pytest

from deadlock.agents import AgentManager, identify, redact
from deadlock.runner import Rejection


def test_exact_agent_identification_not_prompt_matching():
    assert identify("codex", "/bin/codex", ["codex", "exec"]) == "codex"
    assert identify("node", "/bin/node", ["node", "/lib/@anthropic-ai/claude-code/cli.js"]) == "claude"
    assert identify("python", "/bin/python", ["python", "print('codex')"]) is None
    assert identify("codex-fake", "/bin/codex-fake", []) is None


def test_workspace_is_canonicalized_and_bounded(runner, tmp_path):
    manager = AgentManager(runner.settings)
    assert manager.workspace(str(tmp_path)) == tmp_path
    with pytest.raises(Rejection):
        manager.workspace(str(tmp_path / ".."))
    (tmp_path / "escape").symlink_to("/tmp", target_is_directory=True)
    with pytest.raises(Rejection):
        manager.workspace(str(tmp_path / "escape"))


async def test_real_process_tree_pause_resume_stop_and_pid_identity(runner, tmp_path):
    # A disposable local child process exercises actual OS signals, without touching user agents.
    counter = tmp_path / "counter"
    code = (
        "import time,pathlib\np=pathlib.Path("
        + repr(str(counter))
        + ")\ni=0\nwhile True:\n i+=1\n p.write_text(str(i))\n time.sleep(.03)"
    )
    child = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
    manager = AgentManager(runner.settings)
    record = {
        "id": "test-child",
        "name": "Disposable control fixture",
        "pid": child.pid,
        "created": psutil.Process(child.pid).create_time(),
        "provider": "codex",
        "source": "adopted process",
        "state": "RUNNING",
        "controls": ["pause", "stop"],
        "cwd": str(tmp_path),
    }
    manager.records[record["id"]] = record
    try:
        for _ in range(30):
            if counter.exists():
                break
            await asyncio.sleep(0.02)
        assert counter.exists()
        await manager.control(record["id"], "pause")
        before = counter.read_text()
        await asyncio.sleep(0.12)
        assert counter.read_text() == before
        assert psutil.Process(child.pid).status() == psutil.STATUS_STOPPED
        await manager.control(record["id"], "resume")
        await asyncio.sleep(0.12)
        assert int(counter.read_text()) > int(before)
        record["created"] += 1
        with pytest.raises(Rejection):
            await manager.control(record["id"], "pause")
        record["created"] -= 1
        await manager.control(record["id"], "stop")
        child.wait(timeout=3)
        assert child.returncode < 0
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGCONT)
            child.terminate()
            child.wait(timeout=3)


def test_parent_and_own_process_protection(runner):
    manager = AgentManager(runner.settings)
    with pytest.raises(Rejection) as exc:
        manager.checked_process({"pid": os.getpid(), "created": psutil.Process().create_time()})
    assert exc.value.code == "PROTECTED_PROCESS"


def test_secret_redaction():
    assert "sk-" not in redact("key sk-abcdefghijklmnopqrstuv")
    assert "abcdefghi" not in redact("password=abcdefghi")


async def test_launch_stream_lifecycle_with_cli_fixture(runner, tmp_path, monkeypatch):
    executable = tmp_path / "codex"
    executable.write_text(
        "#!"
        + sys.executable
        + '\nimport json,sys\nprompt=sys.stdin.read()\nprint(json.dumps({"type":"thread.started","thread_id":"session-fixture"}),flush=True)\nprint(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":prompt}}),flush=True)\n'
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    manager = AgentManager(runner.settings)
    record = await manager.launch(
        "codex", str(tmp_path), "Literal prompt: $(no execution); `nothing`", name="CLI fixture"
    )
    await asyncio.gather(*manager.tasks)
    result = manager.records[record["id"]]
    assert result["state"] == "COMPLETED"
    assert result["session_id"] == "session-fixture"
    assert "$(no execution)" in result["logs"][-1]["text"]
    assert result["exit_code"] == 0
