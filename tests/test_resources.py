import pytest
from conftest import vm

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
