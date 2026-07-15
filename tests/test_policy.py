from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import NOW

from janitor.config import ConfigError, iso, narrow
from janitor.policy import evaluate


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "lifecycle"},
        {"subscription_id": "different-subscription"},
        {"resource_groups": ["other-workloads"]},
        {"grace_hours": 0},
        {"protected_resources": []},
        {"services": []},
        {"max_actions_per_window": 999},
        {"max_actions_per_run": 0},
        {"max_actions_per_run": 11},
        {"max_actions_per_run": True},
        {"dry_run": "false"},
        {"resource_ids": "all"},
    ],
)
def test_requests_cannot_expand_authority(policy, payload):
    with pytest.raises(ConfigError):
        narrow(policy, payload)


def test_requests_can_only_enable_dryrun_or_reduce_cap(policy):
    assert narrow(policy, {"dry_run": True, "max_actions_per_run": 1}).dry_run
    with pytest.raises(ConfigError):
        narrow(replace(policy, dry_run=True), {"dry_run": False})


@pytest.mark.parametrize(
    "field,value",
    [
        ("ttl_hours", float("nan")),
        ("grace_hours", float("inf")),
        ("ttl_hours", 1e100),
        ("max_actions_per_run", -1),
        ("runtime_seconds", 600),
        ("locations", "*"),
        ("resource_groups", ("*",)),
        ("tenant_id", "wrong"),
    ],
)
def test_operator_validation(policy, field, value):
    with pytest.raises(ConfigError):
        replace(policy, **{field: value})


@pytest.mark.parametrize(
    "ttl", ["NaN", "Infinity", "-Infinity", "1e100", "0", "-3", "", "garbage", True]
)
def test_malformed_resource_ttl_is_ineligible(policy, cloud, ttl):
    r = next(iter(cloud.resources.values()))
    r["labels"].pop("janitor-expires-at")
    r["labels"]["janitor-ttl-hours"] = ttl
    action, reason = evaluate(r, {"first_seen_at": iso(NOW)}, policy, NOW)
    assert action is None and reason in ("invalid_ttl", "invalid_expiry")


def test_ttl_uses_first_seen_and_iso_expiry(policy, cloud):
    r = next(iter(cloud.resources.values()))
    assert evaluate(r, {}, policy, NOW)[0] == "deallocate"
    r["labels"].pop("janitor-expires-at")
    s = {"first_seen_at": iso(NOW)}
    assert evaluate(r, s, policy, NOW)[1] == "not_expired"
    assert evaluate(r, s, policy, NOW + timedelta(hours=25))[0] == "deallocate"


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda r: r["labels"].update({"do-not-cleanup": "false"}), "excluded"),
        (lambda r: r["labels"].pop("janitor-managed"), "not_opted_in"),
        (lambda r: r.update(status="transitioning"), "transitioning"),
    ],
)
def test_protection_labels_fail_closed(policy, cloud, mutate, reason):
    r = next(iter(cloud.resources.values()))
    mutate(r)
    assert evaluate(r, {}, policy, NOW) == (None, reason)
