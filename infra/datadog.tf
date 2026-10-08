variable "observability_provider" {
  type    = string
  default = "none"
  validation {
    condition     = contains(["none", "datadog"], var.observability_provider)
    error_message = "Usa none o datadog."
  }
}

variable "datadog_site" {
  type    = string
  default = "datadoghq.com"
  validation {
    condition     = contains(["datadoghq.com", "us3.datadoghq.com", "us5.datadoghq.com", "datadoghq.eu", "ap1.datadoghq.com", "ap2.datadoghq.com"], var.datadog_site)
    error_message = "Sitio Datadog no admitido."
  }
}

variable "datadog_api_key" {
  type      = string
  default   = ""
  sensitive = true
  ephemeral = true
}

locals {
  datadog_enabled = var.observability_provider == "datadog"
}

resource "aws_secretsmanager_secret" "datadog" {
  count                   = local.datadog_enabled ? 1 : 0
  name_prefix             = "${local.name}-datadog-"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "datadog" {
  count                    = local.datadog_enabled ? 1 : 0
  secret_id                = aws_secretsmanager_secret.datadog[0].id
  secret_string_wo         = var.datadog_api_key
  secret_string_wo_version = var.secret_revision
}
