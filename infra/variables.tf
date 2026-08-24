variable "subscription_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$", var.subscription_id))
    error_message = "Use a canonical lowercase subscription UUID."
  }
}
variable "tenant_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$", var.tenant_id))
    error_message = "Use a canonical lowercase tenant UUID."
  }
}
variable "name" {
  type    = string
  default = "ephemeral-janitor"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,22}[a-z0-9]$", var.name)) && !strcontains(var.name, "--")
    error_message = "Use a 4-24 character lowercase Azure resource name without consecutive hyphens."
  }
}
variable "location" {
  type    = string
  default = "eastus"
}
variable "resource_groups" {
  description = "Existing, explicitly enrolled workload resource groups in this subscription."
  type        = set(string)
  validation {
    condition = length(var.resource_groups) > 0 && alltrue([
      for group in var.resource_groups : can(regex("^[a-z0-9_.()-]+$", group)) && !startswith(group, "mc_")
    ])
    error_message = "Provide lowercase workload groups; AKS managed groups cannot be enrolled."
  }
}
variable "locations" {
  type    = set(string)
  default = ["eastus"]
  validation {
    condition     = length(var.locations) > 0 && alltrue([for region in var.locations : can(regex("^[a-z0-9]+$", region))])
    error_message = "Provide at least one canonical Azure location."
  }
}
variable "state_account" {
  description = "Globally unique storage account name; this module creates it."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.state_account))
    error_message = "Storage accounts require 3-24 lowercase letters or digits."
  }
}
variable "image" {
  description = "Prebuilt public image or Azure Container Registry image, pinned by digest."
  type        = string
  validation {
    condition     = can(regex("^[^[:space:]]+@sha256:[0-9a-f]{64}$", var.image))
    error_message = "Supply an immutable image@sha256 digest."
  }
}
variable "registry" {
  description = "Optional existing ACR in legacy RBAC mode; enable ARM audience authentication."
  type        = object({ id = string, server = string })
  default     = null
  validation {
    condition     = var.registry == null ? true : can(regex("^[a-z0-9]+[.]azurecr[.]io$", var.registry.server))
    error_message = "Use an Azure Public Cloud registry login server."
  }
}
variable "services" {
  type    = set(string)
  default = ["compute", "aks", "container_apps", "app_services", "logic_apps"]
  validation {
    condition     = length(var.services) > 0 && length(setsubtract(var.services, ["compute", "aks", "container_apps", "app_services", "logic_apps"])) == 0
    error_message = "Choose supported Azure services."
  }
}
variable "dry_run" {
  type    = bool
  default = true
}
variable "mode" {
  type    = string
  default = "stop"
  validation {
    condition     = contains(["stop", "lifecycle"], var.mode)
    error_message = "mode must be stop or lifecycle."
  }
}
variable "schedule_enabled" {
  description = "False creates a manual-only job for initial review. Enabling the timer replaces the job."
  type        = bool
  default     = false
}
variable "schedule" {
  description = "Five-field UTC cron expression."
  type        = string
  default     = "*/15 * * * *"
  validation {
    condition     = length(split(" ", trimspace(var.schedule))) == 5
    error_message = "Use a five-field Container Apps cron expression."
  }
}
variable "ttl_hours" {
  type    = number
  default = 24
  validation {
    condition     = var.ttl_hours >= 1 / 60 && var.ttl_hours <= 87600
    error_message = "TTL must be between one minute and ten years."
  }
}
variable "grace_hours" {
  type    = number
  default = 24
  validation {
    condition     = var.grace_hours >= 1 / 60 && var.grace_hours <= 87600
    error_message = "Recovery grace must be between one minute and ten years."
  }
}
variable "max_actions_per_run" {
  type    = number
  default = 10
  validation {
    condition     = var.max_actions_per_run >= 1 && var.max_actions_per_run <= 1000 && floor(var.max_actions_per_run) == var.max_actions_per_run
    error_message = "Run cap must be an integer from 1 to 1000."
  }
}
variable "max_actions_per_window" {
  type    = number
  default = 10
  validation {
    condition     = var.max_actions_per_window >= 1 && var.max_actions_per_window <= 1000 && floor(var.max_actions_per_window) == var.max_actions_per_window
    error_message = "Shared cap must be an integer from 1 to 1000."
  }
}
variable "window_seconds" {
  type    = number
  default = 3600
  validation {
    condition     = var.window_seconds >= 1 && var.window_seconds <= 86400 && floor(var.window_seconds) == var.window_seconds
    error_message = "Budget window must be an integer from 1 to 86400 seconds."
  }
}
variable "max_pool_nodes" {
  description = "Maximum size of an eligible AKS pool; one pool still consumes one action."
  type        = number
  default     = 10
  validation {
    condition     = var.max_pool_nodes >= 1 && var.max_pool_nodes <= 1000 && floor(var.max_pool_nodes) == var.max_pool_nodes
    error_message = "Pool size cap must be an integer from 1 to 1000."
  }
}
variable "alert_action_group_ids" {
  description = "Existing Azure Monitor action groups for failure alerts; empty leaves alert creation disabled."
  type        = set(string)
  default     = []
}
