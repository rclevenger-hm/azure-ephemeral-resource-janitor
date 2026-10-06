resource "azurerm_resource_group" "janitor" {
  name     = "${var.name}-infra"
  location = var.location
  tags     = { do-not-cleanup = "true" }
  lifecycle {
    precondition {
      condition     = !contains(var.resource_groups, "${var.name}-infra")
      error_message = "Janitor infrastructure must be outside enrolled workload groups."
    }
  }
}
resource "azurerm_storage_account" "state" {
  name                            = var.state_account
  resource_group_name             = azurerm_resource_group.janitor.name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = "ZRS"
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
  tags                            = { do-not-cleanup = "true" }
  blob_properties {
    versioning_enabled = true
    delete_retention_policy { days = 30 }
    container_delete_retention_policy { days = 30 }
  }
  lifecycle { prevent_destroy = true }
}
resource "azurerm_storage_container" "state" {
  name                  = "janitor"
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
  lifecycle { prevent_destroy = true }
}
resource "azurerm_storage_management_policy" "reports" {
  storage_account_id = azurerm_storage_account.state.id
  rule {
    name    = "expire-run-reports"
    enabled = true
    filters {
      prefix_match = ["janitor/v1/subscriptions/${var.subscription_id}/runs/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob { delete_after_days_since_modification_greater_than = 90 }
      version { delete_after_days_since_creation = 90 }
      snapshot { delete_after_days_since_creation_greater_than = 90 }
    }
  }
  rule {
    name    = "expire-old-checkpoint-versions"
    enabled = true
    filters {
      prefix_match = ["janitor/v1/subscriptions/${var.subscription_id}/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      version { delete_after_days_since_creation = 30 }
      snapshot { delete_after_days_since_creation_greater_than = 30 }
    }
  }
}
