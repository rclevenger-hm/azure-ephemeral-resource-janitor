mock_provider "azurerm" {}
variables {
  subscription_id = "11111111-2222-3333-4444-555555555555"
  tenant_id       = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
  resource_groups = ["ephemeral-dev"]
  state_account   = "janitorsafetytest"
  image           = "example.azurecr.io/janitor@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}
run "dryrun_is_readonly_for_workloads" {
  command = plan
  assert {
    condition = alltrue([for action in azurerm_role_definition.workloads.permissions[0].actions :
      endswith(lower(action), "/read")
    ])
    error_message = "Dry run must not grant workload write/action/delete permissions."
  }
  assert {
    condition = (length(azurerm_container_app_job.janitor.manual_trigger_config) == 1 &&
      azurerm_container_app_job.janitor.replica_retry_limit == 0 &&
      azurerm_container_app_job.janitor.replica_timeout_in_seconds == 600 &&
      azurerm_container_app_job.janitor.manual_trigger_config[0].parallelism == 1 &&
    azurerm_container_app_job.janitor.manual_trigger_config[0].replica_completion_count == 1)
    error_message = "Start manual-only, without fan-out or automatic retries."
  }
  assert {
    condition = (!azurerm_storage_account.state.shared_access_key_enabled &&
      !azurerm_storage_account.state.allow_nested_items_to_be_public &&
      azurerm_storage_account.state.blob_properties[0].versioning_enabled &&
    azurerm_storage_container.state.container_access_type == "private")
    error_message = "Checkpoint storage must be private, versioned and use identity authentication."
  }
  assert {
    condition = alltrue([for assignment in azurerm_role_assignment.workloads :
      endswith(assignment.scope, "/resourceGroups/ephemeral-dev")
    ])
    error_message = "Workload roles must be scoped to explicitly enrolled resource groups."
  }
  assert {
    condition = alltrue([for action in azurerm_role_definition.control_reads.permissions[0].actions :
      endswith(lower(action), "/read")
    ])
    error_message = "Subscription-wide grants must contain only selected control-plane reads."
  }
}
run "live_stop_grants_no_delete" {
  command = plan
  variables {
    dry_run  = false
    services = ["compute"]
  }
  assert {
    condition = (contains(local.workload_actions, "Microsoft.Compute/virtualMachines/deallocate/action") &&
      !contains(local.workload_actions, "Microsoft.Compute/virtualMachines/delete") &&
    !contains(local.workload_actions, "Microsoft.ContainerService/managedClusters/agentPools/write"))
    error_message = "Live stop mode must not grant VM deletion or unrelated mutations."
  }
}
run "live_lifecycle_enables_vm_delete" {
  command = plan
  variables {
    dry_run  = false
    mode     = "lifecycle"
    services = ["compute"]
  }
  assert {
    condition     = contains(local.workload_actions, "Microsoft.Compute/virtualMachines/delete")
    error_message = "Explicit lifecycle mode needs the VM delete permission."
  }
}
run "scheduled_job_is_single_replica" {
  command = plan
  variables { schedule_enabled = true }
  assert {
    condition = (length(azurerm_container_app_job.janitor.manual_trigger_config) == 0 &&
      azurerm_container_app_job.janitor.schedule_trigger_config[0].cron_expression == "*/15 * * * *" &&
      azurerm_container_app_job.janitor.schedule_trigger_config[0].parallelism == 1 &&
    azurerm_container_app_job.janitor.schedule_trigger_config[0].replica_completion_count == 1)
    error_message = "Scheduling must preserve the single-worker execution settings."
  }
}
run "infra_cannot_be_enrolled" {
  command = plan
  variables { resource_groups = ["ephemeral-janitor-infra"] }
  expect_failures = [azurerm_resource_group.janitor]
}
run "run_cap_cannot_exceed_shared_cap" {
  command = plan
  variables { max_actions_per_run = 11 }
  expect_failures = [azurerm_container_app_job.janitor]
}
run "image_registry_must_match" {
  command = plan
  variables {
    registry = {
      id     = "/subscriptions/11111111-2222-3333-4444-555555555555/resourceGroups/images/providers/Microsoft.ContainerRegistry/registries/other"
      server = "other.azurecr.io"
    }
  }
  expect_failures = [azurerm_container_app_job.janitor]
}
