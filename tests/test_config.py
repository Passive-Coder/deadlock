from pathlib import Path

from deadlock.config import Settings


def test_blank_workspace_roots_example_uses_current_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DEADLOCK_WORKSPACE_ROOTS", "")
    settings = Settings(data_dir=tmp_path, database="sqlite")
    assert settings.roots == [Path.cwd().resolve()]
