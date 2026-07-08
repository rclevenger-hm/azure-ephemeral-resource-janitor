"""Service-specific snapshots and protections. Never include app settings or secrets."""

from .config import ConfigError
from .models import tags


def disk_snapshot(disk):
    # A legacy VHD URI can contain a SAS token. Only retain lifecycle-relevant fields.
    return {
        "name": disk.get("name"),
        "lun": disk.get("lun"),
        "delete_option": disk.get("deleteOption"),
        "managed_disk": disk.get("managedDisk", {}).get("id"),
        "diff_disk_option": disk.get("diffDiskSettings", {}).get("option"),
    }


def normalize(policy, kind, name, raw, *, view=None, cluster=None, managed_group=False):
    name = policy.validate_name(name, kind)
    if raw.get("id", "").lower() != name:
        raise ConfigError("ARM returned a different resource")
    p = raw.get("properties", {})
    labels = tags(p.get("tags") if kind == "aks" else raw.get("tags"))
    location = (cluster or raw).get("location", "").lower().replace(" ", "")
    protection = None
    if location not in policy.locations:
        protection = "location_not_enrolled"
    if managed_group:
        protection = "managed_resource_group"
    identity = raw.get("systemData", {}).get("createdAt", name)
    status = "transitioning"
    snapshot = {"etag": raw.get("etag") or p.get("eTag")}
    if kind == "compute":
        identity = p.get("vmId")
        if not identity:
            protection = "missing_vm_identity"
        states = {s["code"]: s for s in (view or {}).get("statuses", [])}
        power = next((s for key, s in states.items() if key.startswith("PowerState/")), {})
        power_state = power.get("code")
        snapshot.update(
            power_state=power_state,
            power_time=power.get("time"),
            provisioning_state=p.get("provisioningState"),
            created_at=p.get("timeCreated"),
            storage={
                "os_disk": disk_snapshot(p.get("storageProfile", {}).get("osDisk", {})),
                "data_disks": [
                    disk_snapshot(disk) for disk in p.get("storageProfile", {}).get("dataDisks", [])
                ],
            },
            network=[
                {
                    "id": nic.get("id"),
                    "delete_option": nic.get("properties", {}).get("deleteOption"),
                }
                for nic in p.get("networkProfile", {}).get("networkInterfaces", [])
            ],
            vm_size=p.get("hardwareProfile", {}).get("vmSize"),
        )
        if p.get("provisioningState") == "Succeeded":
            status = {
                "PowerState/running": "active",
                "PowerState/stopped": "active",
                "PowerState/deallocated": "inactive",
            }.get(power_state, "transitioning")
        if (
            p.get("virtualMachineScaleSet")
            or raw.get("managedBy")
            or any(key.startswith("aks-managed-") for key in labels)
        ):
            protection = "managed_or_scale_set_vm"
        elif p.get("priority", "").lower() == "spot":
            protection = "spot_vm"
        elif (
            p.get("storageProfile", {}).get("osDisk", {}).get("diffDiskSettings", {}).get("option")
            == "Local"
        ):
            protection = "ephemeral_os_disk"
    elif kind == "aks":
        cp = (cluster or {}).get("properties", {})
        snapshot.update(
            {
                key: p.get(key)
                for key in (
                    "count",
                    "mode",
                    "type",
                    "enableAutoScaling",
                    "osDiskType",
                    "scaleSetPriority",
                    "vmSize",
                )
            }
        )
        snapshot.update(
            power_state=p.get("powerState", {}).get("code"),
            provisioning_state=p.get("provisioningState"),
            cluster_power=cp.get("powerState", {}).get("code"),
            cluster_provisioning=cp.get("provisioningState"),
            cluster_provisioning_mode=cp.get("nodeProvisioningProfile", {}).get("mode"),
        )
        if p.get("provisioningState") == "Succeeded" and cp.get("provisioningState") == "Succeeded":
            status = {"Running": "active", "Stopped": "inactive"}.get(
                snapshot["power_state"], "transitioning"
            )
        if p.get("mode") != "User":
            protection = "system_or_gateway_pool"
        elif p.get("type") != "VirtualMachineScaleSets":
            protection = "unsupported_pool_type"
        elif cp.get("nodeProvisioningProfile", {}).get("mode") == "Auto":
            protection = "node_auto_provisioning"
        elif p.get("enableAutoScaling"):
            protection = "autoscaling_enabled"
        elif p.get("scaleSetPriority") == "Spot":
            protection = "spot_pool"
        elif p.get("osDiskType") != "Managed":
            protection = "ephemeral_or_unknown_os_disk"
        elif type(p.get("count")) is not int or not 0 <= p["count"] <= policy.max_pool_nodes:
            protection = "pool_capacity_limit"
        elif cp.get("powerState", {}).get("code") != "Running":
            protection = "cluster_not_running"
        elif not snapshot["etag"]:
            protection = "missing_etag"
        elif labels.get("janitor-allow-disruption") != "true":
            protection = "disruption_not_approved"
    elif kind == "container_apps":
        snapshot.update(
            provisioning_state=p.get("provisioningState"),
            running_status=p.get("runningStatus"),
            latest_revision=p.get("latestRevisionName"),
            active_revisions_mode=p.get("configuration", {}).get("activeRevisionsMode"),
        )
        if p.get("provisioningState") == "Succeeded":
            status = {"Running": "active", "Stopped": "inactive"}.get(
                p.get("runningStatus"), "transitioning"
            )
    elif kind == "app_services":
        snapshot.update(
            state=p.get("state"),
            kind=raw.get("kind"),
            plan=p.get("serverFarmId"),
            last_modified=p.get("lastModifiedTimeUtc"),
        )
        status = {"Running": "active", "Stopped": "inactive"}.get(p.get("state"), "transitioning")
        if labels.get("janitor-allow-disruption") != "true":
            protection = "whole_app_stop_not_approved"
    elif kind == "logic_apps":
        snapshot.update(
            state=p.get("state"), version=p.get("version"), changed_time=p.get("changedTime")
        )
        status = {"Enabled": "active", "Disabled": "inactive"}.get(p.get("state"), "transitioning")
    return dict(
        id=name,
        kind=kind,
        identity=identity,
        labels=labels,
        snapshot=snapshot,
        status=status,
        protection=protection,
    )
