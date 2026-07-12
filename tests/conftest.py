import copy
import time
from datetime import datetime, timezone

import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ResourceModifiedError

from janitor.config import Policy
from janitor.resources import normalize
from janitor.state import Store

NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
SUB = "11111111-2222-3333-4444-555555555555"
TENANT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PREFIX = f"/subscriptions/{SUB}/resourcegroups/ephemeral/providers"


class Credential:
    def get_token(self, *scopes, **kwargs):
        return AccessToken("test-token", int(time.time()) + 3600)


class Objects:
    def __init__(self):
        self.data = {}
        self.generation = 0
        self.fail = lambda key, body: False
        self.writes = []

    def read(self, key):
        return copy.deepcopy(self.data.get(key, (None, 0)))

    def write(self, key, body, generation):
        if self.fail(key, body):
            raise OSError("lost acknowledgement")
        if self.data.get(key, (None, 0))[1] != generation:
            raise ResourceModifiedError("stale etag")
        self.generation += 1
        etag = f'"etag-{self.generation}"'
        self.data[key] = copy.deepcopy(body), etag
        self.writes.append((key, copy.deepcopy(body)))
        return etag

    def delete(self, key, generation):
        if self.data[key][1] != generation:
            raise ResourceModifiedError("stale etag")
        del self.data[key]


@pytest.fixture
def policy():
    return Policy(
        tenant_id=TENANT,
        subscription_id=SUB,
        resource_groups=("ephemeral",),
        locations=("eastus",),
        state_account="janitorstate",
        state_resource_group="janitor-infra",
        credential_mode="azure_cli",
        dry_run=False,
    )


@pytest.fixture
def objects():
    return Objects()


@pytest.fixture
def store(objects, policy):
    return Store(objects, policy)


def vm(name="vm-a"):
    return dict(
        id=f"{PREFIX}/microsoft.compute/virtualmachines/{name}",
        location="eastus",
        tags={"janitor-managed": "true", "janitor-expires-at": "2026-10-01T00:00:00Z"},
        properties={
            "vmId": "identity-123",
            "provisioningState": "Succeeded",
            "timeCreated": "2026-09-01T00:00:00Z",
            "storageProfile": {
                "osDisk": {"deleteOption": "Delete", "managedDisk": {"id": "disk-a"}}
            },
        },
    )


def pool():
    return dict(
        id=f"{PREFIX}/microsoft.containerservice/managedclusters/aks/agentpools/userpool",
        properties={
            "tags": {
                "janitor-managed": "true",
                "janitor-allow-disruption": "true",
                "janitor-expires-at": "2026-10-01T00:00:00Z",
            },
            "count": 3,
            "mode": "User",
            "type": "VirtualMachineScaleSets",
            "powerState": {"code": "Running"},
            "provisioningState": "Succeeded",
            "eTag": '"pool-etag"',
            "osDiskType": "Managed",
        },
    )


def cluster():
    return dict(
        id=f"{PREFIX}/microsoft.containerservice/managedclusters/aks",
        location="eastus",
        properties={"powerState": {"code": "Running"}, "provisioningState": "Succeeded"},
    )


class Cloud:
    def __init__(self, policy, raws=None):
        self.policy = policy
        self.resources = {}
        for raw in raws or [vm()]:
            self.resources[raw["id"]] = normalize(
                policy,
                "compute",
                raw["id"],
                raw,
                view={"statuses": [{"code": "PowerState/running"}]},
            )
        self.actions = []
        self.failures = {}
        self.poll_result = "succeeded"
        self.refresh_hook = lambda resource: resource
        self.act_hook = lambda resource: None
        self.discovery_error = None
        self.protection_result = None

    def verify_subscription(self):
        pass

    def discover(self, check_time):
        yield from copy.deepcopy(list(self.resources.values()))
        if self.discovery_error:
            raise self.discovery_error

    def refresh(self, kind, name):
        return self.refresh_hook(copy.deepcopy(self.resources[name]))

    def protection(self, resource, action):
        return self.protection_result

    def act(self, resource, action, token):
        self.act_hook(resource)
        self.actions.append((resource["id"], action, token))
        if resource["id"] in self.failures:
            raise self.failures[resource["id"]]
        return {
            "kind": resource["kind"],
            "resource_id": resource["id"],
            "url": None,
            "mode": "status",
        }

    def poll(self, operation):
        return self.poll_result


@pytest.fixture
def cloud(policy):
    return Cloud(policy)
