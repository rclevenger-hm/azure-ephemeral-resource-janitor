locals {
  subscription_scope = "/subscriptions/${var.subscription_id}"
  read_actions = {
    compute        = ["Microsoft.Compute/virtualMachines/read", "Microsoft.Compute/virtualMachines/instanceView/read"]
    aks            = ["Microsoft.ContainerService/managedClusters/read", "Microsoft.ContainerService/managedClusters/agentPools/read"]
    container_apps = ["Microsoft.App/containerApps/read"]
    app_services   = ["Microsoft.Web/sites/read"]
    logic_apps     = ["Microsoft.Logic/workflows/read"]
  }
  write_actions = {
    compute        = concat(["Microsoft.Compute/virtualMachines/deallocate/action"], var.mode == "lifecycle" ? ["Microsoft.Compute/virtualMachines/delete"] : [])
    aks            = ["Microsoft.ContainerService/managedClusters/agentPools/write"]
    container_apps = ["Microsoft.App/containerApps/stop/action"]
    app_services   = ["Microsoft.Web/sites/stop/action"]
    logic_apps     = ["Microsoft.Logic/workflows/disable/action"]
  }
  operation_reads = {
    compute        = ["Microsoft.Compute/locations/operations/read"]
    aks            = ["Microsoft.ContainerService/locations/operations/read", "Microsoft.ContainerService/locations/operationresults/read"]
    container_apps = ["Microsoft.App/locations/operationresults/read", "Microsoft.App/locations/operationstatuses/read"]
    app_services   = []
    logic_apps     = []
  }
  workload_actions = concat(
    ["Microsoft.Resources/subscriptions/resourceGroups/read"],
    flatten([for service in var.services : local.read_actions[service]]),
    var.dry_run ? [] : flatten([for service in var.services : local.write_actions[service]])
  )
}
resource "azurerm_user_assigned_identity" "janitor" {
  name                = var.name
  resource_group_name = azurerm_resource_group.janitor.name
  location            = var.location
  tags                = { do-not-cleanup = "true" }
}
resource "azurerm_role_definition" "workloads" {
  name               = "${var.name}-workloads"
  scope              = local.subscription_scope
  assignable_scopes  = [local.subscription_scope]
  role_definition_id = uuidv5("url", "${local.subscription_scope}/${var.name}/workloads")
  permissions { actions = local.workload_actions }
}
resource "azurerm_role_assignment" "workloads" {
  for_each           = var.resource_groups
  scope              = "${local.subscription_scope}/resourceGroups/${each.value}"
  role_definition_id = azurerm_role_definition.workloads.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.janitor.principal_id
  principal_type     = "ServicePrincipal"
}
resource "azurerm_role_definition" "control_reads" {
  name               = "${var.name}-control-reads"
  scope              = local.subscription_scope
  assignable_scopes  = [local.subscription_scope]
  role_definition_id = uuidv5("url", "${local.subscription_scope}/${var.name}/control-reads")
  permissions {
    actions = concat(
      ["Microsoft.Resources/subscriptions/read", "Microsoft.Authorization/locks/read"],
      flatten([for service in var.services : local.operation_reads[service]])
    )
  }
}
resource "azurerm_role_assignment" "control_reads" {
  scope              = local.subscription_scope
  role_definition_id = azurerm_role_definition.control_reads.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.janitor.principal_id
  principal_type     = "ServicePrincipal"
}
resource "azurerm_role_definition" "state" {
  name               = "${var.name}-state"
  scope              = local.subscription_scope
  assignable_scopes  = [local.subscription_scope]
  role_definition_id = uuidv5("url", "${local.subscription_scope}/${var.name}/state")
  permissions {
    data_actions = [
      "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
      "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
      "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete"
    ]
  }
}
resource "azurerm_role_assignment" "state" {
  scope              = "${azurerm_storage_account.state.id}/blobServices/default/containers/${azurerm_storage_container.state.name}"
  role_definition_id = azurerm_role_definition.state.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.janitor.principal_id
  principal_type     = "ServicePrincipal"
}
resource "azurerm_role_definition" "state_metadata" {
  name               = "${var.name}-state-metadata"
  scope              = local.subscription_scope
  assignable_scopes  = [local.subscription_scope]
  role_definition_id = uuidv5("url", "${local.subscription_scope}/${var.name}/state-metadata")
  permissions { actions = ["Microsoft.Storage/storageAccounts/read"] }
}
resource "azurerm_role_assignment" "state_metadata" {
  scope              = azurerm_storage_account.state.id
  role_definition_id = azurerm_role_definition.state_metadata.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.janitor.principal_id
  principal_type     = "ServicePrincipal"
}
resource "azurerm_role_assignment" "image_pull" {
  count                = var.registry == null ? 0 : 1
  scope                = var.registry.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.janitor.principal_id
  principal_type       = "ServicePrincipal"
}
