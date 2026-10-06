output "job_id" { value = azurerm_container_app_job.janitor.id }
output "resource_group" { value = azurerm_resource_group.janitor.name }
output "identity_client_id" { value = azurerm_user_assigned_identity.janitor.client_id }
output "policy" { value = local.policy }
output "state_container_url" {
  value = "https://${var.state_account}.blob.core.windows.net/${azurerm_storage_container.state.name}"
}
output "log_workspace_id" { value = azurerm_log_analytics_workspace.janitor.workspace_id }
