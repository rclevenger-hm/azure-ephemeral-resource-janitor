from dataclasses import replace

import pytest

from janitor.config import ConfigError, narrow


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
