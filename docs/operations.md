# Operations and recovery

## Reports and health

Read summaries from Container Apps execution logs. A healthy run exits zero and emits `status=complete`; accepted actions appear as `submitted`. A later run polls each saved Azure operation and refreshes the resource before advancing lifecycle history. A complete run can contain `operation_in_progress`: it does not mean every Azure operation finished.

Detailed reports live at `janitor/v1/subscriptions/SUBSCRIPTION/runs/RUN_ID.json`. Use `azure-janitor --report RUN_ID` with the appropriate operator policy and read permissions, or download the private Blob using your own Entra identity. The reports contain the evaluated plan, selected before-state, owner, outcome, reason, and correlation request ID. Run IDs derive from the Container Apps execution name; replaying a completed execution returns its existing report.

| Outcome or reason | Operator response |
| --- | --- |
| `would_act` | Review candidates, expiration, scope, exclusions, and before-state |
| `submitted` / `operation_in_progress` | Wait for subsequent reconciliation; investigate unusually old operations |
| `api_400`, `api_409`, `api_412`, `api_422` | Inspect the resource-specific rejection; later resources may still have succeeded |
| `authorization_failure` | Correct the scoped role or expired access; the run stops |
| `unknown` / `unresolved_action` | Action may have happened; reconcile before retrying |
| `operation_failed` | Inspect the saved Azure operation and its error; resource stays blocked |
| `budget_policy_changed` | Reconcile old reservations and coordinate a policy migration |
| `RunLocked` / `StateError` | Inspect the durable lock and prior run; follow recovery below |
| `discovery_incomplete` | No workload actions were attempted; fix discovery/permissions/bounds |

Log-based alerts should be tested after deployment. Monitor both failed executions and missing successful heartbeats, with a threshold longer than your schedule plus ingestion delay. Azure Activity Log and the stored correlation IDs support investigation; this service does not automatically ingest Activity Log as lifecycle proof.

## Unknown actions and retained locks

Never remove a lock just because it is old. Never clear pending intent simply to get a green pipeline.

1. Disable future job scheduling or remove the ability to start it, and confirm every replica/execution is terminated. When termination cannot be proven, revoke the runtime workload mutation roles and wait for revocation to take effect before recovery.
2. Download the current lock, state, and affected reports, together with their ETags and previous versions. Record the run ID and request ID. Preserve an audit copy before editing.
3. Check the relevant Azure operation, resource state/identity, and Activity Log. Distinguish a definite rejection, an accepted/in-progress operation, a completed action, and an action that remains uncertain. Do not repeat an uncertain destructive request.
4. Prepare a minimal state repair. An accepted operation can be restored as an `operation` plus its saved `submitted` intent for later polling. A proven rejection may have its pending entry cleared; keep its budget reservation until its normal window expires. If evidence is insufficient, keep the resource blocked and retain the saved intent.
5. Replace state using **the observed ETag condition**, preserving unrelated resources and reservations. Add an administrative incident record outside the runner's mutable report. Delete the lock only with its observed ETag after proving the old worker cannot mutate anything.
6. Resume with dry-run, inspect the resulting report, and restore limited live permissions only after the affected history is consistent.

There is intentionally no automatic `--force-unlock`, timeout takeover, or blindly retrying recovery command. A stale conditional write must fail rather than overwrite another operator's repair. Do not restore an entire old Blob version over newer successful action records without reconciling those differences.

## Restoration and renewed expiry

To restore a workload, first extend `janitor-expires-at` into the future or add `do-not-cleanup`. Extension must be observed by a run to reset saved quarantine/stop history. Then use the service's normal administrative start/enable operation:

- VM: `az vm start`; validate attached disk/network deletion settings before later enabling lifecycle mode.
- AKS pool: `az aks nodepool start`; retained node count is restored by Azure. Do not edit the underlying managed VMSS.
- Container App: `az containerapp start`.
- Function App or Web App: `az functionapp start` / `az webapp start`.
- Logic Apps Consumption: enable the workflow through ARM, the portal, or your deployment tooling.

An already-deleted VM cannot be started; restoration needs your own backups and infrastructure definitions. The janitor creates no backups and does not claim that retained disks are a complete recovery strategy.

## Controlled Azure smoke test

Use a dedicated sandbox group, one inexpensive workload, manual triggering, and a per-run/shared cap of one. Validate the target subscription and tenant before each phase.

1. Dry-run an expired opted-in VM and an excluded control VM. Confirm the plan and lack of mutations.
2. Enable compute stop-only permissions. Confirm `deallocate` submission, saved intent/reservation, eventual operation success, and observed deallocated state.
3. With a second expired candidate, start overlapping jobs. Confirm only one owns the lock and the shared cap holds across later runs.
4. Deliberately apply a ReadOnly management lock to a disposable candidate. Confirm the janitor skips it and never attempts lock removal.
5. Enable lifecycle only for the disposable VM, set a short nonzero grace, and opt that VM into deletion. Verify it remains during grace and is deleted only afterward. Inspect attached resource delete options before this step.
6. Restore a separately retained workload after extending its expiry; verify the next run does not immediately stop it again.
7. Repeat service-specific tests for a small AKS User pool, Container App, and whole Function App before enrolling real workloads. Check upstream retries, Kubernetes disruption, and retained billing resources.
8. Generate one controlled initialization failure and verify error logs, nonzero exit, notifications, and your missing-heartbeat monitor.

The repository's unit/contract tests and Terraform mock tests do not execute these live checks. No production readiness claim depends on unperformed Azure integration testing.
