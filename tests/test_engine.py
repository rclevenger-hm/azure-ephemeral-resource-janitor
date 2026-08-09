from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import NOW, Cloud, vm

from janitor.config import iso
from janitor.engine import run
from janitor.state import RunLocked, StateError, Store
from janitor.transport import APIError


def execute(policy, cloud, store, **kwargs):
    return run(policy, {}, cloud, store, clock=lambda: NOW, **kwargs)


def test_plan_and_intent_are_durable_before_any_mutation(policy, cloud, store, objects):
    def check(resource):
        state, _ = store.read("state.json")
        report, _ = store.read(f"runs/{store.run_id}.json")
        assert len(report["resources"]) == 1
        assert report["resources"][0]["outcome"] == "pending"
        assert state["resources"][resource["id"]]["pending"]["action"] == "deallocate"
        assert len(state["reservations"]) == 1

    cloud.act_hook = check
    result = execute(policy, cloud, store)
    assert result["status"] == "complete"
    assert result["counts"] == {"submitted": 1}
    assert store.read("lock.json")[0] is None


@pytest.mark.parametrize(
    "code,expected_actions,status",
    [(400, 3, "partial"), (403, 2, "failed"), (503, 2, "failed"), (429, 2, "failed")],
)
def test_partial_results_survive_action_failure(policy, store, code, expected_actions, status):
    cloud = Cloud(policy, [vm("vm-a"), vm("vm-b"), vm("vm-c")])
    names = list(cloud.resources)
    cloud.failures[names[1]] = APIError(code)
    result = execute(policy, cloud, store)
    assert result["status"] == status
    assert len(cloud.actions) == expected_actions
    durable, _ = store.read(f"runs/{result['run_id']}.json")
    assert durable["resources"][0]["outcome"] == "submitted"
    state, _ = store.read("state.json")
    assert ("pending" in state["resources"][names[1]]) == (code in (503, 429))


def test_unknown_action_is_not_repeated_on_next_run(policy, cloud, store):
    name = next(iter(cloud.resources))
    cloud.failures[name] = TimeoutError()
    assert execute(policy, cloud, store)["status"] == "failed"
    cloud.failures.clear()
    assert execute(policy, cloud, store)["status"] == "partial"
    assert len(cloud.actions) == 1


@pytest.mark.parametrize("checkpoint", ["plan", "intent", "outcome", "state_outcome"])
def test_checkpoint_failure_retains_lock_and_blocks_later_workers(
    policy, cloud, store, objects, checkpoint
):
    def fail(key, body):
        if checkpoint == "plan":
            return "/runs/" in key and body["status"] == "executing"
        if checkpoint == "intent":
            return key.endswith("state.json") and any(
                "pending" in e for e in body["resources"].values()
            )
        if checkpoint == "outcome":
            return "/runs/" in key and any(p["outcome"] == "submitted" for p in body["resources"])
        return key.endswith("state.json") and any(
            "operation" in e for e in body["resources"].values()
        )

    objects.fail = fail
    with pytest.raises(StateError):
        execute(policy, cloud, store)
    assert store.read("lock.json")[0]
    assert len(cloud.actions) == (checkpoint in ("outcome", "state_outcome"))
    objects.fail = lambda key, body: False
    with pytest.raises(RunLocked):
        execute(policy, cloud, Store(objects, policy))


def test_two_workers_cannot_share_lock(policy, cloud, store, objects):
    store.acquire("a" * 32, iso(NOW))
    with pytest.raises(RunLocked):
        execute(policy, cloud, Store(objects, policy))
    assert not cloud.actions


def test_lock_generation_change_fences_checkpoints(policy, store, objects):
    state = store.acquire("a" * 32, iso(NOW))
    objects.write(store.prefix + "lock.json", {"run_id": "a" * 32}, store.lock_generation)
    with pytest.raises(StateError):
        store.save_state(state)


def test_completed_execution_is_not_replayed(policy, cloud, store):
    first = execute(policy, cloud, store, run_id="a" * 32)
    duplicate = execute(policy, cloud, store, run_id="a" * 32)
    assert duplicate["duplicate"] and duplicate["run_id"] == first["run_id"]
    assert len(cloud.actions) == 1


def test_shared_budget_applies_across_independent_workers(policy, store, objects):
    policy = replace(policy, max_actions_per_run=1, max_actions_per_window=1)
    one = Cloud(policy, [vm("vm-a")])
    two = Cloud(policy, [vm("vm-b")])
    two.resources.update(one.resources)
    execute(policy, one, store)
    result = execute(policy, two, Store(objects, policy))
    assert result["reasons"] == {
        "shared_budget_exhausted": 1,
        "stop_confirmed_waiting_for_state": 1,
    }
    assert not two.actions


def test_window_expiry_allows_new_action(policy, cloud, store):
    policy = replace(policy, max_actions_per_run=1, max_actions_per_window=1)
    execute(policy, cloud, store)
    name = next(iter(cloud.resources))
    cloud.resources[name]["snapshot"]["vm_size"] = iso(NOW + timedelta(hours=2))
    run(policy, {}, cloud, store, clock=lambda: NOW + timedelta(hours=2))
    assert len(cloud.actions) == 2


def test_budget_policy_change_requires_reconciliation(policy, cloud, store):
    execute(policy, cloud, store)
    result = execute(replace(policy, window_seconds=7200), cloud, store)
    assert result["error"] == "budget_policy_changed"
    assert len(cloud.actions) == 1
