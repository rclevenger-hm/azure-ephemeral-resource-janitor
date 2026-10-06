import copy
import json
from dataclasses import replace

import pytest
import responses
from conftest import SUB, TENANT, Credential, cluster, pool, vm

from janitor.azure import Azure
from janitor.config import ConfigError
from janitor.resources import normalize
from janitor.transport import ARM


@pytest.mark.parametrize(
    "action,verb,suffix", [("deallocate", "POST", "/deallocate"), ("delete", "DELETE", "")]
)
@responses.activate
def test_vm_actions_never_force_or_claim_conditional_mutation(policy, action, verb, suffix):
    raw = vm()
    resource = normalize(policy, "compute", raw["id"], raw)
    responses.add(verb, ARM + raw["id"] + suffix, status=204)
    result = Azure(policy, Credential()).act(resource, action, "correlation-uuid")
    request = responses.calls[0].request
    assert request.headers["x-ms-client-request-id"] == "correlation-uuid"
    assert "If-Match" not in request.headers
    assert "force" not in request.url and not request.body
    assert result["url"] is None and result["kind"] == "compute"


@responses.activate
def test_pool_stop_uses_etag_and_preserves_capacity(policy):
    raw = pool()
    resource = normalize(policy, "aks", raw["id"], raw, cluster=cluster())
    responses.put(ARM + raw["id"], status=200, json={})
    Azure(policy, Credential()).act(resource, "stop_pool", "correlation-uuid")
    request = responses.calls[0].request
    assert request.headers["If-Match"] == '"pool-etag"'
    assert json.loads(request.body) == {"properties": {"powerState": {"code": "Stopped"}}}


@pytest.mark.parametrize(
    "kind,provider,action,suffix",
    [
        ("container_apps", "microsoft.app/containerapps", "stop_app", "stop"),
        ("app_services", "microsoft.web/sites", "stop_app", "stop"),
        ("logic_apps", "microsoft.logic/workflows", "disable_workflow", "disable"),
    ],
)
@responses.activate
def test_application_action_routes(policy, kind, provider, action, suffix):
    name = f"{policy.subscription_prefix}/resourcegroups/ephemeral/providers/{provider}/app"
    responses.post(ARM + name + "/" + suffix, status=200, json={})
    Azure(policy, Credential()).act({"id": name, "kind": kind}, action, "correlation-uuid")
    assert len(responses.calls) == 1
    assert not responses.calls[0].request.body


@pytest.mark.parametrize(
    "change", [{"tenantId": SUB}, {"subscriptionId": TENANT}, {"state": "Disabled"}]
)
@responses.activate
def test_wrong_tenant_subscription_or_disabled_subscription_fails_closed(policy, change):
    raw = {"subscriptionId": SUB, "tenantId": TENANT, "state": "Enabled", **change}
    responses.get(ARM + policy.subscription_prefix, json=raw)
    with pytest.raises(ConfigError):
        Azure(policy, Credential()).verify_subscription()


@responses.activate
def test_storage_endpoint_must_match_operator_account(policy):
    responses.get(
        ARM + policy.state_account_id,
        json={
            "id": policy.state_account_id,
            "properties": {"primaryEndpoints": {"blob": "https://other.invalid"}},
        },
    )
    with pytest.raises(ConfigError):
        Azure(policy, Credential()).store()
    assert len(responses.calls) == 1


@pytest.mark.parametrize(
    "level,action,blocked",
    [
        ("ReadOnly", "deallocate", True),
        ("CanNotDelete", "delete", True),
        ("CanNotDelete", "deallocate", False),
    ],
)
@responses.activate
def test_inherited_subscription_locks(policy, level, action, blocked):
    raw = vm()
    resource = normalize(policy, "compute", raw["id"], raw)
    lock_path = "/providers/Microsoft.Authorization/locks"
    responses.get(
        ARM + policy.subscription_prefix + lock_path,
        json={
            "value": [
                {
                    "id": policy.subscription_prefix + lock_path + "/protection",
                    "properties": {"level": level},
                }
            ]
        },
    )
    group = f"{policy.subscription_prefix}/resourcegroups/ephemeral"
    for scope in (group, raw["id"]):
        responses.get(ARM + scope + lock_path, json={"value": []})
    assert bool(Azure(policy, Credential()).protection(resource, action)) is blocked


@responses.activate
def test_discovery_paginates_and_only_enrolls_tagged_vms(policy):
    policy = replace(policy, services=("compute",))
    group = f"{policy.subscription_prefix}/resourcegroups/ephemeral"
    collection = group + "/providers/microsoft.compute/virtualmachines"
    one, two = vm(), vm("vm-b")
    excluded = copy.deepcopy(one)
    excluded["tags"] = {}
    responses.get(ARM + group, json={"id": group})
    responses.get(
        ARM + collection, json={"value": [excluded], "nextLink": ARM + collection + "?page=2"}
    )
    responses.get(ARM + collection, json={"value": [one, two]})
    for raw in (one, two):
        responses.get(
            ARM + raw["id"] + "/instanceView", json={"statuses": [{"code": "PowerState/running"}]}
        )
    result = list(Azure(policy, Credential()).discover(lambda: None))
    assert [r["id"] for r in result] == [one["id"], two["id"]]
    assert all(r["status"] == "active" for r in result)


@responses.activate
def test_pool_discovery_uses_azure_tags_and_cluster_context(policy):
    policy = replace(policy, services=("aks",))
    group = f"{policy.subscription_prefix}/resourcegroups/ephemeral"
    parent, raw = cluster(), pool()
    responses.get(ARM + group, json={"id": group})
    responses.get(
        ARM + group + "/providers/microsoft.containerservice/managedclusters",
        json={"value": [parent]},
    )
    responses.get(ARM + parent["id"] + "/agentpools", json={"value": [raw]})
    result = list(Azure(policy, Credential()).discover(lambda: None))
    assert len(result) == 1 and result[0]["protection"] is None
    assert result[0]["snapshot"]["etag"] == '"pool-etag"'
