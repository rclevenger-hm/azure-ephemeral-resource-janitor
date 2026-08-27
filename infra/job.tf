locals {
  policy = {
    tenant_id                  = var.tenant_id
    subscription_id            = var.subscription_id
    resource_groups            = sort(tolist(var.resource_groups))
    locations                  = sort(tolist(var.locations))
    state_account              = var.state_account
    state_resource_group       = azurerm_resource_group.janitor.name
    credential_mode            = "managed_identity"
    managed_identity_client_id = azurerm_user_assigned_identity.janitor.client_id
    services                   = sort(tolist(var.services))
    dry_run                    = var.dry_run
    mode                       = var.mode
    ttl_hours                  = var.ttl_hours
    grace_hours                = var.grace_hours
    max_actions_per_run        = var.max_actions_per_run
    max_actions_per_window     = var.max_actions_per_window
    window_seconds             = var.window_seconds
    max_pool_nodes             = var.max_pool_nodes
    runtime_seconds            = 480
  }
}
resource "azurerm_log_analytics_workspace" "janitor" {
  name                = "${var.name}-logs"
  location            = var.location
  resource_group_name = azurerm_resource_group.janitor.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}
resource "azurerm_container_app_environment" "janitor" {
  name                       = "${var.name}-env"
  location                   = var.location
  resource_group_name        = azurerm_resource_group.janitor.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.janitor.id
  tags                       = { do-not-cleanup = "true" }
}
resource "azurerm_container_app_job" "janitor" {
  name                         = var.name
  location                     = var.location
  resource_group_name          = azurerm_resource_group.janitor.name
  container_app_environment_id = azurerm_container_app_environment.janitor.id
  replica_timeout_in_seconds   = 600
  replica_retry_limit          = 0
  tags                         = { do-not-cleanup = "true" }
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.janitor.id]
  }
  dynamic "registry" {
    for_each = var.registry == null ? [] : [var.registry]
    content {
      server   = registry.value.server
      identity = azurerm_user_assigned_identity.janitor.id
    }
  }
  dynamic "manual_trigger_config" {
    for_each = var.schedule_enabled ? [] : [1]
    content {
      parallelism              = 1
      replica_completion_count = 1
    }
  }
  dynamic "schedule_trigger_config" {
    for_each = var.schedule_enabled ? [1] : []
    content {
      cron_expression          = var.schedule
      parallelism              = 1
      replica_completion_count = 1
    }
  }
  template {
    container {
      name   = "janitor"
      image  = var.image
      cpu    = 0.25
      memory = "0.5Gi"
      env {
        name  = "JANITOR_POLICY"
        value = jsonencode(local.policy)
      }
    }
  }
  lifecycle {
    precondition {
      condition     = var.max_actions_per_run <= var.max_actions_per_window
      error_message = "The run cap cannot exceed the shared action cap."
    }
    precondition {
      condition     = var.registry == null ? true : startswith(var.image, "${var.registry.server}/")
      error_message = "The image must come from the configured registry."
    }
  }
  depends_on = [
    azurerm_role_assignment.workloads, azurerm_role_assignment.control_reads,
    azurerm_role_assignment.state, azurerm_role_assignment.state_metadata,
    azurerm_role_assignment.image_pull
  ]
}
