# Safety contract and limitations

## Authority boundaries

`JANITOR_POLICY` is operator-controlled deployment configuration. `narrow()` accepts only `dry_run`, `max_actions_per_run`, and `resource_ids`. Unknown request fields fail closed. Subscription and tenant UUIDs, resource groups, locations, services, finite numeric bounds, storage identity, and explicit credential choice are validated before work begins.

Workload mutation RBAC is assigned only on enrolled resource groups. Subscription-wide access is limited to subscription metadata, lock reads, and selected operation-status reads. Runtime identity has no role-assignment, job-start, tag-write, storage-key, cluster-credential, secret-list, or generic resource-delete permission. AKS `agentPools/write` is necessarily broader than stopping a pool; restrict who can operate as the identity.

Anyone allowed to update the job or start it with execution overrides is a trusted operator: Azure permits overrides to container configuration. A job invoker is not an untrusted caller. Do not expose that permission as a public trigger. ARM policy and IAM still bound what the identity can do; tags are lifecycle consent, not an authorization boundary against someone already able to alter those tags.

Only Azure Public Cloud endpoints are supported. ARM requests stay on `management.azure.com` within the configured subscription. Redirects are disabled. Pagination cannot switch collections; operation URLs cannot switch hosts or subscriptions. Blob endpoints must match the configured account and its ARM metadata.

## Durable execution

Each run first acquires `v1/subscriptions/SUBSCRIPTION/lock.json` using conditional creation. Lock ownership includes the Blob ETag, which prevents a deleted-and-recreated lock from passing the original owner's checkpoint check. There is no automatic lock timeout or takeover: expiration alone cannot prove an old worker stopped.

`state.json` holds resource first-seen timestamps, pending intents, accepted operations, confirmed lifecycle history, and rolling budget reservations. Updating one object conditionally commits intent and budget together. `runs/RUN_ID.json` is a conditional journal containing the full plan and each observed outcome. Blob versioning and soft delete retain earlier versions.

The saved plan precedes all workload mutations. Every action requires a fresh eligibility evaluation, management-lock check, a second matching snapshot, and durable intent. Partial failures preserve successful earlier actions. Known resource rejections (400/404/409/412/422) permit later resources to continue; authorization failures stop the run. Ambiguous transport, throttling, and server failures retain pending intent and stop further actions. There are no automatic mutation retries.

A failed checkpoint retains the subscription lock. If writing the latest report fails, the previous durable plan/intent remains available; a final report cannot be guaranteed during a storage outage. Requests use UUID correlation IDs for investigation. Azure does not promise idempotency from `x-ms-client-request-id`, so these IDs are not an exactly-once guarantee.

All janitors for a subscription must share the same state account/container and budget settings. Separate containers or identities with other permissions can bypass coordination. Budget changes require deliberate reconciliation; merely increasing a deployment variable does not reset outstanding reservations. One pool or app stop counts as one action even when it affects many nodes/functions. The separate AKS node cap limits that case.

## VM lifecycle

1. An expired opted-in running VM, or stopped-but-still-allocated VM, is deallocated.
2. A subsequent run confirms the ARM operation and observes the VM as deallocated.
3. That observation starts the recovery grace period. A refreshed snapshot change restarts the observed grace or revokes stop authority.
4. Deletion requires operator `mode=lifecycle`, resource `janitor-allow-delete=true`, confirmed history, and elapsed grace. An externally stopped VM has no janitor stop authority.

VM `vmId`, tags, relevant disk/NIC deletion settings, size, creation information, and other selected state are fingerprinted. Changed tags or VM identity revoke old authority. Extending expiry into the future clears stop/quarantine history. Observing a restart after a stopped observation resets stop history.

**Residual race:** VM deallocate/delete and application stop endpoints do not document an atomic tag/state precondition. A resource owner can change a resource after the final refresh. A restart and deallocation entirely between observations may not change the fields Azure returns. This release does not ingest Activity Log events to prove uninterrupted stopped history. Use stop-only mode if these limits are unacceptable; add external approval or event-backed history before relying on automatic deletion for valuable workloads.

VM deletion honors the VM's existing disk and NIC `deleteOption` settings; attached resources configured for deletion may be deleted too. The janitor does not change these settings, force deletion, manage snapshots, remove resource locks, or independently sweep orphan disks/IPs.

## Service protections

AKS updates use the pool's `properties.eTag` in `If-Match` and only set `powerState.code=Stopped`; they do not replace node count, autoscaling, tags, or Kubernetes configuration. Only running User pools in running healthy clusters are eligible. System/Gateway pools, Spot, autoscaled pools, NAP clusters, non-VMSS pools, ephemeral/unknown OS disk types, and oversized pools are excluded. Some exclusions are intentionally stricter than Azure's capabilities. A pool stop is disruptive and is not guaranteed to respect Kubernetes PDBs as an eviction workflow would.

Function/Web App stops require explicit whole-app disruption consent. App Service plan charges may continue; upstream event producers may retry or queue work. Consumption Logic App disablement does not cancel already-running workflow instances. Logic Apps Standard are not discovered as Consumption workflows; their Web App hosting resource may be enrolled deliberately under `app_services`.

Non-VM actions establish quarantine history. A manual restore does not trigger another automatic stop until expiry is extended into the future and observed by the janitor. Failed operations and uncertain outcomes require operator reconciliation.

## Data and operational limits

Reports store selected configuration, owner labels, resource IDs, and operation URLs. They omit app settings, credentials, secret values, full workload definitions, and legacy VHD URLs that can contain SAS tokens. Treat the private state container as operationally sensitive. Reports expire after 90 days; previous checkpoint versions expire after 30 days; current state and locks do not expire automatically.

The runner allows 480 seconds with a 90-second checkpoint reserve inside a 600-second job. Discovery is bounded to 1,000 enrolled resources by default; oversized or incomplete discovery causes no workload mutations. Pagination and HTTP requests check remaining time, with connection/read timeouts and no redirects. This is a bounded development-subscription janitor, not a large-estate orchestration system. Sharding would need explicit non-overlapping scopes and coordinated budgets.
