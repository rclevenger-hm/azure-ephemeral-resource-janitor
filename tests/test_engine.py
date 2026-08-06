import pytest
from conftest import NOW, Cloud, vm

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
