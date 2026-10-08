variable "aws_region" {
  description = "Región para todos los recursos del laboratorio."
  type        = string
  default     = "us-east-1"
}

variable "aws_account_id" {
  description = "Cuenta AWS autorizada para este laboratorio (12 dígitos)."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id debe contener exactamente 12 dígitos."
  }
}

variable "project_name" {
  type    = string
  default = "crewai-lab"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.project_name))
    error_message = "Usa entre 3 y 25 caracteres: minúsculas, números y guiones."
  }
}

variable "private_network" {
  description = "true: subred privada con NAT; false: subred pública sin puertos de entrada."
  type        = bool
  default     = true
}

variable "image_tag" {
  description = "Etiqueta de imagen generada por ./lab up."
  type        = string
  default     = "lab"
}

variable "anthropic_model" {
  type    = string
  default = "claude-sonnet-4-6"
}

variable "anthropic_api_key" {
  description = "Solo en ejecución; ./lab up la solicita o toma ANTHROPIC_API_KEY."
  type        = string
  default     = ""
  sensitive   = true
  ephemeral   = true
}

variable "splunk_hec_endpoint" {
  description = "URL base HTTPS de HEC, sin /services/collector; vacío desactiva Splunk."
  type        = string
  default     = ""
  validation {
    condition     = var.splunk_hec_endpoint == "" || can(regex("^https://[A-Za-z0-9.-]+(:[0-9]+)?/?$", var.splunk_hec_endpoint))
    error_message = "Usa la URL base HTTPS de HEC, por ejemplo https://hec.example.com:8088."
  }
}

variable "splunk_hec_token" {
  description = "Token de HEC; nunca se almacena en el estado de Terraform."
  type        = string
  default     = ""
  sensitive   = true
  ephemeral   = true
}

variable "splunk_hec_verify_tls" {
  description = "Valida el certificado HEC. Puede ser false únicamente para un trial con certificado autofirmado."
  type        = bool
  default     = true
}

variable "splunk_delivery_mode" {
  description = "hec: envío directo para el trial; firehose: requiere habilitación y ACK en Splunk."
  type        = string
  default     = "hec"
  validation {
    condition     = contains(["hec", "firehose"], var.splunk_delivery_mode)
    error_message = "splunk_delivery_mode debe ser hec o firehose."
  }
}

variable "secret_revision" {
  description = "Incrementar al cambiar las claves; ./lab up asigna una nueva revisión."
  type        = number
  default     = 1
}
