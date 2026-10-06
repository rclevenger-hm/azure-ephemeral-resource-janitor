# Azure Ephemeral Resource Janitor

A scheduled Azure Container Apps Job that deallocates expired development VMs, stops opted-in application workloads, and optionally deletes VMs after a confirmed janitor deallocation and a recovery grace period. Managed identity authenticates to Azure; Blob Storage holds plans, action intent, outcomes, lifecycle history, and a shared action budget.

The default deployment is **dry-run and manual-only**. Workload mutation permissions are absent in dry-run deployments. No public HTTP endpoint, account keys, Kubernetes credentials, or background server are required.

## Supported workloads

| Service | Expiry action | Boundaries |
| --- | --- | --- |
| Virtual Machines | Deallocate; optionally delete after grace | Standalone VMs only; excludes Spot, ephemeral OS disks, VMSS members, and managed resource groups |
| AKS | Stop an opted-in user node pool | VMSS-backed, managed OS disks, no autoscaler or node auto-provisioning, explicit disruption consent, size cap, conditional ETag update |
| Container Apps | Stop the entire app | Retains the resource and its configuration; does not delete revisions or jobs |
| Azure Functions / App Service | Stop the entire Function App or Web App | Requires explicit disruption consent; all functions in that app stop; slots are not targeted |
| Logic Apps Consumption | Disable a workflow | Prevents new runs; existing runs are not canceled |
| Kubernetes descheduler | Optional, separate Helm installation | Bounded pod evictions; dry-run by default; not a prerequisite or drain guarantee for AKS stops |

App Service plans, VM disks, network resources, AKS control-plane charges, and other retained resources may continue to cost money. This is an opt-in lifecycle service, not a general subscription wipe tool or a cost estimator.

## Enrollment

Configure the subscription, tenant, workload resource groups, and locations in the operator policy. Then add Azure resource tags:

| Tag | Meaning |
| --- | --- |
| `janitor-managed=true` | Required opt-in; the value must be lowercase `true` |
| `janitor-expires-at=2026-12-01T18:00:00Z` | Explicit expiry with timezone; takes precedence over TTL |
| `janitor-ttl-hours=24` | Positive finite TTL, up to ten years, measured from the first durable observation; defaults to the operator TTL |
| `do-not-cleanup` | Any value excludes the resource, including `false` |
| `janitor-allow-delete=true` | Additional VM deletion opt-in; only effective in operator lifecycle mode |
| `janitor-allow-disruption=true` | Required for AKS pools and whole Function/Web App stops |
| `owner` | Optional owner recorded in reports |

Tag keys are case-insensitive; ambiguous duplicate keys fail discovery closed. AKS enrollment uses **agent-pool Azure resource tags**, not Kubernetes node labels. `NaN`, infinity, extreme TTLs, and malformed timestamps become ineligible decisions without crashing discovery.

## Safety model

- Requests may enable dry-run, reduce the per-run cap, or select a subset of resource IDs. They cannot change deployment scope, services, exclusions, grace periods, or shared budgets.
- Full discovery and the saved plan precede every workload mutation. Intent and a budget reservation are saved atomically before the API call. Each outcome is checkpointed.
- One conditional Blob lock serializes workers for the subscription. A rolling shared budget spans runs. Defaults: ten actions per run and per hour; AKS pools are capped at ten nodes.
- Eligibility, tags, state, and inherited Azure management locks are refreshed immediately before action. AKS updates additionally use `If-Match`.
- VM deletion requires this janitor's confirmed deallocation, observed deallocated state, matching resource identity and configuration, an elapsed grace period, and deletion opt-in. Default grace is 24 hours.
- Long-running operations are reconciled on later runs. A timeout or uncertain response leaves durable pending intent and blocks replay. Storage failures retain the lock for deliberate recovery.

Azure does not provide an equivalent conditional eligibility check for every stop/delete API. VM restarts that occur entirely between observations may also be invisible. See [safety and limitations](docs/safety.md) before enabling deletion.

## Run locally

Python 3.12 or later and Azure CLI authentication are required for a local Azure-connected run:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
cp examples/policy.json policy.local.json
# Edit the tenant, subscription, groups, locations and existing state account.
az login --tenant YOUR_TENANT_ID
export JANITOR_POLICY="$(cat policy.local.json)"
azure-janitor --dry-run --max-actions 1
```

The example uses the explicit `azure_cli` credential mode. The deployed job uses an explicitly selected user-assigned managed identity. Dry runs still write first-seen history and reports to the configured private state container. Grant the local identity the same read/state permissions described in [deployment](docs/deployment.md); do not create a separate state container for overlapping live workers.

```sh
azure-janitor --dry-run --resource-id /subscriptions/UUID/resourceGroups/dev/providers/Microsoft.Compute/virtualMachines/example
azure-janitor --report RUN_UUID
```

The CLI prints a structured summary and private report URI. `partial` and `failed` runs exit nonzero. `submitted` means Azure accepted the action; it does not yet mean the operation completed.

## Deploy and operate

Follow [deployment](docs/deployment.md) to build a digest-pinned image, initialize Terraform with an existing remote backend, deploy the manual dry-run job, review its reports, and enable a timer. Terraform includes scoped custom RBAC roles, private versioned state storage, and optional failure alerts to existing Azure Monitor action groups.

[Operations](docs/operations.md) covers partial failures, operation polling, manual recovery, restoration, and a live smoke-test checklist. [Descheduler](docs/descheduler.md) covers the optional Kubernetes companion. [Design references](docs/references.md) records the Azure API contracts and related projects reviewed.

## Development

```sh
pip install -e '.[test]'
ruff check .
ruff format --check .
pytest -q
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate
terraform -chdir=infra test
```

CI runs Python 3.12/3.13 tests, Terraform mock-provider safety tests, a container build, and Helm chart rendering. These checks do not replace a dry-run and controlled integration test in your Azure subscription. No Azure deployment or live workload mutation occurs in CI.

The initial incremental history uses retrospective author dates requested by the repository owner. Actual creation dates remain in Git committer metadata; see [history provenance](docs/history.md).
