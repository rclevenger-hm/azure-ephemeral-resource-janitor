"""Azure Public Cloud discovery and explicit lifecycle actions."""

from azure.identity import AzureCliCredential, ManagedIdentityCredential

from .blob import BlobObjects
from .config import TYPES, ConfigError, arm_id
from .resources import normalize
from .state import Store
from .transport import ARMClient


class Azure:
    def __init__(self, policy, credential=None, session=None):
        self.policy = policy
        if credential is None:
            credential = (
                ManagedIdentityCredential(
                    client_id=policy.managed_identity_client_id,
                    connection_timeout=3,
                    read_timeout=10,
                    retry_total=0,
                )
                if policy.credential_mode == "managed_identity"
                else AzureCliCredential(tenant_id=policy.tenant_id, process_timeout=10)
            )
        self.credential = credential
        self.client = ARMClient(policy, credential, session)

    @property
    def check_time(self):
        return self.client.check_time

    @check_time.setter
    def check_time(self, value):
        self.client.check_time = value

    def verify_subscription(self):
        raw = self.client.get("subscription", self.policy.subscription_prefix)
        if (
            raw.get("subscriptionId") != self.policy.subscription_id
            or raw.get("tenantId") != self.policy.tenant_id
            or raw.get("state") != "Enabled"
        ):
            raise ConfigError("Subscription, tenant or subscription state does not match policy")

    def store(self):
        raw = self.client.get("storage", self.policy.state_account_id)
        if (
            raw.get("id", "").lower() != self.policy.state_account_id
            or raw.get("properties", {}).get("primaryEndpoints", {}).get("blob", "").rstrip("/")
            != self.policy.blob_url
        ):
            raise ConfigError("State account identity or endpoint mismatch")
        return Store(BlobObjects.connect(self.policy, self.credential), self.policy)

    def discover(self, check_time):
        self.check_time = check_time
        for group in self.policy.resource_groups:
            parent = f"{self.policy.subscription_prefix}/resourcegroups/{group}"
            metadata = self.client.get("resources", parent)
            managed = bool(metadata.get("managedBy")) or group.startswith("mc_")
            for kind in self.policy.services:
                collection = f"{parent}/providers/{TYPES[kind]}"
                for raw in self.client.pages(kind, collection):
                    if kind == "aks":
                        cluster = raw
                        for pool in self.client.pages(kind, arm_id(raw["id"]) + "/agentpools"):
                            labels = pool.get("properties", {}).get("tags", {})
                            if any(
                                k.lower() == "janitor-managed" and v == "true"
                                for k, v in labels.items()
                            ):
                                yield normalize(
                                    self.policy,
                                    kind,
                                    pool["id"],
                                    pool,
                                    cluster=cluster,
                                    managed_group=managed,
                                )
                    elif any(
                        k.lower() == "janitor-managed" and v == "true"
                        for k, v in raw.get("tags", {}).items()
                    ):
                        view = (
                            self.client.get(kind, arm_id(raw["id"]) + "/instanceView")
                            if kind == "compute"
                            else None
                        )
                        yield normalize(
                            self.policy, kind, raw["id"], raw, view=view, managed_group=managed
                        )

    def refresh(self, kind, name):
        name = self.policy.validate_name(name, kind)
        parent = "/".join(name.split("/")[:5])
        group = self.client.get("resources", parent)
        raw = self.client.get(kind, name)
        view = self.client.get(kind, name + "/instanceView") if kind == "compute" else None
        cluster = (
            self.client.get(kind, name.rsplit("/agentpools/", 1)[0]) if kind == "aks" else None
        )
        return normalize(
            self.policy,
            kind,
            name,
            raw,
            view=view,
            cluster=cluster,
            managed_group=bool(group.get("managedBy")) or name.split("/")[4].startswith("mc_"),
        )

    def protection(self, resource, action):
        if resource["protection"]:
            return resource["protection"]
        # ARM enforces locks too. Inspect every ancestor, including subscription locks.
        name = resource["id"]
        group = "/".join(name.split("/")[:5])
        for scope in (self.policy.subscription_prefix, group, name):
            for lock in self.client.pages(
                "locks", scope + "/providers/Microsoft.Authorization/locks"
            ):
                lock_scope = (
                    lock["id"].lower().split("/providers/microsoft.authorization/locks/")[0]
                )
                if name == lock_scope or name.startswith(lock_scope + "/"):
                    level = lock.get("properties", {}).get("level")
                    if level == "ReadOnly" or (level == "CanNotDelete" and action == "delete"):
                        return "management_lock"
        return None

    def act(self, resource, action, token):
        name, kind = resource["id"], resource["kind"]
        self.policy.validate_name(name, kind)
        headers = {"x-ms-client-request-id": token}
        if action == "deallocate" and kind == "compute":
            response = self.client.request(kind, name + "/deallocate", "POST", headers=headers)
        elif action == "delete" and kind == "compute":
            response = self.client.request(kind, name, "DELETE", headers=headers)
        elif action == "stop_pool" and kind == "aks":
            etag = resource["snapshot"]["etag"]
            if not etag:
                raise ConfigError("AKS mutation requires an ETag")
            headers["If-Match"] = etag
            response = self.client.request(
                kind,
                name,
                "PUT",
                body={"properties": {"powerState": {"code": "Stopped"}}},
                headers=headers,
            )
        elif action == "stop_app" and kind in ("container_apps", "app_services"):
            response = self.client.request(kind, name + "/stop", "POST", headers=headers)
        elif action == "disable_workflow" and kind == "logic_apps":
            response = self.client.request(kind, name + "/disable", "POST", headers=headers)
        else:
            raise ConfigError("Unsupported service/action combination")
        return self.client.operation(kind, response, name)

    def poll(self, operation):
        self.policy.validate_name(operation["resource_id"], operation["kind"])
        return self.client.poll(operation)
