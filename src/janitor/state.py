"""ETag-guarded durable checkpoints and a lock without automatic expiry."""

import copy

from azure.core.exceptions import ResourceExistsError, ResourceModifiedError


class StateError(RuntimeError):
    pass


class RunLocked(StateError):
    pass


class Store:
    def __init__(self, objects, policy):
        self.objects = objects
        self.prefix = f"v1/subscriptions/{policy.subscription_id}/"
        self.lock_generation = None
        self.state_generation = 0
        self.report_generation = 0
        self.run_id = None

    def read(self, suffix):
        try:
            return self.objects.read(self.prefix + suffix)
        except Exception as exc:
            raise StateError(f"Cannot read state: {type(exc).__name__}") from exc

    def acquire(self, run_id, at):
        self.run_id = run_id
        self.report_generation = 0
        try:
            self.lock_generation = self.objects.write(
                self.prefix + "lock.json", {"run_id": run_id, "acquired_at": at}, 0
            )
        except (ResourceExistsError, ResourceModifiedError) as exc:
            raise RunLocked(
                "Subscription scope is locked; inspect its owner before recovery"
            ) from exc
        except Exception as exc:
            raise StateError("Lock acquisition uncertain; inspect storage before retrying") from exc
        state, self.state_generation = self.read("state.json")
        if state is not None and (
            state.get("schema") != 1 or not isinstance(state.get("resources"), dict)
        ):
            raise StateError("Unsupported/corrupt state; manual reconciliation required")
        return state or {"schema": 1, "resources": {}, "reservations": [], "budget_policy": None}

    def assert_owned(self):
        lock, generation = self.read("lock.json")
        if not lock or generation != self.lock_generation or lock.get("run_id") != self.run_id:
            raise StateError("Scope lock no longer belongs to this worker")

    def save_state(self, state):
        self.assert_owned()
        try:
            self.state_generation = self.objects.write(
                self.prefix + "state.json", state, self.state_generation
            )
        except Exception as exc:
            raise StateError(
                "State checkpoint uncertain; retained lock requires reconciliation"
            ) from exc

    def save_report(self, report):
        self.assert_owned()
        try:
            self.report_generation = self.objects.write(
                self.prefix + f"runs/{self.run_id}.json",
                copy.deepcopy(report),
                self.report_generation,
            )
        except Exception as exc:
            raise StateError(
                "Report checkpoint uncertain; retained lock requires reconciliation"
            ) from exc

    def release(self):
        self.assert_owned()
        try:
            self.objects.delete(self.prefix + "lock.json", self.lock_generation)
        except Exception as exc:
            raise StateError("Lock release uncertain; inspect storage") from exc
        self.lock_generation = None
