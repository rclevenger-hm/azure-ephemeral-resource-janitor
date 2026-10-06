# Deployment

## Prerequisites

Use Azure Public Cloud, Terraform 1.9+, Docker or an image builder, and an operator authenticated to the chosen tenant/subscription. Choose explicitly enrolled development resource groups and a separate infrastructure group. The runtime state account created by this module must not be your Terraform backend.

The deployer needs rights to create Container Apps, managed identities, storage, Log Analytics, custom role definitions and scoped role assignments. Register the required resource providers beforehand: `Microsoft.App`, `Microsoft.OperationalInsights`, `Microsoft.ManagedIdentity`, `Microsoft.Storage`, and `Microsoft.Insights`, plus the enrolled workload providers. The Terraform provider intentionally does not auto-register providers. Runtime identity needs none of those deployment permissions.

Create or choose an existing Azure Blob Terraform backend with Entra authentication, versioning, soft delete, and restricted access. Grant the deployer the required backend data permissions. CI only validates with `-backend=false`; a real deployment must use the remote backend in `backend.hcl.example`. For automation, use OIDC/workload identity federation rather than a client secret.

## Image and initial deployment

Build the image and publish it to a registry you control. For example:

```sh
docker build -t YOUR_REGISTRY.azurecr.io/azure-janitor:v0.1.0 .
az acr login --name YOUR_REGISTRY
docker push YOUR_REGISTRY.azurecr.io/azure-janitor:v0.1.0
```

Resolve the pushed digest and use `YOUR_REGISTRY.azurecr.io/azure-janitor@sha256:...` in Terraform. The optional `registry` input supports an existing ACR using legacy registry RBAC (`AcrPull`) and ARM audience authentication. For an ABAC-enabled registry, supply an appropriately scoped repository reader assignment instead of relying on this module's `AcrPull` example. Public digest-pinned images require no registry input. Private registries outside ACR are not configured by this module.

```sh
cp infra/terraform.tfvars.example infra/terraform.tfvars
cp infra/backend.hcl.example infra/backend.hcl
# Edit both files for your environment; keep dry_run=true and schedule_enabled=false.
terraform -chdir=infra init -backend-config=backend.hcl
terraform -chdir=infra plan -out=deployment.tfplan
terraform -chdir=infra apply deployment.tfplan
```

Do not commit local backend or variable files containing organization-specific settings. Terraform records policy and identity IDs in state; it does not use runtime account keys or embedded credentials. Allow RBAC propagation before the first run; initial authorization failures must be reviewed, not solved by granting Contributor.

The infrastructure uses ZRS storage and public HTTPS endpoints protected by Entra authentication. Storage anonymous access and shared keys are disabled. This baseline does not build private endpoints, a VNet, or an image registry. Organizations requiring private networking should add a Container Apps workload-profile environment with appropriate egress/DNS and storage private endpoints before deployment.

The job starts **manual-only**. Run it using a trusted operator:

```sh
az containerapp job start --name ephemeral-janitor --resource-group ephemeral-janitor-infra
az containerapp job execution list --name ephemeral-janitor --resource-group ephemeral-janitor-infra
```

Review the durable reports and the controlled smoke tests in [operations](operations.md). First-seen TTL starts when a tagged resource is successfully checkpointed, even during dry-run.

## Enable scheduling and live actions

Set `schedule_enabled=true` and apply a reviewed plan to enable the default 15-minute UTC schedule. Switching between manual and scheduled triggers **replaces the job resource** in the pinned provider; state storage and managed identity remain. Ensure no old execution is active before making that change. Jobs have one replica, no automatic replica retries, and a ten-minute timeout; overlapping executions are still fenced by the persistent Blob lock.

Enable live work by setting `dry_run=false`, initially `services=["compute"]`, `mode="stop"`, and small action caps. Terraform adds only the enabled services' mutation permissions. Enable `lifecycle` separately after validating deallocation, operation reconciliation, grace, and restoration behavior. Deletion still requires per-VM consent.

The role map is intentionally explicit:

| Scope | Runtime rights |
| --- | --- |
| Subscription | Subscription metadata, inherited lock reads, enabled services' regional operation-status reads |
| Each enrolled resource group | Resource-group metadata and selected workload reads; selected mutations only in live mode |
| State storage account | Account metadata read only |
| State container | Blob read/write/delete for checkpoint and lock maintenance; no account-key access |
| Optional exact ACR | `AcrPull` for the job image |

No runtime grant allows changing this job or its IAM. Azure's AKS write permission includes more than stop; protect identity assignment and job configuration carefully.

## Logs and alerts

The module connects the environment to a Log Analytics workspace. Console output contains `event=janitor_run`, status, counts, reasons, run ID, and report URI. Initialization/checkpoint failures emit `event=janitor_failure` with an exception class, without raw exception text.

Provide existing `alert_action_group_ids` to create a five-minute failure query over a 15-minute window. It detects structured errors and common system-level job failures. Query validation is skipped during provisioning because the log tables appear only after the first execution. Validate the query and notification delivery after the smoke test. Enabling a schedule without alert action groups requires your own monitoring integration.

Also monitor the absence of completed runs over a window appropriate to your cron schedule. A never-started job cannot emit its own failure event; the included failure alert does not detect every scheduler, ingestion, or platform outage. Keep notification routing outside runtime credentials.

## Upgrades and removal

Use digest-pinned image updates and inspect plans that modify IAM, scope, budgets, storage, or trigger type. Do not rename or replace the state account/container for an existing subscription without migrating and reconciling its history. All workers must agree on the persisted shared budget policy.

`prevent_destroy` protects the state account/container from routine Terraform destruction. To retire the service, stop future executions, confirm all workers ended, reconcile outstanding operations, export audit records, and revoke workload mutation roles. Removing retained state protection is a deliberate separate administrative operation.
