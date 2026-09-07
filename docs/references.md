# Design references

Reviewed in October 2026. This project implements its Azure adapter independently and reuses the safety model of the owner's OCI/AWS/GCP janitors.

## Related open-source services

| Project | Useful ideas adopted | Deliberate scope here |
| --- | --- | --- |
| [webdevops/azure-janitor](https://github.com/webdevops/azure-janitor) | Explicit cleanup scope, expiry metadata, dry-run, ownership and operational visibility | Typed stop/deallocate actions and durable lifecycle history; no generic resource-group deletion |
| [ubuntu/azure-resource-reaper](https://github.com/ubuntu/azure-resource-reaper) | Scheduled execution and simple opt-in lifetime metadata | First-seen TTL or timezone-aware expiry, strict bounds, and explicit recovery grace |
| [kubernetes-sigs/descheduler](https://github.com/kubernetes-sigs/descheduler) | Existing eviction framework, pod protections, caps, and Helm distribution | Separate optional dry-run deployment; no bespoke eviction controller |

The service does not vendor these projects' implementation code. A future roadmap could add Resource Graph discovery at scale, owner notifications before expiry, event-backed lifecycle proof, approval-backed deletion, cost reporting, and carefully scoped orphan-disk/IP cleanup. Each requires its own permission, concurrency, and recovery design; none is implied by the first release.

## Azure contracts

- [Container Apps jobs](https://learn.microsoft.com/en-us/azure/container-apps/jobs): scheduled UTC cron, execution overrides, managed identity, and replica settings.
- [Automatically supplied environment variables](https://learn.microsoft.com/en-us/azure/container-apps/environment-variables): execution identity via `CONTAINER_APP_JOB_EXECUTION_NAME`.
- [VM deallocate](https://learn.microsoft.com/en-us/rest/api/compute/virtual-machines/deallocate?view=rest-compute-2025-04-01) and [VM delete](https://learn.microsoft.com/en-us/rest/api/compute/virtual-machines/delete?view=rest-compute-2025-04-01): lifecycle actions and asynchronous response headers.
- [AKS agent pool create/update](https://learn.microsoft.com/en-us/rest/api/aks/agent-pools/create-or-update?view=rest-aks-2025-05-01): power-state update, pool tags, `properties.eTag`, and `If-Match`.
- [AKS pool stop/start limitations](https://learn.microsoft.com/en-us/azure/aks/start-stop-nodepools): user-pool requirements, NAP exclusion, whole-pool disruption, and restoration.
- [Container Apps stop](https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/container-apps/stop?view=rest-resource-manager-containerapps-2025-07-01) and [get](https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/container-apps/get?view=rest-resource-manager-containerapps-2025-07-01): app stop and `runningStatus`.
- [Web Apps stop](https://learn.microsoft.com/en-us/rest/api/appservice/web-apps/stop?view=rest-appservice-2024-04-01): whole-app lifecycle action used for App Service and Function Apps.
- [Logic workflows disable](https://learn.microsoft.com/en-us/rest/api/logic/workflows/disable?view=rest-logic-2019-05-01): Consumption workflow disable action.
- [Azure Blob concurrency](https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage): conditional ETag writes and optimistic concurrency.
- [Azure Compute permissions](https://learn.microsoft.com/en-us/azure/role-based-access-control/permissions/compute) and [Containers permissions](https://learn.microsoft.com/en-us/azure/role-based-access-control/permissions/containers): scoped custom roles and operation polling permissions.
- [Terraform Container Apps Job](https://registry.terraform.io/providers/hashicorp/azurerm/4.72.0/docs/resources/container_app_job): deployment schema and trigger replacement behavior.

Pinned API versions appear in `src/janitor/transport.py`; contract tests assert the requests, conditions, and error handling. Changes to Azure behavior should be validated in a sandbox before upgrading these versions.
