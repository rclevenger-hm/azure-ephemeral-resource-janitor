resource "azurerm_monitor_scheduled_query_rules_alert_v2" "failures" {
  count                 = length(var.alert_action_group_ids) == 0 ? 0 : 1
  name                  = "${var.name}-failures"
  resource_group_name   = azurerm_resource_group.janitor.name
  location              = var.location
  scopes                = [azurerm_log_analytics_workspace.janitor.id]
  evaluation_frequency  = "PT5M"
  window_duration       = "PT15M"
  skip_query_validation = true # Tables appear after the first job execution.
  severity              = 2
  description           = "Janitor failures, unresolved actions, or failed job replicas require operator review."
  criteria {
    query                   = <<-KQL
      union isfuzzy=true
        (ContainerAppConsoleLogs_CL
          | where ContainerJobName_s == '${var.name}'
          | extend payload = parse_json(Log_s)
          | where tostring(payload.severity) == 'ERROR'),
        (ContainerAppSystemLogs_CL
          | where ContainerJobName_s == '${var.name}'
          | where Log_s has_any ('Failed', 'Error', 'BackOff', 'DeadlineExceeded'))
    KQL
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 0
    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }
  action { action_groups = var.alert_action_group_ids }
}
