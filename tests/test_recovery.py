from copy import deepcopy
import json
import time

import pytest

from conftest import blocked, finish, plan
from deadlock import artifacts
from deadlock.mediator import Mediator
from deadlock.runner import Rejection, Runner, uid


@pytest.mark.parametrize("scenario,count", [("canonical", 3), ("two_cycle", 2)])
async def test_at01_at02_real_sql_cycle_and_validated_recovery(runner, scenario, count):
    incident = blocked(runner, scenario)
    rows = runner.analytics.query("cycles.sql", runner.persisted)
    assert len(rows) == 1
    assert len(incident["members"]) == count
    await Mediator(runner).investigate()
    finish(runner)
    assert runner.run["status"] == "COMPLETED"
    assert incident["status"] == "RESOLVED"
    assert len(runner.run["artifacts"]) == count
    assert incident["verification"]["valid"]
    for output in runner.run["artifacts"]:
        assert artifacts.validate(runner.directory / output["filename"], output["kind"], runner.rows)["valid"]
    assert not any(w["waiting"] for w in runner.run["workers"])
    assert not any(r["owner"] for r in runner.run["resources"])


@pytest.mark.parametrize("scenario", ["healthy", "contention"])
def test_at03_at04_healthy_and_acyclic_contention_do_not_recover(runner, scenario):
    runner.start(scenario)
    finish(runner)
    assert runner.run["incident"] is None
    assert runner.run["status"] == "COMPLETED"
    assert not runner.operations


def test_at05_incomplete_and_mixed_snapshots_ignored(runner):
    blocked(runner)
    old = runner.persisted
    runner.analytics.execute("UPDATE snapshots SET complete=0 WHERE id={sid}", {"sid": old["id"]})
    assert runner.analytics.query("cycles.sql", old) == []
    new = runner.snapshot()
    new["resources"][0]["owner"] = None
    runner.analytics.snapshot(new)
    assert runner.analytics.query("cycles.sql", new) == []
    assert runner.analytics.query("cycles.sql", old) == []


def test_at06_stale_plan_has_no_mutation(runner):
    blocked(runner)
    chosen = plan(runner)
    runner.resource("r0")["version"] += 1
    before = runner.scope(runner.run["incident"]["members"])
    with pytest.raises(Rejection, match="changed") as exc:
        runner.execute(chosen["id"], uid())
    assert exc.value.code == "STALE_PLAN"
    assert runner.scope(runner.run["incident"]["members"]) == before
    assert not runner.operations


async def test_at06_stale_scenario_replans_within_budgets(runner):
    incident = blocked(runner, "stale_plan")
    await Mediator(runner).investigate()
    finish(runner)
    assert incident["status"] == "RESOLVED"
    assert incident["attempts"] == 2
    assert incident["tool_calls"] <= 8


def test_at07_duplicate_operation_and_payload_binding(runner):
    blocked(runner)
    chosen = plan(runner)
    oid = uid()
    result = runner.execute(chosen["id"], oid)
    after = deepcopy(runner.run)
    repeated = runner.execute(chosen["id"], oid)
    assert repeated["duplicate"]
    assert repeated["attempt"] == result["attempt"]
    assert runner.run == after
    with pytest.raises(Rejection) as exc:
        runner.execute("other-plan", oid)
    assert exc.value.code == "OPERATION_ID_REUSED"
    finish(runner)
    assert len({a["filename"] for a in runner.run["artifacts"]}) == 3


@pytest.mark.parametrize("mode", ["missing", "corrupt", "wrong_attempt"])
def test_at08_invalid_checkpoint_never_releases(runner, mode):
    blocked(runner)
    chosen = plan(runner)
    worker = runner.worker(chosen["candidate"]["worker_id"])
    path = runner.directory / f"checkpoint-{worker['checkpoint_id']}.json"
    if mode == "missing":
        path.unlink()
    elif mode == "corrupt":
        path.write_text("{}")
    else:
        saved = json.loads(path.read_text())
        saved["attempt"] = "wrong"
        path.write_text(json.dumps(saved))
    before = runner.scope(runner.run["incident"]["members"])
    with pytest.raises(Rejection) as exc:
        runner.execute(chosen["id"], uid())
    assert exc.value.code == "INVALID_CHECKPOINT"
    assert runner.scope(runner.run["incident"]["members"]) == before


def test_at09_invented_candidate_and_missing_evidence(runner):
    blocked(runner)
    selected = runner.candidates()[0]
    with pytest.raises(Rejection):
        runner.propose({**selected, "operation": "kill_everything"}, [selected["evidence_id"]], "invalid")
    with pytest.raises(Rejection):
        runner.propose(selected, [], "no evidence")
    assert not runner.plans and not runner.operations


def test_at09_tampered_plan_cannot_add_capability(runner):
    blocked(runner)
    chosen = plan(runner)
    chosen["candidate"]["operation"] = "shell"
    before = runner.scope(runner.run["incident"]["members"])
    with pytest.raises(Rejection):
        runner.execute(chosen["id"], uid())
    assert runner.scope(runner.run["incident"]["members"]) == before


def test_at10_park_failure_precedes_commit_boundary(runner):
    blocked(runner)
    chosen = plan(runner)
    before = deepcopy(runner.run["resources"])
    with pytest.raises(Rejection) as exc:
        runner.execute(chosen["id"], uid(), fail_before_commit=True)
    assert exc.value.code == "PARK_FAILED"
    assert runner.run["resources"] == before


async def test_at11_no_permissible_recovery(runner):
    incident = blocked(runner, "no_recovery")
    before = deepcopy(runner.run["resources"])
    await Mediator(runner).investigate()
    assert incident["status"] == "UNRESOLVED"
    assert "capability" in incident["reason"]
    assert runner.run["resources"] == before
    assert not runner.operations


def test_at12_parked_worker_does_not_reacquire_subset(runner):
    blocked(runner)
    chosen = plan(runner)
    runner.execute(chosen["id"], uid())
    victim = runner.worker(chosen["candidate"]["worker_id"])
    assert victim["state"] == "PARKED"
    runner.tick()
    assert victim["state"] == "PARKED"
    assert not any(r["owner"] == victim["id"] for r in runner.run["resources"])
    finish(runner)
    assert runner.run["incident"]["status"] == "RESOLVED"


def test_at13_unrelated_worker_not_invalidating_plan_or_restarted(runner):
    blocked(runner, "unrelated")
    chosen = plan(runner)
    unrelated = runner.worker("D")
    attempt = unrelated["attempt"]
    unrelated["version"] += 1
    runner.execute(chosen["id"], uid())
    finish(runner)
    assert unrelated["attempt"] == attempt
    assert unrelated["progress"] == unrelated["total"]


@pytest.mark.parametrize("mode", ["missing", "corrupt"])
def test_at14_corrupted_or_missing_artifact_not_resolved(runner, mode):
    blocked(runner)
    chosen = plan(runner)
    runner.execute(chosen["id"], uid())
    for _ in range(30):
        runner.advance()
        if runner.run["artifacts"]:
            break
    output = runner.run["artifacts"][0]
    target = runner.directory / output["filename"]
    target.unlink() if mode == "missing" else target.write_bytes(b"corrupted")
    finish(runner)
    assert runner.run["incident"]["status"] == "UNRESOLVED"
    assert runner.run["status"] == "FAILED"


def test_at15_unavailable_analytics_blocks_new_recovery_and_reports_gap(runner):
    blocked(runner)
    chosen = plan(runner)
    runner.analytics.available = False
    before = deepcopy(runner.run["resources"])
    with pytest.raises(Rejection):
        runner.execute(chosen["id"], uid())
    for _ in range(35):
        runner.tick()
    assert runner.run["resources"] == before
    assert runner.run["evidence_gap"]
    assert len(runner.pending) == 32


def test_at16_epoch_mismatch_and_interrupted_history(runner):
    blocked(runner)
    chosen = plan(runner)
    replacement = Runner(runner.settings, runner.analytics)
    assert runner.run["id"] in replacement.interrupted
    runner.epoch = uid()
    with pytest.raises(Rejection) as exc:
        runner.execute(chosen["id"], uid())
    assert exc.value.code == "EPOCH_MISMATCH"


class InvalidModel:
    async def choose(self, evidence, timeout):
        return {
            "tool": "propose_recovery",
            "candidate_id": "invented",
            "rationale": "invalid",
            "evidence_ids": [],
        }, "test-invalid"


class TimeoutModel:
    async def choose(self, evidence, timeout):
        raise TimeoutError("Model timed out")


@pytest.mark.parametrize("model", [InvalidModel(), TimeoutModel()])
async def test_at17_model_failure_does_not_substitute_deterministic_result(runner, model):
    incident = blocked(runner, strategy="live")
    await Mediator(runner, model).investigate()
    assert incident["status"] == "UNRESOLVED"
    assert not runner.operations
    assert incident["tool_calls"] <= 8


async def test_at18_changed_checkpoint_changes_selection(runner):
    incident = blocked(runner, "changed_candidate")
    await Mediator(runner).investigate()
    assert incident["plan"]["candidate"]["worker_id"] == "A"
    finish(runner)
    assert runner.run["discarded_work"] == 1


def test_resource_models_and_freshness_are_not_generalized(runner):
    blocked(runner)
    snap = runner.snapshot()
    snap["resources"][0]["capacity"] = 2
    runner.analytics.snapshot(snap)
    assert runner.detect(snap) == []
    snap = runner.snapshot()
    snap["captured"] = time.time() - 10
    runner.analytics.snapshot(snap)
    assert runner.detect(snap) == []


def test_cycle_must_persist_without_meaningful_progress(runner):
    blocked(runner)
    runner.settings.persistence = 2
    runner.cycle_since.clear()
    snap = runner.snapshot()
    runner.analytics.snapshot(snap)
    now = time.time()
    assert not runner.detect(snap, now)
    progressed = deepcopy(snap)
    progressed["id"] = uid()
    progressed["captured"] = now + 1.5
    progressed["workers"][0]["progress"] += 1
    progressed["workers"][0]["last_progress"] = now + 1.5
    runner.analytics.snapshot(progressed)
    assert not runner.detect(progressed, now + 1.5)
    final = deepcopy(progressed)
    final["id"] = uid()
    final["captured"] = now + 3.6
    runner.analytics.snapshot(final)
    assert len(runner.detect(final, now + 3.6)) == 1


async def test_restart_all_baseline_measures_actual_lost_work(runner):
    incident = blocked(runner, "unrelated", strategy="restart_all")
    before = {w["id"]: w["attempt"] for w in runner.run["workers"]}
    expected = sum(runner.worker(w)["progress"] for w in incident["members"])
    await Mediator(runner).investigate()
    finish(runner)
    assert runner.run["discarded_work"] == expected
    assert runner.run["preserved_work"] == 0
    assert all(runner.worker(w)["attempt"] != before[w] for w in incident["members"])
    assert runner.worker("D")["attempt"] == before["D"]
    assert incident["status"] == "RESOLVED"


def test_reset_preserves_history_and_artifacts(runner):
    runner.start("contention")
    finish(runner)
    previous = runner.run["id"]
    artifact = runner.directory / runner.run["artifacts"][0]["filename"]
    runner.start()
    assert runner.run["id"] != previous
    assert artifact.exists()
    assert len(runner.history()) == 2


def test_no_recovery_baseline_has_no_mutations(runner):
    blocked(runner, strategy="none")
    for _ in range(20):
        runner.tick()
    assert not runner.operations
    assert all(w["state"] == "WAITING" for w in runner.run["workers"])
    runner.stop()
    assert runner.run["status"] == "CANCELLED"


def test_already_cleared_cycle_does_not_apply_old_plan(runner):
    blocked(runner)
    chosen = plan(runner)
    # Another cooperative action has released one lease since proposal creation.
    runner.resource("r0")["owner"] = None
    before = deepcopy(runner.run["workers"])
    result = runner.execute(chosen["id"], uid())
    assert result["status"] == "ALREADY_CLEAR"
    assert runner.run["workers"] == before
    assert runner.run["discarded_work"] == 0
    assert runner.run["incident"]["status"] == "VERIFYING"
    finish(runner)
    assert runner.run["incident"]["status"] == "RESOLVED"


def test_snapshot_retry_does_not_duplicate_or_replace_evidence(runner):
    blocked(runner)
    original = deepcopy(runner.persisted)
    replay = deepcopy(original)
    replay["resources"][0]["owner"] = None
    assert runner.analytics.snapshot(replay)
    stored = runner.analytics.execute(
        "SELECT owner FROM resources WHERE snapshot_id={sid} AND run_id={rid} AND id={resource}",
        {"sid": original["id"], "rid": original["run_id"], "resource": original["resources"][0]["id"]},
    ).fetchall()
    assert len(stored) == 1
    assert dict(stored[0])["owner"] == original["resources"][0]["owner"]


async def test_query_failure_is_explicit_and_never_invokes_recovery(runner, monkeypatch):
    blocked(runner)

    def unavailable(*args, **kwargs):
        raise RuntimeError("sensitive database connection details")

    monkeypatch.setattr(runner.analytics, "execute", unavailable)
    await Mediator(runner).investigate()
    incident = runner.run["incident"]
    assert incident["status"] == "UNRESOLVED"
    assert not runner.analytics.available
    assert "sensitive" not in incident["reason"]
    assert not runner.operations
