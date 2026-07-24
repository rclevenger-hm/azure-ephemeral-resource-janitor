from dataclasses import replace

import pytest
from conftest import PREFIX, cluster, pool, vm

from janitor.models import tags
from janitor.resources import normalize


def test_vm_stopped_allocated_still_requires_deallocation(policy):
    raw = vm()
    r = normalize(
        policy, "compute", raw["id"], raw, view={"statuses": [{"code": "PowerState/stopped"}]}
    )
    assert r["status"] == "active"
    r = normalize(
        policy, "compute", raw["id"], raw, view={"statuses": [{"code": "PowerState/deallocated"}]}
    )
    assert r["status"] == "inactive"


@pytest.mark.parametrize(
    "properties,reason",
    [
        ({"priority": "Spot"}, "spot_vm"),
        ({"virtualMachineScaleSet": {"id": "scale-set"}}, "managed_or_scale_set_vm"),
        (
            {"storageProfile": {"osDisk": {"diffDiskSettings": {"option": "Local"}}}},
            "ephemeral_os_disk",
        ),
        ({"vmId": None}, "missing_vm_identity"),
    ],
)
def test_vm_safety_exclusions(policy, properties, reason):
    raw = vm()
    raw["properties"].update(properties)
    assert normalize(policy, "compute", raw["id"], raw)["protection"] == reason


def test_managed_resource_group_is_protected(policy):
    raw = vm()
    assert (
        normalize(policy, "compute", raw["id"], raw, managed_group=True)["protection"]
        == "managed_resource_group"
    )


def test_region_must_be_explicitly_enrolled(policy):
    raw = vm()
    raw["location"] = "westus"
    assert normalize(policy, "compute", raw["id"], raw)["protection"] == "location_not_enrolled"


def test_aks_enrollment_uses_resource_tags_and_current_capacity(policy):
    raw = pool()
    resource = normalize(policy, "aks", raw["id"], raw, cluster=cluster())
    assert resource["snapshot"]["count"] == 3
    assert resource["status"] == "active" and resource["protection"] is None
    raw["properties"]["tags"] = {}
    raw["properties"]["nodeLabels"] = {"janitor-managed": "true"}
    assert normalize(policy, "aks", raw["id"], raw, cluster=cluster())["labels"] == {}


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("mode", "System", "system_or_gateway_pool"),
        ("mode", "Gateway", "system_or_gateway_pool"),
        ("type", "VirtualMachines", "unsupported_pool_type"),
        ("enableAutoScaling", True, "autoscaling_enabled"),
        ("scaleSetPriority", "Spot", "spot_pool"),
        ("osDiskType", "Ephemeral", "ephemeral_or_unknown_os_disk"),
        ("count", 11, "pool_capacity_limit"),
        ("eTag", None, "missing_etag"),
    ],
)
def test_aks_safety_exclusions(policy, field, value, reason):
    raw = pool()
    raw["properties"][field] = value
    assert normalize(policy, "aks", raw["id"], raw, cluster=cluster())["protection"] == reason


def test_aks_stopped_cluster_is_not_mutated(policy):
    raw, c = pool(), cluster()
    c["properties"]["powerState"]["code"] = "Stopped"
    assert (
        normalize(policy, "aks", raw["id"], raw, cluster=c)["protection"] == "cluster_not_running"
    )


def test_whole_function_app_stop_requires_disruption_opt_in(policy):
    name = f"{PREFIX}/microsoft.web/sites/function-app"
    raw = dict(
        id=name,
        kind="functionapp,linux",
        location="eastus",
        tags={"janitor-managed": "true"},
        properties={"state": "Running", "serverFarmId": "plan"},
    )
    assert (
        normalize(policy, "app_services", name, raw)["protection"] == "whole_app_stop_not_approved"
    )
    raw["tags"]["janitor-allow-disruption"] = "true"
    assert normalize(policy, "app_services", name, raw)["protection"] is None


def test_container_app_snapshot_excludes_secrets(policy):
    name = f"{PREFIX}/microsoft.app/containerapps/app"
    raw = dict(
        id=name,
        location="East US",
        properties={
            "provisioningState": "Succeeded",
            "runningStatus": "Running",
            "configuration": {"secrets": [{"value": "never-record"}]},
        },
    )
    resource = normalize(policy, "container_apps", name, raw)
    assert resource["status"] == "active"
    assert "never-record" not in str(resource)


def test_logic_app_disabled_state(policy):
    name = f"{PREFIX}/microsoft.logic/workflows/timer"
    resource = normalize(
        policy,
        "logic_apps",
        name,
        dict(id=name, location="eastus", properties={"state": "Disabled"}),
    )
    assert resource["status"] == "inactive"


def test_tag_names_are_case_insensitive_but_values_are_not():
    assert tags({"JANITOR-MANAGED": "true"}) == {"janitor-managed": "true"}
    assert tags({"janitor-managed": "True"}) == {"janitor-managed": "True"}
    with pytest.raises(ValueError):
        tags({"JANITOR-MANAGED": "false", "janitor-managed": "true"})


def test_policy_names_cannot_escape_scopes(policy):
    from janitor.config import ConfigError

    for name in [
        vm()["id"].replace("ephemeral", "production"),
        vm()["id"] + "/../../other",
        vm()["id"] + "?force=true",
        vm()["id"].replace("virtualmachines", "disks"),
    ]:
        with pytest.raises(ConfigError):
            policy.validate_name(name, "compute")
    assert policy.validate_name(vm()["id"].upper(), "compute") == vm()["id"]
    with pytest.raises(ConfigError):
        replace(policy, max_pool_nodes=0)


def test_vm_snapshot_omits_sas_and_records_delete_options(policy):
    raw = vm()
    raw["properties"]["storageProfile"]["osDisk"]["vhd"] = {"uri": "https://example?sig=secret"}
    result = normalize(policy, "compute", raw["id"], raw)
    assert "secret" not in str(result)
    assert result["snapshot"]["storage"]["os_disk"]["delete_option"] == "Delete"


def test_aks_node_auto_provisioning_cluster_is_protected(policy):
    raw, parent = pool(), cluster()
    parent["properties"]["nodeProvisioningProfile"] = {"mode": "Auto"}
    assert (
        normalize(policy, "aks", raw["id"], raw, cluster=parent)["protection"]
        == "node_auto_provisioning"
    )
