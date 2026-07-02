"""Operator-owned subscription boundaries and strictly narrowing invocation options."""

import json
import math
import os
import re
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone

TYPES = {
    "compute": "microsoft.compute/virtualmachines",
    "aks": "microsoft.containerservice/managedclusters",
    "container_apps": "microsoft.app/containerapps",
    "app_services": "microsoft.web/sites",
    "logic_apps": "microsoft.logic/workflows",
}


class ConfigError(ValueError):
    pass


def timestamp(value):
    result = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timestamp must include timezone")
    return result.astimezone(timezone.utc)


def iso(value):
    return timestamp(value).isoformat()


def number(value, name, low, high, integer=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ConfigError(f"{name} must be a number")
    if not low <= value <= high or not math.isfinite(value):
        raise ConfigError(f"{name} must be between {low} and {high}")
    if integer and not isinstance(value, int):
        raise ConfigError(f"{name} must be an integer")
    return value


def arm_id(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(
            r"/subscriptions/[a-fA-F0-9-]{36}/resourceGroups/[a-zA-Z0-9_.()-]+/"
            r"providers/[a-zA-Z0-9.]+/(?:[a-zA-Z0-9_.()-]+/)*[a-zA-Z0-9_.()-]+",
            value,
            re.I,
        )
        or any(p in (".", "..") for p in value.split("/"))
    ):
        raise ConfigError("Expected an ARM resource ID without query strings or traversal")
    return value.lower()


@dataclass(frozen=True)
class Policy:
    tenant_id: str
    subscription_id: str
    resource_groups: tuple
    locations: tuple
    state_account: str
    state_resource_group: str
    state_container: str = "janitor"
    credential_mode: str = "managed_identity"
    managed_identity_client_id: str | None = None
    services: tuple = tuple(TYPES)
    dry_run: bool = True
    mode: str = "stop"
    ttl_hours: float = 24
    grace_hours: float = 24
    max_actions_per_run: int = 10
    max_actions_per_window: int = 10
    window_seconds: int = 3600
    max_resources: int = 1000
    max_pool_nodes: int = 10
    runtime_seconds: int = 480
    protected_resources: tuple = ()

    def __post_init__(self):
        for key in ("tenant_id", "subscription_id"):
            value = getattr(self, key)
            try:
                if str(uuid.UUID(value)) != value:
                    raise ValueError()
            except (ValueError, AttributeError, TypeError) as exc:
                raise ConfigError(f"{key} must be a canonical lowercase UUID") from exc
        for key, pattern in [("resource_groups", r"[a-z0-9_.()-]+"), ("locations", r"[a-z0-9]+")]:
            values = getattr(self, key)
            if (
                not isinstance(values, (list, tuple))
                or not values
                or any(
                    not isinstance(v, str) or not re.fullmatch(pattern, v) or v in (".", "..")
                    for v in values
                )
            ):
                raise ConfigError(f"{key} must be an explicit nonempty lowercase list")
        if not re.fullmatch(r"[a-z0-9]{3,24}", self.state_account):
            raise ConfigError("Invalid state account name")
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", self.state_container)
            or "--" in self.state_container
        ):
            raise ConfigError("Invalid state container name")
        if not re.fullmatch(r"[a-z0-9_.()-]+", self.state_resource_group):
            raise ConfigError("Invalid state resource group")
        if self.state_resource_group in self.resource_groups:
            raise ConfigError("Keep janitor infrastructure outside enrolled resource groups")
        if self.credential_mode not in ("managed_identity", "azure_cli"):
            raise ConfigError("credential_mode must be managed_identity or azure_cli")
        if self.credential_mode == "managed_identity":
            try:
                uuid.UUID(self.managed_identity_client_id)
            except (ValueError, AttributeError, TypeError) as exc:
                raise ConfigError("Managed identity requires its explicit client UUID") from exc
        if not isinstance(self.services, (list, tuple)) or any(
            s not in TYPES for s in self.services
        ):
            raise ConfigError("Unsupported service")
        if type(self.dry_run) is not bool or self.mode not in ("stop", "lifecycle"):
            raise ConfigError("Invalid dry_run or lifecycle mode")
        for key in ("ttl_hours", "grace_hours"):
            number(getattr(self, key), key, 1 / 60, 87600)
        for key, upper in [
            ("max_actions_per_run", 1000),
            ("max_actions_per_window", 1000),
            ("window_seconds", 86400),
            ("max_resources", 10000),
            ("max_pool_nodes", 1000),
            ("runtime_seconds", 480),
        ]:
            number(getattr(self, key), key, 1, upper, integer=True)
        if self.runtime_seconds < 120 or self.max_actions_per_run > self.max_actions_per_window:
            raise ConfigError("Invalid runtime or action limits")
        if not isinstance(self.protected_resources, (list, tuple)):
            raise ConfigError("protected_resources must be a list")
        for name in self.protected_resources:
            if not arm_id(name).startswith(self.subscription_prefix + "/"):
                raise ConfigError("Protected resource is outside the subscription")

    @property
    def subscription_prefix(self):
        return f"/subscriptions/{self.subscription_id}"

    @property
    def state_account_id(self):
        return (
            f"{self.subscription_prefix}/resourcegroups/{self.state_resource_group}"
            f"/providers/microsoft.storage/storageaccounts/{self.state_account}"
        )

    @property
    def blob_url(self):
        return f"https://{self.state_account}.blob.core.windows.net"

    def validate_name(self, name, kind):
        name = arm_id(name)
        parts = name.split("/")
        if parts[2] != self.subscription_id or parts[4] not in self.resource_groups:
            raise ConfigError("Resource outside operator subscription/resource-group scope")
        suffix = (
            r"/[a-z0-9_.()-]+/agentpools/[a-z0-9_.()-]+" if kind == "aks" else r"/[a-z0-9_.()-]+"
        )
        if not re.fullmatch(re.escape("/".join(parts[:6]) + "/" + TYPES[kind]) + suffix, name):
            raise ConfigError("Resource ID does not match the enrolled service")
        return name

    def public(self):
        return json.loads(json.dumps(asdict(self)))


def load_policy(environ=None):
    env = os.environ if environ is None else environ
    try:
        value = json.loads(env["JANITOR_POLICY"])
        if not isinstance(value, dict):
            raise ConfigError("JANITOR_POLICY must be an object")
        return Policy(**value)
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid operator policy: {exc}") from exc


def narrow(policy, request):
    if not isinstance(request, dict) or request.keys() - {
        "dry_run",
        "max_actions_per_run",
        "resource_ids",
    }:
        raise ConfigError("Only dry_run, max_actions_per_run and resource_ids are accepted")
    changes = {}
    if "dry_run" in request:
        if type(request["dry_run"]) is not bool or (policy.dry_run and not request["dry_run"]):
            raise ConfigError("Requests cannot disable operator dry_run")
        changes["dry_run"] = request["dry_run"]
    if "max_actions_per_run" in request:
        changes["max_actions_per_run"] = number(
            request["max_actions_per_run"],
            "max_actions_per_run",
            1,
            policy.max_actions_per_run,
            integer=True,
        )
    if "resource_ids" in request:
        if (
            not isinstance(request["resource_ids"], list)
            or len(request["resource_ids"]) > policy.max_resources
        ):
            raise ConfigError("resource_ids must be a bounded list")
        for value in request["resource_ids"]:
            arm_id(value)
    return replace(policy, **changes)
