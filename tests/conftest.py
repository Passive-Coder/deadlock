import pytest
import os
from deadlock.analytics import Analytics
from deadlock.config import Settings
from deadlock.runner import Runner


@pytest.fixture
def runner(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        database=os.getenv("DEADLOCK_TEST_DATABASE", "sqlite"),
        persistence=0,
        snapshot_interval=0,
        roots=[tmp_path],
        mediator="disabled",
    )
    analytics = Analytics(settings)
    result = Runner(settings, analytics)
    yield result
    if analytics.db:
        analytics.db.close()


def blocked(runner, scenario="canonical", **kwargs):
    runner.start(scenario, **kwargs)
    for _ in range(100):
        runner.tick()
        if runner.run["incident"]:
            return runner.run["incident"]
    raise AssertionError("Expected a qualifying cycle")


def finish(runner):
    for _ in range(250):
        runner.tick()
        if runner.run["status"] != "RUNNING":
            return
    raise AssertionError("Run did not complete")


def plan(runner):
    candidate = runner.candidates()[0]
    return runner.propose(candidate, [candidate["evidence_id"]], "Measured least-cost candidate")
